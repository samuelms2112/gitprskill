"""Schemas de resposta da autenticação."""

from typing import Literal

from pydantic import BaseModel


class TokenResponse(BaseModel):
    """Token de sessão emitido após o login."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
