"""
Tools package - Agent tools for file operations and search.

Exports tool instances (ready to use) and factories (for custom config).
"""

from .schema import (
    AgentTool,
    ToolResult,
    TextContent,
    ImageContent,
    FindParams,
    FindToolDetails,
    GrepParams,
    GrepToolDetails,
    ReadParams,
    ReadToolDetails,
    WriteParams,
    EditParams,
    EditToolDetails,
    GetCustomerOverviewParams,
    GetRecentOperationsParams,
    GetActiveIncidentsParams,
)

from .find import find_tool, create_find_tool
from .grep import grep_tool, create_grep_tool
from .read import read_tool, create_read_tool
from .write import write_tool, create_write_tool
from .edit import edit_tool, create_edit_tool
from .support_db import (
    create_get_customer_overview_tool,
    create_get_recent_operations_tool,
    create_get_active_incidents_tool,
)
from .registry import ToolRegistry, Tool

__all__ = [
    # Schema types
    "AgentTool",
    "ToolResult",
    "TextContent",
    "ImageContent",
    "FindParams",
    "FindToolDetails",
    "GrepParams",
    "GrepToolDetails",
    "ReadParams",
    "ReadToolDetails",
    "WriteParams",
    "EditParams",
    "EditToolDetails",
    "GetCustomerOverviewParams",
    "GetRecentOperationsParams",
    "GetActiveIncidentsParams",
    # Tool instances
    "find_tool",
    "grep_tool",
    "read_tool",
    "write_tool",
    "edit_tool",
    # Tool factories
    "create_find_tool",
    "create_grep_tool",
    "create_read_tool",
    "create_write_tool",
    "create_edit_tool",
    "create_get_customer_overview_tool",
    "create_get_recent_operations_tool",
    "create_get_active_incidents_tool",
    # Registry
    "ToolRegistry",
    "Tool",
]
