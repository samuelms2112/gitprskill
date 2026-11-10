"""Testes unitários da troca de provedor de IA pela variável ``AI_PROVIDER``."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import AINotConfiguredError
from app.services.ai.claude_cli_service import ClaudeCliService
from app.services.ai.factory import open_ai_services
from app.services.ai_service import AIService

VALID_DB_URL = "postgresql+asyncpg://usuario:senha@localhost:5432/db"


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    monkeypatch.setenv("DATABASE_URL", VALID_DB_URL)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_claude_cli_is_the_default_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem ``AI_PROVIDER`` definido, o provedor é o Claude Code CLI."""
    assert _settings(monkeypatch).ai_provider == "claude_cli"


def test_unknown_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provedor fora da lista suportada não é aceito na inicialização."""
    with pytest.raises(ValidationError):
        _settings(monkeypatch, AI_PROVIDER="ollama")


def test_claude_cli_is_configured_when_the_executable_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com o executável presente no servidor, o provedor Claude está configurado, sem chave de API."""
    monkeypatch.setattr("app.core.config.shutil.which", lambda _name: "/usr/local/bin/claude")

    assert _settings(monkeypatch).ai_configured is True


def test_claude_cli_without_executable_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem o executável, a IA é tratada como não configurada (não como erro de execução)."""
    monkeypatch.setattr("app.core.config.shutil.which", lambda _name: None)

    assert _settings(monkeypatch).ai_configured is False


def test_gemini_needs_its_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini sem chave não está configurado."""
    assert _settings(monkeypatch, AI_PROVIDER="gemini").ai_configured is False


async def test_claude_cli_yields_the_claude_service_without_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com ``AI_PROVIDER=claude_cli``, o provedor é o Claude e a memória semântica fica desligada."""
    monkeypatch.setattr("app.core.config.shutil.which", lambda _name: "/usr/local/bin/claude")
    settings = _settings(monkeypatch, CLAUDE_CLI_MODEL="claude-haiku-5-5")

    async with open_ai_services(settings) as services:
        assert isinstance(services.provider, ClaudeCliService)
        assert services.provider is services.backfill_provider is services.pm_generator
        assert services.provider.model == "claude-haiku-5-5"
        assert services.embedder is None


async def test_claude_cli_missing_executable_fails_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Escolher o Claude sem o executável é erro de configuração explícito."""
    monkeypatch.setattr("app.core.config.shutil.which", lambda _name: None)
    settings = _settings(monkeypatch)

    with pytest.raises(AINotConfiguredError):
        async with open_ai_services(settings):
            pass


async def test_gemini_still_selectable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com ``AI_PROVIDER=gemini`` e chave, o provedor é o Gemini."""
    settings = _settings(monkeypatch, AI_PROVIDER="gemini", GEMINI_API_KEY="AIza-chave-de-teste")

    async with open_ai_services(settings) as services:
        assert isinstance(services.provider, AIService)
        assert services.embedder is None


async def test_gemini_without_key_fails_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Escolher Gemini sem chave é erro de configuração explícito."""
    settings = _settings(monkeypatch, AI_PROVIDER="gemini")

    with pytest.raises(AINotConfiguredError):
        async with open_ai_services(settings):
            pass
