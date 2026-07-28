"""Guardrails enums."""

from enum import StrEnum


class GuardrailVerdictType(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


class GuardrailCategory(StrEnum):
    SAFE = "safe"
    PROMPT_INJECTION = "prompt_injection"
    ABUSE = "abuse"
    SENSITIVE_DATA_LEAK = "sensitive_data_leak"
    OFF_POLICY = "off_policy"
