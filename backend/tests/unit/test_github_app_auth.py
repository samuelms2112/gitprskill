"""Testes unitários da autenticação como GitHub App, com a API do GitHub simulada.

Uma chave RSA real é gerada no teste, para validar a assinatura RS256 de verdade.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.exceptions import (
    GitHubAppNotConfiguredError,
    GitHubAuthenticationError,
    GitHubNotFoundError,
)
from app.services.github_app_auth import GitHubAppAuth, GitHubInstallationDiffs
from app.services.github_client import GitHubClient

API = "https://api.github.com"
APP_ID = "123456"
NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC).timestamp()
EXPIRES_AT = "2026-01-10T13:00:00Z"


@dataclass(frozen=True)
class RsaKeys:
    private_pem: str
    public_pem: str


@pytest.fixture(scope="module")
def keys() -> RsaKeys:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return RsaKeys(private_pem=private_pem, public_pem=public_pem)


@dataclass
class FakeClock:
    now: float = NOW

    def __call__(self) -> float:
        return self.now


@dataclass
class FakeGitHub:
    """Simula a API: troca de token de instalação e busca de diff."""

    public_pem: str
    status_by_installation: dict[int, int] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    issued: int = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path.startswith("/app/installations/") and path.endswith("/access_tokens"):
            installation_id = int(path.split("/")[3])
            status = self.status_by_installation.get(installation_id, 201)
            if status != 201:
                return httpx.Response(status, json={"message": "nope"})
            self.issued += 1
            return httpx.Response(201, json={"token": f"ghs_{installation_id}_{self.issued}", "expires_at": EXPIRES_AT})
        if request.method == "GET" and path.startswith("/repos/"):
            return httpx.Response(200, text="diff de teste")
        return httpx.Response(404, json={"message": "Not Found"})

    def app_token_claims(self, request: httpx.Request) -> dict[str, Any]:
        """Decodifica e verifica a assinatura do JWT enviado (sem checar tempo: o relógio é simulado)."""
        token = request.headers["Authorization"].removeprefix("Bearer ")
        claims: dict[str, Any] = jwt.decode(
            token,
            self.public_pem,
            algorithms=["RS256"],
            options={"verify_exp": False, "verify_iat": False},
        )
        return claims


def _auth(keys: RsaKeys, github: FakeGitHub, clock: FakeClock, margin: float = 300) -> GitHubAppAuth:
    def factory(token: str) -> GitHubClient:
        return GitHubClient(
            http_client=httpx.AsyncClient(base_url=API, transport=httpx.MockTransport(github.handler)),
            token=token,
            sleep=_no_sleep,
            clock=clock,
        )

    return GitHubAppAuth(
        app_id=APP_ID,
        private_key_pem=keys.private_pem,
        client_factory=factory,
        clock=clock,
        refresh_margin_seconds=margin,
    )


async def _no_sleep(seconds: float) -> None:
    return None


@pytest.fixture
def github(keys: RsaKeys) -> FakeGitHub:
    return FakeGitHub(public_pem=keys.public_pem)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


# --- JWT do App -----------------------------------------------------------------------


def test_app_jwt_is_rs256_signed_with_app_id_and_short_lifetime(
    keys: RsaKeys, github: FakeGitHub, clock: FakeClock
) -> None:
    """O JWT é RS256, identifica o App pelo ``iss`` e vale no máximo 10 minutos."""
    token = _auth(keys, github, clock).create_app_jwt()

    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, keys.public_pem, algorithms=["RS256"], options={"verify_exp": False})

    assert header["alg"] == "RS256"
    assert claims["iss"] == APP_ID
    assert claims["iat"] == int(NOW) - 60  # tolerância de relógio
    assert claims["exp"] - claims["iat"] <= 600


def test_app_jwt_is_rejected_when_signed_with_other_key(keys: RsaKeys, github: FakeGitHub, clock: FakeClock) -> None:
    """Um JWT assinado por outra chave não passa na verificação com a chave pública do App."""
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    forged = jwt.encode({"iss": APP_ID, "iat": int(NOW), "exp": int(NOW) + 60}, other_pem, algorithm="RS256")

    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(forged, keys.public_pem, algorithms=["RS256"], options={"verify_exp": False})


def test_invalid_private_key_fails_at_construction_without_leaking_it(
    github: FakeGitHub, clock: FakeClock
) -> None:
    """Chave PEM inválida é detectada já na inicialização, sem expor o conteúdo na mensagem."""
    secret_looking = "-----BEGIN PRIVATE KEY-----\nSEGREDO-INVALIDO\n-----END PRIVATE KEY-----"

    with pytest.raises(GitHubAppNotConfiguredError) as exc_info:
        GitHubAppAuth(
            app_id=APP_ID,
            private_key_pem=secret_looking,
            client_factory=lambda token: GitHubClient(token=token),
            clock=clock,
        )

    assert "SEGREDO-INVALIDO" not in exc_info.value.message


@pytest.mark.parametrize(
    ("app_id", "has_key"),
    [(None, True), ("", True), ("abc", True), (APP_ID, False)],
    ids=["sem_id", "id_vazio", "id_nao_numerico", "sem_chave"],
)
def test_missing_or_malformed_configuration_is_refused(
    keys: RsaKeys, app_id: str | None, has_key: bool, clock: FakeClock
) -> None:
    """Configuração incompleta do App não permite autenticar."""
    with pytest.raises(GitHubAppNotConfiguredError):
        GitHubAppAuth(
            app_id=app_id,
            private_key_pem=keys.private_pem if has_key else None,
            client_factory=lambda token: GitHubClient(token=token),
            clock=clock,
        )


# --- Troca por token de instalação ----------------------------------------------------


async def test_exchange_uses_app_jwt_and_returns_installation_token(
    keys: RsaKeys, github: FakeGitHub, clock: FakeClock
) -> None:
    """A troca é feita com o JWT do App (Bearer) e devolve o token da instalação."""
    token = await _auth(keys, github, clock).get_installation_access_token(111)

    assert token.token == "ghs_111_1"
    assert token.expires_at == datetime(2026, 1, 10, 13, 0, tzinfo=UTC)
    request = github.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/app/installations/111/access_tokens"
    claims = github.app_token_claims(request)
    assert claims["iss"] == APP_ID


async def test_token_is_cached_until_near_expiry(keys: RsaKeys, github: FakeGitHub, clock: FakeClock) -> None:
    """Chamadas repetidas reutilizam o token sem nova requisição ao GitHub."""
    auth = _auth(keys, github, clock)

    first = await auth.get_installation_access_token(111)
    clock.now = NOW + 1800  # 30 minutos depois, longe da expiração
    second = await auth.get_installation_access_token(111)

    assert first.token == second.token
    assert len(github.requests) == 1


async def test_token_is_renewed_inside_refresh_margin(keys: RsaKeys, github: FakeGitHub, clock: FakeClock) -> None:
    """Perto da expiração (dentro da margem de 5 minutos), um novo token é emitido."""
    auth = _auth(keys, github, clock)
    await auth.get_installation_access_token(111)

    clock.now = datetime(2026, 1, 10, 12, 56, tzinfo=UTC).timestamp()  # faltam 4 minutos
    renewed = await auth.get_installation_access_token(111)

    assert renewed.token == "ghs_111_2"
    assert len(github.requests) == 2


async def test_each_installation_gets_its_own_token(keys: RsaKeys, github: FakeGitHub, clock: FakeClock) -> None:
    """Tenants diferentes nunca compartilham token: cada instalação tem o seu."""
    auth = _auth(keys, github, clock)

    tenant_a = await auth.get_installation_access_token(111)
    tenant_b = await auth.get_installation_access_token(222)

    assert tenant_a.token != tenant_b.token
    assert tenant_a.token.startswith("ghs_111_")
    assert tenant_b.token.startswith("ghs_222_")


async def test_concurrent_requests_for_same_installation_issue_one_token(
    keys: RsaKeys, github: FakeGitHub, clock: FakeClock
) -> None:
    """Chamadas concorrentes para a mesma instalação disparam uma única troca (sem rajada de tokens)."""
    auth = _auth(keys, github, clock)

    results = await asyncio.gather(*(auth.get_installation_access_token(111) for _ in range(5)))

    assert {token.token for token in results} == {"ghs_111_1"}
    assert len(github.requests) == 1


async def test_unknown_installation_raises_not_found_and_is_not_cached(
    keys: RsaKeys, github: FakeGitHub, clock: FakeClock
) -> None:
    """Instalação removida vira ``GitHubNotFoundError`` e não fica no cache."""
    github.status_by_installation[999] = 404
    auth = _auth(keys, github, clock)

    with pytest.raises(GitHubNotFoundError):
        await auth.get_installation_access_token(999)

    github.status_by_installation[999] = 201
    token = await auth.get_installation_access_token(999)
    assert token.token == "ghs_999_1"


async def test_rejected_app_jwt_raises_authentication_error(
    keys: RsaKeys, github: FakeGitHub, clock: FakeClock
) -> None:
    """Chave do App rejeitada pelo GitHub (HTTP 401) vira ``GitHubAuthenticationError``."""
    github.status_by_installation[111] = 401

    with pytest.raises(GitHubAuthenticationError):
        await _auth(keys, github, clock).get_installation_access_token(111)


async def test_installation_id_must_be_positive(keys: RsaKeys, github: FakeGitHub, clock: FakeClock) -> None:
    """Identificador inválido é recusado antes de qualquer chamada."""
    client = GitHubClient(
        http_client=httpx.AsyncClient(base_url=API, transport=httpx.MockTransport(github.handler)),
        token="jwt",
    )
    with pytest.raises(ValueError):
        await client.create_installation_access_token(0)
    assert github.requests == []


async def test_diff_is_fetched_with_the_tenant_installation_token(
    keys: RsaKeys, github: FakeGitHub, clock: FakeClock
) -> None:
    """O diff de um PR do tenant 222 usa o token da instalação 222, nunca o de outro tenant."""
    auth = _auth(keys, github, clock)

    def factory(token: str) -> GitHubClient:
        return GitHubClient(
            http_client=httpx.AsyncClient(base_url=API, transport=httpx.MockTransport(github.handler)),
            token=token,
            sleep=_no_sleep,
            clock=clock,
        )

    diffs = await GitHubInstallationDiffs(auth, factory).get_diff(222, "org", "api", 42)

    assert diffs == "diff de teste"
    diff_request = github.requests[-1]
    assert diff_request.headers["Authorization"] == "Bearer ghs_222_1"
    assert diff_request.url.path == "/repos/org/api/pulls/42"

