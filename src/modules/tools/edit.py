"""
Edit tool - Surgical text replacement with fuzzy matching.

Finds and replaces text in files with support for fuzzy matching
(handles whitespace/quote differences) and generates unified diffs.
"""

from pathlib import Path
from threading import Event
from typing import Optional

from .schema import EditParams, ToolResult, TextContent, EditToolDetails, AgentTool
from .utils.path_utils import resolve_to_cwd
from .utils.operations import EditOperations, create_default_edit_operations, maybe_await
from .utils.edit_diff import (
    detect_line_ending,
    normalize_to_lf,
    restore_line_endings,
    strip_bom,
    normalize_for_fuzzy_match,
    fuzzy_find_text,
    generate_diff_string,
)


class AbortedError(Exception):
    """Raised when operation is aborted."""
    pass


async def _execute_edit_tool(
    tool_call_id: str,
    params: EditParams,
    cwd: Path,
    operations: Optional[EditOperations],
    signal: Optional[Event] = None,
) -> ToolResult:
    """
    Execute the edit tool operation.
    
    Args:
        tool_call_id: Unique identifier
        params: Validated input parameters
        cwd: Current working directory
        operations: Optional custom operations
        signal: Optional abort signal
        
    Returns:
        ToolResult with success message and diff
        
    Raises:
        AbortedError: If operation is cancelled
        FileNotFoundError: If file doesn't exist
        PermissionError: If file is not readable/writable
        ValueError: If text not found or not unique
    """
    # Check abort
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Resolve path
    absolute_path = resolve_to_cwd(params.path, cwd)
    
    # Use default operations if not provided
    ops = operations or create_default_edit_operations()
    
    # Check file access (read + write)
    try:
        await maybe_await(ops.access(str(absolute_path)))
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {params.path}")
    except PermissionError as e:
        raise e
    
    # Check abort
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Read file
    file_bytes = await maybe_await(ops.read_file(str(absolute_path)))
    raw_content = file_bytes.decode('utf-8')
    
    # Check abort
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Strip BOM (LLM won't include invisible BOM in oldText)
    bom, content = strip_bom(raw_content)
    
    # Detect and normalize line endings
    original_ending = detect_line_ending(content)
    normalized_content = normalize_to_lf(content)
    normalized_old_text = normalize_to_lf(params.old_text)
    normalized_new_text = normalize_to_lf(params.new_text)
    
    # Find old text using fuzzy matching
    match_result = fuzzy_find_text(normalized_content, normalized_old_text)
    
    if not match_result.found:
        raise ValueError(
            f"Could not find the exact text in {params.path}. "
            f"The old text must match exactly including all whitespace and newlines."
        )
    
    # Count occurrences using fuzzy-normalized content
    fuzzy_content = normalize_for_fuzzy_match(normalized_content)
    fuzzy_old_text = normalize_for_fuzzy_match(normalized_old_text)
    occurrences = fuzzy_content.count(fuzzy_old_text)
    
    if occurrences > 1:
        raise ValueError(
            f"Found {occurrences} occurrences of the text in {params.path}. "
            f"The text must be unique. Please provide more context to make it unique."
        )
    
    # Check abort
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Perform replacement
    base_content = match_result.content_for_replacement
    new_content = (
        base_content[:match_result.index] +
        normalized_new_text +
        base_content[match_result.index + match_result.match_length:]
    )
    
    # Verify change occurred
    if base_content == new_content:
        raise ValueError(
            f"No changes made to {params.path}. "
            f"The replacement produced identical content."
        )
    
    # Restore line endings and BOM
    final_content = bom + restore_line_endings(new_content, original_ending)
    
    # Write file
    await maybe_await(ops.write_file(str(absolute_path), final_content))
    
    # Check abort
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Generate diff
    diff_string, first_changed_line = generate_diff_string(base_content, new_content)
    
    return ToolResult(
        content=[TextContent(text=f"Successfully replaced text in {params.path}.")],
        details=EditToolDetails(
            diff=diff_string,
            first_changed_line=first_changed_line,
        ),
    )


def create_edit_tool(
    cwd: Path,
    operations: Optional[EditOperations] = None,
) -> AgentTool:
    """Create an edit tool configured for a specific working directory."""
    async def execute(
        tool_call_id: str,
        params: EditParams,
        signal: Optional[Event] = None,
    ) -> ToolResult:
        """Execute the edit tool."""
        return await _execute_edit_tool(
            tool_call_id,
            params,
            cwd,
            operations,
            signal,
        )
    
    return AgentTool(
        name="edit",
        label="edit",
        description=(
            "Edit a file by replacing exact text. The oldText must match exactly "
            "(including whitespace). Use this for precise, surgical edits."
        ),
        parameters_schema=EditParams,
        execute=execute,
    )


# Default edit tool
edit_tool = create_edit_tool(Path.cwd())