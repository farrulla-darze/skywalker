"""Agent orchestration layer — manages lifecycle, guardrails, delegation, and execution.

AgentManager is the high-level controller that:
1. Wires user session, toolsets, and dependencies
2. Applies input/output guardrails
3. Handles delegation and multi-agent workflows
4. Coordinates observability across all execution paths
5. Instantiates AgentExecutor for actual LLM runs

Design principles:
- Clear layering: AgentManager = orchestration, AgentExecutor = execution
- Composability: Delegators recurse through get_agent_manager
- Centralized dependency hydration: All context, toolsets, metadata prepared once
- Observability-first: Every branch wrapped with Langfuse tracking
"""

import logging
from contextlib import nullcontext
from typing import Any, Dict, List, Optional

from ..core.config import Config
from ..core.session import SessionManager
from ..tools.registry import ToolRegistry
from ..tools.schema import AgentTool
from .agent_executor import AgentExecutor
from .guardrail_manager import AgentGuardrailManager
from .schemas import (
    BasicDependencies,
    ToolsetDependencies,
    AgentExecutorResponse,
    AgentGuardrailResponse,
    YAMLAgentConfig,
)
from .agent_factory import AgentFactory
from .agent_registry import AgentRegistry

logger = logging.getLogger(__name__)


class AgentManager:
    """Orchestration layer for agent lifecycle, guardrails, and multi-agent coordination.

    AgentManager transforms an agent's configuration into a ready-to-run execution
    environment, applies guardrails/delegation logic, and delegates to AgentExecutor
    for the actual LLM run.

    Key responsibilities:
    - Agent lifecycle management (creation, caching, teardown)
    - Toolset assembly with dependency injection
    - Input/output guardrail enforcement
    - Delegation to sub-agents (recursive agent invocation)
    - Observability tracking across all execution paths
    """

    def __init__(
        self,
        config: Config,
        session_manager: SessionManager,
        yaml_agents: Optional[List[YAMLAgentConfig]] = None,
        enable_guardrails: bool = True,
    ):
        """Initialize the agent manager.

        Args:
            config: Global configuration.
            session_manager: Session manager for conversation persistence.
            yaml_agents: List of YAML-defined agents available for delegation.
            enable_guardrails: Whether to enable input/output guardrails (default: True).
        """
        self.config = config
        self.session_manager = session_manager
        self.yaml_agents = yaml_agents or []
        self.enable_guardrails = enable_guardrails

        # Cache of AgentExecutor instances by (session_id, agent_name)
        self._executor_cache: Dict[str, AgentExecutor] = {}

        # Initialize guardrail manager if enabled
        self.guardrail_manager: Optional[AgentGuardrailManager] = None
        if enable_guardrails:
            self.guardrail_manager = AgentGuardrailManager(config)
            logger.info("AgentManager initialized with guardrails enabled")
        else:
            logger.info("AgentManager initialized with guardrails disabled")

    # ========================================================================
    # Observability Helpers
    # ========================================================================

    def _init_manager_span(self, agent_name: str, session_id: str, user_id: str) -> Any:
        """Initialize a Langfuse observation span for this manager orchestration.

        Args:
            agent_name: Name of the agent being orchestrated.
            session_id: Session identifier.
            user_id: User identifier.

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
                name=f"manager_{agent_name}",
                metadata={
                    "session_id": session_id,
                    "user_id": user_id,
                    "agent_name": agent_name,
                    "guardrails_enabled": self.enable_guardrails,
                },
            )
        except Exception as e:
            logger.debug("Langfuse unavailable: %s", str(e))
            return nullcontext()

    # ========================================================================
    # Toolset & Dependency Preparation
    # ========================================================================

    def _create_sub_agent_tools(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> List[AgentTool]:
        """Create sub-agent tools from YAML agent configurations.

        Each YAML agent is wrapped as a callable tool that delegates through
        AgentManager for proper orchestration.

        Args:
            session_id: Session identifier.
            user_id: Optional user identifier for context.

        Returns:
            List of AgentTool instances for sub-agents.
        """
        sub_agent_tools = []

        # Use agent_registry to create sub-agent tools
        if hasattr(self, 'agent_registry') and self.agent_registry:
            sub_agent_tools = self.agent_registry.create_sub_agent_tools(
                agent_manager=self,
                session_id=session_id,
                user_id=user_id,
            )
        else:
            # Fallback: create tools manually if agent_registry not available
            for yaml_config in self.yaml_agents:
                # Skip agents that are not sub-agents
                if yaml_config.trigger.type != "sub_agent":
                    continue

                # Create agent as tool using agent_factory
                if hasattr(self, 'agent_factory') and self.agent_factory:
                    tool = self.agent_factory.create_sub_agent_tool(
                        yaml_config=yaml_config,
                        agent_manager=self,
                        session_id=session_id,
                        user_id=user_id,
                    )
                    sub_agent_tools.append(tool)

                    logger.debug(
                        "Created sub-agent tool: name=%s, session_id=%s",
                        yaml_config.name,
                        session_id,
                    )

        if sub_agent_tools:
            logger.info(
                "Created %d sub-agent tools: %s",
                len(sub_agent_tools),
                [t.name for t in sub_agent_tools],
            )

        return sub_agent_tools

    def _prepare_toolsets_and_dependencies(
        self,
        session_id: str,
        agent_config: Optional[YAMLAgentConfig] = None,
        additional_tools: Optional[List[str]] = None,
        user_id: Optional[str] = None,
    ) -> tuple[List[AgentTool], List[ToolsetDependencies]]:
        """Prepare toolsets and their dependencies for an agent.

        Args:
            session_id: Session identifier.
            agent_config: Optional YAML agent configuration.
            additional_tools: Optional list of additional tool names.
            user_id: Optional user identifier for sub-agent tool context.

        Returns:
            Tuple of (tools, toolset_dependencies).
        """
        # Create tool registry for this session
        session_dir = self.session_manager.get_session_dir(session_id)
        registry = ToolRegistry.create_for_session(session_dir)
        factory = registry.create_toolset_factory()

        # Determine which tools to include
        tool_names = []
        if agent_config and agent_config.tools.include:
            tool_names.extend(agent_config.tools.include)
        if additional_tools:
            tool_names.extend(additional_tools)

        # Build tools (native + additional)
        tools = factory.create_tools_for_agent(
            include_native=True,
            additional_tools=tool_names if tool_names else None,
        )

        # Add sub-agent tools (agents as callable tools)
        sub_agent_tools = self._create_sub_agent_tools(session_id, user_id)
        tools.extend(sub_agent_tools)

        # Build toolset dependencies (metadata for each toolset)
        toolset_deps = []
        if tools:
            # Group tools by type (native, knowledge, agent, custom)
            native_tools = [t for t in tools if t.name in ["find", "grep", "read", "write", "edit"]]
            knowledge_tools = [t for t in tools if t.name in ["web_search", "rag_search"]]
            agent_tools = [t for t in tools if t in sub_agent_tools]

            if native_tools:
                toolset_deps.append(
                    ToolsetDependencies(
                        id="native",
                        metadata={"tool_count": len(native_tools), "tools": [t.name for t in native_tools]},
                    )
                )

            if knowledge_tools:
                toolset_deps.append(
                    ToolsetDependencies(
                        id="knowledge",
                        metadata={"tool_count": len(knowledge_tools), "tools": [t.name for t in knowledge_tools]},
                    )
                )

            if agent_tools:
                toolset_deps.append(
                    ToolsetDependencies(
                        id="agents",
                        metadata={"tool_count": len(agent_tools), "tools": [t.name for t in agent_tools]},
                    )
                )

        logger.info(
            "Prepared toolsets: session_id=%s, tool_count=%d, toolset_deps=%d",
            session_id,
            len(tools),
            len(toolset_deps),
        )

        return tools, toolset_deps

    def _build_dependencies(
        self,
        user_id: str,
        session_id: str,
        message: str,
        toolset_deps: List[ToolsetDependencies],
    ) -> BasicDependencies:
        """Build BasicDependencies for agent execution.

        Args:
            user_id: User identifier.
            session_id: Session identifier.
            message: Current user message.
            toolset_deps: List of toolset dependencies.

        Returns:
            BasicDependencies instance ready for injection.
        """
        return BasicDependencies(
            user_id=user_id,
            session_id=session_id,
            message=message,
            toolset_dependencies=toolset_deps,
        )

    # ========================================================================
    # Agent Executor Creation & Caching
    # ========================================================================

    def _get_or_create_executor(
        self,
        agent_name: str,
        session_id: str,
        system_prompt: str,
        model: str,
        tools: List[AgentTool],
        tool_registry: ToolRegistry,
    ) -> AgentExecutor:
        """Get cached executor or create a new one.

        Args:
            agent_name: Name of the agent.
            session_id: Session identifier.
            system_prompt: Agent's system prompt.
            model: Model string.
            tools: List of tools to register.
            tool_registry: Tool registry for tool lookups.

        Returns:
            AgentExecutor instance (cached or newly created).
        """
        cache_key = f"{session_id}:{agent_name}"

        # Return cached executor if available
        if cache_key in self._executor_cache:
            logger.debug("Using cached executor: %s", cache_key)
            return self._executor_cache[cache_key]

        # Create new executor
        executor = AgentExecutor(
            agent_name=agent_name,
            system_prompt=system_prompt,
            model=model,
            config=self.config,
            session_manager=self.session_manager,
            tools=tools,
            tool_registry=tool_registry,
        )

        # Cache for reuse
        self._executor_cache[cache_key] = executor
        logger.info("Created and cached new executor: %s", cache_key)

        return executor

    # ========================================================================
    # Guardrail Processing
    # ========================================================================

    async def _apply_input_guardrails(
        self,
        user_message: str,
        user_id: str,
        session_id: str,
    ) -> AgentGuardrailResponse:
        """Apply input guardrails to validate user message.

        Args:
            user_message: User's input message.
            user_id: User identifier.
            session_id: Session identifier.

        Returns:
            AgentGuardrailResponse with validation result.
        """
        if not self.enable_guardrails or not self.guardrail_manager:
            # Guardrails disabled - auto-approve
            return AgentGuardrailResponse(
                approved=True,
                reason="Guardrails disabled",
                response=None,
            )

        return await self.guardrail_manager.validate_input(
            user_message=user_message,
            user_id=user_id,
            session_id=session_id,
        )

    async def _apply_output_guardrails(
        self,
        agent_response: str,
        user_message: str,
        user_id: str,
    ) -> AgentGuardrailResponse:
        """Apply output guardrails to validate agent response.

        Args:
            agent_response: Agent's generated response.
            user_message: Original user message.
            user_id: User identifier.

        Returns:
            AgentGuardrailResponse with validation result.
        """
        if not self.enable_guardrails or not self.guardrail_manager:
            # Guardrails disabled - auto-approve
            return AgentGuardrailResponse(
                approved=True,
                reason="Guardrails disabled",
                response=None,
            )

        return await self.guardrail_manager.validate_output(
            agent_response=agent_response,
            user_message=user_message,
            user_id=user_id,
        )

    # ========================================================================
    # Delegation & Sub-Agent Invocation
    # ========================================================================

    def _find_agent_config(self, agent_name: str) -> Optional[YAMLAgentConfig]:
        """Find YAML agent configuration by name.

        Args:
            agent_name: Name of the agent to find.

        Returns:
            YAMLAgentConfig if found, None otherwise.
        """
        return next(
            (agent for agent in self.yaml_agents if agent.name == agent_name),
            None,
        )

    async def delegate_to_agent(
        self,
        agent_name: str,
        session_id: str,
        user_id: str,
        message: str,
    ) -> AgentExecutorResponse:
        """Delegate execution to a named sub-agent.

        This enables multi-agent workflows by recursively invoking other agents
        through fresh AgentManager instances.

        Args:
            agent_name: Name of the sub-agent to invoke.
            session_id: Session identifier.
            user_id: User identifier.
            message: Message to send to the sub-agent.

        Returns:
            AgentExecutorResponse from the sub-agent.
        """
        logger.info(
            "Delegating to sub-agent '%s': session_id=%s, user_id=%s",
            agent_name,
            session_id,
            user_id,
        )

        # Find agent configuration
        agent_config = self._find_agent_config(agent_name)
        if not agent_config:
            error_msg = f"Sub-agent '{agent_name}' not found"
            logger.error(error_msg)
            return AgentExecutorResponse(
                success=False,
                session_id=session_id,
                response=error_msg,
                tool_calls=[],
                error=error_msg,
            )

        # Run the sub-agent through get_response (which handles all orchestration)
        return await self.get_response(
            agent_name=agent_name,
            session_id=session_id,
            user_id=user_id,
            message=message,
            agent_config=agent_config,
        )

    # ========================================================================
    # Main Orchestration Method
    # ========================================================================

    async def get_response(
        self,
        agent_name: str,
        session_id: str,
        user_id: str,
        message: str,
        agent_config: Optional[YAMLAgentConfig] = None,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AgentExecutorResponse:
        """Get response from an agent with full orchestration.

        This is the main entry point for agent execution. It:
        1. Initializes observability tracking
        2. Applies input guardrails
        3. Prepares toolsets and dependencies
        4. Creates/retrieves AgentExecutor
        5. Executes the agent
        6. Applies output guardrails
        7. Returns structured response

        Args:
            agent_name: Name of the agent to run.
            session_id: Session identifier.
            user_id: User identifier.
            message: User message to process.
            agent_config: Optional YAML agent configuration (for sub-agents).
            system_prompt: Optional system prompt override.
            model: Optional model override.

        Returns:
            AgentExecutorResponse with execution results.
        """
        logger.info(
            "AgentManager.get_response started: agent=%s, session_id=%s, user_id=%s",
            agent_name,
            session_id,
            user_id,
        )

        # Initialize manager-level span for observability
        span = self._init_manager_span(agent_name, session_id, user_id)

        with span:
            # ================================================================
            # STEP 1: Apply Input Guardrails
            # ================================================================
            input_validation = await self._apply_input_guardrails(
                user_message=message,
                user_id=user_id,
                session_id=session_id,
            )

            if not input_validation.approved:
                # Input rejected - return pre-composed response
                logger.warning(
                    "Input guardrail rejected: agent=%s, reason=%s",
                    agent_name,
                    input_validation.reason,
                )
                return AgentExecutorResponse(
                    success=True,  # Success from orchestration perspective
                    session_id=session_id,
                    response=input_validation.response or "I cannot process this request.",
                    tool_calls=[],
                    error=None,
                )

            # ================================================================
            # STEP 2: Prepare Toolsets & Dependencies
            # ================================================================
            tools, toolset_deps = self._prepare_toolsets_and_dependencies(
                session_id=session_id,
                agent_config=agent_config,
                user_id=user_id,
            )

            # Build dependencies (prepared for future dependency injection)
            # Currently, AgentExecutor doesn't require explicit dependency passing
            # but this maintains the dependency preparation pattern for future use
            _ = self._build_dependencies(
                user_id=user_id,
                session_id=session_id,
                message=message,
                toolset_deps=toolset_deps,
            )

            # ================================================================
            # STEP 3: Create/Retrieve AgentExecutor
            # ================================================================
            session_dir = self.session_manager.get_session_dir(session_id)
            tool_registry = ToolRegistry.create_for_session(session_dir)

            # Determine system prompt and model
            final_prompt = system_prompt
            final_model = model

            if agent_config:
                final_prompt = final_prompt or agent_config.prompt
                final_model = final_model or agent_config.model

            final_prompt = final_prompt or "You are a helpful assistant."
            final_model = final_model or self.config.models.default

            executor = self._get_or_create_executor(
                agent_name=agent_name,
                session_id=session_id,
                system_prompt=final_prompt,
                model=final_model,
                tools=tools,
                tool_registry=tool_registry,
            )

            # ================================================================
            # STEP 4: Execute Agent via AgentExecutor
            # ================================================================
            response = await executor.get_response(
                session_id=session_id,
                user_id=user_id,
                message=message,
                save_to_history=True,
            )

            if not response.success:
                # Execution failed - return error response
                logger.error(
                    "AgentExecutor failed: agent=%s, error=%s",
                    agent_name,
                    response.error,
                )
                return response

            # ================================================================
            # STEP 5: Apply Output Guardrails
            # ================================================================
            output_validation = await self._apply_output_guardrails(
                agent_response=response.response,
                user_message=message,
                user_id=user_id,
            )

            if not output_validation.approved and output_validation.response:
                # Output rejected - use revised response
                logger.warning(
                    "Output guardrail revised: agent=%s, reason=%s",
                    agent_name,
                    output_validation.reason,
                )
                response.response = output_validation.response

            # ================================================================
            # STEP 6: Return Final Response
            # ================================================================
            logger.info(
                "AgentManager.get_response completed: agent=%s, session_id=%s",
                agent_name,
                session_id,
            )

            return response

    # ========================================================================
    # Helper Methods for Main Agent (Backward Compatibility)
    # ========================================================================

    async def run_main_agent(
        self,
        session_id: str,
        user_id: str,
        message: str,
        system_prompt: Optional[str] = None,
    ) -> AgentExecutorResponse:
        """Run the main orchestrator agent.

        This is a convenience method for running the main agent (as opposed to
        sub-agents defined in YAML).

        Args:
            session_id: Session identifier.
            user_id: User identifier.
            message: User message.
            system_prompt: Optional system prompt.

        Returns:
            AgentExecutorResponse from the main agent.
        """
        return await self.get_response(
            agent_name="main",
            session_id=session_id,
            user_id=user_id,
            message=message,
            system_prompt=system_prompt,
        )

    def clear_executor_cache(self, session_id: Optional[str] = None) -> None:
        """Clear cached executors.

        Args:
            session_id: Optional session ID to clear (clears all if None).
        """
        if session_id:
            # Clear only executors for this session
            keys_to_remove = [k for k in self._executor_cache if k.startswith(f"{session_id}:")]
            for key in keys_to_remove:
                del self._executor_cache[key]
            logger.info("Cleared executor cache for session: %s", session_id)
        else:
            # Clear all executors
            self._executor_cache.clear()
            logger.info("Cleared entire executor cache")
