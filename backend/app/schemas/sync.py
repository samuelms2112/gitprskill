"""Schemas da sincronização histórica (backfill) de repositórios."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SyncState = Literal["queued", "running", "completed", "failed"]


class SyncRequest(BaseModel):
    """Pedido de backfill. ``days_back`` limita o histórico; ausente = todo o histórico."""

    model_config = ConfigDict(extra="forbid")

    days_back: int | None = Field(default=None, ge=1, le=3650)


class SyncAccepted(BaseModel):
    """Resposta 202: o job foi aceito e pode ser acompanhado pelo ``task_id``."""

    task_id: str
    state: SyncState


class InstallationSyncResult(BaseModel):
    """Resultado da sincronização da lista de repositórios pela API da instalação."""

    synced: int


class SyncStatus(BaseModel):
    """Estado de um job de backfill, guardado no Redis enquanto o job existe."""

    task_id: str
    tenant_id: int
    repository_id: int
    state: SyncState
    examined: int = 0
    stored: int = 0
    new: int = 0
    skipped: int = 0
    error: str | None = None
    updated_at: datetime
