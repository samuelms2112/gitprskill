"""Ponto de entrada da aplicação FastAPI.

Execução local: ``uvicorn app.main:app --reload``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.database import get_engine
from app.core.logging import configure_logging, get_logger

API_PREFIX = "/api/v1"
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Configura logs na subida e libera o pool de conexões no encerramento."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "Aplicação iniciada",
        extra={"environment": settings.environment, "version": settings.app_version},
    )
    try:
        yield
    finally:
        await get_engine().dispose()
        logger.info("Pool de conexões encerrado")


def create_app() -> FastAPI:
    """Fábrica da aplicação. Facilita a criação de instâncias isoladas em testes.

    Documentação interativa (``/docs``) é desabilitada em produção.
    """
    settings = get_settings()
    docs_enabled = not settings.is_production

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    register_exception_handlers(app)
    # Sem cookies: a autenticação é por cabeçalho Authorization, então não há allow_credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
        max_age=600,
    )
    app.include_router(api_router, prefix=API_PREFIX)
    return app


app = create_app()
