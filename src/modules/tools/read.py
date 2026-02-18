"""
Read tool - Read file contents (text or images).

Reads file contents with support for offset/limit for large text files.
Handles both text files and images (jpg, png, gif, webp, etc.).
"""

import base64
from pathlib import Path
from threading import Event
from typing import Optional

from .schema import ReadParams, ToolResult, TextContent, ImageContent, ReadToolDetails, AgentTool
from .utils.path_utils import resolve_to_cwd
from .utils.truncate import truncate_head, format_size, DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES
from .utils.operations import ReadOperations, create_default_read_operations, maybe_await
from .utils.image_utils import resize_image_if_needed


# Constants
DEFAULT_AUTO_RESIZE_IMAGES = True


class AbortedError(Exception):
    """Raised when operation is aborted via signal."""
    pass


async def _execute_read_tool(
    tool_call_id: str,
    params: ReadParams,
    cwd: Path,
    operations: Optional[ReadOperations],
    auto_resize_images: bool,
    signal: Optional[Event] = None,
) -> ToolResult:
    """
    Execute the read tool operation.
    
    This is the core executor that handles both text and image files.
    For text files, applies offset/limit/truncation.
    For images, encodes to base64 and optionally resizes.
    
    Args:
        tool_call_id: Unique identifier for this tool call
        params: Validated input parameters
        cwd: Current working directory (workspace root)
        operations: Optional custom operations (None = use local filesystem)
        auto_resize_images: Whether to resize large images
        signal: Optional threading.Event for cancellation
        
    Returns:
        ToolResult with file contents and metadata
        
    Raises:
        AbortedError: If operation is cancelled via signal
        FileNotFoundError: If file doesn't exist
        PermissionError: If file is not readable
    """
    # Check if already aborted
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Resolve path (handles ~, relative paths, macOS quirks)
    absolute_path = resolve_to_cwd(params.path, cwd)
    
    # Use default operations if not provided
    ops = operations or create_default_read_operations()
    
    # Check if file exists and is readable (throws if not)
    await maybe_await(ops.access(str(absolute_path)))
    
    # Check abort after access check
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Detect if file is an image
    mime_type = None
    if ops.detect_image_mime_type:
        mime_type = await maybe_await(ops.detect_image_mime_type(str(absolute_path)))
    
    # Check abort after MIME detection
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Branch based on file type
    if mime_type:
        # Handle as image
        return await _read_image_file(
            absolute_path,
            mime_type,
            ops,
            auto_resize_images,
            signal,
        )
    else:
        # Handle as text
        return await _read_text_file(
            absolute_path,
            params.path,  # Original path for error messages
            params.offset,
            params.limit,
            ops,
            signal,
        )


async def _read_text_file(
    absolute_path: Path,
    original_path: str,
    offset: Optional[int],
    limit: Optional[int],
    ops: ReadOperations,
    signal: Optional[Event],
) -> ToolResult:
    """
    Read a text file with offset/limit/truncation support.
    
    This implements the three-stage content selection:
    1. Read entire file
    2. Apply offset/limit (user-specified chunk)
    3. Apply truncation (system limits)
    
    Args:
        absolute_path: Absolute path to the file
        original_path: Original path from user (for error messages)
        offset: Optional 1-indexed line number to start from
        limit: Optional number of lines to read
        ops: Operations for file reading
        signal: Optional abort signal
        
    Returns:
        ToolResult with text content
    """
    # Read file as bytes
    file_bytes = await maybe_await(ops.read_file(str(absolute_path)))
    
    # Check abort after reading
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Decode as UTF-8 text
    try:
        text_content = file_bytes.decode('utf-8')
    except UnicodeDecodeError as e:
        raise ValueError(f"File is not valid UTF-8 text: {e}")
    
    # Split into lines
    all_lines = text_content.split('\n')
    total_file_lines = len(all_lines)
    
    # Apply offset if specified (convert 1-indexed to 0-indexed)
    start_line = (offset - 1) if offset else 0
    start_line_display = start_line + 1  # For display (1-indexed)
    
    # Validate offset
    if start_line >= total_file_lines:
        raise ValueError(
            f"Offset {offset} is beyond end of file ({total_file_lines} lines total)"
        )
    
    # Apply limit if specified
    if limit is not None:
        end_line = min(start_line + limit, total_file_lines)
        selected_content = '\n'.join(all_lines[start_line:end_line])
        user_limited_lines = end_line - start_line
    else:
        selected_content = '\n'.join(all_lines[start_line:])
        user_limited_lines = None
    
    # Apply truncation (respects both line and byte limits)
    truncation = truncate_head(
        selected_content,
        max_lines=DEFAULT_MAX_LINES,
        max_bytes=DEFAULT_MAX_BYTES,
    )
    
    # Build output with actionable notices
    output_text, details = _format_text_output(
        truncation,
        start_line_display,
        total_file_lines,
        user_limited_lines,
        start_line,
        all_lines,
        original_path,
    )
    
    return ToolResult(
        content=[TextContent(text=output_text)],
        details=details,
    )


def _format_text_output(
    truncation,
    start_line_display: int,
    total_file_lines: int,
    user_limited_lines: Optional[int],
    start_line: int,
    all_lines: list[str],
    original_path: str,
) -> tuple[str, Optional[ReadToolDetails]]:
    """
    Format text output with actionable notices.
    
    This implements the three notice types:
    1. First line too large → suggest bash tool
    2. Truncation occurred → suggest next offset
    3. User limit reached → show remaining lines
    
    Args:
        truncation: TruncationResult from truncate_head
        start_line_display: 1-indexed starting line for display
        total_file_lines: Total number of lines in file
        user_limited_lines: Number of lines user requested (or None)
        start_line: 0-indexed starting line
        all_lines: All lines from file
        original_path: Original path from user
        
    Returns:
        Tuple of (output_text, details)
    """
    details = None
    
    # Case 1: First line at offset exceeds byte limit
    if truncation.first_line_exceeds_limit:
        first_line_size = len(all_lines[start_line].encode('utf-8'))
        output_text = (
            f"[Line {start_line_display} is {format_size(first_line_size)}, "
            f"exceeds {format_size(DEFAULT_MAX_BYTES)} limit. "
            f"Use bash: sed -n '{start_line_display}p' {original_path} | "
            f"head -c {DEFAULT_MAX_BYTES}]"
        )
        details = ReadToolDetails(truncation={
            "truncated": True,
            "first_line_exceeds_limit": True,
        })
        return output_text, details
    
    # Case 2: Truncation occurred
    if truncation.truncated:
        end_line_display = start_line_display + truncation.output_lines - 1
        next_offset = end_line_display + 1
        
        output_text = truncation.content
        
        if truncation.truncated_by == "lines":
            output_text += (
                f"\n\n[Showing lines {start_line_display}-{end_line_display} "
                f"of {total_file_lines}. Use offset={next_offset} to continue.]"
            )
        else:  # truncated by bytes
            output_text += (
                f"\n\n[Showing lines {start_line_display}-{end_line_display} "
                f"of {total_file_lines} ({format_size(DEFAULT_MAX_BYTES)} limit). "
                f"Use offset={next_offset} to continue.]"
            )
        
        details = ReadToolDetails(truncation={
            "truncated": True,
            "truncated_by": truncation.truncated_by,
            "total_lines": truncation.total_lines,
            "output_lines": truncation.output_lines,
        })
        return output_text, details
    
    # Case 3: User limit reached (but no truncation)
    if user_limited_lines is not None:
        if start_line + user_limited_lines < len(all_lines):
            remaining = len(all_lines) - (start_line + user_limited_lines)
            next_offset = start_line + user_limited_lines + 1
            
            output_text = truncation.content
            output_text += (
                f"\n\n[{remaining} more lines in file. "
                f"Use offset={next_offset} to continue.]"
            )
            return output_text, details
    
    # Case 4: No truncation, no user limit exceeded
    return truncation.content, details


async def _read_image_file(
    absolute_path: Path,
    mime_type: str,
    ops: ReadOperations,
    auto_resize_images: bool,
    signal: Optional[Event],
) -> ToolResult:
    """
    Read an image file and encode to base64.
    
    Optionally resizes large images to save tokens.
    
    Args:
        absolute_path: Absolute path to the image
        mime_type: Detected MIME type
        ops: Operations for file reading
        auto_resize_images: Whether to resize large images
        signal: Optional abort signal
        
    Returns:
        ToolResult with image content
    """
    # Read file as bytes
    file_bytes = await maybe_await(ops.read_file(str(absolute_path)))
    
    # Check abort after reading
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Encode to base64
    base64_data = base64.b64encode(file_bytes).decode('ascii')
    
    # Optionally resize
    if auto_resize_images:
        resized_data, dimension_note = resize_image_if_needed(
            base64_data,
            mime_type,
            max_dimension=2000,
        )
        
        # Build text note
        text_note = f"Read image file [{mime_type}]"
        if dimension_note:
            text_note += f"\n{dimension_note}"
        
        return ToolResult(
            content=[
                TextContent(text=text_note),
                ImageContent(data=resized_data, mime_type=mime_type),
            ],
            details=None,
        )
    else:
        # No resizing
        text_note = f"Read image file [{mime_type}]"
        
        return ToolResult(
            content=[
                TextContent(text=text_note),
                ImageContent(data=base64_data, mime_type=mime_type),
            ],
            details=None,
        )


def create_read_tool(
    cwd: Path,
    auto_resize_images: bool = DEFAULT_AUTO_RESIZE_IMAGES,
    operations: Optional[ReadOperations] = None,
) -> AgentTool:
    """
    Create a read tool configured for a specific working directory.
    
    Args:
        cwd: Current working directory (workspace root)
        auto_resize_images: Whether to auto-resize large images (default: True)
        operations: Optional custom operations for remote execution
        
    Returns:
        AgentTool descriptor for the read tool
    """
    async def execute(
        tool_call_id: str,
        params: ReadParams,
        signal: Optional[Event] = None,
    ) -> ToolResult:
        """Execute the read tool."""
        return await _execute_read_tool(
            tool_call_id,
            params,
            cwd,
            operations,
            auto_resize_images,
            signal,
        )
    
    return AgentTool(
        name="read",
        label="read",
        description=(
            f"Read the contents of a file. Supports text files and images "
            f"(jpg, png, gif, webp). Images are sent as attachments. "
            f"For text files, output is truncated to {DEFAULT_MAX_LINES} lines or "
            f"{DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first). "
            f"Use offset/limit for large files. When you need the full file, "
            f"continue with offset until complete."
        ),
        parameters_schema=ReadParams,
        execute=execute,
    )


# Default read tool using current working directory
read_tool = create_read_tool(Path.cwd())