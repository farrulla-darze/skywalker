"""Live integration test for web_search tool against DuckDuckGo.

This test is intended to be runnable both with pytest and directly as a script.
It executes the real web search tool and validates that fetched results are
returned in the expected format.

Usage as standalone script:
    python tests/integration/test_web_search_live.py
    python tests/integration/test_web_search_live.py "CloudWalk payment solutions"
    python tests/integration/test_web_search_live.py "Python async best practices" --max-results 10
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.modules.tools.web_search import WebSearchParams, create_web_search_tool


def _details_as_dict(details) -> dict:
    """Normalize ToolResult.details to a plain dict for test assertions/printing."""
    if details is None:
        return {}
    if isinstance(details, dict):
        return details
    if hasattr(details, "model_dump"):
        return details.model_dump(exclude_none=True)
    return {}


@pytest.mark.asyncio
async def test_web_search_live_query_returns_real_data():
    """Query DuckDuckGo and validate response contains search results."""
    query = "CloudWalk payment gateway"

    tool = create_web_search_tool()
    params = WebSearchParams(query=query, max_results=5)

    result = await tool.execute("integration-live-web-search", params)

    assert result.content, "Expected content blocks in ToolResult"
    response_text = result.content[0].text

    # Should contain results or a no results message
    assert (
        "Search results for" in response_text or
        "No results found" in response_text
    ), "Expected search results or no results message"

    # Should not have error messages
    assert "Web search failed:" not in response_text


@pytest.mark.asyncio
async def test_web_search_max_results_limit():
    """Verify max_results parameter limits the number of results."""
    query = "Python programming"

    tool = create_web_search_tool()
    params = WebSearchParams(query=query, max_results=3)

    result = await tool.execute("integration-max-results-test", params)

    assert result.content, "Expected content blocks in ToolResult"
    assert result.details is not None

    # Check that results count doesn't exceed max_results
    details = _details_as_dict(result.details)
    results_count = details.get("results_count", 0)
    assert results_count <= 3, f"Expected at most 3 results, got {results_count}"


async def run_standalone_query(query: str, max_results: int):
    """Run a standalone web search query and print the results."""
    print("\n" + "="*80)
    print("WEB SEARCH TOOL - STANDALONE TEST")
    print("="*80)

    print(f"\n🔍 Query: {query}")
    print(f"🔢 Max Results: {max_results}")
    print("\n" + "-"*80)
    print("Executing web search...")
    print("-"*80 + "\n")

    try:
        tool = create_web_search_tool()
        params = WebSearchParams(query=query, max_results=max_results)

        result = await tool.execute("standalone-test", params)

        if result.content:
            response_text = result.content[0].text
            print("✅ TOOL RESPONSE:")
            print("\n" + "="*80)
            print(response_text)
            print("="*80 + "\n")

            # Display details
            if result.details:
                print("📊 DETAILS:")
                details = _details_as_dict(result.details)
                for key, value in details.items():
                    print(f"  {key}: {value}")
                print()

            # Analyze response
            if "Web search failed:" in response_text:
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
        description="Test web search tool with custom queries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s "CloudWalk payment solutions"
  %(prog)s "Python async programming" --max-results 10

  # Run pytest instead:
  pytest %(prog)s -v -s
        """
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="CloudWalk payment gateway features",
        help="Search query (default: 'CloudWalk payment gateway features')"
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Maximum number of results to retrieve (default: 5, max: 10)"
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
        exit_code = asyncio.run(run_standalone_query(args.query, args.max_results))
        raise SystemExit(exit_code)
