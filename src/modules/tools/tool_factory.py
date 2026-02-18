"""Tool factory — converts tool definitions into runtime PydanticTool instances."""

import logging
import unicodedata
from typing import Any, Callable, List

from pydantic import BaseModel, Field
from pydantic_ai.tools import Tool as PydanticTool
from pydantic_ai.toolsets import FunctionToolset

from .enums import ToolsetTypeEnum
from .schema import AgentTool

logger = logging.getLogger(__name__)


# ============================================================================
# Agent-as-Tool Factory
# ============================================================================


class AgentAsToolParams(BaseModel):
    """Standard input schema for agent-as-tool invocations."""
    query: str = Field(..., description="The query or task to send to the agent")


class AgentAsToolFactory:
    """Factory for converting an agent configuration into a PydanticTool.

    Agent-as-tool exposes a simple {query: string} schema because it only
    needs a freeform prompt. The factory wraps the agent execution logic
    into a callable tool that other agents can invoke.
    """

    def __init__(
        self,
        name: str,
        description: str,
        agent_executor: Callable[[str], Any],
    ):
        """Initialize the agent-as-tool factory.

        Args:
            name: Tool name (used for registration).
            description: Tool description shown to the LLM.
            agent_executor: Async callable that executes the agent with a query string.
        """
        self.name = name
        self.description = description
        self.agent_executor = agent_executor

    @staticmethod
    def _to_ascii(text: str) -> str:
        """Convert text to ASCII, removing accents and special characters."""
        normalized = unicodedata.normalize("NFKD", text)
        return normalized.encode("ascii", "ignore").decode("ascii")

    def create_tool(self) -> PydanticTool:
        """Create a PydanticTool that delegates to the agent executor.

        Returns:
            PydanticTool instance ready for registration.
        """
        tool_name = self._to_ascii(self.name.lower().replace(" ", "_"))

        async def agent_tool_function(query: str) -> str:
            """Execute the agent with the provided query."""
            logger.info("AgentTool '%s' invoked with query: %s", tool_name, query[:100])
            try:
                result = await self.agent_executor(query)
                return str(result)
            except Exception as e:
                logger.error("AgentTool '%s' execution failed: %s", tool_name, str(e), exc_info=True)
                return f"Error executing {tool_name}: {str(e)}"

        return PydanticTool.from_schema(
            function=agent_tool_function,
            name=tool_name,
            description=self.description,
            json_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The query that will be used to execute the agent"
                    }
                },
                "required": ["query"]
            },
        )


# ============================================================================
# Toolset Factory
# ============================================================================


class ToolsetFactory:
    """Factory for building FunctionToolset instances from tool definitions.

    Given a list of AgentTool instances or tool names, builds the appropriate
    FunctionToolset that PydanticAgent.run() can consume.

    Supports:
    - NATIVE: Built-in file tools (find, grep, read, write, edit)
    - KNOWLEDGE: Knowledge retrieval tools (web_search, rag_search)
    - AGENT: Agent-as-tools
    - CUSTOM: Custom tools with specific schemas
    """

    def __init__(self, tool_registry: "ToolRegistry" = None):
        """Initialize the toolset factory.

        Args:
            tool_registry: Optional ToolRegistry for looking up tools by name.
        """
        self.tool_registry = tool_registry

    def create_toolset(
        self,
        tools: List[AgentTool] = None,
        tool_names: List[str] = None,
        toolset_type: ToolsetTypeEnum = ToolsetTypeEnum.CUSTOM,
    ) -> FunctionToolset:
        """Create a FunctionToolset from a list of tools or tool names.

        Args:
            tools: List of AgentTool instances to include.
            tool_names: List of tool names to look up in the registry.
            toolset_type: Type of toolset being created (for logging/metadata).

        Returns:
            FunctionToolset instance ready for agent registration.

        Raises:
            ValueError: If neither tools nor tool_names is provided, or if
                        tool_names are provided without a registry.
        """
        if tools is None and tool_names is None:
            raise ValueError("Either 'tools' or 'tool_names' must be provided")

        # Resolve tool_names to AgentTool instances if needed
        if tool_names:
            if not self.tool_registry:
                raise ValueError("tool_registry is required when using tool_names")

            resolved_tools = []
            for name in tool_names:
                tool = self.tool_registry.get_tool(name)
                if tool is None:
                    logger.warning("Tool '%s' not found in registry, skipping", name)
                    continue
                resolved_tools.append(tool)

            tools = resolved_tools

        if not tools:
            logger.warning("No tools available for toolset type '%s'", toolset_type)
            return FunctionToolset()

        logger.info(
            "Creating toolset: type=%s, tool_count=%d, tools=%s",
            toolset_type,
            len(tools),
            [t.name for t in tools],
        )

        # Build FunctionToolset with all tools
        # Note: We'll use the tool_bridge pattern to register these on an agent
        # FunctionToolset is primarily used for grouping tools together
        toolset = FunctionToolset()

        return toolset

    def create_native_toolset(self) -> List[AgentTool]:
        """Create the native toolset (file operations).

        Returns:
            List of native AgentTool instances.
        """
        if not self.tool_registry:
            logger.warning("No tool registry available for native toolset")
            return []

        native_tool_names = ["find", "grep", "read", "write", "edit"]
        return self.tool_registry.filter_tools(allow=native_tool_names)

    def create_knowledge_toolset(self) -> List[AgentTool]:
        """Create the knowledge toolset (web_search, rag_search).

        Returns:
            List of knowledge AgentTool instances.
        """
        if not self.tool_registry:
            logger.warning("No tool registry available for knowledge toolset")
            return []

        knowledge_tool_names = ["web_search", "rag_search"]
        return self.tool_registry.filter_tools(allow=knowledge_tool_names)

    def create_tools_for_agent(
        self,
        include_native: bool = True,
        additional_tools: List[str] = None,
    ) -> List[AgentTool]:
        """Create a complete tool list for an agent.

        This is the main entry point for building agent tool configurations.
        Native tools are always included by default.

        Args:
            include_native: Whether to include native file tools (default: True).
            additional_tools: List of additional tool names to include.

        Returns:
            List of AgentTool instances ready for registration.
        """
        tools = []

        # Always include native tools unless explicitly disabled
        if include_native:
            tools.extend(self.create_native_toolset())

        # Add additional tools if specified
        if additional_tools:
            additional = self.tool_registry.filter_tools(allow=additional_tools)
            tools.extend(additional)

        logger.info(
            "Created agent tool configuration: native=%s, additional=%s, total=%d",
            include_native,
            additional_tools or [],
            len(tools),
        )

        return tools
