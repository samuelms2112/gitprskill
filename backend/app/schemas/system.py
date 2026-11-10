"""Schemas do diagnóstico e da reautenticação da sessão do Claude Code CLI."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClaudeStatusResponse(BaseModel):
    """Resultado do teste de sessão. ``error_message`` é ``None`` quando a sessão está válida."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authenticated: bool
    last_checked: datetime
    error_message: str | None


class ClaudeReauthResponse(BaseModel):
    """Login iniciado: o administrador abre ``login_url``, autoriza e devolve o código."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    login_id: str
    login_url: str


class ClaudeReauthCompleteRequest(BaseModel):
    """Código de autorização copiado da página do Claude."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    login_id: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=512)
