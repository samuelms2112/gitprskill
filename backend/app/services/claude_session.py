"""Gestão da sessão do Claude Code CLI: diagnóstico, estado da fila e reautenticação.

* ``check_session`` faz um teste real (``claude -p "ok"``) para saber se o login ainda vale.
* O estado ``AUTH_REQUIRED`` fica no Redis, compartilhado por API e worker. Enquanto estiver ativo,
  o worker pausa o processamento da fila sem descartar nenhum PR.
* ``ClaudeReauthManager`` inicia ``claude auth login``, extrai o link de autorização e, depois que o
  administrador envia o código, conclui o login. O processo fica vivo entre as duas chamadas.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

import redis

from app.core.exceptions import (
    AIError,
    AIRateLimitError,
    AIUnavailableError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.services.ai.claude_cli_service import ClaudeCliService

logger = get_logger(__name__)

AUTH_STATE_KEY: Final = "claude:session:state"
AUTH_OK: Final = "OK"
AUTH_REQUIRED: Final = "AUTH_REQUIRED"

LOGIN_URL_PATTERN: Final = re.compile(r"https://[^\s\"'<>]+")
LOGIN_TIMEOUT_SECONDS: Final = 60.0
LOGIN_CODE_TIMEOUT_SECONDS: Final = 120.0
PENDING_LOGIN_TTL_SECONDS: Final = 600.0
MAX_CODE_CHARS: Final = 512


@dataclass(frozen=True, slots=True)
class SessionStatus:
    """Resultado de um teste de sessão."""

    authenticated: bool
    last_checked: datetime
    error_message: str | None


@dataclass(frozen=True, slots=True)
class ReauthStart:
    """Login iniciado: o link para o administrador abrir e o identificador para concluir."""

    login_id: str
    login_url: str


async def check_session(service: ClaudeCliService) -> SessionStatus:
    """Testa a sessão com uma chamada real e classifica o resultado. Não lança exceções de IA."""
    checked_at = datetime.now(UTC)
    try:
        await service.ask("ok")
    except AIRateLimitError:
        # Sessão válida, apenas sem cota no momento.
        return SessionStatus(True, checked_at, "Sessão válida, mas com limite de uso atingido.")
    except AIError as exc:
        return SessionStatus(False, checked_at, exc.message)
    return SessionStatus(True, checked_at, None)


def read_auth_state(client: redis.Redis) -> str:
    """Estado atual da sessão. Sem registro, a sessão é considerada válida."""
    return AUTH_REQUIRED if client.get(AUTH_STATE_KEY) == AUTH_REQUIRED else AUTH_OK


def set_auth_required(client: redis.Redis, reason: str) -> None:
    """Pausa a fila: a sessão precisa de novo login."""
    client.set(AUTH_STATE_KEY, AUTH_REQUIRED)
    logger.warning("Fila pausada: sessão do Claude exige login", extra={"reason": reason[:200]})


def clear_auth_required(client: redis.Redis) -> None:
    """Retoma a fila."""
    client.delete(AUTH_STATE_KEY)


@dataclass(slots=True)
class _PendingLogin:
    process: asyncio.subprocess.Process
    expires_at: float
    drain: asyncio.Task[None] | None = field(default=None)


class ClaudeReauthManager:
    """Mantém os logins em andamento. Uma instância por processo da API."""

    def __init__(self, *, command: str) -> None:
        self._command = command
        self._pending: dict[str, _PendingLogin] = {}

    async def start(self) -> ReauthStart:
        """Inicia ``claude auth login`` e devolve o link de autorização.

        Raises:
            AIUnavailableError: CLI ausente, ou o link não apareceu no tempo limite.
        """
        await self._discard_expired()
        try:
            process = await asyncio.create_subprocess_exec(
                self._command,
                "auth",
                "login",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=tempfile.gettempdir(),
            )
        except FileNotFoundError as exc:
            raise AIUnavailableError(f"Claude Code CLI não encontrado: '{self._command}'.") from exc

        try:
            login_url = await asyncio.wait_for(self._read_login_url(process), LOGIN_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            await _terminate(process)
            raise AIUnavailableError("O Claude não devolveu o link de autorização a tempo.") from exc
        except AIUnavailableError:
            await _terminate(process)
            raise

        login_id = uuid.uuid4().hex
        pending = _PendingLogin(process=process, expires_at=time.monotonic() + PENDING_LOGIN_TTL_SECONDS)
        # Continua drenando a saída para o processo não travar com o buffer cheio.
        pending.drain = asyncio.create_task(_drain(process))
        self._pending[login_id] = pending
        return ReauthStart(login_id=login_id, login_url=login_url)

    async def complete(self, login_id: str, code: str) -> None:
        """Envia o código de autorização ao login e espera o CLI concluir.

        Raises:
            NotFoundError: Login desconhecido ou expirado.
            AIUnavailableError: O CLI não concluiu o login.
        """
        pending = self._pending.pop(login_id, None)
        if pending is None or pending.expires_at < time.monotonic():
            raise NotFoundError("Login não encontrado ou expirado. Inicie a renovação de novo.")

        process = pending.process
        if process.stdin is not None:
            process.stdin.write(f"{code.strip()}\n".encode())
            await process.stdin.drain()
            process.stdin.close()
        try:
            returncode = await asyncio.wait_for(process.wait(), LOGIN_CODE_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            await _terminate(process)
            raise AIUnavailableError("O login não foi concluído a tempo.") from exc
        finally:
            if pending.drain is not None:
                pending.drain.cancel()
        if returncode != 0:
            raise AIUnavailableError("O código de autorização foi recusado pelo Claude.")

    async def _read_login_url(self, process: asyncio.subprocess.Process) -> str:
        assert process.stdout is not None
        buffer = ""
        while True:
            chunk = await process.stdout.read(1024)
            if not chunk:
                raise AIUnavailableError("O comando de login terminou sem devolver um link.")
            buffer += chunk.decode("utf-8", "replace")
            match = LOGIN_URL_PATTERN.search(buffer)
            if match is not None:
                return match.group(0)

    async def _discard_expired(self) -> None:
        now = time.monotonic()
        for login_id in [key for key, item in self._pending.items() if item.expires_at < now]:
            pending = self._pending.pop(login_id)
            await _terminate(pending.process)


async def _drain(process: asyncio.subprocess.Process) -> None:
    if process.stdout is None:
        return
    while await process.stdout.read(4096):
        pass


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            return
        await process.wait()
