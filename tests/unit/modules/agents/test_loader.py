"""Tests for YAML agent loader."""

import importlib.util
import sys
import tempfile
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


_schema = _load_module("modules.agents.yaml_schema")
_loader = _load_module("modules.agents.loader")
AgentLoader = _loader.AgentLoader
YAMLAgentConfig = _schema.YAMLAgentConfig


class TestAgentLoader:
    def test_discover_empty_directory(self, tmp_path: Path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        loader = AgentLoader(agents_dir)
        assert loader.discover() == []

    def test_discover_nonexistent_directory(self, tmp_path: Path):
        loader = AgentLoader(tmp_path / "does_not_exist")
        assert loader.discover() == []

    def test_discover_valid_yml(self, tmp_path: Path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        yml_content = (
            "name: test_agent\n"
            "description: A test agent\n"
            "prompt: You are a test.\n"
        )
        (agents_dir / "test.yml").write_text(yml_content)

        loader = AgentLoader(agents_dir)
        configs = loader.discover()
        assert len(configs) == 1
        assert configs[0].name == "test_agent"
        assert configs[0].trigger.type == "sub_agent"

    def test_discover_multiple_yml(self, tmp_path: Path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        for i in range(3):
            yml = f"name: agent_{i}\ndescription: Agent {i}\nprompt: Prompt {i}\n"
            (agents_dir / f"agent_{i}.yml").write_text(yml)

        loader = AgentLoader(agents_dir)
        configs = loader.discover()
        assert len(configs) == 3
        names = {c.name for c in configs}
        assert names == {"agent_0", "agent_1", "agent_2"}

    def test_discover_skips_empty_yml(self, tmp_path: Path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "empty.yml").write_text("")

        loader = AgentLoader(agents_dir)
        assert loader.discover() == []

    def test_discover_invalid_yml_raises(self, tmp_path: Path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "bad.yml").write_text("name: only_name\n")

        loader = AgentLoader(agents_dir)
        with pytest.raises(Exception):
            loader.discover()

    def test_discover_ignores_non_yml(self, tmp_path: Path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "readme.md").write_text("# Not an agent")
        (agents_dir / "valid.yml").write_text(
            "name: x\ndescription: X\nprompt: P\n"
        )

        loader = AgentLoader(agents_dir)
        configs = loader.discover()
        assert len(configs) == 1
