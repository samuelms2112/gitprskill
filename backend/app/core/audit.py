"""Trilha de auditoria: eventos administrativos e de sistema, registrados como logs estruturados.

Cada evento tem um nome estável em ``event`` e campos extras (ex.: ``user_id``, ``pr_id``), para
filtrar por ``audit_event`` no agregador de logs. Nunca registre segredos nos campos.
"""

from __future__ import annotations

from app.core.logging import get_logger

_audit_logger = get_logger("audit")


def audit_event(event: str, **fields: object) -> None:
    """Registra um evento de auditoria."""
    _audit_logger.info(event, extra={"audit_event": event, **fields})
