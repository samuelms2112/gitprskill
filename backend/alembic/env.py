"""Ambiente de execução das migrações do Alembic, com suporte ao engine assíncrono.

As migrações usam a mesma ``DATABASE_URL`` da aplicação e ``Base.metadata`` como
alvo do autogenerate. ``NullPool`` evita reaproveitar conexões após o término do
processo de migração.
"""

import asyncio

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings

# Importar o pacote de modelos registra todas as tabelas em Base.metadata.
from app.models import Base

config = context.config
# Logging é configurado pela própria aplicação (JSON); o alembic.ini não define seções de log.

target_metadata = Base.metadata


def _database_url() -> str:
    """Obtém a URL do banco a partir das configurações da aplicação."""
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Gera SQL sem conectar ao banco (``alembic upgrade --sql``)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    """Executa as migrações em uma conexão síncrona obtida via ``run_sync``."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Cria o engine assíncrono temporário, aplica as migrações e o descarta."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Executa as migrações online, via ``asyncio.run``."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
