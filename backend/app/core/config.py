"""Configurações centralizadas da aplicação.

Os valores são lidos de variáveis de ambiente e do arquivo ``.env``, sendo
validados na inicialização. Segredos são ``SecretStr`` para não aparecerem em
logs, ``repr`` ou mensagens de erro. ``hide_input_in_errors`` impede que a
``DATABASE_URL`` (que contém a senha) seja ecoada em erros de validação.
"""

import shutil
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ASYNC_POSTGRES_PREFIX = "postgresql+asyncpg://"
REDIS_PREFIXES = ("redis://", "rediss://")
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Modelo tipado com todas as configurações da aplicação."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "GitHub Management Platform"
    # Frontend: destino do redirecionamento após o login e origens autorizadas (CORS).
    frontend_url: str = "http://localhost:3000"
    cors_allowed_origins: str = "http://localhost:3000"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    database_url: str = Field(
        ...,
        description="URL assíncrona do PostgreSQL, ex.: postgresql+asyncpg://user:pass@host:5432/db",
    )
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=100)
    db_echo: bool = False

    redis_url: str = Field(default="redis://localhost:6379/0")

    # GitHub App: autenticação por instalação (um token por tenant). Não há token global.
    github_app_id: str | None = None
    github_app_private_key: SecretStr | None = None
    github_webhook_secret: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    # Sessão (JWT) e OAuth. A chave deve ter no mínimo 32 caracteres (ex.: openssl rand -hex 32).
    jwt_secret_key: SecretStr = Field(...)
    jwt_access_token_ttl_minutes: int = Field(default=60, ge=5, le=1440)
    oauth_state_ttl_minutes: int = Field(default=10, ge=1, le=30)
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: SecretStr | None = None
    github_oauth_redirect_uri: str | None = None
    github_oauth_scopes: str = "read:user user:email"

    # Provedor de IA: "claude_cli" (Claude Code CLI autenticado no servidor) ou "gemini" (nuvem).
    ai_provider: Literal["claude_cli", "gemini"] = "claude_cli"
    # Executável do Claude Code CLI e modelo usado nas análises e no parecer PM/PO.
    claude_cli_command: str = "claude"
    claude_cli_model: str = "claude-sonnet-5-5"
    claude_cli_timeout_seconds: float = Field(default=300.0, gt=0, le=1800)
    claude_max_diff_chars: int = Field(default=60_000, ge=1_000, le=500_000)

    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    gemini_model: str = "gemini-3.5-flash"
    gemini_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    # Diffs maiores que isso são truncados antes de serem enviados ao modelo.
    gemini_max_diff_chars: int = Field(default=60_000, ge=1_000, le=500_000)

    github_api_base_url: str = "https://api.github.com"
    github_request_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    github_max_rate_limit_wait_seconds: float = Field(default=900.0, ge=0)
    # Branches de destino cujos merges são persistidos (lista separada por vírgulas).
    tracked_base_branches: str = "main,master,master-tip"

    @property
    def tracked_branches(self) -> frozenset[str]:
        """Conjunto normalizado das branches rastreadas."""
        return frozenset(
            branch.strip() for branch in self.tracked_base_branches.split(",") if branch.strip()
        )

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        """Garante o driver assíncrono exigido pelo SQLAlchemy Async."""
        if not value.startswith(ASYNC_POSTGRES_PREFIX):
            raise ValueError(f"DATABASE_URL deve começar com '{ASYNC_POSTGRES_PREFIX}'.")
        return value

    @model_validator(mode="before")
    @classmethod
    def _blank_values_mean_unset(cls, data: object) -> object:
        """Variável presente porém vazia (ex.: ``GEMINI_API_KEY=``) conta como não configurada."""
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if not (isinstance(value, str) and value.strip() == "")}
        return data

    @field_validator("github_app_private_key", mode="before")
    @classmethod
    def _normalize_app_private_key(cls, value: object) -> object:
        """Aceita a chave PEM com ``\\n`` escapados (formato comum em variáveis de ambiente)."""
        if isinstance(value, str) and "\\n" in value:
            return value.replace("\\n", "\n")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def _validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        """Rejeita chaves de assinatura fracas. A mensagem não revela o valor."""
        if len(value.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET_KEY deve ter pelo menos {MIN_JWT_SECRET_LENGTH} caracteres.")
        return value

    @field_validator("redis_url")
    @classmethod
    def _validate_redis_url(cls, value: str) -> str:
        """Garante um esquema Redis válido para o broker do Celery."""
        if not value.startswith(REDIS_PREFIXES):
            raise ValueError("REDIS_URL deve começar com 'redis://' ou 'rediss://'.")
        return value

    @property
    def ai_configured(self) -> bool:
        """A IA está disponível? Com Claude CLI, o executável precisa existir; com Gemini, a chave."""
        if self.ai_provider == "claude_cli":
            return shutil.which(self.claude_cli_command) is not None
        return self.gemini_api_key is not None

    @property
    def cors_origins(self) -> list[str]:
        """Origens autorizadas a chamar a API pelo navegador."""
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        """Indica se a aplicação roda em produção."""
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Retorna a instância única (cacheada) das configurações."""
    return Settings()
