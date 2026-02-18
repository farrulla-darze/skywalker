"""Tests for sub-agent tool factory."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Direct-load — mock pydantic_ai before importing sub_agent_tool
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


# Stub pydantic_ai so sub_agent_tool can import without the real package
if "pydantic_ai" not in sys.modules:
    _pai = types.ModuleType("pydantic_ai")
    _pai.Agent = MagicMock
    sys.modules["pydantic_ai"] = _pai

_schema_mod = _load_module("modules.agents.yaml_schema")
_tool_schema = _load_module("modules.tools.schema")
_session_mod = _load_module("modules.core.session")
_sub_agent_tool = _load_module("modules.agents.sub_agent_tool")

YAMLAgentConfig = _schema_mod.YAMLAgentConfig
AgentToolsConfig = _schema_mod.AgentToolsConfig
AgentTool = _tool_schema.AgentTool
SessionManager = _session_mod.SessionManager
AgentAsToolParams = _sub_agent_tool.AgentAsToolParams
create_agent_as_tool = _sub_agent_tool.create_agent_as_tool


class _FakeModelsConfig:
    default = "openai:gpt-5-mini-2025-08-07"


class _FakeConfig:
    models = _FakeModelsConfig()


class _FakeRuntime:
    """Minimal runtime stub for testing tool creation."""

    def __init__(self, tmp_path: Path):
        self.session_manager = SessionManager(tmp_path / "sessions")
        self.config = _FakeConfig()


class TestAgentAsToolParams:
    def test_task_required(self):
        with pytest.raises(Exception):
            AgentAsToolParams()

    def test_task_valid(self):
        p = AgentAsToolParams(task="Do something")
        assert p.task == "Do something"


class TestCreateAgentAsTool:
    def test_creates_agent_tool(self, tmp_path: Path):
        config = YAMLAgentConfig(
            name="test_sub",
            description="A test sub-agent",
            prompt="You are a test.",
            tools=AgentToolsConfig(include=["read"]),
        )
        runtime = _FakeRuntime(tmp_path)
        session_id = runtime.session_manager.create_session()

        tool = create_agent_as_tool(config, runtime, session_id)

        assert isinstance(tool, AgentTool)
        assert tool.name == "test_sub"
        assert tool.description == "A test sub-agent"
        assert tool.parameters_schema is AgentAsToolParams
        assert callable(tool.execute)

    def test_uses_yaml_name_as_tool_name(self, tmp_path: Path):
        config = YAMLAgentConfig(
            name="kb_agent",
            description="Knowledge base",
            prompt="Search.",
        )
        runtime = _FakeRuntime(tmp_path)
        session_id = runtime.session_manager.create_session()
        tool = create_agent_as_tool(config, runtime, session_id)
        assert tool.name == "kb_agent"

    def test_uses_yaml_description(self, tmp_path: Path):
        config = YAMLAgentConfig(
            name="agent",
            description="Custom description here",
            prompt="Prompt.",
        )
        runtime = _FakeRuntime(tmp_path)
        session_id = runtime.session_manager.create_session()
        tool = create_agent_as_tool(config, runtime, session_id)
        assert tool.description == "Custom description here"
