from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .bootstrap import SERVICE_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(SERVICE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = Field("rag-core", alias="RAG_CORE_SERVICE_NAME")
    host: str = Field("0.0.0.0", alias="RAG_CORE_HOST")
    port: int = Field(7220, alias="RAG_CORE_PORT")
    data_dir: Path = Field(
        SERVICE_ROOT / "data",
        alias="RAG_CORE_DATA_DIR",
    )
    default_config_path: Path = Field(
        SERVICE_ROOT / "config" / "defaults.yaml",
        alias="RAG_CORE_DEFAULT_CONFIG",
    )
    public_base_url: str = Field("", alias="RAG_CORE_PUBLIC_BASE_URL")
    service_token: str = Field("", alias="RAG_CORE_SERVICE_TOKEN")
    log_dir: Path = Field(SERVICE_ROOT / "data" / "logs", alias="RAG_CORE_LOG_DIR")
    log_level: str = Field("INFO", alias="RAG_CORE_LOG_LEVEL")
    log_max_bytes: int = Field(10_485_760, alias="RAG_CORE_LOG_MAX_BYTES")
    log_backup_count: int = Field(10, alias="RAG_CORE_LOG_BACKUP_COUNT")

    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openai_base_url: str = Field("", alias="OPENAI_BASE_URL")
    openai_llm_model: str = Field("gpt-4o-mini", alias="OPENAI_LLM_MODEL")
    openai_vision_model: str = Field("gpt-4o", alias="OPENAI_VISION_MODEL")
    openai_embed_model: str = Field("text-embedding-3-large", alias="OPENAI_EMBED_MODEL")
    openai_embed_dim: int = Field(3072, alias="OPENAI_EMBED_DIM")

    ollama_base_url: str = Field("", alias="OLLAMA_BASE_URL")
    ollama_api_key: str = Field("ollama", alias="OLLAMA_API_KEY")
    ollama_llm_model: str = Field("", alias="OLLAMA_LLM_MODEL")
    ollama_vision_model: str = Field("", alias="OLLAMA_VISION_MODEL")
    ollama_embed_model: str = Field("", alias="OLLAMA_EMBED_MODEL")
    ollama_embed_dim: int = Field(768, alias="OLLAMA_EMBED_DIM")

    mineru_api_key: str = Field("", alias="MINERU_API_KEY")
    mineru_api_base_url: str = Field("https://mineru.net", alias="MINERU_API_BASE_URL")


class AppConfig(BaseModel):
    """Thin wrapper around defaults.yaml.

    The YAML remains intentionally permissive so new modes can be exposed
    without changing the service settings layer on every experiment.
    """

    raw: dict[str, Any]

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name, {})
        return value if isinstance(value, dict) else {}

    def get(self, dotted_key: str, default: Any = None) -> Any:
        current: Any = self.raw
        for part in dotted_key.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current


def deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_service_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (SERVICE_ROOT / path).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir = _resolve_service_path(settings.data_dir)
    settings.log_dir = _resolve_service_path(settings.log_dir)
    settings.default_config_path = _resolve_service_path(settings.default_config_path)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    return settings


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    settings = get_settings()
    if not settings.default_config_path.exists():
        return AppConfig(raw={})
    with open(settings.default_config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        data = {}
    return AppConfig(raw=data)

