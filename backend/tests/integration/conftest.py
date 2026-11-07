"""Fixtures de integração: PostgreSQL real, esquema recriado a cada teste e cliente HTTP em memória.

Os testes são pulados quando ``INTEGRATION_DATABASE_URL`` não está definida. Use um banco
dedicado: ele é apagado e recriado a cada teste.
"""

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text

from app.api.deps import get_token_service
from app.core.config import get_settings
from app.core.database import get_engine, get_session_factory
from app.main import app
from app.models import Base

INTEGRATION_URL = os.environ.get("INTEGRATION_DATABASE_URL")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Pula os testes de integração quando o banco de testes não foi informado."""
    if INTEGRATION_URL:
        return
    skip = pytest.mark.skip(reason="INTEGRATION_DATABASE_URL não definida")
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(skip)


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    get_token_service.cache_clear()


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Aponta a aplicação para o banco de integração e recria todas as tabelas."""
    assert INTEGRATION_URL is not None
    monkeypatch.setenv("DATABASE_URL", INTEGRATION_URL)
    _clear_caches()

    engine = get_engine()
    async with engine.begin() as connection:
        # A coluna de embedding usa o tipo ``vector`` do pgvector: a extensão precisa existir.
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    yield

    await engine.dispose()
    _clear_caches()


@pytest.fixture(autouse=True)
async def _database_ready(db: None) -> None:
    """Todo teste de integração executa contra o banco com o esquema recriado."""


@pytest.fixture
async def client(db: None) -> AsyncIterator[httpx.AsyncClient]:
    """Cliente HTTP em memória contra a aplicação real, com o banco de integração."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
