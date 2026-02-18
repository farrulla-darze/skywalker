"""Session management for Skywalker agents.

Session directory layout
------------------------
::

    ~/.skywalker/sessions/{sessionId}/
    ├── sessionDir/                   # Shared workspace (cwd for ALL agents)
    ├── conversations/
    │   ├── main.jsonl                # Main agent conversation
    │   └── {agentName}.jsonl         # Sub-agent conversation
    └── session.json                  # Session metadata
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A single message in a conversation."""
    role: str  # user, assistant, system, tool
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tool_calls: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class SessionMetadata(BaseModel):
    """Persisted session metadata (session.json)."""
    session_id: str
    user_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    context_tokens: int = 0


class SessionManager:
    """Manages shared session directories and per-agent JSONL conversations."""

    def __init__(self, sessions_root: str | Path):
        """Initialize session manager.

        Args:
            sessions_root: Root directory for all sessions
                           (e.g. ``~/.skywalker/sessions/``).
        """
        self.sessions_root = Path(sessions_root)
        self.sessions_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, user_id: Optional[str] = None) -> str:
        """Create a new session with its full directory structure.

        Args:
            user_id: Optional user identifier stored as session metadata.

        Returns:
            The generated session ID.
        """
        session_id = str(uuid.uuid4())
        session_path = self._session_path(session_id)

        # Create directories
        (session_path / "sessionDir").mkdir(parents=True, exist_ok=True)
        (session_path / "conversations").mkdir(parents=True, exist_ok=True)

        # Write initial metadata
        meta = SessionMetadata(session_id=session_id, user_id=user_id)
        self._save_metadata(session_id, meta)

        return session_id

    def find_session_by_user(self, user_id: str) -> Optional[str]:
        """Find an existing session for a given user.

        Scans all session directories and returns the most recently updated
        session ID that belongs to *user_id*, or ``None`` if no session
        exists for that user.

        Args:
            user_id: User identifier to search for.

        Returns:
            Session ID or ``None``.
        """
        best_id: Optional[str] = None
        best_time: Optional[datetime] = None

        if not self.sessions_root.exists():
            return None

        for child in self.sessions_root.iterdir():
            if not child.is_dir():
                continue
            meta = self._load_metadata(child.name)
            if meta and meta.user_id == user_id:
                if best_time is None or meta.updated_at > best_time:
                    best_id = meta.session_id
                    best_time = meta.updated_at

        return best_id

    def get_session_dir(self, session_id: str) -> Path:
        """Return the shared workspace path for a session.

        Args:
            session_id: Session identifier.

        Returns:
            Absolute path to ``sessionDir/``.
        """
        return self._session_path(session_id) / "sessionDir"

    def session_exists(self, session_id: str) -> bool:
        """Check whether a session directory exists."""
        return self._session_path(session_id).is_dir()

    # ------------------------------------------------------------------
    # Conversation (JSONL) helpers
    # ------------------------------------------------------------------

    def add_message(
        self,
        session_id: str,
        conversation_name: str,
        message: Message,
    ) -> None:
        """Append a message to a conversation JSONL file.

        Args:
            session_id: Session identifier.
            conversation_name: Conversation name (e.g. ``"main"``,
                ``"kb_agent"``).  The ``.jsonl`` suffix is added automatically.
            message: Message to append.
        """
        jsonl_path = self._conversation_path(session_id, conversation_name)
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with open(jsonl_path, "a") as f:
            f.write(json.dumps(message.model_dump(exclude_none=True), default=str) + "\n")

        # Touch updated_at in metadata
        meta = self._load_metadata(session_id)
        if meta:
            meta.updated_at = datetime.now(timezone.utc)
            self._save_metadata(session_id, meta)

    def load_conversation(
        self,
        session_id: str,
        conversation_name: str,
    ) -> List[Message]:
        """Read all messages from a conversation JSONL file.

        Args:
            session_id: Session identifier.
            conversation_name: Conversation name (without ``.jsonl``).

        Returns:
            List of messages (empty list if file doesn't exist).
        """
        jsonl_path = self._conversation_path(session_id, conversation_name)
        if not jsonl_path.exists():
            return []

        messages: List[Message] = []
        with open(jsonl_path, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    messages.append(Message(**json.loads(stripped)))
        return messages

    # ------------------------------------------------------------------
    # Token tracking
    # ------------------------------------------------------------------

    def update_tokens(
        self,
        session_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        context_tokens: int = 0,
    ) -> None:
        """Accumulate token counts for the session."""
        meta = self._load_metadata(session_id)
        if meta is None:
            return
        meta.input_tokens += input_tokens
        meta.output_tokens += output_tokens
        meta.total_tokens = meta.input_tokens + meta.output_tokens
        meta.context_tokens = context_tokens
        self._save_metadata(session_id, meta)

    def get_metadata(self, session_id: str) -> Optional[SessionMetadata]:
        """Return metadata for a session (or ``None``)."""
        return self._load_metadata(session_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_root / session_id

    def _conversation_path(self, session_id: str, name: str) -> Path:
        return self._session_path(session_id) / "conversations" / f"{name}.jsonl"

    def _metadata_path(self, session_id: str) -> Path:
        return self._session_path(session_id) / "session.json"

    def _load_metadata(self, session_id: str) -> Optional[SessionMetadata]:
        path = self._metadata_path(session_id)
        if not path.exists():
            return None
        with open(path, "r") as f:
            return SessionMetadata(**json.load(f))

    def _save_metadata(self, session_id: str, meta: SessionMetadata) -> None:
        path = self._metadata_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(meta.model_dump(), f, indent=2, default=str)
