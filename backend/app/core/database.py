"""Engine assíncrona do SQLAlchemy e gerenciamento de sessões.

Padrão adotado: *Unit of Work por requisição*. Cada requisição recebe uma
sessão própria via injeção de dependência, com commit ao final em caso de
sucesso e rollback automático em caso de falha.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.exceptions import DatabaseError
from app.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache
def get_engine() -> AsyncEngine:
    """Cria (uma única vez) o engine assíncrono com pool de conexões.

    ``pool_pre_ping`` descarta conexões mortas antes de usá-las, evitando erros
    após reinícios do banco.
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        echo=settings.db_echo,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Fábrica de sessões. ``expire_on_commit=False`` mantém objetos legíveis após commit."""
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Dependência FastAPI que fornece uma sessão por requisição.

    Erros de banco são convertidos em ``DatabaseError`` para resposta HTTP 503,
    sem vazar detalhes internos do driver ao cliente.

    Yields:
        Sessão assíncrona vinculada à requisição corrente.

    Raises:
        DatabaseError: Quando ocorre falha do SQLAlchemy durante a requisição.
    """
    session = get_session_factory()()
    try:
        yield session
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.exception("Falha de banco de dados durante a requisição")
        raise DatabaseError("Banco de dados indisponível no momento.") from exc
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
