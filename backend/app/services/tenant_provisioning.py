"""Provisionamento de tenants e repositórios a partir dos eventos de instalação do GitHub App.

* ``installation.created``: garante o tenant (cria se não existir), torna quem instalou o App
  ``OWNER`` e cadastra os repositórios incluídos na instalação.
* ``installation.deleted``: desvincula a instalação do tenant, preservando os dados históricos.
* ``installation_repositories.added``: cadastra os repositórios recém-incluídos.
* ``installation_repositories.removed``: não apaga nada. O histórico dos repositórios é preservado.

Todas as operações são idempotentes: entregas repetidas não criam duplicatas.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.enums import MemberRole
from app.models.tenant import Tenant
from app.models.tenant_member import TenantMember
from app.schemas.github import (
    InstallationEventPayload,
    InstallationRepositoriesEventPayload,
)
from app.services.outcomes import IngestionOutcome
from app.services.repository_catalog import register_repositories
from app.services.users import upsert_user

logger = get_logger(__name__)


class TenantProvisioningService:
    """Mantém a relação entre instalações do GitHub App, tenants e repositórios."""

    def __init__(self, session: AsyncSession) -> None:
        """Associa o serviço a uma sessão."""
        self._session = session

    async def handle(self, event: InstallationEventPayload) -> IngestionOutcome:
        """Aplica a ação do evento ``installation`` e devolve o desfecho."""
        if event.action == "created":
            tenant_id = await self._ensure_tenant(event)
            await register_repositories(self._session, tenant_id, event.repositories)
            return IngestionOutcome.PROVISIONED
        if event.action == "deleted":
            return await self._detach(event.installation.id)
        return IngestionOutcome.IGNORED_ACTION

    async def handle_repositories(
        self, event: InstallationRepositoriesEventPayload
    ) -> IngestionOutcome:
        """Cadastra os repositórios adicionados à instalação. Remoções são registradas, não apagadas."""
        tenant_id = await self._tenant_id_for(event.installation.id)
        if tenant_id is None:
            return IngestionOutcome.IGNORED_UNKNOWN_INSTALLATION
        if event.action == "added":
            await register_repositories(self._session, tenant_id, event.repositories_added)
            return IngestionOutcome.REGISTERED_REPOSITORIES
        if event.action == "removed":
            logger.info(
                "Repositórios removidos da instalação; histórico preservado",
                extra={"count": len(event.repositories_removed)},
            )
        return IngestionOutcome.IGNORED_ACTION

    async def _ensure_tenant(self, event: InstallationEventPayload) -> int:
        """Devolve o id do tenant da instalação, criando-o e vinculando o instalador se preciso."""
        installation_id = event.installation.id
        existing = await self._tenant_id_for(installation_id)
        if existing is not None:
            # Entrega repetida: o tenant já existe; só os repositórios são reconciliados.
            return existing

        account = event.installation.account
        slug = await self._available_slug(account.login.lower(), installation_id)
        tenant = Tenant(name=account.login, slug=slug, github_installation_id=installation_id)
        self._session.add(tenant)
        await self._session.flush()

        installer = await upsert_user(
            self._session,
            github_id=event.sender.id,
            login=event.sender.login,
            email=None,
            avatar_url=event.sender.avatar_url,
        )
        self._session.add(TenantMember(tenant_id=tenant.id, user_id=installer.id, role=MemberRole.OWNER))
        await self._session.flush()
        logger.info("Tenant provisionado", extra={"tenant_slug": slug})
        return tenant.id

    async def _detach(self, installation_id: int) -> IngestionOutcome:
        tenant = await self._session.scalar(
            select(Tenant).where(Tenant.github_installation_id == installation_id)
        )
        if tenant is None:
            return IngestionOutcome.IGNORED_UNKNOWN_INSTALLATION
        tenant.github_installation_id = None
        await self._session.flush()
        logger.info("Instalação desvinculada do tenant", extra={"tenant_slug": tenant.slug})
        return IngestionOutcome.DETACHED

    async def _tenant_id_for(self, installation_id: int) -> int | None:
        found = await self._session.scalar(
            select(Tenant.id).where(Tenant.github_installation_id == installation_id)
        )
        return int(found) if found is not None else None

    async def _available_slug(self, login: str, installation_id: int) -> str:
        """Usa o login como slug; se já estiver ocupado, acrescenta o id da instalação."""
        taken = await self._session.scalar(select(Tenant.id).where(Tenant.slug == login))
        return login if taken is None else f"{login}-{installation_id}"
