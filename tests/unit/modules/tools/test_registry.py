"""Tests for ToolRegistry."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Direct-load — avoiding relative imports by pre-loading dependencies
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


_schema = _load_module("modules.tools.schema")

AgentTool = _schema.AgentTool
ToolResult = _schema.ToolResult
TextContent = _schema.TextContent


def _make_tool(name: str) -> AgentTool:
    """Helper to create a dummy AgentTool."""
    from pydantic import BaseModel, Field

    class DummyParams(BaseModel):
        value: str = Field(default="x")

    async def dummy_execute(tool_call_id, params, signal=None):
        return ToolResult(content=[TextContent(text="ok")])

    return AgentTool(
        name=name,
        label=name,
        description=f"Dummy {name} tool",
        parameters_schema=DummyParams,
        execute=dummy_execute,
    )


class ToolRegistry:
    """Minimal reimplementation for unit testing — mirrors registry.py logic."""

    def __init__(self):
        self._tools = {}

    def register_tool(self, name, tool):
        self._tools[name] = tool

    def get_tool(self, name):
        return self._tools.get(name)

    def get_all_tools(self):
        return list(self._tools.values())

    def filter_tools(self, allow=None, deny=None):
        tools = self.get_all_tools()
        if allow is not None:
            allowed = set(allow)
            tools = [t for t in tools if t.name in allowed]
        if deny is not None:
            denied = set(deny)
            tools = [t for t in tools if t.name not in denied]
        return tools


# Load the real registry using a trick: pre-populate sys.modules
# with the tool factories as stubs so we can test the class logic.
def _load_registry():
    """Load registry.py, substituting tool factory imports with stubs."""
    # Create stub modules for find, grep, read, write, edit
    for tool_name in ("find", "grep", "read", "write", "edit"):
        mod_name = f"modules.tools.{tool_name}"
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)

            def _make_factory(tn):
                def create_tool(cwd, **kwargs):
                    return _make_tool(tn)
                return create_tool

            setattr(stub, f"create_{tool_name}_tool", _make_factory(tool_name))
            setattr(stub, f"{tool_name}_tool", _make_tool(tool_name))
            sys.modules[mod_name] = stub

    return _load_module("modules.tools.registry")


_registry = _load_registry()
RealToolRegistry = _registry.ToolRegistry
Tool = _registry.Tool


class TestToolRegistry:
    def test_register_and_get(self):
        reg = RealToolRegistry()
        tool = _make_tool("foo")
        reg.register_tool("foo", tool)
        assert reg.get_tool("foo") is tool

    def test_get_missing_returns_none(self):
        reg = RealToolRegistry()
        assert reg.get_tool("missing") is None

    def test_get_all_tools(self):
        reg = RealToolRegistry()
        reg.register_tool("a", _make_tool("a"))
        reg.register_tool("b", _make_tool("b"))
        tools = reg.get_all_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"a", "b"}

    def test_filter_allow(self):
        reg = RealToolRegistry()
        reg.register_tool("a", _make_tool("a"))
        reg.register_tool("b", _make_tool("b"))
        reg.register_tool("c", _make_tool("c"))
        filtered = reg.filter_tools(allow=["a", "c"])
        assert len(filtered) == 2
        names = {t.name for t in filtered}
        assert names == {"a", "c"}

    def test_filter_deny(self):
        reg = RealToolRegistry()
        reg.register_tool("a", _make_tool("a"))
        reg.register_tool("b", _make_tool("b"))
        reg.register_tool("c", _make_tool("c"))
        filtered = reg.filter_tools(deny=["b"])
        assert len(filtered) == 2
        names = {t.name for t in filtered}
        assert names == {"a", "c"}

    def test_filter_allow_and_deny(self):
        reg = RealToolRegistry()
        reg.register_tool("a", _make_tool("a"))
        reg.register_tool("b", _make_tool("b"))
        reg.register_tool("c", _make_tool("c"))
        filtered = reg.filter_tools(allow=["a", "b"], deny=["b"])
        assert len(filtered) == 1
        assert filtered[0].name == "a"

    def test_filter_no_filters(self):
        reg = RealToolRegistry()
        reg.register_tool("x", _make_tool("x"))
        filtered = reg.filter_tools()
        assert len(filtered) == 1

    def test_create_for_session(self, tmp_path: Path):
        session_dir = tmp_path / "sessionDir"
        reg = RealToolRegistry.create_for_session(session_dir)
        assert session_dir.exists()
        names = {t.name for t in reg.get_all_tools()}
        assert names == {"find", "grep", "read", "write", "edit"}

    def test_tool_alias(self):
        assert Tool is AgentTool
