"""Variáveis presentes mas vazias (ex.: ``GEMINI_API_KEY=``) contam como não configuradas."""

import pytest

from app.core.config import Settings

VALID_DB_URL = "postgresql+asyncpg://usuario:senha@localhost:5432/db"


@pytest.mark.parametrize("variable", ["GEMINI_API_KEY", "GITHUB_APP_PRIVATE_KEY", "GITHUB_OAUTH_CLIENT_SECRET"])
def test_blank_secret_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    """Uma chave vazia não pode ser confundida com uma chave configurada."""
    monkeypatch.setenv("DATABASE_URL", VALID_DB_URL)
    monkeypatch.setenv(variable, "")

    settings = Settings(_env_file=None)

    field = {
        "GEMINI_API_KEY": "gemini_api_key",
        "GITHUB_APP_PRIVATE_KEY": "github_app_private_key",
        "GITHUB_OAUTH_CLIENT_SECRET": "github_oauth_client_secret",
    }[variable]
    assert getattr(settings, field) is None


def test_blank_plain_value_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Campo com valor padrão e variável vazia usa o padrão, não o texto vazio."""
    monkeypatch.setenv("DATABASE_URL", VALID_DB_URL)
    monkeypatch.setenv("GITHUB_API_BASE_URL", "")

    assert Settings(_env_file=None).github_api_base_url == "https://api.github.com"
