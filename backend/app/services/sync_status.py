"""Armazenamento do progresso dos jobs de backfill.

``RedisSyncStatusStore`` é usado em produção (API e worker compartilham o Redis).
``InMemorySyncStatusStore`` é usado nos testes, sem depender de um Redis rodando.
Os status expiram após ``STATUS_TTL_SECONDS`` para não acumular chaves para sempre.
"""

from __future__ import annotations

from typing import Protocol

import redis

from app.schemas.sync import SyncStatus

STATUS_TTL_SECONDS = 7 * 24 * 3600
KEY_PREFIX = "sync:status:"


class SyncStatusStore(Protocol):
    """Contrato de leitura e escrita do status de um job."""

    def save(self, status: SyncStatus) -> None: ...

    def load(self, task_id: str) -> SyncStatus | None: ...


class RedisSyncStatusStore:
    """Status em Redis, serializado como JSON com expiração."""

    def __init__(self, client: redis.Redis) -> None:
        """Recebe um cliente Redis já configurado (com ``decode_responses=True``)."""
        self._client = client

    def save(self, status: SyncStatus) -> None:
        self._client.set(
            f"{KEY_PREFIX}{status.task_id}",
            status.model_dump_json(),
            ex=STATUS_TTL_SECONDS,
        )

    def load(self, task_id: str) -> SyncStatus | None:
        raw = self._client.get(f"{KEY_PREFIX}{task_id}")
        if raw is None:
            return None
        return SyncStatus.model_validate_json(str(raw))


class InMemorySyncStatusStore:
    """Implementação em memória, usada nos testes."""

    def __init__(self) -> None:
        self._items: dict[str, SyncStatus] = {}

    def save(self, status: SyncStatus) -> None:
        self._items[status.task_id] = status

    def load(self, task_id: str) -> SyncStatus | None:
        return self._items.get(task_id)
