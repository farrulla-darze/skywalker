"""Agent execution engine — runs a single agent with dependencies, tools, and observability."""

import json
import logging
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import ModelMessage

from .schemas import BasicDependencies, AgentExecutorResponse, YAMLAgentConfig
from ..core.config import Config
from ..core.session import SessionManager, Message
from ..tools.registry import ToolRegistry
from ..tools.schema import AgentTool, ToolResult, TextContent
from .agent_factory import AgentFactory
from .agent_registry import AgentRegistry

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Orchestrator — discovers YAML agents, manages sessions, and builds tools."""

    def __init__(
        self,
        config: Config,
        agents_dir: str | Path = ".skywalker/agents",
    ):
        """Initialize agent runtime.

        Args:
            config: Skywalker configuration.
            agents_dir: Path to directory containing ``*.yml`` agent definitions.
        """
        self.config = config
        self.agents_dir = Path(agents_dir)

        # Resolve sessions root (expand ~)
        sessions_root = Path(config.session.sessions_root).expanduser()
        self.session_manager = SessionManager(sessions_root)

        # Enable Pydantic AI instrumentation only when Langfuse is configured
        if config.langfuse.enabled:
            try:
                PydanticAgent.instrument_all()
                logger.info("Pydantic AI instrumentation enabled (Langfuse)")
            except Exception:
                logger.warning("Failed to enable Langfuse instrumentation, continuing without tracing")

        # Create agent factory and registry
        tool_registry_base = ToolRegistry()  # Base registry for factory (tools added per-session)
        self.agent_factory = AgentFactory(
            tool_registry=tool_registry_base,
            session_manager=self.session_manager,
        )
        self.agent_registry = AgentRegistry(
            agent_factory=self.agent_factory,
            agents_dir=agents_dir,
        )

        # Extra tools (manually registered)
        self.tools: Dict[str, Any] = {}

    def discover_agents(self) -> List[YAMLAgentConfig]:
        """Scan the agents directory for YAML definitions.

        Returns:
            List of validated YAML agent configs.
        """
        # Use the agent registry to discover agents
        return self.agent_registry.discover_agents()

    def create_session(self, user_id: str | None = None) -> str:
        """Create a new session directory structure.

        Args:
            user_id: Optional user identifier stored as session metadata.

        Returns:
            Session ID.
        """
        return self.session_manager.create_session(user_id=user_id)

    def get_or_create_session(self, user_id: str) -> str:
        """Return an existing session for *user_id* or create a new one.

        Args:
            user_id: User identifier.

        Returns:
            Session ID (existing or newly created).
        """
        existing = self.session_manager.find_session_by_user(user_id)
        if existing:
            return existing
        return self.create_session(user_id=user_id)

    def build_main_agent_tools(self, session_id: str, user_id: Optional[str] = None) -> ToolRegistry:
        """Build a ToolRegistry for the main agent in a given session.

        The registry contains:
        - Default file tools (find, grep, read, write, edit) scoped to ``sessionDir``
        - Sub-agent tools from discovered YAML agents

        Args:
            session_id: Session identifier.
            user_id: Optional user identifier.

        Returns:
            ToolRegistry with native tools and sub-agent tools.
        """
        session_dir = self.session_manager.get_session_dir(session_id)
        registry = ToolRegistry.create_for_session(session_dir)

        # Register any manually-added extra tools
        for name, tool in self.tools.items():
            registry.register_tool(name, tool)

        # Create and register sub-agent tools
        sub_agent_tools = self._create_sub_agent_tools(session_id, user_id)
        for tool in sub_agent_tools:
            registry.register_tool(tool.name, tool)

        logger.debug(
            "Built tool registry for session: session_id=%s, tool_count=%d, sub_agents=%d",
            session_id,
            len(registry.get_all_tools()),
            len(sub_agent_tools),
        )

        return registry

    def _create_sub_agent_tools(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> List[AgentTool]:
        """Create sub-agent tools from YAML configurations.

        Each sub-agent is wrapped as a callable tool that creates a new
        AgentExecutor instance for execution.

        Args:
            session_id: Session identifier.
            user_id: Optional user identifier.

        Returns:
            List of AgentTool instances for sub-agents.
        """
        from .agent_factory import AgentAsToolParams

        sub_agent_tools = []
        agent_configs = self.agent_registry.get_all_agent_configs()

        for agent_config in agent_configs:
            if agent_config.trigger.type != "sub_agent":
                continue

            # Create closure to capture agent_config and runtime properly
            def create_execute_fn(config: YAMLAgentConfig, runtime: "AgentRuntime"):
                async def execute(
                    tool_call_id: str,
                    params: AgentAsToolParams,
                    signal=None,
                ) -> ToolResult:
                    """Execute the sub-agent."""
                    logger.info(
                        "Sub-agent tool invoked: agent=%s, session_id=%s, query_length=%d",
                        config.name,
                        session_id,
                        len(params.query),
                    )

                    try:
                        # Get tools for this sub-agent from YAML config
                        sub_agent_tool_names = config.tools.include or []
                        sub_agent_tools_list = []

                        # Build a temporary tool registry for this sub-agent
                        # with the tools it needs from the global registry
                        from ..tools.registry import ToolRegistry
                        temp_registry = ToolRegistry()

                        for tool_name in sub_agent_tool_names:
                            # Try to get tool from runtime's extra tools dict
                            tool = runtime.tools.get(tool_name)
                            if tool:
                                sub_agent_tools_list.append(tool)
                                temp_registry.register_tool(tool_name, tool)
                            else:
                                logger.warning(
                                    "Sub-agent '%s' requested tool '%s' but it's not available in runtime.tools",
                                    config.name,
                                    tool_name,
                                )

                        # Create AgentExecutor for this sub-agent
                        executor = AgentExecutor(
                            agent_name=config.name,
                            system_prompt=config.prompt,  # YAMLAgentConfig uses 'prompt' not 'system_prompt'
                            model=config.model or runtime.config.models.default,
                            config=runtime.config,
                            session_manager=runtime.session_manager,
                            tools=sub_agent_tools_list,
                        )

                        # Execute the sub-agent using get_response
                        result = await executor.get_response(
                            session_id=session_id,
                            user_id=user_id or "unknown",
                            message=params.query,
                            save_to_history=True,
                        )

                        if result.success:
                            logger.info(
                                "Sub-agent execution completed: agent=%s, response_length=%d",
                                config.name,
                                len(result.response),
                            )
                            return ToolResult(content=[TextContent(text=result.response)])
                        else:
                            error_msg = result.error or "Unknown error"
                            logger.error(
                                "Sub-agent execution failed: agent=%s, error=%s",
                                config.name,
                                error_msg,
                            )
                            return ToolResult(
                                content=[TextContent(text=f"Sub-agent '{config.name}' error: {error_msg}")]
                            )

                    except Exception as e:
                        error_text = f"Sub-agent '{config.name}' failed: {str(e)}"
                        logger.error(
                            "Sub-agent tool exception: agent=%s, error=%s",
                            config.name,
                            str(e),
                            exc_info=True,
                        )
                        return ToolResult(content=[TextContent(text=error_text)])

                return execute

            execute_fn = create_execute_fn(agent_config, self)  # Pass runtime (self) to closure

            tool = AgentTool(
                name=agent_config.name,
                label=agent_config.name,
                description=agent_config.description,
                parameters_schema=AgentAsToolParams,
                execute=execute_fn,
            )
            sub_agent_tools.append(tool)

            logger.debug(
                "Created sub-agent tool: name=%s, session_id=%s",
                agent_config.name,
                session_id,
            )

        if sub_agent_tools:
            logger.info(
                "Created %d sub-agent tool(s): %s",
                len(sub_agent_tools),
                [t.name for t in sub_agent_tools],
            )

        return sub_agent_tools

    def register_extra_tool(self, name: str, tool: Any) -> None:
        """Register a non-default tool (e.g. bash, slack).

        Args:
            name: Tool name.
            tool: AgentTool instance.
        """
        self.tools[name] = tool

    def get_extra_tool(self, name: str) -> Optional[Any]:
        """Get a registered extra tool by name."""
        return self.tools.get(name)


class AgentExecutor:
    """Execution engine for running agents with full observability and context management.

    AgentExecutor is the central execution engine that:
    - Composes the final prompt (template + context)
    - Instantiates PydanticAgent with tools
    - Manages observability/token tracking via Langfuse
    - Emits structured results

    Design principles:
    - Separation of concerns: Focuses solely on execution; orchestration lives elsewhere
    - Observability-first: Every major step is tracked via Langfuse
    - Reusable: Works for direct calls, delegated runs, agent-as-tool scenarios
    """

    def __init__(
        self,
        agent_name: str,
        system_prompt: str,
        model: str,
        config: Config,
        session_manager: SessionManager,
        tools: Optional[List[AgentTool]] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        """Initialize the agent executor.

        Args:
            agent_name: Name of the agent (for logging and tracing).
            system_prompt: Base system prompt (context will be added).
            model: Model string (e.g., "openai:gpt-4", "anthropic:claude-3-5-sonnet").
            config: Global configuration (for Langfuse settings).
            session_manager: Session manager for conversation history.
            tools: List of AgentTool instances to register.
            tool_registry: Optional ToolRegistry for looking up additional tools.
        """
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.model = model
        self.config = config
        self.session_manager = session_manager
        self.tools = tools or []
        self.tool_registry = tool_registry

        # Normalize model string (provider/model → provider:model)
        if "/" in self.model and ":" not in self.model:
            self.model = self.model.replace("/", ":", 1)

        # Create PydanticAgent (tools will be registered after initialization)
        self.pydantic_agent = PydanticAgent(
            model=self.model,
            system_prompt="",  # Will be set dynamically in each run
            instrument=True,
        )

        # Register tools directly on the PydanticAgent
        if self.tools:
            for tool in self.tools:
                # Create a wrapper that adapts our AgentTool to pydantic-ai format
                # Our tools have signature: execute(tool_call_id, params, signal=None)
                # But pydantic-ai expects: execute(tool_call_id, params)
                # So we need to wrap and exclude the signal parameter

                # Create wrapper using a closure to capture both exec_fn AND params_cls
                # IMPORTANT: Both must be captured in the factory to avoid late-binding issues
                def make_wrapper(exec_fn, param_schema):
                    async def wrapper(tool_call_id: str, params: param_schema):
                        # Call original execute without signal parameter
                        return await exec_fn(tool_call_id, params, signal=None)
                    return wrapper

                execute_fn = make_wrapper(tool.execute, tool.parameters_schema)

                # Register tool with pydantic-ai using tool_plain
                self.pydantic_agent.tool_plain(
                    execute_fn,
                    name=tool.name,
                    description=tool.description,
                )

            tool_names = [t.name for t in self.tools]
            logger.info(
                "AgentExecutor '%s' initialized: model=%s, tool_count=%d, tools=%s",
                self.agent_name,
                self.model,
                len(tool_names),
                tool_names,
            )
            # Log detailed tool information for debugging
            for tool in self.tools:
                logger.debug(
                    "  → Tool '%s' bound to AgentExecutor '%s': description=%s",
                    tool.name,
                    self.agent_name,
                    tool.description[:80] + "..." if len(tool.description) > 80 else tool.description,
                )
        else:
            logger.info(
                "AgentExecutor '%s' initialized: model=%s, no tools",
                self.agent_name,
                self.model,
            )

    # ========================================================================
    # Observability Helpers
    # ========================================================================

    def _init_agent_run(self, session_id: str, user_id: str, message: str) -> Any:
        """Initialize a Langfuse observation span for this agent run.

        Args:
            session_id: Session identifier.
            user_id: User identifier.
            message: User message being processed.

        Returns:
            Langfuse span context manager or nullcontext if disabled.
        """
        if not self.config.langfuse.enabled:
            return nullcontext()

        try:
            from langfuse import get_client
            client = get_client()
            return client.start_as_current_observation(
                as_type="span",
                name=f"agent_{self.agent_name}",
                metadata={
                    "session_id": session_id,
                    "user_id": user_id,
                    "agent_name": self.agent_name,
                    "model": self.model,
                },
                input={"message": message},
            )
        except Exception as e:
            logger.debug("Langfuse unavailable: %s", str(e))
            return nullcontext()

    def _add_context_to_agent_run(self, span: Any, context: Dict[str, Any]) -> None:
        """Add context metadata to the current Langfuse span.

        Args:
            span: Langfuse span object.
            context: Context dictionary to add.
        """
        if span is not None and hasattr(span, "update"):
            try:
                span.update(metadata={"context": context})
            except Exception as e:
                logger.debug("Failed to update Langfuse span: %s", str(e))

    def _end_agent_run_with_success(
        self,
        span: Any,
        response: str,
        tool_calls: Optional[List[Dict[str, Any]]],
        tokens_used: Dict[str, int],
    ) -> None:
        """End the Langfuse span with success status.

        Args:
            span: Langfuse span object.
            response: Agent response text.
            tool_calls: List of tool calls made during execution.
            tokens_used: Token usage statistics.
        """
        if span is not None and hasattr(span, "update"):
            try:
                span.update(
                    output={
                        "response": response,
                        "tool_calls": tool_calls or [],
                    },
                    metadata={
                        "tokens": tokens_used,
                    },
                    level="DEFAULT",
                )
            except Exception as e:
                logger.debug("Failed to end Langfuse span: %s", str(e))

    def _end_agent_run_with_error(self, span: Any, error: str) -> None:
        """End the Langfuse span with error status.

        Args:
            span: Langfuse span object.
            error: Error message.
        """
        if span is not None and hasattr(span, "update"):
            try:
                span.update(
                    output={"error": error},
                    level="ERROR",
                    status_message=error,
                )
            except Exception as e:
                logger.debug("Failed to end Langfuse span: %s", str(e))

    # ========================================================================
    # Context Management
    # ========================================================================

    def _get_context(
        self,
        session_id: str,
        user_id: str,
        agent_name: str,
    ) -> str:
        """Build the dynamic context for this agent run.

        Combines:
        - Current datetime
        - User/session identifiers
        - Base system prompt
        - Conversation history (if available)

        Args:
            session_id: Session identifier.
            user_id: User identifier.
            agent_name: Name of the agent (for loading conversation history).

        Returns:
            Complete context string to prepend to system prompt.
        """
        current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Load conversation history for this agent
        history = self.session_manager.load_conversation(session_id, agent_name)

        # Build context header
        context_parts = [
            f"Current Date/Time: {current_datetime}",
            f"User ID: {user_id}",
            f"Session ID: {session_id}",
            "",
            self.system_prompt,
        ]

        # Optionally include recent conversation summary
        if history and len(history) > 0:
            context_parts.append("")
            context_parts.append("=== Recent Conversation ===")
            # Include last N messages for context (e.g., last 5 exchanges)
            recent_history = history[-10:] if len(history) > 10 else history
            for msg in recent_history:
                context_parts.append(f"{msg.role.upper()}: {msg.content[:200]}")

        return "\n".join(context_parts)

    def _build_message_history(
        self,
        session_id: str,
        agent_name: str,
    ) -> List[Dict[str, str]]:
        """Build pydantic-ai compatible message history from session.

        Args:
            session_id: Session identifier.
            agent_name: Name of the agent (for loading conversation history).

        Returns:
            List of message dictionaries with 'role' and 'content'.
        """
        history = self.session_manager.load_conversation(session_id, agent_name)
        message_history = []

        for msg in history:
            if msg.role in ("user", "assistant"):
                message_history.append({
                    "role": msg.role,
                    "content": msg.content,
                })

        return message_history

    # ========================================================================
    # Tool Call Extraction
    # ========================================================================

    def _extract_tool_calls(self, result) -> Optional[List[Dict[str, Any]]]:
        """Extract tool calls and results from pydantic-ai AgentRunResult.

        Returns a list of dicts with format:
        [
            {
                "name": "tool_name",
                "args": {...},
                "result": "tool result text"
            },
            ...
        ]

        Args:
            result: PydanticAI AgentRunResult object.

        Returns:
            List of tool call dictionaries or None if no tool calls.
        """
        try:
            messages = result.new_messages()
            tool_calls = []
            tool_call_map = {}

            for msg in messages:
                if hasattr(msg, 'parts'):
                    for part in msg.parts:
                        part_kind = getattr(part, 'part_kind', None)

                        if part_kind == 'tool-call':
                            tool_call_id = part.tool_call_id
                            args = part.args
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = None
                            elif not isinstance(args, dict):
                                args = None

                            tool_call_map[tool_call_id] = {
                                "name": part.tool_name,
                                "args": args
                            }

                        elif part_kind == 'tool-return':
                            tool_call_id = part.tool_call_id
                            if tool_call_id in tool_call_map:
                                call_data = tool_call_map[tool_call_id]
                                tool_calls.append({
                                    "name": call_data["name"],
                                    "args": call_data["args"],
                                    "result": str(part.content)
                                })

            return tool_calls if tool_calls else None

        except Exception as e:
            logger.warning("Failed to extract tool calls: %s", str(e))
            return None

    # ========================================================================
    # Main Execution Method
    # ========================================================================

    async def get_response(
        self,
        session_id: str,
        user_id: str,
        message: str,
        save_to_history: bool = True,
    ) -> AgentExecutorResponse:
        """Execute the agent and return a structured response.

        This is the main entry point for agent execution. It:
        1. Initializes observability tracking
        2. Builds context from session history
        3. Runs the PydanticAgent
        4. Extracts tool calls and response
        5. Persists messages to session
        6. Returns structured result

        Args:
            session_id: Session identifier.
            user_id: User identifier.
            message: User message to process.
            save_to_history: Whether to save messages to session history (default: True).

        Returns:
            AgentExecutorResponse with success status, response, and metadata.
        """
        logger.info(
            "AgentExecutor '%s' run started: session_id=%s, user_id=%s, message_length=%d",
            self.agent_name,
            session_id,
            user_id,
            len(message),
        )

        # Initialize Langfuse span
        span = self._init_agent_run(session_id, user_id, message)

        with span:
            try:
                # Build context for this run
                context = self._get_context(session_id, user_id, self.agent_name)
                self._add_context_to_agent_run(span, {"context_length": len(context)})

                # Update system prompt with context
                self.pydantic_agent._system_prompt = context

                # Build message history (for conversation continuity)
                message_history = self._build_message_history(session_id, self.agent_name)

                # Save user message to history before execution
                if save_to_history:
                    user_msg = Message(
                        role="user",
                        content=message,
                        metadata={"user_id": user_id},
                    )
                    self.session_manager.add_message(session_id, self.agent_name, user_msg)

                # Execute agent
                logger.debug("AgentExecutor '%s' calling pydantic_agent.run", self.agent_name)
                result = await self.pydantic_agent.run(
                    message,
                    message_history=[],  # We include history in system prompt
                )

                # Extract response
                response_text = result.output if hasattr(result, "output") else str(result)

                # Extract tool calls
                tool_calls_data = self._extract_tool_calls(result)
                if tool_calls_data:
                    logger.info(
                        "AgentExecutor '%s' tool calls: session_id=%s, tool_count=%d, tools=%s",
                        self.agent_name,
                        session_id,
                        len(tool_calls_data),
                        [tc["name"] for tc in tool_calls_data],
                    )

                # Save assistant response to history
                if save_to_history:
                    assistant_msg = Message(
                        role="assistant",
                        content=response_text,
                        tool_calls=tool_calls_data,
                    )
                    self.session_manager.add_message(session_id, self.agent_name, assistant_msg)

                # Update token counts (rough estimate)
                input_tokens = len(context + message) // 4
                output_tokens = len(response_text) // 4
                self.session_manager.update_tokens(
                    session_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

                # End span with success
                self._end_agent_run_with_success(
                    span,
                    response_text,
                    tool_calls_data,
                    {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    },
                )

                logger.info(
                    "AgentExecutor '%s' run completed: session_id=%s, response_length=%d",
                    self.agent_name,
                    session_id,
                    len(response_text),
                )

                return AgentExecutorResponse(
                    success=True,
                    session_id=session_id,
                    response=response_text,
                    tool_calls=[tc["name"] for tc in tool_calls_data] if tool_calls_data else [],
                    error=None,
                )

            except Exception as e:
                logger.error(
                    "AgentExecutor '%s' run failed: session_id=%s, error=%s",
                    self.agent_name,
                    session_id,
                    str(e),
                    exc_info=True,
                )

                error_msg = f"Agent execution error: {str(e)}"

                # Save error to history
                if save_to_history:
                    error_message = Message(
                        role="assistant",
                        content=error_msg,
                    )
                    self.session_manager.add_message(session_id, self.agent_name, error_message)

                # End span with error
                self._end_agent_run_with_error(span, error_msg)

                return AgentExecutorResponse(
                    success=False,
                    session_id=session_id,
                    response=error_msg,
                    tool_calls=[],
                    error=str(e),
                )


class BaseAgent:
    """Main orchestrator agent using Pydantic AI.

    The BaseAgent's file tools share the same ``sessionDir`` workspace
    as all sub-agents — enabling seamless file sharing.
    """

    def __init__(
        self,
        config: Config,
        runtime: AgentRuntime,
        session_id: str,
        system_prompt: str = "",
        user_id: Optional[str] = None,
    ):
        """Initialize base agent.

        Args:
            config: Global configuration.
            runtime: AgentRuntime (provides session manager, tool registry).
            session_id: Current session ID.
            system_prompt: Optional system prompt for the main agent.
            user_id: Optional user identifier for context.
        """
        self.config = config
        self.runtime = runtime
        self.session_id = session_id
        self.session_manager = runtime.session_manager
        self.user_id = user_id

        # Build tool registry with native tools AND sub-agent tools
        # The registry already includes sub-agent tools created by build_main_agent_tools()
        self.tool_registry = runtime.build_main_agent_tools(session_id, user_id)

        # Resolve model
        model_str = config.models.default
        if "/" in model_str and ":" not in model_str:
            model_str = model_str.replace("/", ":", 1)

        # Build system prompt with context
        current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        context_prompt = f"""Current Date/Time: {current_datetime}
User ID: {user_id or 'Unknown'}

{system_prompt or 'You are a helpful customer support agent.'}"""

        # Get ALL tools from registry (native + sub-agent tools)
        # BaseAgent should have access to native tools and sub-agent tools only
        all_tools = self.tool_registry.get_all_tools()
        NATIVE_TOOL_NAMES = ["find", "grep", "read", "write", "edit"]
        sub_agent_names = [
            agent.name
            for agent in runtime.agent_registry.get_all_agent_configs()
            if agent.trigger.type == "sub_agent"
        ]

        base_agent_tools = [
            t for t in all_tools
            if t.name in NATIVE_TOOL_NAMES or t.name in sub_agent_names
        ]

        # Use AgentFactory to create PydanticAgent with proper tool binding
        self.pydantic_agent = runtime.agent_factory.create_pydantic_agent(
            agent_name="main",
            system_prompt=context_prompt,
            model=model_str,
            tools=base_agent_tools,
            session_id=session_id,
        )

        # Log initialization with detailed tool information
        tool_names = [t.name for t in base_agent_tools]
        native_tools = [t.name for t in base_agent_tools if t.name in NATIVE_TOOL_NAMES]
        sub_agent_tool_names = [t.name for t in base_agent_tools if t.name in sub_agent_names]

        logger.info(
            "BaseAgent initialized: session_id=%s, user_id=%s, model=%s, tool_count=%d",
            session_id,
            user_id,
            model_str,
            len(tool_names),
        )
        logger.info(
            "BaseAgent tools bound to PydanticAgent: %s",
            tool_names,
        )
        logger.info("  → BaseAgent tool composition:")
        logger.info("     • Native file tools (%d): %s", len(native_tools), native_tools)
        logger.info("     • Sub-agent tools (%d): %s", len(sub_agent_tool_names), sub_agent_tool_names)
        logger.info("  → BaseAgent can delegate to sub-agents for specialized tasks")
        logger.info("     (web_search/rag_search via kb_agent, customer data via customer_data)")

    def _langfuse_span(self):
        """Return a Langfuse observation context manager, or nullcontext if unavailable."""
        if not self.config.langfuse.enabled:
            return nullcontext()
        try:
            from langfuse import get_client
            client = get_client()
            return client.start_as_current_observation(
                as_type="span",
                name="main_agent",
                metadata={"session_id": self.session_id},
            )
        except Exception:
            logging.getLogger(__name__).debug("Langfuse unavailable, running without tracing")
            return nullcontext()

    def _extract_tool_calls(self, result) -> List[Dict[str, Any]] | None:
        """Extract tool calls and results from pydantic-ai AgentRunResult.

        Returns a list of dicts with format:
        [
            {
                "name": "tool_name",
                "args": {...},
                "result": "tool result text"
            },
            ...
        ]
        """
        try:
            # Get new messages from this run
            messages = result.new_messages()

            tool_calls = []
            tool_call_map = {}  # Map tool_call_id -> {name, args}

            for msg in messages:
                if hasattr(msg, 'parts'):
                    for part in msg.parts:
                        part_kind = getattr(part, 'part_kind', None)

                        # Track tool calls
                        if part_kind == 'tool-call':
                            tool_call_id = part.tool_call_id
                            # Parse args if it's a JSON string
                            args = part.args
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = None
                            elif not isinstance(args, dict):
                                args = None

                            tool_call_map[tool_call_id] = {
                                "name": part.tool_name,
                                "args": args
                            }

                        # Match tool returns with their calls
                        elif part_kind == 'tool-return':
                            tool_call_id = part.tool_call_id
                            if tool_call_id in tool_call_map:
                                call_data = tool_call_map[tool_call_id]
                                # Extract text from content
                                result_text = str(part.content)

                                tool_calls.append({
                                    "name": call_data["name"],
                                    "args": call_data["args"],
                                    "result": result_text
                                })

            return tool_calls if tool_calls else None

        except Exception as e:
            logger.warning(f"Failed to extract tool calls: {e}")
            return None

    async def run(self, user_message: str, user_id: str = None, **kwargs: Any) -> Dict[str, Any]:
        """Run the agent with a user message.

        Args:
            user_message: User's message.
            user_id: Optional user identifier to include in message metadata.

        Returns:
            Agent response with metadata.
        """
        logger.info(
            "BaseAgent.run started: session_id=%s, user_id=%s, message_length=%d",
            self.session_id,
            user_id,
            len(user_message),
        )

        # Record user message with user_id in metadata
        user_msg = Message(
            role="user",
            content=user_message,
            metadata={"user_id": user_id} if user_id else None
        )
        self.session_manager.add_message(self.session_id, "main", user_msg)

        with self._langfuse_span() as root_span:
            try:
                logger.debug("Calling pydantic_agent.run with message: %s", user_message[:100])
                result = await self.pydantic_agent.run(
                    user_message,
                    message_history=[],
                )

                # Extract response text (use .output if available, fallback to str)
                response_text = result.output if hasattr(result, "output") else str(result)
                logger.info(
                    "BaseAgent.run completed: session_id=%s, response_length=%d",
                    self.session_id,
                    len(response_text),
                )

                # Extract tool calls from pydantic-ai result
                tool_calls_data = self._extract_tool_calls(result)
                if tool_calls_data:
                    logger.info(
                        "BaseAgent tool calls: session_id=%s, tool_count=%d, tools=%s",
                        self.session_id,
                        len(tool_calls_data),
                        [tc["name"] for tc in tool_calls_data],
                    )

                # Record assistant response WITH tool calls
                assistant_msg = Message(
                    role="assistant",
                    content=response_text,
                    tool_calls=tool_calls_data if tool_calls_data else None
                )
                self.session_manager.add_message(self.session_id, "main", assistant_msg)

                # Update token counts
                self.session_manager.update_tokens(
                    self.session_id,
                    input_tokens=len(user_message) // 4,
                    output_tokens=len(response_text) // 4,
                )

                if root_span is not None:
                    root_span.update(
                        input={"message": user_message},
                        output={"response": response_text},
                    )

                meta = self.session_manager.get_metadata(self.session_id)
                return {
                    "response": response_text,
                    "session_id": self.session_id,
                    "metadata": {
                        "input_tokens": meta.input_tokens if meta else 0,
                        "output_tokens": meta.output_tokens if meta else 0,
                        "total_tokens": meta.total_tokens if meta else 0,
                    },
                }

            except Exception as e:
                logger.error(
                    "BaseAgent.run error: session_id=%s, error=%s",
                    self.session_id,
                    str(e),
                    exc_info=True,
                )
                error_msg = f"Agent error: {str(e)}"

                error_message = Message(role="assistant", content=error_msg)
                self.session_manager.add_message(self.session_id, "main", error_message)

                if root_span is not None:
                    root_span.update(
                        input={"message": user_message},
                        output={"error": error_msg},
                        level="ERROR",
                        status_message=str(e),
                    )

                return {
                    "response": error_msg,
                    "session_id": self.session_id,
                    "error": str(e),
                    "metadata": {},
                }
