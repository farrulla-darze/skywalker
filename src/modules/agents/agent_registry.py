"""Agent registry — manages discovery, storage, and retrieval of sub-agents.

This module consolidates agent management logic including:
- Discovering agents from YAML files
- Storing agent configurations
- Creating sub-agent tools for the main agent
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

from pydantic_ai import Agent as PydanticAgent

from .agent_factory import AgentFactory
from .loader import AgentLoader
from .schemas import YAMLAgentConfig
from ..tools.schema import AgentTool

if TYPE_CHECKING:
    from .agent_manager import AgentManager

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Registry for sub-agents discovered from YAML files.

    Responsibilities:
    - Discover agents from .skywalker/agents directory
    - Store agent configurations
    - Create sub-agent tools for delegation
    - Provide access to agent specs and instances

    Args:
        agent_factory: Factory for creating PydanticAgent instances
        agents_dir: Directory containing YAML agent definitions
    """

    def __init__(
        self,
        agent_factory: AgentFactory,
        agents_dir: str | Path = ".skywalker/agents",
    ):
        """Initialize the agent registry.

        Args:
            agent_factory: Factory for creating agents.
            agents_dir: Path to directory containing *.yml agent definitions.
        """
        self.agent_factory = agent_factory
        self.agents_dir = Path(agents_dir)

        # Storage for agent configurations
        self._agent_configs: Dict[str, YAMLAgentConfig] = {}

        # Storage for created PydanticAgent instances (lazy creation)
        self._pydantic_agents: Dict[str, PydanticAgent] = {}

    def discover_agents(self) -> List[YAMLAgentConfig]:
        """Discover and load agent configurations from YAML files.

        Returns:
            List of discovered agent configurations.
        """
        loader = AgentLoader(self.agents_dir)
        configs = loader.discover()

        # Store configurations
        for config in configs:
            self._agent_configs[config.name] = config

        # Define native tools that are always available
        NATIVE_TOOLS = ["find", "grep", "read", "write", "edit"]

        # Log summary
        if configs:
            logger.info(
                "AgentRegistry discovered %d agent(s) from %s",
                len(configs),
                self.agents_dir,
            )
            for config in configs:
                # Get additional tools (excluding native tools)
                yaml_tools = config.tools.include if config.tools.include else []
                additional_tools = [t for t in yaml_tools if t not in NATIVE_TOOLS]
                all_tools = NATIVE_TOOLS + additional_tools

                logger.info(
                    "  → Agent '%s': model=%s, tools=%s (native: %s, additional: %s), trigger=%s",
                    config.name,
                    config.model or "(default)",
                    all_tools,
                    NATIVE_TOOLS,
                    additional_tools if additional_tools else "[]",
                    config.trigger.type,
                )
        else:
            logger.warning(
                "AgentRegistry found no agents in %s",
                self.agents_dir,
            )

        return configs

    def get_all_agent_configs(self) -> List[YAMLAgentConfig]:
        """Get all discovered agent configurations.

        Returns:
            List of all agent configurations.
        """
        return list(self._agent_configs.values())

    def get_agent_config(self, agent_name: str) -> Optional[YAMLAgentConfig]:
        """Get agent configuration by name.

        Args:
            agent_name: Name of the agent.

        Returns:
            Agent configuration or None if not found.
        """
        return self._agent_configs.get(agent_name)

    def has_agent(self, agent_name: str) -> bool:
        """Check if an agent exists in the registry.

        Args:
            agent_name: Name of the agent to check.

        Returns:
            True if agent exists, False otherwise.
        """
        return agent_name in self._agent_configs

    def create_sub_agent_tools(
        self,
        agent_manager: "AgentManager",
        session_id: str,
        user_id: Optional[str] = None,
    ) -> List[AgentTool]:
        """Create sub-agent tools for all registered agents.

        These tools allow the main agent to delegate to sub-agents.

        Args:
            agent_manager: AgentManager for delegation.
            session_id: Current session ID.
            user_id: Optional user identifier.

        Returns:
            List of AgentTool instances for sub-agents.
        """
        sub_agent_tools = []

        for config in self._agent_configs.values():
            # Only create tools for sub-agent type agents
            if config.trigger.type != "sub_agent":
                continue

            tool = self.agent_factory.create_sub_agent_tool(
                yaml_config=config,
                agent_manager=agent_manager,
                session_id=session_id,
                user_id=user_id,
            )
            sub_agent_tools.append(tool)

            logger.debug(
                "Created sub-agent tool: name=%s, session_id=%s",
                config.name,
                session_id,
            )

        if sub_agent_tools:
            logger.info(
                "AgentRegistry created %d sub-agent tool(s): %s",
                len(sub_agent_tools),
                [t.name for t in sub_agent_tools],
            )

        return sub_agent_tools

    def get_agent_names(self) -> List[str]:
        """Get list of all registered agent names.

        Returns:
            List of agent names.
        """
        return list(self._agent_configs.keys())

    def clear(self) -> None:
        """Clear all stored agents and configurations."""
        self._agent_configs.clear()
        self._pydantic_agents.clear()
        logger.info("AgentRegistry cleared")
