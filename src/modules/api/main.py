"""FastAPI application — single /chat endpoint for the Skywalker agent system."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Dict, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException

from ..core.config import Config
from ..agents.agent_executor import AgentRuntime, BaseAgent
from .schemas import ChatRequest, ChatResponse
from ..knowledge_bases.router import kb_router, set_kb_service
from ..knowledge_bases.service import KnowledgeBaseService
from ..knowledge_bases.scraper import WebScraper
from ..knowledge_bases.chunker import MarkdownChunker
from ..knowledge_bases.vector_store import PineconeVectorStore

# Configure logging for the application
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# Set our modules to INFO level to see agent discovery logs
logging.getLogger('src.modules.agents').setLevel(logging.INFO)
logging.getLogger('src.modules.api').setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state initialised during the lifespan
# ---------------------------------------------------------------------------

_runtime: AgentRuntime | None = None
_agents: Dict[str, BaseAgent] = {}  # session_id → BaseAgent (cached)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load config, discover YAML agents, initialize knowledge base."""
    global _runtime

    logger.info("=" * 80)
    logger.info("Skywalker Agent System - Startup")
    logger.info("=" * 80)

    config = Config.load_from_file("config/skywalker.json")
    _runtime = AgentRuntime(config)

    # Register specialized tools (knowledge and support tools)
    # These tools are needed by sub-agents but not available to the main agent
    from ..tools.web_search import create_web_search_tool
    from ..tools.rag_search import create_rag_search_tool
    from ..tools.support_db import (
        create_get_customer_overview_tool,
        create_get_recent_operations_tool,
        create_get_active_incidents_tool,
    )

    # Register knowledge tools
    _runtime.register_extra_tool("web_search", create_web_search_tool())
    _runtime.register_extra_tool("rag_search", create_rag_search_tool())

    # Register support tools
    _runtime.register_extra_tool("get_customer_overview", create_get_customer_overview_tool())
    _runtime.register_extra_tool("get_recent_operations", create_get_recent_operations_tool())
    _runtime.register_extra_tool("get_active_incidents", create_get_active_incidents_tool())

    logger.info("Registered 5 specialized tools (web_search, rag_search, get_customer_overview, get_recent_operations, get_active_incidents)")

    # Discover YAML agents
    _runtime.discover_agents()

    # Log comprehensive agent and tool information
    logger.info("")
    logger.info("=" * 80)
    logger.info("Agent Registry Summary")
    logger.info("=" * 80)

    # Define native tools that are always available to all agents
    NATIVE_TOOLS = ["find", "grep", "read", "write", "edit"]

    # Get agent configurations from the registry
    discovered_agents = _runtime.agent_registry.get_all_agent_configs()

    if discovered_agents:
        logger.info("Discovered %d agent(s):", len(discovered_agents))
        logger.info("")

        for idx, agent_config in enumerate(discovered_agents, 1):
            logger.info("[%d] Agent: %s", idx, agent_config.name)
            logger.info("    Description: %s", agent_config.description)
            logger.info("    Model: %s", agent_config.model or config.models.default)
            logger.info("    Trigger Type: %s", agent_config.trigger.type)

            # Get YAML-declared tools and separate from native tools
            yaml_tools = agent_config.tools.include if agent_config.tools.include else []
            additional_tools = [t for t in yaml_tools if t not in NATIVE_TOOLS]
            all_tools = NATIVE_TOOLS + additional_tools
            total_tools = len(all_tools)

            logger.info("    Tools Available (%d total):", total_tools)
            logger.info("      Native tools (%d):", len(NATIVE_TOOLS))
            for tool_name in NATIVE_TOOLS:
                logger.info("        • %s", tool_name)

            if additional_tools:
                logger.info("      Additional tools (%d):", len(additional_tools))
                for tool_name in additional_tools:
                    logger.info("        • %s", tool_name)
            else:
                logger.info("      Additional tools: (none)")
            logger.info("")
    else:
        logger.warning("No agents discovered. Check agents directory: %s", _runtime.agent_registry.agents_dir)

    logger.info("=" * 80)
    logger.info("Tool Registry Summary")
    logger.info("=" * 80)
    logger.info("Available tool types:")
    logger.info("  • Native file tools: find, grep, read, write, edit")
    logger.info("  • Knowledge tools: web_search, rag_search")
    logger.info("  • Support tools: get_customer_overview, get_recent_operations, get_active_incidents")
    logger.info("  • Sub-agent tools: (created dynamically per session)")
    logger.info("")
    logger.info("=" * 80)
    logger.info("Skywalker ready — %d sub-agent(s) discovered", len(discovered_agents))
    logger.info("=" * 80)
    
    # Initialize knowledge base service
    try:
        pinecone_api_key = os.getenv("PINECONE_API_KEY")
        pinecone_index_host = os.getenv("PINECONE_INDEX_HOST")
        openai_api_key = os.getenv("OPENAI_API_KEY")

        if not pinecone_api_key or not pinecone_index_host or not openai_api_key:
            raise ValueError("Missing Pinecone/OpenAI credentials in environment variables")

        vector_store = PineconeVectorStore(
            pinecone_api_key=pinecone_api_key,
            pinecone_index_host=pinecone_index_host,
            openai_api_key=openai_api_key,
        )
        md_output_dir = Path("~/.skywalker/mardown_kb").expanduser()
        scraper_output_dir = md_output_dir / "scraped_sources"
        scraper = WebScraper(output_dir=scraper_output_dir)
        chunker = MarkdownChunker()
        
        kb_service = KnowledgeBaseService(
            vector_store=vector_store,
            scraper=scraper,
            chunker=chunker,
            md_output_dir=md_output_dir,
        )
        set_kb_service(kb_service)
        logger.info("Knowledge base service initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize knowledge base service: {e}")
    
    yield

    # Shutdown — nothing to clean up for now
    _runtime = None
    _agents.clear()


app = FastAPI(
    title="Skywalker Customer Support",
    version="0.1.0",
    lifespan=lifespan,
)

# Include knowledge base router
app.include_router(kb_router)


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


# ------------------------------------------------------------------
# Chat
# ------------------------------------------------------------------

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a message and receive an agent response.

    By default, each request creates a new session. To continue an existing
    conversation, provide the ``sessionId`` from a previous response.
    """
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Agent runtime not initialised")

    user_id = request.user_id
    question = request.question

    # 1. Determine session: use provided session_id if valid, otherwise create new
    if request.session_id:
        # Check if provided session exists
        if _runtime.session_manager.session_exists(request.session_id):
            session_id = request.session_id
            logger.info(f"Using existing session {session_id} for user {user_id}")
        else:
            logger.warning(
                f"Session {request.session_id} not found for user {user_id}, "
                "creating new session"
            )
            session_id = _runtime.create_session(user_id=user_id)
    else:
        # Always create new session when no session_id provided
        session_id = _runtime.create_session(user_id=user_id)
        logger.info(f"Created new session {session_id} for user {user_id}")

    # 2. Get or build a BaseAgent for the session
    agent = _get_or_create_agent(session_id, user_id=user_id)

    # 3. Run the agent with user_id for metadata
    result = await agent.run(question, user_id=user_id)

    return ChatResponse(
        sessionId=session_id,
        response=result["response"],
        metadata=result.get("metadata", {}),
    )


def _get_or_create_agent(session_id: str, user_id: Optional[str] = None) -> BaseAgent:
    """Return a cached BaseAgent or build one for *session_id*."""
    if session_id in _agents:
        return _agents[session_id]

    assert _runtime is not None
    agent = BaseAgent(
        config=_runtime.config,
        runtime=_runtime,
        session_id=session_id,
        user_id=user_id,
    )
    _agents[session_id] = agent
    return agent


# ------------------------------------------------------------------
# Agents
# ------------------------------------------------------------------

