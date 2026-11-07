"""Emissão e validação de tokens JWT (sessão do usuário e ``state`` do OAuth).

Decisões de segurança:
    * Algoritmo fixado em HS256; ``none`` e qualquer outro são rejeitados na decodificação.
    * ``iss``, ``aud``, ``exp``, ``iat`` e ``jti`` são obrigatórios e verificados.
    * O claim ``typ`` impede usar um token de um tipo onde outro é esperado
      (ex.: um ``state`` do OAuth como token de sessão).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt import InvalidTokenError

from app.core.config import MIN_JWT_SECRET_LENGTH

JWT_ALGORITHM = "HS256"
ISSUER = "github-management-platform"
AUDIENCE = "github-management-api"
ACCESS_TOKEN_TYPE = "access"
OAUTH_STATE_TYPE = "oauth_state"
_REQUIRED_CLAIMS = ["exp", "iat", "sub", "aud", "iss", "jti", "typ"]


class TokenValidationError(Exception):
    """Token inválido, expirado ou de tipo inesperado. Camadas superiores o convertem em erro HTTP."""


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """Claims de um token de sessão já validado."""

    user_id: int
    expires_at: datetime


class TokenService:
    """Cria e valida tokens JWT. Sem estado: depende apenas do segredo e dos TTLs."""

    def __init__(
        self,
        *,
        secret: str,
        access_token_ttl: timedelta,
        oauth_state_ttl: timedelta,
    ) -> None:
        """Configura o serviço.

        Raises:
            ValueError: Se o segredo for mais curto que o mínimo exigido.
        """
        if len(secret) < MIN_JWT_SECRET_LENGTH:
            raise ValueError("Segredo JWT insuficiente.")
        self._secret = secret
        self._access_ttl = access_token_ttl
        self._state_ttl = oauth_state_ttl

    def create_access_token(self, user_id: int) -> tuple[str, int]:
        """Gera um token de sessão para o usuário.

        Returns:
            Tupla ``(token, expires_in_seconds)``.
        """
        token = self._encode(str(user_id), ACCESS_TOKEN_TYPE, self._access_ttl)
        return token, int(self._access_ttl.total_seconds())

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        """Valida um token de sessão e extrai o identificador do usuário.

        Raises:
            TokenValidationError: Se o token for inválido, expirado ou de outro tipo.
        """
        claims = self._decode(token, ACCESS_TOKEN_TYPE)
        try:
            user_id = int(claims["sub"])
        except (TypeError, ValueError) as exc:
            raise TokenValidationError("Claim 'sub' inválido.") from exc
        return AccessTokenClaims(
            user_id=user_id,
            expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
        )

    def create_oauth_state(self) -> str:
        """Gera um ``state`` assinado e com expiração, usado para proteção contra CSRF no OAuth."""
        return self._encode(secrets.token_urlsafe(16), OAUTH_STATE_TYPE, self._state_ttl)

    def validate_oauth_state(self, state: str) -> None:
        """Confirma que o ``state`` foi emitido por este serviço e ainda está válido.

        Raises:
            TokenValidationError: Se o ``state`` for inválido, expirado ou adulterado.
        """
        self._decode(state, OAUTH_STATE_TYPE)

    def _encode(self, subject: str, token_type: str, ttl: timedelta) -> str:
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": subject,
            "typ": token_type,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + ttl,
            "jti": secrets.token_urlsafe(12),
        }
        return jwt.encode(payload, self._secret, algorithm=JWT_ALGORITHM)

    def _decode(self, token: str, expected_type: str) -> dict[str, Any]:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                self._secret,
                algorithms=[JWT_ALGORITHM],
                audience=AUDIENCE,
                issuer=ISSUER,
                options={"require": _REQUIRED_CLAIMS},
            )
        except InvalidTokenError as exc:
            raise TokenValidationError(f"Token inválido: {exc.__class__.__name__}.") from exc
        if claims.get("typ") != expected_type:
            raise TokenValidationError("Tipo de token inesperado.")
        return claims
