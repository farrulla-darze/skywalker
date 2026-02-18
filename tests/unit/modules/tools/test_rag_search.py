"""Tests for rag_search tool."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest


_SRC = Path(__file__).resolve().parents[4] / "src"


def _ensure_package(name: str, path: Path):
    """Ensure a namespace package exists in sys.modules for direct-loaded modules."""
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]
        sys.modules[name] = pkg


def _load_module(dotted: str):
    parts = dotted.split(".")
    file_path = _SRC.joinpath(*parts).with_suffix(".py")
    spec = importlib.util.spec_from_file_location(dotted, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_rag_search_module():
    """Load rag_search.py with a lightweight vector_store stub."""
    _ensure_package("modules", _SRC / "modules")
    _ensure_package("modules.tools", _SRC / "modules" / "tools")
    _ensure_package("modules.knowledge_bases", _SRC / "modules" / "knowledge_bases")

    kb_vector_store_module = "modules.knowledge_bases.vector_store"
    if kb_vector_store_module not in sys.modules:
        stub = types.ModuleType(kb_vector_store_module)

        class PineconeVectorStore:  # pragma: no cover - type placeholder for import
            pass

        stub.PineconeVectorStore = PineconeVectorStore
        sys.modules[kb_vector_store_module] = stub

    # Ensure required relatives are loaded before rag_search
    _load_module("modules.tools.enums")
    _load_module("modules.tools.schema")

    return _load_module("modules.tools.rag_search")


class TestRagSearchTool:
    @pytest.mark.asyncio
    async def test_execute_uses_namespace_from_environment(self, monkeypatch):
        rag_search = _load_rag_search_module()

        captured = {}

        class FakeVectorStore:
            async def query(self, query_text, top_k, namespace, filter):
                captured["query_text"] = query_text
                captured["top_k"] = top_k
                captured["namespace"] = namespace
                return [
                    {
                        "id": "doc-1",
                        "score": 0.91,
                        "metadata": {
                            "chunk_text": "CloudWalk supports instant settlements.",
                            "source_url": "https://example.com/doc",
                        },
                    }
                ]

        monkeypatch.setenv("PINECONE_NAMESPACE", "infinitepay")
        monkeypatch.setattr(rag_search, "get_vector_store", lambda: FakeVectorStore())

        tool = rag_search.create_rag_search_tool()
        params = rag_search.RagSearchParams(query="instant settlement", top_k=3)

        result = await tool.execute("tool-call-1", params)

        assert captured["query_text"] == "instant settlement"
        assert captured["top_k"] == 3
        assert captured["namespace"] == "infinitepay"
        assert len(result.content) == 1
        assert "Knowledge base results for 'instant settlement':" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execute_explicit_namespace_overrides_environment(self, monkeypatch):
        rag_search = _load_rag_search_module()

        captured = {}

        class FakeVectorStore:
            async def query(self, query_text, top_k, namespace, filter):
                captured["namespace"] = namespace
                return []

        monkeypatch.setenv("PINECONE_NAMESPACE", "infinitepay")
        monkeypatch.setattr(rag_search, "get_vector_store", lambda: FakeVectorStore())

        tool = rag_search.create_rag_search_tool()
        params = rag_search.RagSearchParams(query="fees", namespace="custom-ns")

        result = await tool.execute("tool-call-2", params)

        assert captured["namespace"] == "custom-ns"
        assert len(result.content) == 1
        assert "No results found in knowledge base for: fees" in result.content[0].text
