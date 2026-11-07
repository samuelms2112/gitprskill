"""Testes unitários das configurações da aplicação."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

VALID_DB_URL = "postgresql+asyncpg://usuario:senha@localhost:5432/db"


def test_loads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valores de ambiente são carregados e tipados corretamente."""
    monkeypatch.setenv("DATABASE_URL", VALID_DB_URL)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DB_POOL_SIZE", "5")

    settings = Settings(_env_file=None)

    assert settings.database_url == VALID_DB_URL
    assert settings.log_level == "DEBUG"
    assert settings.db_pool_size == 5


@pytest.mark.parametrize(
    "invalid_url",
    [
        "postgresql://usuario:senha@localhost/db",  # driver síncrono
        "mysql+asyncmy://usuario:senha@localhost/db",
    ],
)
def test_rejects_non_asyncpg_database_url(
    monkeypatch: pytest.MonkeyPatch, invalid_url: str
) -> None:
    """Somente o driver assíncrono asyncpg é aceito."""
    monkeypatch.setenv("DATABASE_URL", invalid_url)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_error_message_does_not_leak_database_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Erros de validação não devem ecoar a senha presente na URL."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://usuario:senha_secreta_123@host/db")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    assert "senha_secreta_123" not in str(exc_info.value)


def test_secrets_are_masked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Segredos ficam ocultos em ``repr`` e acessíveis apenas via ``get_secret_value``."""
    monkeypatch.setenv("DATABASE_URL", VALID_DB_URL)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "segredo_do_webhook")

    settings = Settings(_env_file=None)

    assert "segredo_do_webhook" not in repr(settings)
    assert settings.github_webhook_secret is not None
    assert settings.github_webhook_secret.get_secret_value() == "segredo_do_webhook"


def test_app_private_key_accepts_escaped_newlines(monkeypatch: pytest.MonkeyPatch) -> None:
    """A chave PEM pode vir numa linha só, com ``\\n`` escapados, como em variáveis de ambiente."""
    monkeypatch.setenv("DATABASE_URL", VALID_DB_URL)
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "-----BEGIN X-----\\nabc\\n-----END X-----")

    settings = Settings(_env_file=None)

    assert settings.github_app_private_key is not None
    assert settings.github_app_private_key.get_secret_value() == "-----BEGIN X-----\nabc\n-----END X-----"


def test_production_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """``is_production`` reflete o ambiente configurado."""
    monkeypatch.setenv("DATABASE_URL", VALID_DB_URL)
    monkeypatch.setenv("ENVIRONMENT", "production")

    assert Settings(_env_file=None).is_production is True
