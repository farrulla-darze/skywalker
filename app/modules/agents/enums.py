"""Agents module enums."""

from enum import StrEnum


class AgentKind(StrEnum):
    ROUTER = "router"          # entry-point orchestrator
    SPECIALIST = "specialist"  # delegated sub-agent (exposed to the router as a tool)
