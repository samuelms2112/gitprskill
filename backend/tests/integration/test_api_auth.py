"""Testes de integração do fluxo de login com GitHub OAuth.

O GitHub é simulado com ``httpx.MockTransport``: nenhuma chamada real é feita.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.api.deps import get_github_oauth_service, get_token_service
from app.core.config import get_settings
from app.core.database import get_session_factory
from app.main import app
from app.models.user import User
from app.services.github_client import GitHubClient
from app.services.github_oauth import AUTHORIZE_URL, TOKEN_URL, GitHubOAuthService
from tests.integration.helpers import count_rows

pytestmark = pytest.mark.integration

CODE = "codigo-de-teste"
PROFILE = {"id": 7001, "login": "ana", "email": "ana@example.com", "avatar_url": "https://a/1"}
Handler = Callable[[httpx.Request], httpx.Response]


def _override_oauth(token_handler: Handler, api_handler: Handler) -> Callable[[], AsyncIterator[GitHubOAuthService]]:
    """Substitui o serviço OAuth por um que usa transportes simulados."""
    settings = get_settings()

    async def _service() -> AsyncIterator[GitHubOAuthService]:
        http = httpx.AsyncClient(transport=httpx.MockTransport(token_handler))
        try:
            yield GitHubOAuthService(
                client_id=settings.github_oauth_client_id,
                client_secret=settings.github_oauth_client_secret,
                redirect_uri=settings.github_oauth_redirect_uri,
                scopes=settings.github_oauth_scopes,
                http_client=http,
                api_client_factory=lambda token: GitHubClient(
                    http_client=httpx.AsyncClient(
                        base_url=settings.github_api_base_url,
                        transport=httpx.MockTransport(api_handler),
                    ),
                    token=token,
                ),
            )
        finally:
            await http.aclose()

    return _service


def _fragment(response: httpx.Response) -> dict[str, list[str]]:
    """Lê os parâmetros do fragmento da URL de redirecionamento (onde vai o token)."""
    return parse_qs(urlparse(response.headers["location"]).fragment)


def _github_ok(request: httpx.Request) -> httpx.Response:
    """Simula o GitHub: aceita o código de teste e devolve o perfil em ``/user``."""
    if str(request.url) == TOKEN_URL:
        form = parse_qs(request.content.decode())
        if form.get("code") != [CODE]:
            return httpx.Response(200, json={"error": "bad_verification_code"})
        return httpx.Response(200, json={"access_token": "gho_teste", "token_type": "bearer"})
    if request.url.path == "/user":
        assert request.headers["Authorization"] == "Bearer gho_teste"
        return httpx.Response(200, json=PROFILE)
    return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def oauth_override() -> Iterator[None]:
    """Instala o serviço simulado e o remove ao final do teste."""
    yield
    app.dependency_overrides.pop(get_github_oauth_service, None)


def _install(token_handler: Handler = _github_ok, api_handler: Handler = _github_ok) -> None:
    app.dependency_overrides[get_github_oauth_service] = _override_oauth(token_handler, api_handler)


async def test_login_redirects_to_github_with_signed_state(
    client: httpx.AsyncClient, oauth_override: None
) -> None:
    """``/login`` redireciona para o GitHub com ``client_id``, ``redirect_uri`` e um ``state`` assinado."""
    _install()

    response = await client.get("/api/v1/auth/github/login")

    assert response.status_code == 302
    location = urlparse(response.headers["location"])
    query = parse_qs(location.query)
    assert f"{location.scheme}://{location.netloc}{location.path}" == AUTHORIZE_URL
    assert query["client_id"] == [get_settings().github_oauth_client_id]
    assert query["redirect_uri"] == [get_settings().github_oauth_redirect_uri]
    assert query["scope"] == [get_settings().github_oauth_scopes]
    get_token_service().validate_oauth_state(query["state"][0])  # não lança: state válido


async def test_full_callback_creates_user_and_issues_session(
    client: httpx.AsyncClient, oauth_override: None
) -> None:
    """Callback com ``state`` válido e ``code`` correto cria o usuário e devolve um JWT utilizável."""
    _install()
    state = get_token_service().create_oauth_state()

    response = await client.get(
        "/api/v1/auth/github/callback", params={"code": CODE, "state": state}
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("http://localhost:3000/auth/callback#")
    fragment = _fragment(response)
    assert int(fragment["expires_in"][0]) > 0

    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {fragment['access_token'][0]}"}
    )
    assert me.status_code == 200
    assert me.json()["login"] == "ana"
    assert me.json()["email"] == "ana@example.com"


async def test_second_login_updates_existing_user(
    client: httpx.AsyncClient, oauth_override: None
) -> None:
    """Logins repetidos atualizam o mesmo usuário (chave: ``github_id``)."""
    _install()
    for _ in range(2):
        state = get_token_service().create_oauth_state()
        await client.get("/api/v1/auth/github/callback", params={"code": CODE, "state": state})

    assert await count_rows(User) == 1


async def test_callback_rejects_forged_state(client: httpx.AsyncClient, oauth_override: None) -> None:
    """``state`` não emitido pelo servidor (proteção contra CSRF) é recusado."""
    _install()

    response = await client.get(
        "/api/v1/auth/github/callback", params={"code": CODE, "state": "nao-e-um-jwt"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_oauth_state"
    assert await count_rows(User) == 0


async def test_callback_rejects_state_signed_with_other_key(
    client: httpx.AsyncClient, oauth_override: None
) -> None:
    """``state`` assinado com outra chave é recusado."""
    from datetime import timedelta

    from app.core.security import TokenService

    _install()
    foreign = TokenService(
        secret="outra-chave-com-mais-de-trinta-e-dois-caracteres",
        access_token_ttl=timedelta(minutes=5),
        oauth_state_ttl=timedelta(minutes=5),
    ).create_oauth_state()

    response = await client.get(
        "/api/v1/auth/github/callback", params={"code": CODE, "state": foreign}
    )
    assert response.status_code == 400


async def test_rejected_code_returns_bad_gateway(client: httpx.AsyncClient, oauth_override: None) -> None:
    """Código recusado pelo GitHub vira 502 com o motivo, sem criar usuário."""
    _install()
    state = get_token_service().create_oauth_state()

    response = await client.get(
        "/api/v1/auth/github/callback", params={"code": "codigo-errado", "state": state}
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "github_oauth_failed"
    assert "bad_verification_code" in response.json()["error"]["message"]
    assert await count_rows(User) == 0


async def test_github_outage_during_exchange_returns_bad_gateway(
    client: httpx.AsyncClient, oauth_override: None
) -> None:
    """Falha de comunicação com o GitHub na troca é reportada como erro de gateway."""
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("indisponível", request=request)

    _install(token_handler=_down)
    state = get_token_service().create_oauth_state()

    response = await client.get(
        "/api/v1/auth/github/callback", params={"code": CODE, "state": state}
    )
    assert response.status_code == 502


async def test_session_token_is_stored_as_user_id_subject(
    client: httpx.AsyncClient, oauth_override: None
) -> None:
    """O ``sub`` do JWT é o ``id`` interno do usuário, não o ``github_id``."""
    _install()
    state = get_token_service().create_oauth_state()
    response = await client.get("/api/v1/auth/github/callback", params={"code": CODE, "state": state})

    claims = get_token_service().decode_access_token(_fragment(response)["access_token"][0])
    async with get_session_factory()() as session:
        user = await session.get(User, claims.user_id)
    assert user is not None
    assert user.github_id == PROFILE["id"]
