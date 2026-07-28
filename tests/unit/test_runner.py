"""Unit tests: AgentRunner — instructions, history, steps, delegation (mocked model)."""

import pytest

from app.core.config import Settings
from app.modules.agents.enums import AgentKind
from app.modules.agents.models import Agent
from app.modules.agents.runner import AgentRunner, HistoryTurn
from app.modules.tools.service import ToolRunContext, build_default_registry

pytestmark = pytest.mark.anyio

SETTINGS = Settings(
    default_model="test",  # pydantic-ai TestModel via model string is not used; we override below
    graph_enabled=False,
    support_db_path="db/support_db/support.db",
)


def make_agent(**overrides) -> Agent:
    defaults = dict(
        id="a1",
        name="Test Router",
        slug="test-router",
        description="",
        instructions="You are a test agent.",
        model=None,
        kind=AgentKind.ROUTER,
        expose_as_tool=False,
        enabled=True,
        tools=[],
        is_system=False,
    )
    defaults.update(overrides)
    return Agent(**defaults)


def make_ctx() -> ToolRunContext:
    return ToolRunContext(settings=SETTINGS, user_ref="user-1", session_id="s1")


async def test_run_returns_text_and_real_usage():
    agent = make_agent(model="test")  # pydantic-ai's built-in TestModel
    runner = AgentRunner(SETTINGS, build_default_registry(), [])
    outcome = await runner.run(agent, "hello", [], make_ctx())
    assert isinstance(outcome.text, str) and outcome.text
    # Usage must come from the model result, not len//4 estimates
    assert outcome.input_tokens > 0
    assert outcome.output_tokens > 0


async def test_history_is_passed_to_the_model():
    agent = make_agent(model="test")
    runner = AgentRunner(SETTINGS, build_default_registry(), [])
    history = [
        HistoryTurn(role="user", content="first question"),
        HistoryTurn(role="assistant", content="first answer"),
    ]
    messages = runner._build_message_history(history)
    assert len(messages) == 2
    outcome = await runner.run(agent, "follow-up", history, make_ctx())
    assert outcome.text


async def test_tool_call_is_recorded_as_step():
    # TestModel calls every registered tool once by default
    agent = make_agent(model="test", tools=["get_active_incidents"])
    runner = AgentRunner(SETTINGS, build_default_registry(), [])
    outcome = await runner.run(agent, "are there incidents?", [], make_ctx())
    tools_called = [s.tool for s in outcome.steps]
    assert "get_active_incidents" in tools_called
    step = outcome.steps[0]
    assert step.duration_ms >= 0
    assert step.result_preview


async def test_specialist_is_exposed_and_nested_steps_recorded():
    specialist = make_agent(
        id="a2",
        slug="helper",
        name="Helper",
        kind=AgentKind.SPECIALIST,
        expose_as_tool=True,
        model="test",
        tools=["get_active_incidents"],
        description="Helps with things",
    )
    router = make_agent(model="test")
    runner = AgentRunner(SETTINGS, build_default_registry(), [specialist])
    outcome = await runner.run(router, "delegate please", [], make_ctx())
    delegation = next((s for s in outcome.steps if s.tool == "agent:helper"), None)
    assert delegation is not None
    assert delegation.nested_steps, "specialist tool calls should be captured as nested steps"


async def test_unknown_tool_is_skipped_gracefully():
    agent = make_agent(model="test", tools=["ghost_tool"])
    runner = AgentRunner(SETTINGS, build_default_registry(), [])
    outcome = await runner.run(agent, "hi", [], make_ctx())
    assert outcome.text  # run succeeds; unknown tool just isn't registered
