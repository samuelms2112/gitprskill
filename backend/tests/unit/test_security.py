"""Testes unitários da emissão e validação de JWT (sessão e ``state`` do OAuth)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest

from app.core.security import (
    ACCESS_TOKEN_TYPE,
    AUDIENCE,
    ISSUER,
    JWT_ALGORITHM,
    TokenService,
    TokenValidationError,
)

SECRET = "chave-de-teste-com-mais-de-trinta-e-dois-caracteres"


@pytest.fixture
def service() -> TokenService:
    return TokenService(
        secret=SECRET,
        access_token_ttl=timedelta(minutes=5),
        oauth_state_ttl=timedelta(minutes=10),
    )


def _raw_token(claims: dict[str, Any], key: str = SECRET, algorithm: str = JWT_ALGORITHM) -> str:
    """Gera um token manualmente, para simular emissores maliciosos ou mal configurados."""
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "sub": "1",
        "typ": ACCESS_TOKEN_TYPE,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": "abc123",
    }
    base.update(claims)
    return jwt.encode(base, key if algorithm != "none" else None, algorithm=algorithm)


def test_access_token_roundtrip_returns_user_id_and_ttl(service: TokenService) -> None:
    """Token emitido é validado e devolve o usuário e a validade em segundos."""
    token, expires_in = service.create_access_token(42)

    claims = service.decode_access_token(token)

    assert expires_in == 300
    assert claims.user_id == 42
    assert claims.expires_at > datetime.now(UTC)


def test_each_token_has_unique_identifier(service: TokenService) -> None:
    """Dois tokens emitidos para o mesmo usuário são distintos (``jti`` aleatório)."""
    first, _ = service.create_access_token(1)
    second, _ = service.create_access_token(1)
    assert first != second


def test_expired_token_is_rejected(service: TokenService) -> None:
    """Token com ``exp`` no passado é recusado."""
    expired = TokenService(
        secret=SECRET,
        access_token_ttl=timedelta(minutes=-1),
        oauth_state_ttl=timedelta(minutes=1),
    )
    token, _ = expired.create_access_token(1)

    with pytest.raises(TokenValidationError):
        service.decode_access_token(token)


def test_token_signed_with_other_key_is_rejected(service: TokenService) -> None:
    """Assinatura de outra chave é recusada."""
    forged = _raw_token({}, key="outra-chave-qualquer-com-mais-de-32-caracteres")

    with pytest.raises(TokenValidationError):
        service.decode_access_token(forged)


def test_tampered_signature_is_rejected(service: TokenService) -> None:
    """Alterar um caractere da assinatura invalida o token."""
    token, _ = service.create_access_token(1)
    tampered = token[:-3] + ("AAA" if token[-3:] != "AAA" else "BBB")

    with pytest.raises(TokenValidationError):
        service.decode_access_token(tampered)


def test_alg_none_is_rejected(service: TokenService) -> None:
    """Token sem assinatura (``alg: none``), ataque clássico, é recusado."""
    unsigned = _raw_token({}, algorithm="none")

    with pytest.raises(TokenValidationError):
        service.decode_access_token(unsigned)


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "outra-api"},
        {"iss": "outro-emissor"},
    ],
    ids=["audiencia_errada", "emissor_errado"],
)
def test_wrong_audience_or_issuer_is_rejected(service: TokenService, claims: dict[str, Any]) -> None:
    """Tokens emitidos para outro público ou por outro emissor são recusados."""
    with pytest.raises(TokenValidationError):
        service.decode_access_token(_raw_token(claims))


def test_missing_required_claim_is_rejected(service: TokenService) -> None:
    """Token sem ``jti`` (claim obrigatório) é recusado."""
    now = datetime.now(UTC)
    payload = {
        "sub": "1",
        "typ": ACCESS_TOKEN_TYPE,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(payload, SECRET, algorithm=JWT_ALGORITHM)

    with pytest.raises(TokenValidationError):
        service.decode_access_token(token)


def test_non_numeric_subject_is_rejected(service: TokenService) -> None:
    """O ``sub`` deve ser o id numérico do usuário."""
    with pytest.raises(TokenValidationError):
        service.decode_access_token(_raw_token({"sub": "nao-numerico"}))


def test_oauth_state_cannot_be_used_as_session_token(service: TokenService) -> None:
    """Um ``state`` do OAuth não serve como token de sessão (confusão de tipos)."""
    state = service.create_oauth_state()

    with pytest.raises(TokenValidationError, match="Tipo de token"):
        service.decode_access_token(state)


def test_session_token_cannot_be_used_as_oauth_state(service: TokenService) -> None:
    """Um token de sessão não é aceito como ``state`` do OAuth."""
    token, _ = service.create_access_token(1)

    with pytest.raises(TokenValidationError):
        service.validate_oauth_state(token)


def test_oauth_state_roundtrip(service: TokenService) -> None:
    """``state`` emitido pelo serviço é aceito."""
    service.validate_oauth_state(service.create_oauth_state())


def test_expired_oauth_state_is_rejected() -> None:
    """``state`` expirado é recusado, limitando a janela de reuso."""
    expired = TokenService(
        secret=SECRET,
        access_token_ttl=timedelta(minutes=5),
        oauth_state_ttl=timedelta(minutes=-1),
    )
    with pytest.raises(TokenValidationError):
        expired.validate_oauth_state(expired.create_oauth_state())


def test_weak_secret_is_refused_at_construction() -> None:
    """Segredos curtos não são aceitos pelo serviço."""
    with pytest.raises(ValueError):
        TokenService(
            secret="curta",
            access_token_ttl=timedelta(minutes=5),
            oauth_state_ttl=timedelta(minutes=5),
        )
