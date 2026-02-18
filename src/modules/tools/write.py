"""
Write tool - Write content to files.

Writes content to a file, creating parent directories if needed.
Always overwrites existing files.
"""

from pathlib import Path
from threading import Event
from typing import Optional

from .schema import WriteParams, ToolResult, TextContent, AgentTool
from .utils.path_utils import resolve_to_cwd
from .utils.operations import WriteOperations, create_default_write_operations, maybe_await


class AbortedError(Exception):
    """Raised when operation is aborted via signal."""
    pass


async def _execute_write_tool(
    tool_call_id: str,
    params: WriteParams,
    cwd: Path,
    operations: Optional[WriteOperations],
    signal: Optional[Event] = None,
) -> ToolResult:
    """
    Execute the write tool operation.
    
    Args:
        tool_call_id: Unique identifier for this tool call
        params: Validated input parameters
        cwd: Current working directory (workspace root)
        operations: Optional custom operations
        signal: Optional abort signal
        
    Returns:
        ToolResult with success message
        
    Raises:
        AbortedError: If operation is cancelled
        PermissionError: If file is not writable
        OSError: If write fails
    """
    # Check if already aborted
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Resolve path
    absolute_path = resolve_to_cwd(params.path, cwd)
    
    # Get parent directory
    parent_dir = absolute_path.parent
    
    # Use default operations if not provided
    ops = operations or create_default_write_operations()
    
    # Create parent directories
    await maybe_await(ops.mkdir(str(parent_dir)))
    
    # Check abort before writing
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Write file
    await maybe_await(ops.write_file(str(absolute_path), params.content))
    
    # Check abort after writing
    if signal and signal.is_set():
        raise AbortedError("Operation aborted")
    
    # Calculate byte count
    byte_count = len(params.content.encode('utf-8'))
    
    # Return success message
    return ToolResult(
        content=[TextContent(
            text=f"Successfully wrote {byte_count} bytes to {params.path}"
        )],
        details=None,
    )


def create_write_tool(
    cwd: Path,
    operations: Optional[WriteOperations] = None,
) -> AgentTool:
    """
    Create a write tool configured for a specific working directory.
    
    Args:
        cwd: Current working directory (workspace root)
        operations: Optional custom operations for remote execution
        
    Returns:
        AgentTool descriptor for the write tool
    """
    async def execute(
        tool_call_id: str,
        params: WriteParams,
        signal: Optional[Event] = None,
    ) -> ToolResult:
        """Execute the write tool."""
        return await _execute_write_tool(
            tool_call_id,
            params,
            cwd,
            operations,
            signal,
        )
    
    return AgentTool(
        name="write",
        label="write",
        description=(
            "Write content to a file. Creates the file if it doesn't exist, "
            "overwrites if it does. Automatically creates parent directories."
        ),
        parameters_schema=WriteParams,
        execute=execute,
    )


# Default write tool
write_tool = create_write_tool(Path.cwd())