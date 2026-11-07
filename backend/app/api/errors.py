"""Handlers globais que convertem exceções da aplicação em respostas JSON padronizadas."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Registra os handlers de exceção na aplicação.

    Formato da resposta de erro::

        {"error": {"code": "...", "message": "...", "details": {}}}

    Args:
        app: Instância FastAPI onde os handlers serão registrados.
    """

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        """Converte ``AppError`` em JSON, registrando o evento no nível adequado."""
        log = logger.error if exc.status_code >= 500 else logger.warning
        log(
            "Erro de aplicação",
            extra={
                "error_code": exc.code,
                "status_code": exc.status_code,
                "path": request.url.path,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers or None,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )
