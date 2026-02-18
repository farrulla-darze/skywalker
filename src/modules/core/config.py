"""Configuration management for Skywalker system."""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

load_dotenv()


class SessionConfig(BaseModel):
    """Session management configuration."""
    sessions_root: str = Field(
        default="~/.skywalker/sessions",
        alias="sessionsRoot",
    )


class HybridSearchConfig(BaseModel):
    """Hybrid search configuration."""
    enabled: bool = True
    vector_weight: float = Field(default=0.7, alias="vectorWeight")
    text_weight: float = Field(default=0.3, alias="textWeight")
    candidate_multiplier: int = Field(default=4, alias="candidateMultiplier")


class QueryConfig(BaseModel):
    """Memory query configuration."""
    hybrid: Optional[HybridSearchConfig] = None


class MemoryConfig(BaseModel):
    """Memory system configuration."""
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    backend: str = "sqlite"
    store: str
    query: Optional[QueryConfig] = None


class ProviderConfig(BaseModel):
    """LLM provider configuration."""
    api_key: str = Field(alias="apiKey")


class ModelsConfig(BaseModel):
    """Models configuration."""
    default: str = Field(
        default="openai:gpt-5-mini-2025-08-07",
        description="Default model used for agents that don't specify one",
    )
    providers: Dict[str, ProviderConfig]


class LangfuseConfig(BaseModel):
    """Langfuse observability configuration."""
    enabled: bool = True
    public_key: Optional[str] = Field(default=None, alias="publicKey")
    secret_key: Optional[str] = Field(default=None, alias="secretKey")
    host: str = "http://localhost:3000"


class DatabaseConfig(BaseModel):
    """Database configuration."""
    url: str


class Config(BaseModel):
    """Main Skywalker configuration."""
    session: SessionConfig
    memory: MemoryConfig
    models: ModelsConfig
    langfuse: LangfuseConfig
    database: DatabaseConfig

    @classmethod
    def load_from_file(cls, config_path: str | Path) -> "Config":
        """Load configuration from JSON file with environment variable substitution."""
        config_path = Path(config_path)

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r") as f:
            config_data = json.load(f)

        config_data = cls._substitute_env_vars(config_data)
        return cls(**config_data)

    @staticmethod
    def _substitute_env_vars(data: Any) -> Any:
        """Recursively substitute environment variables in configuration."""
        if isinstance(data, dict):
            return {k: Config._substitute_env_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [Config._substitute_env_vars(item) for item in data]
        elif isinstance(data, str):
            if data.startswith("${") and data.endswith("}"):
                var_expr = data[2:-1]
                if ":-" in var_expr:
                    var_name, default = var_expr.split(":-", 1)
                    value = os.getenv(var_name, default)
                    return value if value != "" else (default if default != "" else None)
                else:
                    value = os.getenv(var_expr)
                    if value is None:
                        raise ValueError(f"Environment variable {var_expr} not set")
                    return value
            return data
        else:
            return data


class Settings(BaseSettings):
    """Application settings from environment variables."""
    log_level: str = "INFO"
    environment: str = "development"

    class Config:
        env_file = ".env"
        case_sensitive = False
