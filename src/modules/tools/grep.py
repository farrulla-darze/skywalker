"""
Grep tool - Search file contents by regex pattern.

Searches for lines matching a regex pattern in files, using ripgrep (rg)
as the default backend. Supports both local filesystem and remote execution
via pluggable operations.
"""

import subprocess
import sys
from pathlib import Path
from threading import Event
from typing import Optional

from .schema import GrepParams, ToolResult, TextContent, GrepToolDetails, AgentTool
from .utils.operations import create_default_grep_operations, GrepOperations, maybe_await
from .utils.path_utils import resolve_to_cwd
from .utils.truncate import truncate_head, truncate_line, format_size, DEFAULT_MAX_BYTES, GREP_MAX_LINE_LENGTH
from .utils.binary_manager import ensure_rg, BinaryNotFoundError

# Constants
DEFAULT_RESULT_LIMIT = 1000


class AbortedError(Exception):
    """Exception raised when the tool execution is aborted via signal."""
    pass


async def _execute_grep_tool(
    tool_call_id: str,
    params: GrepParams,
    cwd: Path,
    operations: Optional[GrepOperations],
    signal: Optional[Event] = None,
) -> ToolResult:
    """
    Execute the grep tool operation.

    This is the core executor that handles both custom operations
    and default rg binary execution.

    Args:
        tool_call_id: Unique identifier for this tool call
        params: Validated input parameters
        cwd: Current working directory (workspace root)
        operations: Optional custom operations (None = use rg binary)
        signal: Optional threading.Event for cancellation

    Returns:
        ToolResult with matching lines and metadata

    Raises:
        AbortedError: If operation is cancelled via signal
        FileNotFoundError: If search path doesn't exist
        RuntimeError: If rg binary is unavailable
    """
    # Check if already aborted
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")

    # Resolve search path
    search_dir = params.path or "."
    search_path = resolve_to_cwd(search_dir, cwd)

    # Choose execution path based on custom provided operations
    if operations is not None:
        return await _execute_with_custom_ops(
            params,
            search_path,
            operations,
            signal,
        )

    # Default rg binary path
    return await _execute_with_rg_binary(
        params,
        search_path,
        signal,
    )


async def _execute_with_custom_ops(
    params: GrepParams,
    search_path: Path,
    ops: GrepOperations,
    signal: Optional[Event],
) -> ToolResult:
    """
    Execute grep using custom operations (e.g., SSH, Docker).

    This path is used when the user provides custom grep operations,
    typically for remote execution scenarios.

    Args:
        params: Grep parameters
        search_path: Absolute path to search in
        ops: Custom operations implementation
        signal: Optional abort signal

    Returns:
        ToolResult with matching lines

    Raises:
        AbortedError: If cancelled
        FileNotFoundError: If search path doesn't exist
    """
    # Check abort before starting
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")

    path_exists = await maybe_await(ops.exists(str(search_path)))
    if not path_exists:
        raise FileNotFoundError(f"Path {search_path} does not exist")

    # Check abort after exists check
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")

    # Build options dict
    options = {
        "include": params.include,
        "case_insensitive": params.case_insensitive or False,
        "context_lines": params.context_lines,
        "limit": DEFAULT_RESULT_LIMIT,
    }

    # Execute custom grep operation
    raw_output = await maybe_await(ops.grep(params.pattern, str(search_path), options))

    # Check abort after grep operation
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")

    # Handle empty results
    if not raw_output or not raw_output.strip():
        return ToolResult(
            content=[TextContent(text="No matches found")],
            details=None,
        )

    # Format and return results
    return _format_results(raw_output, str(search_path), signal)


async def _execute_with_rg_binary(
    params: GrepParams,
    search_path: Path,
    signal: Optional[Event],
) -> ToolResult:
    """
    Execute grep using rg (ripgrep) binary (default path).

    This is the high-performance path that uses the rg binary
    for fast content searching with .gitignore support.

    Args:
        params: Grep parameters
        search_path: Absolute path to search in
        signal: Optional abort signal

    Returns:
        ToolResult with matching lines

    Raises:
        AbortedError: If cancelled
        BinaryNotFoundError: If rg binary not available
        RuntimeError: If rg execution fails
    """
    # Check abort before starting
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")

    # Ensure rg binary is available
    try:
        rg_path = ensure_rg(silent=True)
    except BinaryNotFoundError as e:
        raise RuntimeError(str(e))

    # Build rg command arguments
    args = [
        rg_path,
        "--color=never",
        "--line-number",
        "--with-filename",
        "--hidden",
        "--max-count",
        str(DEFAULT_RESULT_LIMIT),
    ]

    # Optional: glob filter
    if params.include:
        args.extend(["--glob", params.include])

    # Optional: case insensitive
    if params.case_insensitive:
        args.append("-i")

    # Optional: context lines
    if params.context_lines is not None:
        args.extend(["-C", str(params.context_lines)])

    # Add pattern and search path
    args.append(params.pattern)
    args.append(str(search_path))

    # Check abort before executing
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")

    # Execute rg
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("rg command timed out after 60 seconds")
    except Exception as e:
        raise RuntimeError(f"Failed to run rg: {e}")

    # Check abort after execution
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")

    # rg exit codes: 0 = matches found, 1 = no matches, 2 = error
    if result.returncode == 2:
        error_msg = result.stderr.strip() or f"rg exited with code {result.returncode}"
        raise RuntimeError(error_msg)

    output = result.stdout.strip()

    # Handle no matches (exit code 1 or empty output)
    if result.returncode == 1 or not output:
        return ToolResult(
            content=[TextContent(text="No matches found")],
            details=None,
        )

    # Format and return results
    return _format_results(output, str(search_path), signal)


def _format_results(
    raw_output: str,
    search_path_str: str,
    signal: Optional[Event],
) -> ToolResult:
    """
    Format grep results with line truncation, path relativization,
    and overall output truncation.

    Args:
        raw_output: Raw rg output string
        search_path_str: Search path prefix to strip from file paths
        signal: Optional abort signal

    Returns:
        ToolResult with formatted content and details
    """
    lines = raw_output.split("\n")

    # Check if result limit was reached
    result_limit_reached = len(lines) >= DEFAULT_RESULT_LIMIT

    # Process each line: truncate long lines and relativize paths
    processed_lines = []
    for line in lines:
        # Check abort periodically
        if signal and signal.is_set():
            raise AbortedError("Operation aborted")

        if not line:
            processed_lines.append(line)
            continue

        # Relativize file paths in the output
        # rg output format: "path/to/file:line_number:content"
        if line.startswith(search_path_str):
            line = line[len(search_path_str):].lstrip("/")

        # Truncate long lines
        truncated_line, _ = truncate_line(line, GREP_MAX_LINE_LENGTH)
        processed_lines.append(truncated_line)

    # Join processed lines
    processed_output = "\n".join(processed_lines)

    # Apply overall truncation
    truncation = truncate_head(
        processed_output,
        max_lines=sys.maxsize,
        max_bytes=DEFAULT_MAX_BYTES,
    )

    # Build output with notices
    result_output = truncation.content
    details_dict = {}
    notices = []

    if result_limit_reached:
        notices.append(f"{DEFAULT_RESULT_LIMIT} results limit reached")
        details_dict["result_limit_reached"] = DEFAULT_RESULT_LIMIT

    if truncation.truncated:
        notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
        details_dict["truncation"] = {
            "truncated": truncation.truncated,
            "truncated_by": truncation.truncated_by,
            "total_bytes": truncation.total_bytes,
            "output_bytes": truncation.output_bytes,
        }

    # Append notices to output
    if notices:
        result_output += f"\n\n[{'. '.join(notices)}]"

    # Create details object if any details exist
    details = GrepToolDetails(**details_dict) if details_dict else None

    return ToolResult(
        content=[TextContent(text=result_output)],
        details=details,
    )


def create_grep_tool(
    cwd: Path,
    operations: Optional[GrepOperations] = None,
) -> AgentTool:
    """
    Create a grep tool configured for a specific working directory.

    Args:
        cwd: Current working directory (workspace root)
        operations: Optional custom operations for remote execution

    Returns:
        AgentTool descriptor for the grep tool

    Example:
        >>> tool = create_grep_tool(Path("/home/user/project"))
        >>> result = await tool.execute("call-123", GrepParams(pattern="TODO"), None)
    """
    async def execute(
        tool_call_id: str,
        params: GrepParams,
        signal: Optional[Event] = None,
    ) -> ToolResult:
        """Execute the grep tool."""
        return await _execute_grep_tool(
            tool_call_id,
            params,
            cwd,
            operations,
            signal,
        )

    return AgentTool(
        name="grep",
        label="grep",
        description=(
            f"Search file contents by regex pattern. Returns matching lines "
            f"with file paths and line numbers. Respects .gitignore. "
            f"Output is truncated to {DEFAULT_RESULT_LIMIT} results or "
            f"{DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first). "
            f"Lines longer than {GREP_MAX_LINE_LENGTH} chars are truncated."
        ),
        parameters_schema=GrepParams,
        execute=execute,
    )


# Default grep tool using current working directory
grep_tool = create_grep_tool(Path.cwd())
