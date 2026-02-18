"""Tests for tool_bridge module."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Direct-load — mock pydantic_ai before importing tool_bridge
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


# Stub pydantic_ai
if "pydantic_ai" not in sys.modules:
    _pai = types.ModuleType("pydantic_ai")
    _pai.Agent = MagicMock
    sys.modules["pydantic_ai"] = _pai

_tool_schema = _load_module("modules.tools.schema")
_bridge = _load_module("modules.agents.tool_bridge")

AgentTool = _tool_schema.AgentTool
ToolResult = _tool_schema.ToolResult
TextContent = _tool_schema.TextContent
register_tools_on_agent = _bridge.register_tools_on_agent


class TestRegisterToolsOnAgent:
    def test_registers_tool_on_pydantic_agent(self):
        """Verify that register_tools_on_agent calls agent.tool_plain for each tool."""
        from pydantic import BaseModel, Field

        class Params(BaseModel):
            query: str = Field(default="test")

        async def execute(tool_call_id, params, signal=None):
            return ToolResult(content=[TextContent(text="result")])

        tool = AgentTool(
            name="my_tool",
            label="my_tool",
            description="A test tool",
            parameters_schema=Params,
            execute=execute,
        )

        registered = []

        class FakeAgent:
            def tool_plain(self, fn, name=None, description=None):
                registered.append({"name": name, "description": description, "fn": fn})

        fake = FakeAgent()
        register_tools_on_agent(fake, [tool])

        assert len(registered) == 1
        assert registered[0]["name"] == "my_tool"
        assert registered[0]["description"] == "A test tool"

    def test_registers_multiple_tools(self):
        from pydantic import BaseModel

        class P(BaseModel):
            x: str = "a"

        async def noop(tool_call_id, params, signal=None):
            return ToolResult(content=[TextContent(text="")])

        tools = [
            AgentTool(name=f"t{i}", label=f"t{i}", description=f"Tool {i}",
                      parameters_schema=P, execute=noop)
            for i in range(3)
        ]

        registered = []

        class FakeAgent:
            def tool_plain(self, fn, name=None, description=None):
                registered.append(name)

        fake = FakeAgent()
        register_tools_on_agent(fake, tools)

        assert registered == ["t0", "t1", "t2"]
