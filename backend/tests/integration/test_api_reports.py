"""Testes de integração dos relatórios de PRs e das release notes, pela API real."""

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import update

from app.api.deps import get_ai_service
from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.exceptions import AIRateLimitError
from app.main import app
from app.models.enums import AICategory, AIRiskLevel, MemberRole
from app.models.pull_request import PullRequest
from app.tasks.github_events import handle_event
from tests.factories.github import build_pull_request_event, build_user
from tests.fakes import FakeReleaseNotesAI
from tests.integration.helpers import (
    add_member,
    create_tenant,
    create_user,
    session_token,
)

pytestmark = pytest.mark.integration

TRACKED = frozenset({"main", "master", "master-tip"})
ENDPOINT_PRS = "/api/v1/reports/prs"
ENDPOINT_NOTES = "/api/v1/reports/release-notes"


def _merged_event(
    *,
    installation_id: int,
    number: int,
    pr_id: int,
    author_id: int,
    author_login: str,
    merged_at: str,
    base_ref: str = "main",
) -> dict[str, Any]:
    payload = build_pull_request_event(
        installation_id=installation_id, number=number, pr_id=pr_id, base_ref=base_ref
    )
    payload["pull_request"]["user"] = build_user(user_id=author_id, login=author_login)
    payload["pull_request"]["merged_at"] = merged_at
    return payload


async def _ingest(payload: dict[str, Any]) -> None:
    await handle_event(
        get_session_factory(),
        tracked_branches=TRACKED,
        event_name="pull_request",
        delivery_id="d",
        payload=payload,
    )


async def _enrich(tenant_id: int, number: int, category: AICategory, risk: AIRiskLevel) -> None:
    """Simula o enriquecimento de um PR do tenant (o fluxo real é coberto em test_enrichment)."""
    async with get_session_factory()() as session, session.begin():
        await session.execute(
            update(PullRequest)
            .where(PullRequest.tenant_id == tenant_id, PullRequest.number == number)
            .values(ai_summary=f"Resumo do PR {number}.", ai_category=category, ai_risk_level=risk)
        )


@pytest.fixture
async def scenario() -> dict[str, Any]:
    """Tenant A com dois PRs de autores diferentes, tenant B com um PR de mesmo número."""
    tenant_a = await create_tenant(slug="tenant-a", installation_id=111)
    tenant_b = await create_tenant(slug="tenant-b", installation_id=222)
    ana = await create_user(github_id=7001, login="dev-ana")
    bruno_user = await create_user(github_id=7002, login="dev-bruno")
    carla = await create_user(github_id=7003, login="carla")
    await add_member(tenant_id=tenant_a, user_id=ana, role=MemberRole.DEVELOPER)
    await add_member(tenant_id=tenant_b, user_id=bruno_user, role=MemberRole.OWNER)

    await _ingest(_merged_event(installation_id=111, number=1, pr_id=1, author_id=7001,
                                author_login="dev-ana", merged_at="2026-01-10T12:00:00Z"))
    await _ingest(_merged_event(installation_id=111, number=2, pr_id=2, author_id=7002,
                                author_login="dev-bruno", merged_at="2026-02-01T12:00:00Z"))
    await _ingest(_merged_event(installation_id=222, number=1, pr_id=3, author_id=7001,
                                author_login="dev-ana", merged_at="2026-01-10T12:00:00Z"))
    await _enrich(tenant_a, 1, AICategory.FEATURE, AIRiskLevel.LOW)
    await _enrich(tenant_a, 2, AICategory.SECURITY, AIRiskLevel.HIGH)

    return {"ana": ana, "carla": carla, "tenant_a": tenant_a, "tenant_b": tenant_b}


@pytest.fixture
def ai_override() -> Callable[[Any], None]:
    """Instala um fake do serviço de IA e o remove ao final do teste."""

    def install(fake: Any) -> None:
        async def _service() -> AsyncIterator[Any]:
            yield fake

        app.dependency_overrides[get_ai_service] = _service

    yield install
    app.dependency_overrides.pop(get_ai_service, None)


def _auth(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token(user_id)}"}


async def test_report_lists_only_the_requested_tenant(
    client: httpx.AsyncClient, scenario: dict[str, Any]
) -> None:
    """O relatório de A não contém o PR de mesmo número do tenant B."""
    response = await client.get(ENDPOINT_PRS, params={"tenant_slug": "tenant-a"}, headers=_auth(scenario["ana"]))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["number"] for item in body["items"]} == {1, 2}
    assert all(item["repository"] == "org/api" for item in body["items"])


async def test_report_is_ordered_by_merge_date_descending(
    client: httpx.AsyncClient, scenario: dict[str, Any]
) -> None:
    """Os PRs aparecem do mais recente para o mais antigo."""
    response = await client.get(ENDPOINT_PRS, params={"tenant_slug": "tenant-a"}, headers=_auth(scenario["ana"]))

    assert [item["number"] for item in response.json()["items"]] == [2, 1]


async def test_report_includes_enrichment_fields(client: httpx.AsyncClient, scenario: dict[str, Any]) -> None:
    """Os campos de IA aparecem no relatório."""
    response = await client.get(ENDPOINT_PRS, params={"tenant_slug": "tenant-a"}, headers=_auth(scenario["ana"]))

    pr2 = next(item for item in response.json()["items"] if item["number"] == 2)
    assert pr2["ai_category"] == "SECURITY"
    assert pr2["ai_risk_level"] == "HIGH"
    assert pr2["ai_summary"] == "Resumo do PR 2."
    assert pr2["author"] == "dev-bruno"


@pytest.mark.parametrize(
    ("params", "expected_numbers"),
    [
        ({"ai_category": "SECURITY"}, [2]),
        ({"author": "dev-ana"}, [1]),
        ({"start_date": "2026-01-15"}, [2]),
        ({"end_date": "2026-01-31"}, [1]),
        ({"start_date": "2026-01-10", "end_date": "2026-01-10"}, [1]),
    ],
    ids=["categoria_ia", "autor", "a_partir_de", "ate", "dia_exato"],
)
async def test_report_filters(
    client: httpx.AsyncClient, scenario: dict[str, Any], params: dict[str, str], expected_numbers: list[int]
) -> None:
    """Filtros por categoria de IA, autor e período combinam corretamente com o tenant."""
    response = await client.get(
        ENDPOINT_PRS, params={"tenant_slug": "tenant-a", **params}, headers=_auth(scenario["ana"])
    )

    assert response.status_code == 200
    assert sorted(item["number"] for item in response.json()["items"]) == expected_numbers


async def test_report_pagination_keeps_total(client: httpx.AsyncClient, scenario: dict[str, Any]) -> None:
    """``total`` reflete o conjunto filtrado, independentemente da página pedida."""
    response = await client.get(
        ENDPOINT_PRS,
        params={"tenant_slug": "tenant-a", "limit": 1, "offset": 1},
        headers=_auth(scenario["ana"]),
    )

    body = response.json()
    assert body["total"] == 2
    assert [item["number"] for item in body["items"]] == [1]


async def test_report_rejects_inverted_period(client: httpx.AsyncClient, scenario: dict[str, Any]) -> None:
    """Período com início posterior ao fim é recusado."""
    response = await client.get(
        ENDPOINT_PRS,
        params={"tenant_slug": "tenant-a", "start_date": "2026-03-01", "end_date": "2026-01-01"},
        headers=_auth(scenario["ana"]),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_payload"


async def test_report_for_non_member_is_not_found(client: httpx.AsyncClient, scenario: dict[str, Any]) -> None:
    """Ana não lê o relatório do tenant B; carla não lê nenhum."""
    other = await client.get(ENDPOINT_PRS, params={"tenant_slug": "tenant-b"}, headers=_auth(scenario["ana"]))
    none = await client.get(ENDPOINT_PRS, params={"tenant_slug": "tenant-a"}, headers=_auth(scenario["carla"]))

    assert other.status_code == 404
    assert none.status_code == 404


async def test_report_requires_authentication(client: httpx.AsyncClient, scenario: dict[str, Any]) -> None:
    """Sem token, o relatório não é acessível."""
    response = await client.get(ENDPOINT_PRS, params={"tenant_slug": "tenant-a"})
    assert response.status_code == 401


async def test_unknown_ai_category_is_rejected_by_validation(
    client: httpx.AsyncClient, scenario: dict[str, Any]
) -> None:
    """Categoria fora do domínio é recusada antes de chegar ao banco."""
    response = await client.get(
        ENDPOINT_PRS, params={"tenant_slug": "tenant-a", "ai_category": "HACK"}, headers=_auth(scenario["ana"])
    )
    assert response.status_code == 422


async def test_release_notes_are_generated_in_chronological_order(
    client: httpx.AsyncClient, scenario: dict[str, Any], ai_override: Callable[[Any], None]
) -> None:
    """As release notes recebem os PRs do período em ordem cronológica e devolvem o Markdown do modelo."""
    fake = FakeReleaseNotesAI(markdown="## Novas funcionalidades\n- Login (#1)")
    ai_override(fake)

    response = await client.post(
        ENDPOINT_NOTES,
        json={"tenant_slug": "tenant-a", "start_date": "2026-01-01", "end_date": "2026-12-31"},
        headers=_auth(scenario["ana"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["markdown"] == "## Novas funcionalidades\n- Login (#1)"
    assert body["pr_count"] == 2
    assert fake.calls == [[1, 2]]


async def test_release_notes_for_branch_without_prs_skip_the_model(
    client: httpx.AsyncClient, scenario: dict[str, Any], ai_override: Callable[[Any], None]
) -> None:
    """Sem PRs no escopo, a resposta é fixa e o modelo não é chamado (economia de cota)."""
    fake = FakeReleaseNotesAI()
    ai_override(fake)

    response = await client.post(
        ENDPOINT_NOTES,
        json={"tenant_slug": "tenant-a", "start_date": "2026-01-01", "end_date": "2026-12-31", "base_branch": "master-tip"},
        headers=_auth(scenario["ana"]),
    )

    assert response.json()["pr_count"] == 0
    assert "Nenhum Pull Request" in response.json()["markdown"]
    assert fake.calls == []


async def test_release_notes_rate_limit_returns_429_with_retry_after(
    client: httpx.AsyncClient, scenario: dict[str, Any], ai_override: Callable[[Any], None]
) -> None:
    """Limite da IA chega ao cliente como 429 com ``Retry-After``."""
    ai_override(FakeReleaseNotesAI(error=AIRateLimitError(retry_after=30)))

    response = await client.post(
        ENDPOINT_NOTES,
        json={"tenant_slug": "tenant-a", "start_date": "2026-01-01", "end_date": "2026-12-31"},
        headers=_auth(scenario["ana"]),
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert response.json()["error"]["code"] == "ai_rate_limited"


async def test_release_notes_for_non_member_never_reach_the_model(
    client: httpx.AsyncClient, scenario: dict[str, Any], ai_override: Callable[[Any], None]
) -> None:
    """Quem não é membro recebe 404 e o modelo não recebe dados de outro tenant."""
    fake = FakeReleaseNotesAI()
    ai_override(fake)

    response = await client.post(
        ENDPOINT_NOTES,
        json={"tenant_slug": "tenant-a", "start_date": "2026-01-01", "end_date": "2026-12-31"},
        headers=_auth(scenario["carla"]),
    )

    assert response.status_code == 404
    assert fake.calls == []


async def test_release_notes_without_ai_key_return_503(
    client: httpx.AsyncClient, scenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem ``GEMINI_API_KEY``, o endpoint informa claramente que a IA não está configurada."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()

    response = await client.post(
        ENDPOINT_NOTES,
        json={"tenant_slug": "tenant-a", "start_date": "2026-01-01", "end_date": "2026-12-31"},
        headers=_auth(scenario["ana"]),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_not_configured"


@pytest.mark.parametrize(
    ("start", "end"),
    [("2026-03-01", "2026-01-01"), ("2026-01-01", "2028-01-01")],
    ids=["periodo_invertido", "periodo_longo_demais"],
)
async def test_release_notes_reject_invalid_periods(
    client: httpx.AsyncClient, scenario: dict[str, Any], start: str, end: str
) -> None:
    """Períodos inválidos ou longos demais são recusados antes de qualquer chamada à IA."""
    response = await client.post(
        ENDPOINT_NOTES,
        json={"tenant_slug": "tenant-a", "start_date": start, "end_date": end},
        headers=_auth(scenario["ana"]),
    )
    assert response.status_code == 422


async def test_release_notes_reject_untracked_branch(client: httpx.AsyncClient, scenario: dict[str, Any]) -> None:
    """Somente ``main``, ``master`` e ``master-tip`` são aceitas como branch."""
    response = await client.post(
        ENDPOINT_NOTES,
        json={"tenant_slug": "tenant-a", "start_date": "2026-01-01", "end_date": "2026-12-31", "base_branch": "develop"},
        headers=_auth(scenario["ana"]),
    )
    assert response.status_code == 422
