"""Evaluation enums."""

from enum import StrEnum


class GoldenCategory(StrEnum):
    FEES = "fees"
    PRODUCT_HOWTO = "product_howto"
    ACCOUNT_ISSUE = "account_issue"
    GENERAL_WEB = "general_web"
    OUT_OF_SCOPE = "out_of_scope"
    ADVERSARIAL = "adversarial"
    MULTI_TURN = "multi_turn"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Provenance(StrEnum):
    CHALLENGE_SPEC = "challenge_spec"
    HANDCRAFTED = "handcrafted"
    SYNTHETIC = "synthetic"
    PRODUCTION_TRACE = "production_trace"


class ExpectedRoute(StrEnum):
    KNOWLEDGE = "knowledge"
    SUPPORT = "support"
    ESCALATION = "escalation"
    DIRECT = "direct"


class EvalLayer(StrEnum):
    RETRIEVAL = "retrieval"  # deterministic, no LLM needed
    FULL = "full"            # runs the agent end-to-end (needs LLM credentials)


class EvalRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
