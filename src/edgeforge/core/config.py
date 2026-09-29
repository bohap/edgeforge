"""Application settings, loaded from environment variables prefixed with ``EDGEFORGE_``."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EDGEFORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.DEV
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    log_format: LogFormat = LogFormat.JSON
    database_url: str = "postgresql+psycopg://edgeforge:edgeforge@localhost:5432/edgeforge"
    understat_requests_per_second: float = Field(default=0.4, gt=0, le=5)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
