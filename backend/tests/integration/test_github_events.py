"""Testes de integração do processamento de eventos do GitHub App, contra PostgreSQL real.

Cobrem: roteamento por instalação, isolamento entre tenants, idempotência,
revisões e provisionamento de tenants pelo evento ``installation``.
"""

import pytest
from sqlalchemy import select

from app.core.database import get_session_factory
from app.core.exceptions import InvalidPayloadError
from app.models import (
    Contributor,
    PullRequest,
    Repository,
    Review,
    Tenant,
    TenantMember,
)
from app.models.enums import MemberRole, PullRequestState, ReviewState
from app.tasks.github_events import handle_event
from tests.factories.github import (
    build_installation_event,
    build_pull_request_event,
    build_review_event,
)
from tests.integration.helpers import count_rows, create_tenant

pytestmark = pytest.mark.integration

TRACKED = frozenset({"main", "master", "master-tip"})


async def _process(event_name: str, payload: dict, delivery: str = "entrega-1") -> str:
    return await handle_event(
        get_session_factory(),
        tracked_branches=TRACKED,
        event_name=event_name,
        delivery_id=delivery,
        payload=payload,
    )


async def _first(model: type) -> object:
    async with get_session_factory()() as session:
        return (await session.execute(select(model))).scalars().first()


async def test_merged_pr_is_stored_under_the_installation_tenant() -> None:
    """Evento de merge é gravado com o ``tenant_id`` da instalação que o originou."""
    tenant_id = await create_tenant(slug="acme", installation_id=111)

    outcome = await _process("pull_request", build_pull_request_event(installation_id=111))

    assert outcome == "processed"
    pr = await _first(PullRequest)
    repo = await _first(Repository)
    author = await _first(Contributor)
    assert pr.tenant_id == tenant_id
    assert repo.tenant_id == tenant_id
    assert author.tenant_id == tenant_id
    assert pr.state is PullRequestState.CLOSED
    assert pr.is_merged is True


async def test_same_github_repository_is_isolated_per_tenant() -> None:
    """O mesmo repositório do GitHub em dois tenants gera registros separados."""
    tenant_a = await create_tenant(slug="tenant-a", installation_id=111)
    tenant_b = await create_tenant(slug="tenant-b", installation_id=222)

    await _process("pull_request", build_pull_request_event(installation_id=111, pr_id=1))
    await _process("pull_request", build_pull_request_event(installation_id=222, pr_id=2))

    async with get_session_factory()() as session:
        repos = (await session.execute(select(Repository).order_by(Repository.tenant_id))).scalars().all()
    assert [repo.tenant_id for repo in repos] == [tenant_a, tenant_b]
    assert repos[0].github_id == repos[1].github_id  # mesmo repositório no GitHub
    assert await count_rows(PullRequest) == 2


async def test_unknown_installation_is_ignored_and_nothing_is_stored() -> None:
    """Sem tenant para a instalação, nenhum dado é gravado."""
    outcome = await _process("pull_request", build_pull_request_event(installation_id=999))

    assert outcome == "ignored_unknown_installation"
    assert await count_rows(PullRequest) == 0
    assert await count_rows(Repository) == 0


async def test_event_without_installation_is_ignored() -> None:
    """Payload sem ``installation`` não pode ser associado a tenant algum."""
    await create_tenant(slug="acme", installation_id=111)
    payload = build_pull_request_event()
    payload.pop("installation")

    outcome = await _process("pull_request", payload)

    assert outcome == "ignored_missing_installation"
    assert await count_rows(PullRequest) == 0


async def test_redelivery_does_not_duplicate_records() -> None:
    """Reprocessar a mesma entrega é idempotente."""
    await create_tenant(slug="acme", installation_id=111)
    payload = build_pull_request_event(installation_id=111)

    await _process("pull_request", payload)
    await _process("pull_request", payload)

    assert await count_rows(PullRequest) == 1
    assert await count_rows(Repository) == 1
    assert await count_rows(Contributor) == 1


async def test_open_pr_review_is_stored_and_pr_is_created_open() -> None:
    """Review chega antes do merge: o PR é gravado aberto e a revisão, associada a ele."""
    await create_tenant(slug="acme", installation_id=111)

    outcome = await _process(
        "pull_request_review",
        build_review_event(installation_id=111, review_state="approved"),
    )

    assert outcome == "stored_review"
    review = await _first(Review)
    pr = await _first(PullRequest)
    async with get_session_factory()() as session:
        reviewer = (
            await session.execute(select(Contributor).where(Contributor.login == "dev-bruno"))
        ).scalar_one()
    assert review.state is ReviewState.APPROVED  # webhook envia minúsculas
    assert review.pull_request_id == pr.id
    assert review.reviewer_id == reviewer.id
    assert pr.state is PullRequestState.OPEN
    assert pr.is_merged is False


async def test_later_merge_updates_the_pr_stored_from_a_review() -> None:
    """O merge posterior atualiza o PR criado pela revisão, sem duplicá-lo."""
    await create_tenant(slug="acme", installation_id=111)
    await _process("pull_request_review", build_review_event(installation_id=111, pr_merged=False))

    await _process("pull_request", build_pull_request_event(installation_id=111, pr_id=1001))

    assert await count_rows(PullRequest) == 1
    pr = await _first(PullRequest)
    assert pr.is_merged is True
    assert pr.merged_at is not None


async def test_review_state_is_updated_on_redelivery() -> None:
    """Uma nova revisão do mesmo ID atualiza o estado, sem criar outra linha."""
    await create_tenant(slug="acme", installation_id=111)
    await _process("pull_request_review", build_review_event(installation_id=111, review_state="commented"))

    await _process("pull_request_review", build_review_event(installation_id=111, review_state="changes_requested"))

    assert await count_rows(Review) == 1
    review = await _first(Review)
    assert review.state is ReviewState.CHANGES_REQUESTED


async def test_dismissed_review_is_ignored() -> None:
    """Estados fora do domínio, como ``dismissed``, não são persistidos."""
    await create_tenant(slug="acme", installation_id=111)

    outcome = await _process(
        "pull_request_review",
        build_review_event(installation_id=111, review_state="dismissed"),
    )

    assert outcome == "ignored_review_state"
    assert await count_rows(Review) == 0


async def test_review_on_untracked_branch_is_ignored() -> None:
    """Revisões em branches fora da lista rastreada não geram registros."""
    await create_tenant(slug="acme", installation_id=111)

    outcome = await _process(
        "pull_request_review",
        build_review_event(installation_id=111, base_ref="feature/x"),
    )

    assert outcome == "ignored_branch"
    assert await count_rows(PullRequest) == 0


async def test_installation_created_provisions_tenant_with_installer_as_owner() -> None:
    """Instalar o App cria o tenant e torna quem instalou o ``OWNER``."""
    outcome = await _process(
        "installation",
        build_installation_event(installation_id=5001, account_login="acme", sender_id=7001),
    )

    assert outcome == "provisioned"
    async with get_session_factory()() as session:
        tenant = (await session.execute(select(Tenant))).scalar_one()
        membership = (await session.execute(select(TenantMember))).scalar_one()
    assert tenant.slug == "acme"
    assert tenant.github_installation_id == 5001
    assert membership.tenant_id == tenant.id
    assert membership.role is MemberRole.OWNER


async def test_installation_redelivery_does_not_duplicate_tenant() -> None:
    """Entrega repetida de ``installation.created`` não cria outro tenant."""
    payload = build_installation_event(installation_id=5001)

    await _process("installation", payload)
    await _process("installation", payload)

    assert await count_rows(Tenant) == 1
    assert await count_rows(TenantMember) == 1


async def test_slug_collision_appends_installation_id() -> None:
    """Se o login já é um slug existente, o tenant recebe um sufixo com o id da instalação."""
    await create_tenant(slug="acme", installation_id=None)

    await _process("installation", build_installation_event(installation_id=5001, account_login="acme"))

    async with get_session_factory()() as session:
        slugs = set((await session.execute(select(Tenant.slug))).scalars().all())
    assert slugs == {"acme", "acme-5001"}


async def test_installation_deleted_detaches_and_stops_routing() -> None:
    """Após remover o App, eventos da instalação deixam de ser roteados, mas o histórico permanece."""
    await _process("installation", build_installation_event(installation_id=5001))
    await _process("installation", build_installation_event(action="deleted", installation_id=5001))

    tenant = await _first(Tenant)
    assert tenant.github_installation_id is None

    outcome = await _process("pull_request", build_pull_request_event(installation_id=5001))
    assert outcome == "ignored_unknown_installation"


async def test_unsupported_event_is_ignored() -> None:
    """Eventos sem tratamento retornam o desfecho apropriado sem efeitos colaterais."""
    assert await _process("star", {"action": "created"}) == "ignored_unsupported_event"


async def test_invalid_payload_raises_domain_error() -> None:
    """Payload sem campos obrigatórios é recusado com erro de aplicação (não é reenviado)."""
    await create_tenant(slug="acme", installation_id=111)
    payload = build_pull_request_event(installation_id=111)
    del payload["pull_request"]["user"]

    with pytest.raises(InvalidPayloadError):
        await _process("pull_request", payload)
