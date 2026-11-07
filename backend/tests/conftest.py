"""Configuração compartilhada da suíte de testes.

Define variáveis de ambiente mínimas antes de importar a aplicação, para que
``Settings`` seja válido sem depender de um ``.env`` real. Também limpa o cache
de configurações entre os testes, evitando vazamento de estado.
"""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "segredo-de-teste")
os.environ.setdefault("JWT_SECRET_KEY", "chave-jwt-de-teste-com-mais-de-32-caracteres")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "client-id-de-teste")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "client-secret-de-teste")
os.environ.setdefault("GITHUB_OAUTH_REDIRECT_URI", "http://testserver/api/v1/auth/github/callback")

import pytest  # noqa: E402

from app.core.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Isola cada teste de configurações cacheadas por testes anteriores."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
