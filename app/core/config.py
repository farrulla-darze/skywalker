"""Application configuration — single source of truth, loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration for the Skywalker backend.

    Every value can be overridden via environment variable (see .env.example).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Application -----------------------------------------------------
    environment: str = "development"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"

    # --- Database (application state: users, agents, sessions, evals) ----
    database_url: str = "sqlite+aiosqlite:///./skywalker.db"

    # --- Security --------------------------------------------------------
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3001"]
    )
    # Legacy challenge endpoint (POST /chat) may be called without a JWT.
    allow_anonymous_chat: bool = True

    # --- LLM -------------------------------------------------------------
    openai_api_key: str | None = None
    default_model: str = "openai:gpt-5-mini"
    # Guardrails are simple ALLOW/BLOCK judges — same rationale as ragas_model:
    # a reasoning model can stall for minutes "thinking" on one (observed 10min+
    # on a single output-guardrail call).
    guardrail_model: str = "openai:gpt-4.1-mini"
    guardrails_enabled: bool = False
    # RAGAS judge — a non-reasoning model: reasoning models burn the token
    # budget before emitting the structured judge output (IncompleteOutput).
    ragas_model: str = "gpt-4.1-mini"
    # Per-request LLM timeouts (seconds). The OpenAI client retries twice on
    # timeout, so worst-case wall time per logical call is ~3x these values.
    llm_request_timeout_seconds: int = 120
    guardrail_timeout_seconds: int = 30
    # How long a chat turn blocks waiting for the human's Telegram reply in a
    # consult_human round before telling the customer a specialist will follow up.
    consultation_timeout_seconds: int = 120
    # Hard cap on one Telegram turn (webhook or polling). The effective cap is
    # raised at runtime to consultation_timeout_seconds + 120 if that is larger,
    # so consult_human rounds are never cut off.
    telegram_turn_timeout_seconds: int = 300

    # --- RAG / vector store (Qdrant) -------------------------------------
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "skywalker_kb"
    default_namespace: str = "getnet"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1024

    # --- Knowledge graph (Neo4j) -----------------------------------------
    graph_enabled: bool = False
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "skywalker-graph"

    # --- Support database (mock external support system) -----------------
    support_db_path: str = "db/support_db/support.db"

    # --- Observability (Langfuse, optional) ------------------------------
    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (overridable in tests via dependency injection)."""
    return Settings()
