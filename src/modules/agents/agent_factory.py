"""Agent factory — creates and configures PydanticAgent instances with proper tool binding.

This module consolidates agent creation logic including:
- Tool binding from AgentTool to PydanticAgent
- Sub-agent wrapping as callable tools
- Tool call logging to session files
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent as PydanticAgent

from ..tools.registry import ToolRegistry
from ..tools.schema import AgentTool, ToolResult, TextContent
from .schemas import YAMLAgentConfig

if TYPE_CHECKING:
    from ..core.session import SessionManager
    from .agent_manager import AgentManager

logger = logging.getLogger(__name__)


class AgentAsToolParams(BaseModel):
    """Input schema for invoking a sub-agent as a callable tool."""
    query: str = Field(..., description="The question or task to send to the sub-agent")


class AgentFactory:
    """Factory for creating PydanticAgent instances with proper tool binding.

    Responsibilities:
    - Create PydanticAgent from YAML configurations
    - Bind AgentTool instances to PydanticAgent
    - Wrap sub-agents as callable tools
    - Log all tool calls to session conversation files

    Args:
        tool_registry: Central registry of available tools
        session_manager: For logging tool calls to session files
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        session_manager: Optional["SessionManager"] = None,
    ):
        """Initialize the agent factory.

        Args:
            tool_registry: Registry containing all available tools.
            session_manager: Optional session manager for tool call logging.
        """
        self.tool_registry = tool_registry
        self.session_manager = session_manager

    def create_pydantic_agent(
        self,
        agent_name: str,
        system_prompt: str,
        model: str,
        tools: List[AgentTool],
        session_id: Optional[str] = None,
    ) -> PydanticAgent:
        """Create a PydanticAgent with tools properly bound.

        Args:
            agent_name: Name of the agent (for logging).
            system_prompt: System prompt for the agent.
            model: Model string (e.g., "openai:gpt-4").
            tools: List of AgentTool instances to bind.
            session_id: Optional session ID for tool call logging.

        Returns:
            Configured PydanticAgent instance with tools registered.
        """
        # Create the PydanticAgent
        pydantic_agent = PydanticAgent(
            model=model,
            system_prompt=system_prompt,
            instrument=True,
        )

        # Register all tools
        for tool in tools:
            self._register_tool_on_agent(
                pydantic_agent=pydantic_agent,
                tool=tool,
                agent_name=agent_name,
                session_id=session_id,
            )

        logger.info(
            "AgentFactory created PydanticAgent: name=%s, model=%s, tool_count=%d, tools=%s",
            agent_name,
            model,
            len(tools),
            [t.name for t in tools],
        )

        return pydantic_agent

    def _register_tool_on_agent(
        self,
        pydantic_agent: PydanticAgent,
        tool: AgentTool,
        agent_name: str,
        session_id: Optional[str] = None,
    ) -> None:
        """Register a single AgentTool on a PydanticAgent.

        Creates a wrapper that:
        1. Logs tool calls to session conversation file
        2. Executes the tool
        3. Extracts text from ToolResult for LLM consumption

        Args:
            pydantic_agent: The PydanticAgent to register the tool on.
            tool: The AgentTool to register.
            agent_name: Name of the agent using this tool.
            session_id: Optional session ID for logging.
        """
        params_cls = tool.parameters_schema
        execute_fn = tool.execute

        async def wrapper(params: params_cls) -> str:  # type: ignore
            """Tool wrapper that logs calls and executes the tool."""
            # Log tool call start
            logger.info(
                "Tool call started: agent=%s, tool=%s, params=%s",
                agent_name,
                tool.name,
                params.dict() if hasattr(params, "dict") else params,
            )

            # Log to session file if session manager available
            if self.session_manager and session_id:
                self._log_tool_call_to_session(
                    session_id=session_id,
                    agent_name=agent_name,
                    tool_name=tool.name,
                    params=params,
                )

            try:
                # Execute the tool
                result: ToolResult = await execute_fn(
                    tool_call_id="factory",
                    params=params,
                    signal=None,
                )

                # Extract text content from ToolResult
                parts = []
                for block in result.content:
                    if hasattr(block, "text"):
                        parts.append(block.text)

                result_text = "\n".join(parts) if parts else ""

                # Log successful completion
                logger.info(
                    "Tool call completed: agent=%s, tool=%s, result_length=%d",
                    agent_name,
                    tool.name,
                    len(result_text),
                )

                # Log result to session file
                if self.session_manager and session_id:
                    self._log_tool_result_to_session(
                        session_id=session_id,
                        agent_name=agent_name,
                        tool_name=tool.name,
                        result=result_text,
                    )

                return result_text

            except Exception as e:
                error_msg = f"Error in {tool.name}: {str(e)}"
                logger.error(
                    "Tool call error: agent=%s, tool=%s, error=%s, params=%s",
                    agent_name,
                    tool.name,
                    str(e),
                    params,
                    exc_info=True,
                )

                # Log error to session file
                if self.session_manager and session_id:
                    self._log_tool_error_to_session(
                        session_id=session_id,
                        agent_name=agent_name,
                        tool_name=tool.name,
                        error=str(e),
                    )

                return error_msg

        # Set function name for pydantic-ai
        wrapper.__name__ = tool.name

        # Register using agent.tool_plain
        pydantic_agent.tool_plain(
            wrapper,
            name=tool.name,
            description=tool.description,
        )

        logger.debug(
            "Registered tool on agent: agent=%s, tool=%s, description=%s",
            agent_name,
            tool.name,
            tool.description[:80] + "..." if len(tool.description) > 80 else tool.description,
        )

    def create_sub_agent_tool(
        self,
        yaml_config: YAMLAgentConfig,
        agent_manager: "AgentManager",
        session_id: str,
        user_id: Optional[str] = None,
    ) -> AgentTool:
        """Create an AgentTool that wraps a sub-agent for delegation.

        This allows the main agent to call sub-agents as if they were regular tools.

        Args:
            yaml_config: YAML configuration for the sub-agent.
            agent_manager: AgentManager for delegation.
            session_id: Current session ID.
            user_id: Optional user identifier.

        Returns:
            AgentTool that delegates to the sub-agent.
        """
        agent_name = yaml_config.name

        async def execute(
            tool_call_id: str,
            params: AgentAsToolParams,
            signal=None,
        ) -> ToolResult:
            """Execute the sub-agent by delegating to AgentManager."""
            logger.info(
                "Sub-agent tool invoked: agent=%s, session_id=%s, user_id=%s, query_length=%d",
                agent_name,
                session_id,
                user_id,
                len(params.query),
            )

            try:
                # Delegate to AgentManager for proper orchestration
                response = await agent_manager.delegate_to_agent(
                    agent_name=agent_name,
                    session_id=session_id,
                    user_id=user_id or "unknown",
                    message=params.query,
                )

                if response.success:
                    logger.info(
                        "Sub-agent execution completed: agent=%s, session_id=%s, response_length=%d",
                        agent_name,
                        session_id,
                        len(response.response),
                    )
                    return ToolResult(content=[TextContent(text=response.response)])
                else:
                    logger.error(
                        "Sub-agent execution failed: agent=%s, session_id=%s, error=%s",
                        agent_name,
                        session_id,
                        response.error,
                    )
                    error_text = f"Sub-agent '{agent_name}' failed: {response.error}"
                    return ToolResult(content=[TextContent(text=error_text)])

            except Exception as e:
                logger.error(
                    "Sub-agent execution error: agent=%s, session_id=%s, error=%s",
                    agent_name,
                    session_id,
                    str(e),
                    exc_info=True,
                )
                error_text = f"Sub-agent '{agent_name}' error: {str(e)}"
                return ToolResult(content=[TextContent(text=error_text)])

        return AgentTool(
            name=agent_name,
            label=agent_name,
            description=yaml_config.description,
            parameters_schema=AgentAsToolParams,
            execute=execute,
        )

    # ========================================================================
    # Tool Call Logging to Session Files
    # ========================================================================

    def _log_tool_call_to_session(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        params: Any,
    ) -> None:
        """Log tool call to session conversation file.

        Args:
            session_id: Session identifier.
            agent_name: Name of the agent making the tool call.
            tool_name: Name of the tool being called.
            params: Parameters passed to the tool.
        """
        if not self.session_manager:
            return

        try:
            from ..core.session import Message

            # Convert params to dict if possible
            params_dict = params.dict() if hasattr(params, "dict") else str(params)

            message = Message(
                role="tool",
                content=f"Tool call: {tool_name}",
                metadata={
                    "tool_name": tool_name,
                    "tool_params": params_dict,
                    "tool_status": "started",
                },
            )

            self.session_manager.add_message(session_id, agent_name, message)
            logger.debug(
                "Logged tool call to session: session_id=%s, agent=%s, tool=%s",
                session_id,
                agent_name,
                tool_name,
            )

        except Exception as e:
            logger.warning(
                "Failed to log tool call to session: %s",
                str(e),
                exc_info=True,
            )

    def _log_tool_result_to_session(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        result: str,
    ) -> None:
        """Log tool result to session conversation file.

        Args:
            session_id: Session identifier.
            agent_name: Name of the agent.
            tool_name: Name of the tool.
            result: Tool execution result.
        """
        if not self.session_manager:
            return

        try:
            from ..core.session import Message

            # Truncate long results for metadata
            result_preview = result[:200] + "..." if len(result) > 200 else result

            message = Message(
                role="tool",
                content=f"Tool result: {tool_name}",
                metadata={
                    "tool_name": tool_name,
                    "tool_status": "completed",
                    "result_preview": result_preview,
                    "result_length": len(result),
                },
            )

            self.session_manager.add_message(session_id, agent_name, message)

        except Exception as e:
            logger.warning(
                "Failed to log tool result to session: %s",
                str(e),
                exc_info=True,
            )

    def _log_tool_error_to_session(
        self,
        session_id: str,
        agent_name: str,
        tool_name: str,
        error: str,
    ) -> None:
        """Log tool error to session conversation file.

        Args:
            session_id: Session identifier.
            agent_name: Name of the agent.
            tool_name: Name of the tool.
            error: Error message.
        """
        if not self.session_manager:
            return

        try:
            from ..core.session import Message

            message = Message(
                role="tool",
                content=f"Tool error: {tool_name}",
                metadata={
                    "tool_name": tool_name,
                    "tool_status": "error",
                    "error": error,
                },
            )

            self.session_manager.add_message(session_id, agent_name, message)

        except Exception as e:
            logger.warning(
                "Failed to log tool error to session: %s",
                str(e),
                exc_info=True,
            )
