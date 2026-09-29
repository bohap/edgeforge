import pytest
from pydantic import ValidationError

from edgeforge.core.config import Environment, LogFormat, Settings


def test_defaults_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("EDGEFORGE_ENVIRONMENT", "EDGEFORGE_LOG_LEVEL", "EDGEFORGE_LOG_FORMAT"):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.environment is Environment.DEV
    assert settings.log_level == "INFO"
    assert settings.log_format is LogFormat.JSON


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDGEFORGE_ENVIRONMENT", "test")
    monkeypatch.setenv("EDGEFORGE_LOG_FORMAT", "console")
    monkeypatch.setenv("EDGEFORGE_DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")

    settings = Settings(_env_file=None)

    assert settings.environment is Environment.TEST
    assert settings.log_format is LogFormat.CONSOLE
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"


def test_rejects_unknown_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDGEFORGE_LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
