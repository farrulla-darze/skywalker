"""Tests for the restructured SessionManager."""

import importlib.util
import json
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


_session = _load_module("modules.core.session")
SessionManager = _session.SessionManager
SessionMetadata = _session.SessionMetadata
Message = _session.Message


class TestSessionManager:
    def test_create_session(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        session_id = sm.create_session()

        assert session_id
        assert (tmp_path / "sessions" / session_id / "sessionDir").is_dir()
        assert (tmp_path / "sessions" / session_id / "conversations").is_dir()
        assert (tmp_path / "sessions" / session_id / "session.json").is_file()

    def test_get_session_dir(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        session_id = sm.create_session()
        session_dir = sm.get_session_dir(session_id)
        assert session_dir == tmp_path / "sessions" / session_id / "sessionDir"

    def test_session_exists(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        session_id = sm.create_session()
        assert sm.session_exists(session_id)
        assert not sm.session_exists("nonexistent")

    def test_add_and_load_messages(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        session_id = sm.create_session()

        msg1 = Message(role="user", content="Hello")
        msg2 = Message(role="assistant", content="Hi there!")

        sm.add_message(session_id, "main", msg1)
        sm.add_message(session_id, "main", msg2)

        loaded = sm.load_conversation(session_id, "main")
        assert len(loaded) == 2
        assert loaded[0].role == "user"
        assert loaded[0].content == "Hello"
        assert loaded[1].role == "assistant"
        assert loaded[1].content == "Hi there!"

    def test_load_nonexistent_conversation(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        session_id = sm.create_session()
        loaded = sm.load_conversation(session_id, "nonexistent")
        assert loaded == []

    def test_multiple_conversations(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        session_id = sm.create_session()

        sm.add_message(session_id, "main", Message(role="user", content="main msg"))
        sm.add_message(session_id, "kb_agent", Message(role="user", content="kb msg"))

        main_msgs = sm.load_conversation(session_id, "main")
        kb_msgs = sm.load_conversation(session_id, "kb_agent")

        assert len(main_msgs) == 1
        assert main_msgs[0].content == "main msg"
        assert len(kb_msgs) == 1
        assert kb_msgs[0].content == "kb msg"

    def test_update_tokens(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        session_id = sm.create_session()

        sm.update_tokens(session_id, input_tokens=100, output_tokens=50)
        meta = sm.get_metadata(session_id)
        assert meta is not None
        assert meta.input_tokens == 100
        assert meta.output_tokens == 50
        assert meta.total_tokens == 150

        # Accumulate
        sm.update_tokens(session_id, input_tokens=10, output_tokens=5)
        meta = sm.get_metadata(session_id)
        assert meta.input_tokens == 110
        assert meta.output_tokens == 55

    def test_metadata_persistence(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        session_id = sm.create_session()

        meta = sm.get_metadata(session_id)
        assert meta is not None
        assert meta.session_id == session_id

        # Load from a fresh manager instance
        sm2 = SessionManager(tmp_path / "sessions")
        meta2 = sm2.get_metadata(session_id)
        assert meta2 is not None
        assert meta2.session_id == session_id

    def test_jsonl_append_mode(self, tmp_path: Path):
        """Verify messages are appended (not overwritten)."""
        sm = SessionManager(tmp_path / "sessions")
        session_id = sm.create_session()

        for i in range(5):
            sm.add_message(
                session_id, "agent_x", Message(role="user", content=f"msg {i}")
            )

        msgs = sm.load_conversation(session_id, "agent_x")
        assert len(msgs) == 5
        assert msgs[4].content == "msg 4"
