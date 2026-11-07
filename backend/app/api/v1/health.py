"""Endpoint de saúde da API, que também verifica a conectividade com o banco."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session

router = APIRouter(prefix="/health", tags=["Saúde"])


class HealthResponse(BaseModel):
    """Resposta do health check."""

    status: Literal["ok"]
    version: str
    environment: str
    database: Literal["ok"]


@router.get("", response_model=HealthResponse, summary="Verifica a saúde da API e do banco")
async def health_check(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> HealthResponse:
    """Executa ``SELECT 1``. Falhas de banco resultam em HTTP 503 pelo handler global."""
    await session.execute(text("SELECT 1"))
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        database="ok",
    )
