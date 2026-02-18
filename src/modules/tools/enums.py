"""Enumerations for tool and toolset types."""

from enum import Enum


class ToolTypeEnum(str, Enum):
    """Types of tools that can be registered."""

    NATIVE = "native"      # Built-in file tools (find, grep, read, write, edit)
    AGENT = "agent"        # Agent exposed as a tool
    CUSTOM = "custom"      # Custom tool with specific schema
    KNOWLEDGE = "knowledge"  # Knowledge base tools (web_search, rag_search)


class ToolsetTypeEnum(str, Enum):
    """Types of toolsets available to agents."""

    NATIVE = "native"      # Default file tools (find, grep, read, write, edit)
    AGENT = "agent"        # Collection of agent-as-tools
    CUSTOM = "custom"      # Custom toolset with specific tools
    KNOWLEDGE = "knowledge"  # Knowledge retrieval tools (web_search, rag_search)
    