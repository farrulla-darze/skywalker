"""Tools module enums."""

from enum import StrEnum


class ToolCategory(StrEnum):
    KNOWLEDGE = "knowledge"  # retrieval: rag_search, web_search, graph_search
    SUPPORT = "support"      # customer data lookups
    ACTION = "action"        # side effects: escalate_to_human
