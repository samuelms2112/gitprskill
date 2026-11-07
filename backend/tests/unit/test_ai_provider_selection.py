"""Testes unitários da troca de provedor de IA pela variável ``AI_PROVIDER``."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import AINotConfiguredError
from app.services.ai.consensus import LocalAIConsensusEngine
from app.services.ai.factory import open_ai_services
from app.services.ai_service import AIService

VALID_DB_URL = "postgresql+asyncpg://usuario:senha@localhost:5432/db"


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    monkeypatch.setenv("DATABASE_URL", VALID_DB_URL)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_gemini_is_the_default_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem ``AI_PROVIDER`` definido, o provedor é o Gemini (comportamento anterior preservado)."""
    assert _settings(monkeypatch).ai_provider == "gemini"


def test_unknown_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provedor fora da lista suportada não é aceito na inicialização."""
    with pytest.raises(ValidationError):
        _settings(monkeypatch, AI_PROVIDER="openai")


def test_ollama_is_configured_with_models_and_without_any_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """O conselho local funciona sem chave de API: basta haver modelos configurados."""
    settings = _settings(monkeypatch, AI_PROVIDER="ollama")

    assert settings.ai_configured is True
    assert settings.ollama_model_list == [
        "qwen2.5-coder:7b",
        "deepseek-r1:8b",
        "llama3.1:8b",
        "mistral:7b",
        "phi3:3.8b",
        "gemma2:9b",
    ]


def test_ollama_without_models_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conselho sem modelos não está configurado: a IA é tratada como indisponível, não como erro."""
    settings = _settings(monkeypatch, AI_PROVIDER="ollama", OLLAMA_MODELS=" , ")

    assert settings.ai_configured is False


def test_gemini_needs_its_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini sem chave não está configurado, mesmo que existam modelos locais."""
    settings = _settings(monkeypatch, AI_PROVIDER="gemini")

    assert settings.ai_configured is False


async def test_switching_to_ollama_yields_the_local_consensus_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com ``AI_PROVIDER=ollama``, o provedor é o conselho local e os embeddings são ligados."""
    settings = _settings(monkeypatch, AI_PROVIDER="ollama")

    async with open_ai_services(settings) as services:
        assert isinstance(services.provider, LocalAIConsensusEngine)
        assert services.embedder is not None


async def test_switching_to_gemini_yields_gemini_without_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com ``AI_PROVIDER=gemini``, o provedor é o Gemini e a memória semântica fica desligada."""
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


async def test_ollama_without_models_fails_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Escolher Ollama sem modelos é erro de configuração explícito."""
    # Valor não vazio sem modelo nenhum. (Valor vazio conta como "não definido" e usa o padrão.)
    settings = _settings(monkeypatch, AI_PROVIDER="ollama", OLLAMA_MODELS=" , ")

    with pytest.raises(AINotConfiguredError):
        async with open_ai_services(settings):
            pass


async def test_pm_agent_uses_its_own_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """O parecer PM/PO usa ``OLLAMA_PM_MODEL``, não um modelo do conselho técnico."""
    from app.services.ai.ollama import OllamaTextModel

    settings = _settings(monkeypatch, AI_PROVIDER="ollama", OLLAMA_PM_MODEL="gemma2:9b")

    async with open_ai_services(settings) as services:
        assert isinstance(services.pm_generator, OllamaTextModel)
        assert services.pm_generator.model == "gemma2:9b"
