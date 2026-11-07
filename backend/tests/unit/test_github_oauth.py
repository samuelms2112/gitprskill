"""Testes unitários do serviço de login OAuth, com o GitHub simulado por ``MockTransport``."""

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import SecretStr

from app.core.exceptions import OAuthError, OAuthNotConfiguredError
from app.services.github_client import GitHubClient
from app.services.github_oauth import AUTHORIZE_URL, TOKEN_URL, GitHubOAuthService

CLIENT_ID = "client-123"
REDIRECT = "https://app.example.com/api/v1/auth/github/callback"
PROFILE = {"id": 7001, "login": "ana", "email": None, "avatar_url": None}


def _service(
    token_handler: Any,
    *,
    client_id: str | None = CLIENT_ID,
    redirect_uri: str | None = REDIRECT,
    api_handler: Any = None,
) -> GitHubOAuthService:
    def api_factory(token: str) -> GitHubClient:
        return GitHubClient(
            http_client=httpx.AsyncClient(
                base_url="https://api.github.com",
                transport=httpx.MockTransport(api_handler or (lambda r: httpx.Response(200, json=PROFILE))),
            ),
            token=token,
        )

    return GitHubOAuthService(
        client_id=client_id,
        client_secret=SecretStr("segredo-oauth"),
        redirect_uri=redirect_uri,
        scopes="read:user user:email",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(token_handler)),
        api_client_factory=api_factory,
    )


def test_authorize_url_contains_required_parameters() -> None:
    """A URL de autorização leva client_id, redirect_uri, escopos e o state."""
    url = _service(lambda r: httpx.Response(500)).build_authorize_url("state-xyz")

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZE_URL
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["scope"] == ["read:user user:email"]
    assert query["state"] == ["state-xyz"]


def test_authorize_url_requires_configuration() -> None:
    """Sem ``client_id`` configurado, o login não é iniciado."""
    service = _service(lambda r: httpx.Response(500), client_id=None)

    with pytest.raises(OAuthNotConfiguredError):
        service.build_authorize_url("state")


async def test_complete_login_exchanges_code_and_returns_profile() -> None:
    """Código válido vira token, e o token é usado para buscar o perfil."""
    seen_form: dict[str, list[str]] = {}

    def token_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TOKEN_URL
        seen_form.update(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"access_token": "gho_ok", "token_type": "bearer"})

    def api_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer gho_ok"
        return httpx.Response(200, json=PROFILE)

    profile = await _service(token_handler, api_handler=api_handler).complete_login("codigo-1")

    assert profile.login == "ana"
    assert seen_form["code"] == ["codigo-1"]
    assert seen_form["client_secret"] == ["segredo-oauth"]
    assert seen_form["redirect_uri"] == [REDIRECT]


async def test_rejected_code_raises_oauth_error_with_reason() -> None:
    """O GitHub responde 200 com ``error`` para códigos inválidos; isso vira ``OAuthError``."""
    service = _service(lambda r: httpx.Response(200, json={"error": "bad_verification_code"}))

    with pytest.raises(OAuthError, match="bad_verification_code"):
        await service.complete_login("expirado")


async def test_http_error_on_exchange_raises_oauth_error() -> None:
    """Erro HTTP na troca de código vira ``OAuthError``."""
    with pytest.raises(OAuthError):
        await _service(lambda r: httpx.Response(500)).complete_login("c")


async def test_network_failure_on_exchange_raises_oauth_error() -> None:
    """Falha de rede na troca vira ``OAuthError``, sem vazar a exceção do transporte."""

    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rota", request=request)

    with pytest.raises(OAuthError):
        await _service(_down).complete_login("c")


async def test_non_json_response_raises_oauth_error() -> None:
    """Resposta que não é JSON é tratada como falha da integração."""
    with pytest.raises(OAuthError):
        await _service(lambda r: httpx.Response(200, text="<html>")).complete_login("c")
