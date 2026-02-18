"""Tests for chat API schemas."""

import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Direct-load
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


_schemas = _load_module("modules.api.schemas")
ChatRequest = _schemas.ChatRequest
ChatResponse = _schemas.ChatResponse


class TestChatRequest:
    def test_valid_request(self):
        req = ChatRequest(userId="user-1", question="What is CloudWalk?")
        assert req.user_id == "user-1"
        assert req.question == "What is CloudWalk?"

    def test_missing_user_id_raises(self):
        with pytest.raises(Exception):
            ChatRequest(question="Hello")

    def test_missing_question_raises(self):
        with pytest.raises(Exception):
            ChatRequest(userId="user-1")

    def test_empty_user_id_raises(self):
        with pytest.raises(Exception):
            ChatRequest(userId="", question="Hello")

    def test_empty_question_raises(self):
        with pytest.raises(Exception):
            ChatRequest(userId="user-1", question="")

    def test_alias_user_id(self):
        """userId in JSON maps to user_id in Python."""
        req = ChatRequest.model_validate({"userId": "u1", "question": "Hi"})
        assert req.user_id == "u1"


class TestChatResponse:
    def test_valid_response(self):
        resp = ChatResponse(
            sessionId="sess-abc",
            response="Hello!",
            metadata={"input_tokens": 10},
        )
        assert resp.session_id == "sess-abc"
        assert resp.response == "Hello!"
        assert resp.metadata == {"input_tokens": 10}

    def test_default_metadata(self):
        resp = ChatResponse(sessionId="s1", response="Hi")
        assert resp.metadata == {}

    def test_serialisation_uses_alias(self):
        resp = ChatResponse(sessionId="s1", response="Hi")
        data = resp.model_dump(by_alias=True)
        assert "sessionId" in data
        assert "session_id" not in data
