"""
Find tool - Search for files by glob pattern.
 
Searches for files matching a glob pattern, respecting .gitignore files.
Supports both local filesystem and remote execution via pluggable operations.
"""

import sys
import subprocess
from pathlib import Path
from threading import Event
from typing import Callable, Awaitable, Optional, Union

from .schema import FindParams, ToolResult, TextContent, FindToolDetails, AgentTool
from .utils.operations import create_default_find_operations, FindOperations, maybe_await
from .utils.path_utils import resolve_to_cwd
from .utils.truncate import truncate_head, format_size, DEFAULT_MAX_BYTES
from .utils.binary_manager import ensure_fd, BinaryNotFoundError

# Constants
DEFAULT_LIMIT = 1000

class AbortedError(Exception):
    """Exception raised when the tool execution is aborted via signal."""
    pass

async def _execute_find_tool(
    tool_call_id: str,
    params: FindParams,
    cwd: Path,
    operations: Optional[FindOperations],
    signal: Optional[Event] = None,
) -> ToolResult:
    """
    Execute the find tool operation.
    
    This is the core executor that handles both custom operations
    and default fd binary execution.
    
    Args:
        tool_call_id: Unique identifier for this tool call
        params: Validated input parameters
        cwd: Current working directory (workspace root)
        operations: Optional custom operations (None = use fd binary)
        signal: Optional threading.Event for cancellation
        
    Returns:
        ToolResult with found files and metadata
        
    Raises:
        AbortedError: If operation is cancelled via signal
        FileNotFoundError: If search path doesn't exist
        RuntimeError: If fd binary is unavailable
    """
    # Check if already aborted
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")

    # Resolve search path
    search_dir = params.path or "."
    search_path = resolve_to_cwd(search_dir, cwd)

    # Determine effective limit
    effective_limit = params.limit if params.limit is not None else DEFAULT_LIMIT

    # Choose execution path based on custom provided operations
    ops = operations or create_default_find_operations()

    # Custom operations path - if provided
    if operations is not None:
        return await _execute_with_custom_operations(
            params.pattern,
            search_path,
            effective_limit,
            ops,
            signal,
        )

    # Default fd binary path
    return await _execute_with_fd_binary(
        params.pattern,
        search_path,
        effective_limit,
        signal,
    )
    
async def _execute_with_custom_operations(
    pattern: str,
    search_path: Path,
    effective_limit: int,
    ops: FindOperations,
    signal: Optional[Event],
) -> ToolResult:
    """
    Execute find using custom operations (e.g., SSH, Docker).
    
    This path is used when the user provides custom filesystem operations,
    typically for remote execution scenarios.
    
    Args:
        pattern: Glob pattern to match
        search_path: Absolute path to search in
        effective_limit: Maximum number of results
        ops: Custom operations implementation
        signal: Optional abort signal
        
    Returns:
        ToolResult with found files
        
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

    # Execute custom glob operation
    results = await maybe_await(ops.glob(pattern, str(search_path), {
        "ignore": [],
        "limit": effective_limit,
    }))

    # Check abort after glob operation
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")

    # Handle empty results
    if len(results) == 0:
        return ToolResult(
            content=[TextContent(text="No files found matching pattern")],
            details=None,
        )
    
    # Relativize paths (convert absolute to relative)
    relativized = []
    search_path_str = str(search_path)

    for p in results:
        if p.startswith(search_path_str):
            # Remove search_path prefix
            relative = p[len(search_path_str):].lstrip('/')
            relativized.append(relative)
        else:
            # Use Path.relative_to for proper relative path calculation
            try:
                relative = str(Path(p).relative_to(search_path))
                relativized.append(relative)
            except ValueError:
                # If relative_to fails, just use the path as-is
                relativized.append(p)
    
    # Format and truncate results
    return _format_results(relativized, effective_limit)

async def _execute_with_fd_binary(
    pattern: str,
    search_path: Path,
    effective_limit: int,
    signal: Optional[Event],
) -> ToolResult:
    """
    Execute find using fd binary (default path).
    
    This is the high-performance path that uses the fd binary
    for fast file searching with .gitignore support.
    
    Args:
        pattern: Glob pattern to match
        search_path: Absolute path to search in
        effective_limit: Maximum number of results
        signal: Optional abort signal
        
    Returns:
        ToolResult with found files
        
    Raises:
        AbortedError: If cancelled
        BinaryNotFoundError: If fd binary not available
        RuntimeError: If fd execution fails
    """
    # Check abort before starting
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Ensure fd binary is available
    try:
        fd_path = ensure_fd(silent=True)
    except BinaryNotFoundError as e:
        raise RuntimeError(str(e))
    
    # Build fd command arguments
    args = [
        fd_path,
        "--glob",           # Treat pattern as glob, not regex
        "--color=never",    # No ANSI color codes
        "--hidden",         # Include hidden files
        "--max-results",
        str(effective_limit),
    ]
    
    # Find all .gitignore files in the search path
    gitignore_files = _find_gitignore_files(search_path)
    
    # Add each .gitignore file to fd arguments
    for gitignore_path in gitignore_files:
        args.extend(["--ignore-file", str(gitignore_path)])
    
    # Add pattern and search path
    args.append(pattern)
    args.append(str(search_path))
    
    # Check abort before executing
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Execute fd
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=60,  # 60 second timeout
            # Note: We don't check signal during subprocess execution
            # For true async cancellation, you'd need to use asyncio.create_subprocess_exec
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"fd command timed out after 60 seconds")
    except Exception as e:
        raise RuntimeError(f"Failed to run fd: {e}")
    
    # Check abort after execution
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Get output
    output = result.stdout.strip()
    
    # Check for errors
    if result.returncode != 0:
        error_msg = result.stderr.strip() or f"fd exited with code {result.returncode}"
        # If we have output despite error, continue (fd sometimes returns non-zero with results)
        if not output:
            raise RuntimeError(error_msg)
    
    # Handle empty results
    if not output:
        return ToolResult(
            content=[TextContent(text="No files found matching pattern")],
            details=None,
        )
    
    # Parse output lines
    lines = output.split("\n")
    relativized = []
    search_path_str = str(search_path)
    
    for raw_line in lines:
        # Remove carriage return and whitespace
        line = raw_line.rstrip("\r").strip()
        if not line:
            continue
        
        # Check if line has trailing slash (directory indicator)
        had_trailing_slash = line.endswith("/") or line.endswith("\\")
        
        # Relativize path
        if line.startswith(search_path_str):
            # Remove search_path prefix
            relative_path = line[len(search_path_str):].lstrip("/\\")
        else:
            # Use Path.relative_to
            try:
                relative_path = str(Path(line).relative_to(search_path))
            except ValueError:
                # If relative_to fails, use as-is
                relative_path = line
        
        # Restore trailing slash if it was there
        if had_trailing_slash and not relative_path.endswith("/"):
            relative_path += "/"
        
        relativized.append(relative_path)
    
    # Format and return results
    return _format_results(relativized, effective_limit)
 
 
def _find_gitignore_files(search_path: Path) -> list[Path]:
    """
    Find all .gitignore files in the search path.
    
    Args:
        search_path: Directory to search in
        
    Returns:
        List of absolute paths to .gitignore files
        
    Note:
        Ignores node_modules and .git directories to avoid slowdowns.
    """
    gitignore_files = []
    
    # Check for root .gitignore
    root_gitignore = search_path / ".gitignore"
    if root_gitignore.exists():
        gitignore_files.append(root_gitignore)
    
    # Find nested .gitignore files
    try:
        # Use rglob to recursively find .gitignore files
        for gitignore in search_path.rglob(".gitignore"):
            # Skip if in node_modules or .git
            parts = gitignore.parts
            if "node_modules" in parts or ".git" in parts:
                continue
            
            gitignore_files.append(gitignore)
    except (PermissionError, OSError):
        # Ignore permission errors during glob
        pass
    
    return gitignore_files

def _format_results(
    relativized: list[str],
    effective_limit: int,
) -> ToolResult:
    """
    Format find results with truncation and notices.
    
    Args:
        relativized: List of relative file paths
        effective_limit: The limit that was applied
        
    Returns:
        ToolResult with formatted content and details
    """
    # Check if result limit was reached
    result_limit_reached = len(relativized) >= effective_limit
    
    # Join paths with newlines
    raw_output = "\n".join(relativized)
    
    # Apply truncation (no line limit, only byte limit)
    truncation = truncate_head(
        raw_output,
        max_lines=sys.maxsize,  # No line limit for find results
        max_bytes=DEFAULT_MAX_BYTES,
    )
    
    # Build output with notices
    result_output = truncation.content
    details_dict = {}
    notices = []
    
    if result_limit_reached:
        notices.append(f"{effective_limit} results limit reached")
        details_dict["result_limit_reached"] = effective_limit
    
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
    details = FindToolDetails(**details_dict) if details_dict else None
    
    return ToolResult(
        content=[TextContent(text=result_output)],
        details=details,
    )

    

def create_find_tool(
    cwd: Path,
    ops: Optional[FindOperations] = None,
) -> AgentTool:
    """
    Create a find tool configured for a specific working directory.
    
    Args:
        cwd: Current working directory (workspace root)
        operations: Optional custom operations for remote execution
        
    Returns:
        AgentTool descriptor for the find tool
        
    Example:
        >>> tool = create_find_tool(Path("/home/user/project"))
        >>> result = await tool.execute("call-123", FindParams(pattern="*.py"), None)
    """
    async def execute(
        tool_call_id: str,
        params: FindParams,
        signal: Optional[Event] = None,
    ) -> ToolResult:
        """Execute the find tool."""
        return await _execute_find_tool(
            tool_call_id,
            params,
            cwd,
            ops,
            signal,
        )
    
    return AgentTool(
        name="find",
        label="find",
        description=(
            f"Search for files by glob pattern. Returns matching file paths "
            f"relative to the search directory. Respects .gitignore. "
            f"Output is truncated to {DEFAULT_LIMIT} results or "
            f"{DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first)."
        ),
        parameters_schema=FindParams,
        execute=execute,
    )
 
 
# Default find tool using current working directory
find_tool = create_find_tool(Path.cwd())