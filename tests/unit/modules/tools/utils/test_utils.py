"""Tests for src/modules/tools/utils/ (path_utils and truncate)."""

import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Direct-load helpers — bypass heavy __init__.py re-exports so we don't
# need the full dependency tree (pydantic-settings, sqlalchemy, …).
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parents[5] / "src"


def _load_module(dotted: str):
    """Import a single .py file by its dotted module path under src/."""
    parts = dotted.split(".")
    file_path = _SRC.joinpath(*parts).with_suffix(".py")
    spec = importlib.util.spec_from_file_location(dotted, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)
    return mod


_path_utils = _load_module("modules.tools.utils.path_utils")
_truncate = _load_module("modules.tools.utils.truncate")

normalize_unicode_spaces = _path_utils.normalize_unicode_spaces
normalize_at_prefix = _path_utils.normalize_at_prefix
expand_path = _path_utils.expand_path
resolve_to_cwd = _path_utils.resolve_to_cwd

format_size = _truncate.format_size
truncate_head = _truncate.truncate_head
truncate_line = _truncate.truncate_line
TruncationResult = _truncate.TruncationResult


# ---------------------------------------------------------------------------
# path_utils: normalize_unicode_spaces
# ---------------------------------------------------------------------------

class TestNormalizeUnicodeSpaces:
    def test_normal_string_unchanged(self):
        assert normalize_unicode_spaces("hello world") == "hello world"

    def test_replaces_non_breaking_space(self):
        assert normalize_unicode_spaces("hello\u00A0world") == "hello world"

    def test_replaces_various_unicode_spaces(self):
        # \u2003 = em space, \u3000 = ideographic space
        assert normalize_unicode_spaces("a\u2003b\u3000c") == "a b c"

    def test_mixed_ascii_and_unicode_spaces(self):
        assert normalize_unicode_spaces("a \u200Ab") == "a  b"

    def test_empty_string(self):
        assert normalize_unicode_spaces("") == ""


# ---------------------------------------------------------------------------
# path_utils: normalize_at_prefix
# ---------------------------------------------------------------------------

class TestNormalizeAtPrefix:
    def test_strips_at_prefix(self):
        assert normalize_at_prefix("@/some/path") == "/some/path"

    def test_no_at_prefix(self):
        assert normalize_at_prefix("/some/path") == "/some/path"

    def test_at_alone(self):
        assert normalize_at_prefix("@") == ""

    def test_empty_string(self):
        assert normalize_at_prefix("") == ""


# ---------------------------------------------------------------------------
# path_utils: expand_path
# ---------------------------------------------------------------------------

class TestExpandPath:
    def test_tilde_alone(self):
        assert expand_path("~") == str(Path.home())

    def test_tilde_subpath(self):
        result = expand_path("~/Documents/file.txt")
        assert result == str(Path.home() / "Documents/file.txt")

    def test_absolute_path_unchanged(self):
        assert expand_path("/usr/local/bin") == "/usr/local/bin"

    def test_relative_path_unchanged(self):
        assert expand_path("some/relative") == "some/relative"

    def test_unicode_spaces_normalized(self):
        result = expand_path("~/my\u00A0folder")
        assert result == str(Path.home() / "my folder")

    def test_at_prefix_expanded(self):
        result = expand_path("@~/Documents")
        expected = str(Path.home() / "Documents")
        assert result == expected


# ---------------------------------------------------------------------------
# path_utils: resolve_to_cwd
# ---------------------------------------------------------------------------

class TestResolveToCwd:
    def test_relative_resolved_against_cwd(self):
        result = resolve_to_cwd("docs/readme.md", "/home/user")
        assert result == Path("/home/user/docs/readme.md")

    def test_absolute_returned_as_is(self):
        result = resolve_to_cwd("/etc/config", "/home/user")
        assert result == Path("/etc/config")

    def test_tilde_expanded_not_joined(self):
        result = resolve_to_cwd("~/file.txt", "/home/user")
        expected = Path(str(Path.home() / "file.txt"))
        assert result == expected

    def test_cwd_as_path_object(self):
        cwd = Path("/project")
        result = resolve_to_cwd("src/main.py", cwd)
        assert result == Path("/project/src/main.py")


# ---------------------------------------------------------------------------
# truncate: format_size
# ---------------------------------------------------------------------------

class TestFormatSize:
    def test_zero_bytes(self):
        assert format_size(0) == "0B"

    def test_small_bytes(self):
        assert format_size(500) == "500B"

    def test_boundary_1023(self):
        assert format_size(1023) == "1023B"

    def test_exact_1024_shows_kb(self):
        assert format_size(1024) == "1.0KB"

    def test_kilobytes(self):
        assert format_size(1500) == "1.5KB"

    def test_megabytes(self):
        assert format_size(2 * 1024 * 1024) == "2.0MB"

    def test_fractional_megabytes(self):
        assert format_size(int(1.5 * 1024 * 1024)) == "1.5MB"


# ---------------------------------------------------------------------------
# truncate: truncate_head
# ---------------------------------------------------------------------------

class TestTruncateHead:
    def test_no_truncation_needed(self):
        result = truncate_head("line1\nline2", max_lines=10, max_bytes=1000)
        assert result.truncated is False
        assert result.truncated_by is None
        assert result.content == "line1\nline2"
        assert result.total_lines == 2
        assert result.output_lines == 2

    def test_truncated_by_lines(self):
        content = "\n".join(f"line{i}" for i in range(10))
        result = truncate_head(content, max_lines=3, max_bytes=50_000)
        assert result.truncated is True
        assert result.truncated_by == "lines"
        assert result.output_lines == 3
        assert result.content == "line0\nline1\nline2"

    def test_truncated_by_bytes(self):
        content = "aaaa\nbbbb\ncccc\ndddd"
        result = truncate_head(content, max_lines=100, max_bytes=10)
        assert result.truncated is True
        assert result.truncated_by == "bytes"
        assert len(result.content.encode("utf-8")) <= 10

    def test_first_line_exceeds_limit(self):
        content = "a" * 200 + "\nshort"
        result = truncate_head(content, max_lines=100, max_bytes=50)
        assert result.truncated is True
        assert result.first_line_exceeds_limit is True
        assert result.content == ""
        assert result.output_lines == 0

    def test_empty_content(self):
        result = truncate_head("", max_lines=10, max_bytes=1000)
        assert result.truncated is False
        assert result.content == ""
        assert result.total_lines == 1  # "".split('\n') -> ['']

    def test_metadata_fields(self):
        result = truncate_head("hello", max_lines=5, max_bytes=100)
        assert result.max_lines == 5
        assert result.max_bytes == 100
        assert result.last_line_partial is False


# ---------------------------------------------------------------------------
# truncate: truncate_line
# ---------------------------------------------------------------------------

class TestTruncateLine:
    def test_short_line_unchanged(self):
        text, was_truncated = truncate_line("short", max_chars=500)
        assert text == "short"
        assert was_truncated is False

    def test_long_line_truncated(self):
        long = "x" * 600
        text, was_truncated = truncate_line(long, max_chars=500)
        assert was_truncated is True
        assert text.endswith("... [truncated]")
        assert text.startswith("x" * 500)

    def test_exact_boundary_not_truncated(self):
        exact = "a" * 500
        text, was_truncated = truncate_line(exact, max_chars=500)
        assert text == exact
        assert was_truncated is False

    def test_one_over_boundary_truncated(self):
        text, was_truncated = truncate_line("a" * 501, max_chars=500)
        assert was_truncated is True

    def test_empty_line(self):
        text, was_truncated = truncate_line("", max_chars=500)
        assert text == ""
        assert was_truncated is False
