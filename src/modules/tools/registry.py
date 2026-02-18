"""Tool registry — central store for AgentTool instances."""

from pathlib import Path
from typing import Dict, List, Optional

from .schema import AgentTool
from .find import create_find_tool
from .grep import create_grep_tool
from .read import create_read_tool
from .write import create_write_tool
from .edit import create_edit_tool
from .web_search import create_web_search_tool
from .rag_search import create_rag_search_tool
from .support_db import (
    create_get_active_incidents_tool,
    create_get_customer_overview_tool,
    create_get_recent_operations_tool,
)

# Type alias expected by base.py
Tool = AgentTool


class ToolRegistry:
    """Central registry of available agent tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, AgentTool] = {}

    def register_tool(self, name: str, tool: AgentTool) -> None:
        """Register a tool by name."""
        self._tools[name] = tool

    def get_tool(self, name: str) -> Optional[AgentTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> List[AgentTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def filter_tools(
        self,
        allow: Optional[List[str]] = None,
        deny: Optional[List[str]] = None,
    ) -> List[AgentTool]:
        """Return tools filtered by allow/deny lists.

        Args:
            allow: If set, only include tools whose name is in this list.
            deny: If set, exclude tools whose name is in this list.

        Returns:
            Filtered list of AgentTool.
        """
        tools = self.get_all_tools()

        if allow is not None:
            allowed = set(allow)
            tools = [t for t in tools if t.name in allowed]

        if deny is not None:
            denied = set(deny)
            tools = [t for t in tools if t.name not in denied]

        return tools

    def get_tools_by_type(self, tool_type: str) -> List[AgentTool]:
        """Get all tools of a specific type.

        Args:
            tool_type: Type of tools to retrieve (e.g., 'native', 'knowledge', 'agent').

        Returns:
            List of tools matching the specified type.
        """
        # For now, we'll use naming conventions to determine type
        # This could be enhanced with metadata on AgentTool
        if tool_type == "native":
            return self.filter_tools(allow=["find", "grep", "read", "write", "edit"])
        elif tool_type == "knowledge":
            return self.filter_tools(allow=["web_search", "rag_search"])
        else:
            return []

    def create_toolset_factory(self) -> "ToolsetFactory":
        """Create a ToolsetFactory configured with this registry.

        Returns:
            ToolsetFactory instance that can look up tools from this registry.
        """
        from .tool_factory import ToolsetFactory
        return ToolsetFactory(tool_registry=self)

    @classmethod
    def create_for_session(cls, session_dir: Path) -> "ToolRegistry":
        """Create a registry pre-loaded with the default file tools scoped to *session_dir*.

        The five default tools (find, grep, read, write, edit) all use
        *session_dir* as their working directory so every agent in the session
        shares the same workspace.

        Args:
            session_dir: Path to the session's ``sessionDir/`` workspace.

        Returns:
            A new ToolRegistry with the default tools registered.
        """
        session_dir.mkdir(parents=True, exist_ok=True)

        registry = cls()
        # Register native file tools
        registry.register_tool("find", create_find_tool(session_dir))
        registry.register_tool("grep", create_grep_tool(session_dir))
        registry.register_tool("read", create_read_tool(session_dir))
        registry.register_tool("write", create_write_tool(session_dir))
        registry.register_tool("edit", create_edit_tool(session_dir))
        # Knowledge base tools (only available to agents that explicitly include them)
        registry.register_tool("web_search", create_web_search_tool())
        registry.register_tool("rag_search", create_rag_search_tool())
        # Support database tools (only available to agents that explicitly include them)
        registry.register_tool("get_customer_overview", create_get_customer_overview_tool())
        registry.register_tool("get_recent_operations", create_get_recent_operations_tool())
        registry.register_tool("get_active_incidents", create_get_active_incidents_tool())
        return registry
