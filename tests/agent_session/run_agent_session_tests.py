from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx


PREVIEW_CHARS_FILE = 100
PREVIEW_CHARS_MESSAGE = 200


@dataclass
class TestCase:
    name: str
    description: str
    default_question: str
    default_user_id: str
    default_session_id: Optional[str]
    default_chat_url: str
    sessions_root: str


def _load_test_cases(path: Path) -> List[TestCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    tests = raw.get("tests", [])
    cases: List[TestCase] = []
    for t in tests:
        cases.append(
            TestCase(
                name=t["name"],
                description=t.get("description", ""),
                default_question=t["default_question"],
                default_user_id=t["default_user_id"],
                default_session_id=t.get("default_session_id"),
                default_chat_url=t["default_chat_url"],
                sessions_root=t["sessions_root"],
            )
        )
    return cases


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run /chat agent_session test cases")
    parser.add_argument(
        "--test",
        default=None,
        help="Run only the test with this name (default: run all)",
    )
    parser.add_argument(
        "--question",
        default=None,
        help="Override the default_question for the selected test(s)",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        dest="user_id",
        help="Override the default_user_id for the selected test(s)",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        dest="session_id",
        help="Override the default_session_id (use 'none' to force null)",
    )
    return parser.parse_args()


def _normalize_session_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value.strip().lower() in {"none", "null", ""}:
        return None
    return value


def _call_chat(chat_url: str, user_id: str, question: str, session_id: Optional[str]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "userId": user_id,
        "question": question,
    }
    if session_id is not None:
        payload["sessionId"] = session_id

    timeout_s = float(os.getenv("CHAT_TIMEOUT", "180"))

    with httpx.Client(timeout=timeout_s) as client:
        resp = client.post(chat_url, json=payload)
        resp.raise_for_status()
        return resp.json()


def _preview_text(text: str, max_chars: int) -> str:
    cleaned = text.replace("\r\n", "\n")
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1] + "…"


def _iterate_files(root: Path) -> Iterable[Path]:
    for p in sorted(root.rglob("*")):
        if p.is_file():
            yield p


def _file_preview(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "<binary>"
    except Exception as exc:
        return f"<error reading file: {exc}>"
    return _preview_text(text, PREVIEW_CHARS_FILE)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not path.exists():
        return items
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except Exception:
            items.append({"_raw": line})
    return items


def _format_conversations(session_dir: Path) -> str:
    conv_dir = session_dir / "conversations"
    if not conv_dir.exists():
        return "(no conversations directory found)"

    lines: List[str] = []
    jsonl_files = sorted(conv_dir.glob("*.jsonl"))
    if not jsonl_files:
        return "(no conversation jsonl files found)"

    for jsonl_path in jsonl_files:
        lines.append(f"### Conversation: `{jsonl_path.name}`")
        messages = _read_jsonl(jsonl_path)
        if not messages:
            lines.append("(empty)\n")
            continue

        for idx, msg in enumerate(messages, 1):
            role = msg.get("role", "?")
            ts = msg.get("timestamp", "")
            content = msg.get("content", "")
            lines.append(f"{idx}. **{role}** {f'({ts})' if ts else ''}")
            if content:
                lines.append("    " + _preview_text(str(content), PREVIEW_CHARS_MESSAGE).replace("\n", "\\n"))

            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                lines.append("    tool_calls:")
                for tc in tool_calls:
                    name = tc.get("name")
                    args = tc.get("args")
                    result = tc.get("result")
                    lines.append(f"      - name: {name}")
                    if args is not None:
                        try:
                            args_str = json.dumps(args, ensure_ascii=False)
                        except Exception:
                            args_str = str(args)
                        lines.append("        args: " + _preview_text(args_str, 300))
                    if result is not None:
                        lines.append("        result: " + _preview_text(str(result), 300).replace("\n", "\\n"))

            metadata = msg.get("metadata")
            if isinstance(metadata, dict) and metadata:
                try:
                    meta_str = json.dumps(metadata, ensure_ascii=False)
                except Exception:
                    meta_str = str(metadata)
                lines.append("    metadata: " + _preview_text(meta_str, 400))

        lines.append("")

    return "\n".join(lines).strip()


def _format_session_files(session_dir: Path) -> str:
    if not session_dir.exists():
        return f"(session dir not found: {session_dir})"

    lines: List[str] = []
    for p in _iterate_files(session_dir):
        rel = p.relative_to(session_dir)
        preview = _file_preview(p)
        preview_oneline = preview.replace("\n", "\\n")
        lines.append(f"- `{rel}`: {preview_oneline}")
    return "\n".join(lines) if lines else "(no files)"


def _write_result_file(results_dir: Path, test_name: str, content: str) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{test_name}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def _run_case(case: TestCase, overrides: argparse.Namespace) -> None:
    question = overrides.question if overrides.question is not None else case.default_question
    user_id = overrides.user_id if overrides.user_id is not None else case.default_user_id
    session_id = (
        _normalize_session_id(overrides.session_id)
        if overrides.session_id is not None
        else _normalize_session_id(case.default_session_id)
    )

    sep = "=" * 72
    print(f"\n{sep}")
    print(f"TEST: {case.name}")
    print(f"{sep}")
    print(f"Description : {case.description}")
    print(f"chat_url    : {case.default_chat_url}")
    print(f"user_id     : {user_id}")
    print(f"session_id  : {session_id!r}")
    print(f"question    : {question}")
    print(sep)

    try:
        response_json = _call_chat(
            chat_url=case.default_chat_url,
            user_id=user_id,
            question=question,
            session_id=session_id,
        )
    except Exception as exc:
        print(f"\n[ERROR] HTTP call failed for test '{case.name}': {exc}")
        _write_error_result(case, question, user_id, session_id, str(exc))
        return

    print("\n=== /chat Response ===")
    print(json.dumps(response_json, indent=2, ensure_ascii=False))

    returned_session_id = response_json.get("sessionId")

    sessions_root = Path(case.sessions_root).expanduser()
    session_dir = sessions_root / str(returned_session_id) if returned_session_id else None

    session_files = _format_session_files(session_dir) if session_dir else "(no sessionId in response)"
    conversations = _format_conversations(session_dir) if session_dir else "(no sessionId in response)"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    report = "\n".join(
        [
            f"# Agent Session Test Result: {case.name}",
            "",
            f"Generated: {now}",
            "",
            "## Description (human)",
            case.description,
            "",
            "## Request",
            f"- chat_url: `{case.default_chat_url}`",
            f"- user_id: `{user_id}`",
            f"- session_id (sent): `{session_id}`",
            f"- question: {question}",
            "",
            "## Response", 
            "```json",
            json.dumps(response_json, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Session Files (name + first 100 chars)",
            session_files,
            "",
            "## Conversations (structured)",
            conversations,
            "",
        ]
    )

    results_dir = Path(__file__).resolve().parent / "results"
    out_path = _write_result_file(results_dir, case.name, report)
    print(f"\nWrote result file: {out_path}")


def _write_error_result(
    case: TestCase,
    question: str,
    user_id: str,
    session_id: Optional[str],
    error: str,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report = "\n".join(
        [
            f"# Agent Session Test Result: {case.name}",
            "",
            f"Generated: {now}",
            "",
            "## Description (human)",
            case.description,
            "",
            "## Request",
            f"- chat_url: `{case.default_chat_url}`",
            f"- user_id: `{user_id}`",
            f"- session_id (sent): `{session_id}`",
            f"- question: {question}",
            "",
            "## Result",
            f"**ERROR:** {error}",
            "",
        ]
    )
    results_dir = Path(__file__).resolve().parent / "results"
    out_path = _write_result_file(results_dir, case.name, report)
    print(f"Wrote error result file: {out_path}")


def main() -> None:
    args = _parse_args()
    cases_path = Path(__file__).resolve().parent / "test_cases.json"
    cases = _load_test_cases(cases_path)

    if args.test:
        cases = [c for c in cases if c.name == args.test]
        if not cases:
            available = ", ".join(c.name for c in _load_test_cases(cases_path))
            raise SystemExit(f"Test '{args.test}' not found. Available: {available}")

    print(f"Running {len(cases)} test(s) from test_cases.json")
    for case in cases:
        _run_case(case, args)


if __name__ == "__main__":
    main()
