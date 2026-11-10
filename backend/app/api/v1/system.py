"""Sessão do Claude Code CLI: diagnóstico e reautenticação. Restrito a donos de algum tenant."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

import redis
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.audit import audit_event
from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.exceptions import AuthorizationError
from app.models.enums import MemberRole
from app.models.tenant_member import TenantMember
from app.models.user import User
from app.schemas.system import (
    ClaudeReauthCompleteRequest,
    ClaudeReauthResponse,
    ClaudeStatusResponse,
)
from app.services.ai.claude_cli_service import ClaudeCliService
from app.services.claude_session import (
    ClaudeReauthManager,
    SessionStatus,
    check_session,
    clear_auth_required,
    read_auth_state,
    set_auth_required,
)

router = APIRouter(prefix="/system/claude", tags=["sistema"])


@lru_cache
def get_reauth_manager() -> ClaudeReauthManager:
    """Gerenciador único do processo: guarda os logins em andamento entre as duas chamadas."""
    return ClaudeReauthManager(command=get_settings().claude_cli_command)


def get_claude_service() -> ClaudeCliService:
    """Cliente do Claude Code CLI com as configurações atuais."""
    settings = get_settings()
    return ClaudeCliService(
        command=settings.claude_cli_command,
        model=settings.claude_cli_model,
        timeout=settings.claude_cli_timeout_seconds,
        max_diff_chars=settings.claude_max_diff_chars,
    )


def get_redis_client() -> Iterator[redis.Redis]:
    """Cliente Redis para o estado da fila (``AUTH_REQUIRED``), fechado ao final da requisição."""
    client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        yield client
    finally:
        client.close()


async def require_owner(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """Permite a operação só para usuários que são OWNER de ao menos um tenant.

    Raises:
        AuthorizationError: Usuário autenticado sem papel de dono em nenhum tenant.
    """
    statement = select(TenantMember.id).where(
        TenantMember.user_id == user.id, TenantMember.role == MemberRole.OWNER
    )
    if (await session.scalars(statement)).first() is None:
        raise AuthorizationError("Apenas donos de tenant podem gerenciar a sessão do Claude.")
    return user


Owner = Annotated[User, Depends(require_owner)]


def _to_response(status: SessionStatus) -> ClaudeStatusResponse:
    return ClaudeStatusResponse(
        authenticated=status.authenticated,
        last_checked=status.last_checked,
        error_message=status.error_message,
    )


def _sync_queue_state(client: redis.Redis, status: SessionStatus) -> None:
    """Pausa a fila se a sessão caiu; retoma se voltou. Mantém o estado coerente com o teste."""
    if status.authenticated:
        if read_auth_state(client) == "AUTH_REQUIRED":
            clear_auth_required(client)
            audit_event("claude_session_restored")
    else:
        set_auth_required(client, status.error_message or "sessão inválida")


@router.get("/status", response_model=ClaudeStatusResponse)
async def claude_status(
    _owner: Owner,
    service: Annotated[ClaudeCliService, Depends(get_claude_service)],
    client: Annotated[redis.Redis, Depends(get_redis_client)],
) -> ClaudeStatusResponse:
    """Testa a sessão com uma chamada real (``claude -p "ok"``) e atualiza o estado da fila."""
    status = await check_session(service)
    _sync_queue_state(client, status)
    return _to_response(status)


@router.post("/reauth", response_model=ClaudeReauthResponse)
async def claude_reauth(
    owner: Owner,
    manager: Annotated[ClaudeReauthManager, Depends(get_reauth_manager)],
) -> ClaudeReauthResponse:
    """Inicia o login do Claude Code e devolve o link de autorização para o administrador."""
    started = await manager.start()
    audit_event("claude_reauth_started", user_id=owner.id)
    return ClaudeReauthResponse(login_id=started.login_id, login_url=started.login_url)


@router.post("/reauth/complete", response_model=ClaudeStatusResponse)
async def claude_reauth_complete(
    payload: ClaudeReauthCompleteRequest,
    owner: Owner,
    manager: Annotated[ClaudeReauthManager, Depends(get_reauth_manager)],
    service: Annotated[ClaudeCliService, Depends(get_claude_service)],
    client: Annotated[redis.Redis, Depends(get_redis_client)],
) -> ClaudeStatusResponse:
    """Envia o código do administrador ao login, confere a sessão e retoma a fila se ela estiver válida."""
    await manager.complete(payload.login_id, payload.code)
    status = await check_session(service)
    _sync_queue_state(client, status)
    audit_event("claude_reauth_completed", user_id=owner.id, authenticated=status.authenticated)
    return _to_response(status)
