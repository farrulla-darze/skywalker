"""Skywalker FastAPI application entrypoint."""

import importlib.util
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.logging import setup_logging
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.tracing import setup_tracing, shutdown_tracing
from app.modules.agents import models as _agents_models  # noqa: F401
from app.modules.agents.seeds import seed_agents

# Import all models so Base.metadata knows every table before create_all
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.chat import models as _chat_models  # noqa: F401
from app.modules.chat.api import legacy_router
from app.modules.evaluation import models as _evaluation_models  # noqa: F401
from app.modules.evaluation.seeds import seed_golden_items
from app.modules.integrations import models as _integrations_models  # noqa: F401
from app.modules.knowledge import models as _knowledge_models  # noqa: F401
from app.modules.knowledge.graph_store import Neo4jGraphStore
from app.modules.knowledge.vector_store import QdrantVectorStore
from app.modules.tools.service import build_default_registry

logger = logging.getLogger(__name__)


# Additive column migrations create_all can't apply to existing tables.
# Each statement must be idempotent-ish: failures (column exists / dialect
# quirks) are logged and ignored. Replace with Alembic when schema churn grows.
_LIGHT_MIGRATIONS = [
    "ALTER TABLE chat_messages ADD COLUMN trace_id VARCHAR(64)",
    "ALTER TABLE telegram_integrations ADD COLUMN delivery VARCHAR(16) DEFAULT 'polling'",
]


async def _run_light_migrations(db: Database) -> None:
    from sqlalchemy import text

    for statement in _LIGHT_MIGRATIONS:
        try:
            async with db.engine.begin() as conn:
                await conn.execute(text(statement))
            logger.info("Applied migration: %s", statement)
        except Exception:  # noqa: BLE001 — most commonly "column already exists"
            logger.debug("Migration skipped (likely applied): %s", statement)


def _ensure_support_db(settings: Settings) -> None:
    """Create the mock support database on first run."""
    db_path = Path(settings.support_db_path)
    if db_path.exists():
        return
    init_script = db_path.parent / "init_db.py"
    if not init_script.exists():
        logger.warning("Support DB init script not found at %s", init_script)
        return
    spec = importlib.util.spec_from_file_location("support_init_db", init_script)
    if spec is None or spec.loader is None:
        logger.warning("Could not load support DB init script")
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.init_database()
    logger.info("Support database initialized at %s", db_path)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory — used by uvicorn and by tests (with overridden settings)."""
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Skywalker starting (env=%s)", settings.environment)

        # Observability — must run before any Agent is created
        app.state.tracing_enabled = setup_tracing(settings)

        # Database + tables + seeds
        app.state.db = Database(settings.database_url)
        await app.state.db.create_all()
        await _run_light_migrations(app.state.db)
        async with app.state.db.session_factory() as session:
            await seed_agents(session)
            await seed_golden_items(session)
            # Seed Langfuse prompts from DB baselines (existing versions win —
            # prompts are edited/deployed via the Langfuse UI, no redeploy).
            from app.modules.agents.prompts import sync_prompts_to_langfuse
            from app.modules.agents.repository import AgentRepository

            await sync_prompts_to_langfuse(await AgentRepository(session).list_all())

        # Tool catalog
        app.state.tool_registry = build_default_registry()

        # Shared stores
        app.state.vector_store = QdrantVectorStore(settings)
        app.state.graph_store = Neo4jGraphStore(settings) if settings.graph_enabled else None
        if app.state.graph_store is not None:
            try:
                await app.state.graph_store.ensure_schema()
            except Exception as exc:  # noqa: BLE001 — graph is optional at boot
                logger.warning("Neo4j schema init failed (graph_search degraded): %s", exc)

        # Rate limiter (login)
        app.state.login_rate_limiter = SlidingWindowRateLimiter(
            settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds
        )

        # Mock support system
        _ensure_support_db(settings)

        # Telegram long-polling (local-dev delivery; webhook mode needs no task)
        from app.modules.chat.api import build_chat_service_from_state
        from app.modules.chat.repository import ChatRepository
        from app.modules.integrations.polling import TelegramPollingManager

        def _update_context_builder(session):
            chat_repository = ChatRepository(session)
            service = build_chat_service_from_state(app.state, session, settings)

            async def run_agent_turn(chat_session, text: str) -> str:
                message = await service.run_turn(chat_session, text)
                return message.content

            return chat_repository, run_agent_turn

        app.state.telegram_polling = TelegramPollingManager(
            app.state.db.session_factory, settings, _update_context_builder
        )
        await app.state.telegram_polling.start_all()

        logger.info(
            "Skywalker ready — tools: %s | graph=%s | guardrails=%s | langfuse=%s",
            ", ".join(app.state.tool_registry.names()),
            settings.graph_enabled,
            settings.guardrails_enabled,
            app.state.tracing_enabled,
        )
        yield

        await app.state.telegram_polling.stop_all()
        shutdown_tracing()
        if app.state.graph_store:
            await app.state.graph_store.close()
        await app.state.db.dispose()

    app = FastAPI(title="Skywalker", version="0.2.0", lifespan=lifespan)

    # CORS — restricted to configured origins (frontend dev server / deployed frontend)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_v1_router)
    app.include_router(legacy_router)  # POST /chat — challenge-spec compatibility

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
