"""Workspace management for Skywalker agents."""

from pathlib import Path
from typing import Dict, List, Optional


class WorkspaceManager:
    """Manages agent workspace and bootstrap files."""
    
    # Bootstrap files that are injected into context
    BOOTSTRAP_FILES = [
        "AGENTS.md",
        "SOUL.md",
        "TOOLS.md",
        "IDENTITY.md",
        "USER.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
    ]
    
    def __init__(self, workspace_dir: str | Path):
        """Initialize workspace manager.
        
        Args:
            workspace_dir: Path to agent workspace directory
        """
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # Create memory directory
        self.memory_dir = self.workspace_dir / "memory"
        self.memory_dir.mkdir(exist_ok=True)
    
    def initialize_workspace(self) -> None:
        """Initialize workspace with default bootstrap files if missing."""
        default_contents = {
            "AGENTS.md": self._get_default_agents_md(),
            "SOUL.md": self._get_default_soul_md(),
            "TOOLS.md": self._get_default_tools_md(),
            "IDENTITY.md": self._get_default_identity_md(),
            "USER.md": self._get_default_user_md(),
            "HEARTBEAT.md": self._get_default_heartbeat_md(),
        }
        
        for filename, content in default_contents.items():
            filepath = self.workspace_dir / filename
            if not filepath.exists():
                filepath.write_text(content)
    
    def read_bootstrap_files(self, max_chars_per_file: int = 20000) -> Dict[str, str]:
        """Read all bootstrap files for context injection.
        
        Args:
            max_chars_per_file: Maximum characters to read per file
            
        Returns:
            Dictionary mapping filename to content
        """
        bootstrap_content = {}
        
        for filename in self.BOOTSTRAP_FILES:
            filepath = self.workspace_dir / filename
            
            if filepath.exists():
                content = filepath.read_text()
                if len(content) > max_chars_per_file:
                    content = content[:max_chars_per_file] + f"\n\n[... truncated at {max_chars_per_file} chars ...]"
                bootstrap_content[filename] = content
            else:
                bootstrap_content[filename] = f"[File {filename} not found]"
        
        return bootstrap_content
    
    def read_file(self, relative_path: str) -> str:
        """Read a file from workspace.
        
        Args:
            relative_path: Path relative to workspace
            
        Returns:
            File content
        """
        filepath = self.workspace_dir / relative_path
        
        # Security: ensure path is within workspace
        try:
            filepath = filepath.resolve()
            filepath.relative_to(self.workspace_dir.resolve())
        except ValueError:
            raise ValueError(f"Path {relative_path} is outside workspace")
        
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        
        return filepath.read_text()
    
    def write_file(self, relative_path: str, content: str) -> None:
        """Write a file to workspace.
        
        Args:
            relative_path: Path relative to workspace
            content: Content to write
        """
        filepath = self.workspace_dir / relative_path
        
        # Security: ensure path is within workspace
        try:
            filepath = filepath.resolve()
            filepath.relative_to(self.workspace_dir.resolve())
        except ValueError:
            raise ValueError(f"Path {relative_path} is outside workspace")
        
        # Create parent directories if needed
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        filepath.write_text(content)
    
    def list_files(self, pattern: str = "**/*") -> List[str]:
        """List files in workspace matching pattern.
        
        Args:
            pattern: Glob pattern
            
        Returns:
            List of relative file paths
        """
        files = []
        for filepath in self.workspace_dir.glob(pattern):
            if filepath.is_file():
                rel_path = filepath.relative_to(self.workspace_dir)
                files.append(str(rel_path))
        return sorted(files)
    
    # Default content for bootstrap files
    
    @staticmethod
    def _get_default_agents_md() -> str:
        return """# Agent Operating Instructions

## Purpose
You are a customer support agent designed to help customers with their questions and issues.

## Capabilities
- Search knowledge base for answers
- Fetch customer-specific data
- Escalate complex issues to human analysts via Slack
- Execute tools and scripts to gather information

## Memory
- Write important information to memory files
- Use memory/YYYY-MM-DD.md for daily notes
- Use MEMORY.md for long-term important facts

## Behavior
- Be helpful, professional, and empathetic
- Always verify information before providing answers
- Escalate when uncertain or when issue is complex
- Keep responses clear and concise
"""
    
    @staticmethod
    def _get_default_soul_md() -> str:
        return """# Agent Persona

## Tone
- Professional yet friendly
- Patient and understanding
- Clear and concise

## Boundaries
- Do not make promises you cannot keep
- Do not share customer data inappropriately
- Escalate when you're unsure
- Always prioritize customer satisfaction

## Values
- Accuracy over speed
- Transparency
- Helpfulness
"""
    
    @staticmethod
    def _get_default_tools_md() -> str:
        return """# Tool Usage Notes

## Available Tools
- `memory_search`: Search knowledge base and memory
- `memory_get`: Read specific memory files
- `read`: Read files from workspace
- `write`: Write files to workspace
- `edit`: Edit existing files
- `exec`: Execute bash scripts (sandboxed)
- `sessions_spawn`: Spawn sub-agents for parallel work

## Conventions
- Always search knowledge base before asking for escalation
- Use memory_search for semantic queries
- Write important customer interactions to memory
- Use sub-agents for time-consuming research
"""
    
    @staticmethod
    def _get_default_identity_md() -> str:
        return """# Agent Identity

**Name**: Support Agent
**Role**: Customer Support Assistant
**Emoji**: 🤖
"""
    
    @staticmethod
    def _get_default_user_md() -> str:
        return """# User Profile

This file contains information about the user/customer you're helping.
It will be populated during conversations.
"""
    
    @staticmethod
    def _get_default_heartbeat_md() -> str:
        return """# Heartbeat Checklist

- Check for pending escalations
- Review recent customer interactions
- Update memory if needed
"""
