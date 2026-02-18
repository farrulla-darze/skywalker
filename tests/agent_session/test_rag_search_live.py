"""Live integration test for rag_search tool against Pinecone data.

This test is intended to be runnable both with pytest and directly as a script.
It executes the real RAG tool with real credentials and validates that fetched
results are returned in the expected format.

Usage as standalone script:
    python tests/integration/test_rag_search_live.py
    python tests/integration/test_rag_search_live.py "What are the fees?"
    python tests/integration/test_rag_search_live.py "Query" --namespace infinitepay --top-k 5
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

import pytest

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.modules.tools.rag_search import RagSearchParams, create_rag_search_tool


REQUIRED_ENV_VARS = (
    "PINECONE_API_KEY",
    "PINECONE_INDEX_HOST",
    "OPENAI_API_KEY",
)


def _missing_env_vars() -> list[str]:
    """Return missing required environment variables for live test execution."""
    return [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]


@pytest.mark.asyncio
async def test_rag_search_live_query_returns_real_data():
    """Query real Pinecone namespace and validate response contains retrieved data."""
    missing = _missing_env_vars()
    if missing:
        pytest.skip(
            f"Skipping live rag_search integration test; missing env vars: {', '.join(missing)}"
        )

    query = os.getenv("RAG_TEST_QUERY", "Quais são as taxas da maquininha da InfinitePay?")
    namespace = os.getenv("PINECONE_NAMESPACE", "infinitepay")

    tool = create_rag_search_tool()
    params = RagSearchParams(query=query, top_k=3, namespace=namespace)

    result = await tool.execute("integration-live-rag-search", params)

    assert result.content, "Expected content blocks in ToolResult"
    response_text = result.content[0].text

    assert "Knowledge base search failed:" not in response_text
    assert "No results found" not in response_text
    assert "Knowledge base results for" in response_text
    assert "Result 1" in response_text


async def run_standalone_query(query: str, namespace: str, top_k: int):
    """Run a standalone RAG search query and print the results."""
    print("\n" + "="*80)
    print("RAG SEARCH TOOL - STANDALONE TEST")
    print("="*80)

    # Check environment variables
    missing = _missing_env_vars()
    if missing:
        print(f"\n❌ ERROR: Missing required environment variables: {', '.join(missing)}")
        print("\nPlease set:")
        for var in missing:
            print(f"  export {var}=<value>")
        return 1

    print(f"\n📝 Query: {query}")
    print(f"📁 Namespace: {namespace}")
    print(f"🔢 Top K: {top_k}")
    print("\n" + "-"*80)
    print("Executing RAG search...")
    print("-"*80 + "\n")

    try:
        tool = create_rag_search_tool()
        params = RagSearchParams(query=query, top_k=top_k, namespace=namespace)

        result = await tool.execute("standalone-test", params)

        if result.content:
            response_text = result.content[0].text
            print("✅ TOOL RESPONSE:")
            print("\n" + "="*80)
            print(response_text)
            print("="*80 + "\n")

            # Analyze response
            if "Knowledge base search failed:" in response_text:
                print("⚠️  Search failed")
                return 1
            elif "No results found" in response_text:
                print("⚠️  No results found")
                return 0
            else:
                print("✅ Tool executed successfully and returned results")
                return 0
        else:
            print("❌ No content in tool result")
            return 1

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test RAG search tool with custom queries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s "What are the InfinitePay fees?"
  %(prog)s "Query" --namespace infinitepay --top-k 5

  # Run pytest instead:
  pytest %(prog)s -v -s
        """
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=os.getenv("RAG_TEST_QUERY", "Quais são as taxas da maquininha da InfinitePay?"),
        help="Search query (default: from RAG_TEST_QUERY env or default query)"
    )
    parser.add_argument(
        "--namespace",
        default=os.getenv("PINECONE_NAMESPACE", "infinitepay"),
        help="Pinecone namespace (default: from PINECONE_NAMESPACE env or 'infinitepay')"
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Number of results to retrieve (default: 3)"
    )
    parser.add_argument(
        "--pytest",
        action="store_true",
        help="Run pytest instead of standalone mode"
    )

    args = parser.parse_args()

    if args.pytest:
        raise SystemExit(pytest.main([__file__, "-v", "-s"]))
    else:
        exit_code = asyncio.run(run_standalone_query(args.query, args.namespace, args.top_k))
        raise SystemExit(exit_code)
