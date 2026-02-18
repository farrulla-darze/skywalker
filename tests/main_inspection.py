"""Simple integration test for the /chat endpoint.

This script:
1. Sends a request to the running FastAPI backend (default: http://localhost:8000/chat).
2. Prints the JSON response payload.
3. Locates the corresponding session directory under ~/.skywalker/sessions/{sessionId}.
4. Produces a concise, well-formatted digest of every file in that session so you can
   quickly inspect what the agents produced (messages, metadata, etc.).

Usage:
    # Run with default values (edit them below)
    poetry run python tests/chat_session_inspector.py

    # Or override with command-line arguments
    poetry run python tests/chat_session_inspector.py \
        --question "How do I integrate CloudWalk API?" \
        --user-id tester-123

Make sure the FastAPI server is already running before executing the script.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

import httpx

# ============================================================================
# EDITABLE DEFAULTS - Modify these values to run without command-line args
# ============================================================================

DEFAULT_QUESTION = "what are my incidents registered?"
DEFAULT_USER_ID = "client009"
DEFAULT_SESSION_ID = "1726c487-4960-498c-b6fb-9d44dbe8382b"  # Set to a session ID string to continue an existing session
DEFAULT_CHAT_URL = "http://localhost:8000/chat"
DEFAULT_SESSIONS_ROOT = "~/.skywalker/sessions"
DEFAULT_TIMEOUT = 120.0  # seconds

# ============================================================================

PREVIEW_MAX_LINES = 40
PREVIEW_MAX_CHARS = 4000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exercise /chat and inspect session files.")
    parser.add_argument(
        "--chat-url",
        default=os.getenv("CHAT_URL", DEFAULT_CHAT_URL),
        help="Target /chat endpoint (default: %(default)s)",
    )
    parser.add_argument(
        "--sessions-root",
        default=os.getenv("SKYWALKER_SESSIONS_ROOT", DEFAULT_SESSIONS_ROOT),
        help="Root directory for sessions (default: %(default)s)",
    )
    parser.add_argument(
        "--user-id",
        default=DEFAULT_USER_ID,
        help=f"User ID to send with the chat request (default: {DEFAULT_USER_ID})",
    )
    parser.add_argument(
        "--question",
        default=DEFAULT_QUESTION,
        help=f"Question/prompt to send to the agent (default: {DEFAULT_QUESTION})",
    )
    parser.add_argument(
        "--session-id",
        default=DEFAULT_SESSION_ID,
        help="Optional sessionId to continue an existing session",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    return parser.parse_args()


def call_chat(chat_url: str, user_id: str, question: str, session_id: str | None, timeout: float) -> dict:
    payload = {
        "userId": user_id,
        "question": question,
    }
    if session_id:
        payload["sessionId"] = session_id

    with httpx.Client(timeout=timeout) as client:
        response = client.post(chat_url, json=payload)
        response.raise_for_status()
        return response.json()


def print_response(response_json: dict) -> None:
    print("\n=== /chat Response ===")
    print(json.dumps(response_json, indent=2, ensure_ascii=False))


def summarize_session_dir(session_dir: Path) -> None:
    if not session_dir.exists():
        print(f"\n⚠️  Session directory not found: {session_dir}")
        return

    print(f"\n=== Session Files ({session_dir}) ===")
    for path in sorted(iterate_paths(session_dir)):
        rel = path.relative_to(session_dir)
        if path.is_dir():
            print(f"[DIR]  {rel}")
        else:
            size = path.stat().st_size
            print(f"[FILE] {rel} — {size} bytes")
            preview = build_preview(path)
            if preview:
                print(indent_text(preview, prefix="       "))


def iterate_paths(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        yield path


def build_preview(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "<binary data>"
    except Exception as exc:  # pragma: no cover - defensive
        return f"<error reading file: {exc}>"

    lines = text.splitlines()
    if len(lines) > PREVIEW_MAX_LINES:
        clipped = lines[:PREVIEW_MAX_LINES]
        clipped.append("… (truncated)")
        lines = clipped

    preview_text = "\n".join(lines)
    if len(preview_text) > PREVIEW_MAX_CHARS:
        preview_text = preview_text[:PREVIEW_MAX_CHARS] + "…"
    return preview_text


def indent_text(text: str, prefix: str = "    ") -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def main() -> None:
    args = parse_args()
    response_json = call_chat(
        chat_url=args.chat_url,
        user_id=args.user_id,
        question=args.question,
        session_id=args.session_id,
        timeout=args.timeout,
    )
    print_response(response_json)

    session_id = response_json.get("sessionId")
    if not session_id:
        print("\n⚠️  No sessionId returned in response; nothing to inspect.")
        return

    sessions_root = Path(args.sessions_root).expanduser()
    session_dir = sessions_root / session_id
    summarize_session_dir(session_dir)


if __name__ == "__main__":
    main()
