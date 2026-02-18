"""Tests for YAML agent configuration schema."""

import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Direct-load — bypass heavy __init__.py re-exports
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parents[4] / "src"


def _load_module(dotted: str):
    parts = dotted.split(".")
    file_path = _SRC.joinpath(*parts).with_suffix(".py")
    spec = importlib.util.spec_from_file_location(dotted, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)
    return mod


_schema = _load_module("modules.agents.yaml_schema")
YAMLAgentConfig = _schema.YAMLAgentConfig
TriggerConfig = _schema.TriggerConfig
AgentToolsConfig = _schema.AgentToolsConfig


class TestYAMLAgentConfig:
    def test_valid_minimal(self):
        config = YAMLAgentConfig(
            name="test_agent",
            description="A test agent",
            prompt="You are a test agent.",
        )
        assert config.name == "test_agent"
        assert config.trigger.type == "sub_agent"
        assert config.tools.include == []
        assert config.model is None

    def test_valid_full(self):
        config = YAMLAgentConfig(
            name="kb_agent",
            description="Search knowledge base",
            prompt="Search the KB.",
            trigger=TriggerConfig(type="sub_agent"),
            tools=AgentToolsConfig(include=["read", "grep"]),
            model="openai:gpt-5-nano-2025-08-07",
        )
        assert config.model == "openai:gpt-5-nano-2025-08-07"
        assert config.tools.include == ["read", "grep"]

    def test_missing_name_raises(self):
        with pytest.raises(Exception):
            YAMLAgentConfig(
                description="A test agent",
                prompt="You are a test agent.",
            )

    def test_missing_description_raises(self):
        with pytest.raises(Exception):
            YAMLAgentConfig(
                name="test_agent",
                prompt="You are a test agent.",
            )

    def test_missing_prompt_raises(self):
        with pytest.raises(Exception):
            YAMLAgentConfig(
                name="test_agent",
                description="A test agent",
            )


class TestTriggerConfig:
    def test_default_type(self):
        t = TriggerConfig()
        assert t.type == "sub_agent"

    def test_invalid_type_raises(self):
        with pytest.raises(Exception):
            TriggerConfig(type="webhook")


class TestAgentToolsConfig:
    def test_default_empty(self):
        c = AgentToolsConfig()
        assert c.include == []

    def test_with_tools(self):
        c = AgentToolsConfig(include=["read", "write"])
        assert c.include == ["read", "write"]
