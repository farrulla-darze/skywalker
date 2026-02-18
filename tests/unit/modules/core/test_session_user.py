"""Tests for userId-based session management."""

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


_session = _load_module("modules.core.session")
SessionManager = _session.SessionManager
SessionMetadata = _session.SessionMetadata
Message = _session.Message


class TestSessionMetadataUserId:
    def test_user_id_none_by_default(self):
        meta = SessionMetadata(session_id="abc")
        assert meta.user_id is None

    def test_user_id_stored(self):
        meta = SessionMetadata(session_id="abc", user_id="user-42")
        assert meta.user_id == "user-42"


class TestCreateSessionWithUserId:
    def test_creates_with_user_id(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create_session(user_id="user-1")
        meta = sm.get_metadata(sid)
        assert meta is not None
        assert meta.user_id == "user-1"

    def test_creates_without_user_id(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create_session()
        meta = sm.get_metadata(sid)
        assert meta is not None
        assert meta.user_id is None


class TestFindSessionByUser:
    def test_finds_existing_session(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        sid = sm.create_session(user_id="alice")
        found = sm.find_session_by_user("alice")
        assert found == sid

    def test_returns_none_for_unknown_user(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        sm.create_session(user_id="alice")
        assert sm.find_session_by_user("bob") is None

    def test_returns_none_when_no_sessions(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        assert sm.find_session_by_user("anyone") is None

    def test_returns_most_recent(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        sid1 = sm.create_session(user_id="alice")
        sid2 = sm.create_session(user_id="alice")

        # sid2 was created last, so it should have the later updated_at
        found = sm.find_session_by_user("alice")
        assert found == sid2

    def test_does_not_mix_users(self, tmp_path: Path):
        sm = SessionManager(tmp_path / "sessions")
        sid_a = sm.create_session(user_id="alice")
        sid_b = sm.create_session(user_id="bob")

        assert sm.find_session_by_user("alice") == sid_a
        assert sm.find_session_by_user("bob") == sid_b

    def test_session_survives_fresh_manager(self, tmp_path: Path):
        sm1 = SessionManager(tmp_path / "sessions")
        sid = sm1.create_session(user_id="alice")

        sm2 = SessionManager(tmp_path / "sessions")
        assert sm2.find_session_by_user("alice") == sid
