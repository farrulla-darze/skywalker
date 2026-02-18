"""System prompt builder for Skywalker agents."""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from .workspace import WorkspaceManager


class SystemPromptBuilder:
    """Builds system prompts for agent runs."""
    
    def __init__(self, workspace_manager: WorkspaceManager):
        """Initialize system prompt builder.
        
        Args:
            workspace_manager: Workspace manager instance
        """
        self.workspace_manager = workspace_manager
    
    def build_system_prompt(
        self,
        agent_name: str,
        agent_id: str,
        tools: List[str],
        include_bootstrap: bool = True,
        prompt_mode: str = "full",
    ) -> str:
        """Build system prompt for agent.
        
        Args:
            agent_name: Agent name
            agent_id: Agent identifier
            tools: List of available tool names
            include_bootstrap: Whether to include bootstrap files
            prompt_mode: Prompt mode (full, minimal, none)
            
        Returns:
            System prompt text
        """
        if prompt_mode == "none":
            return f"You are {agent_name}, a helpful AI assistant."
        
        sections = []
        
        # Header
        sections.append(f"# {agent_name}")
        sections.append(f"Agent ID: {agent_id}")
        sections.append("")
        
        # Tooling
        if tools:
            sections.append("## Available Tools")
            sections.append("")
            sections.append("You have access to the following tools:")
            for tool in tools:
                sections.append(f"- `{tool}`")
            sections.append("")
        
        # Safety
        sections.append("## Safety Guidelines")
        sections.append("")
        sections.append("- Do not attempt to bypass security restrictions")
        sections.append("- Do not access files outside your workspace")
        sections.append("- Escalate when uncertain or when issues are complex")
        sections.append("- Protect customer privacy and data")
        sections.append("")
        
        # Workspace
        sections.append("## Workspace")
        sections.append("")
        sections.append(f"Your workspace directory: `{self.workspace_manager.workspace_dir}`")
        sections.append("")
        sections.append("All file operations are relative to this workspace.")
        sections.append("")
        
        # Current time
        sections.append("## Current Date & Time")
        sections.append("")
        now = datetime.now(timezone.utc)
        sections.append(f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        sections.append("")
        
        # Bootstrap files (Project Context)
        if include_bootstrap:
            sections.append("## Project Context")
            sections.append("")
            sections.append("The following workspace files provide context about your role and guidelines:")
            sections.append("")
            
            bootstrap_files = self.workspace_manager.read_bootstrap_files()
            for filename, content in bootstrap_files.items():
                if content and not content.startswith("[File"):
                    sections.append(f"### {filename}")
                    sections.append("")
                    sections.append(content)
                    sections.append("")
        
        # Runtime info
        sections.append("## Runtime Information")
        sections.append("")
        sections.append(f"- Agent: {agent_name} ({agent_id})")
        sections.append(f"- Mode: {prompt_mode}")
        sections.append("")
        
        return "\n".join(sections)
    
    def build_minimal_prompt(
        self,
        agent_name: str,
        agent_id: str,
        tools: List[str],
    ) -> str:
        """Build minimal system prompt for sub-agents.
        
        Args:
            agent_name: Agent name
            agent_id: Agent identifier
            tools: List of available tool names
            
        Returns:
            Minimal system prompt
        """
        return self.build_system_prompt(
            agent_name=agent_name,
            agent_id=agent_id,
            tools=tools,
            include_bootstrap=False,
            prompt_mode="minimal",
        )
