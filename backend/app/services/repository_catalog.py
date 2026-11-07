"""Cadastro de repositórios a partir dos eventos de instalação do GitHub App.

Assim, um repositório aparece no seletor da plataforma assim que é conectado à instalação,
sem depender de já existir um PR mergeado. Os dados vêm reduzidos nesses eventos, então:
    * o dono e a URL são derivados do ``full_name``;
    * a branch padrão só é preenchida na criação. Nas atualizações ela é preservada, porque
      o evento não a informa, e sobrescrevê-la com um valor presumido estaria errado.
"""

from collections.abc import Sequence

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.repository import Repository
from app.schemas.github import GitHubInstallationRepository
from app.schemas.repository import RepositoryCreate
from app.services.validation import validate_domain

logger = get_logger(__name__)

DEFAULT_BRANCH = "main"


async def register_repositories(
    session: AsyncSession,
    tenant_id: int,
    repositories: Sequence[GitHubInstallationRepository],
) -> int:
    """Cria ou atualiza os repositórios do tenant. Devolve quantos foram processados.

    Raises:
        InvalidPayloadError: Se algum nome não for um ``owner/repo`` válido.
    """
    for repository in repositories:
        owner, _, _ = repository.full_name.partition("/")
        data = validate_domain(
            RepositoryCreate,
            tenant_id=tenant_id,
            github_id=repository.id,
            name=repository.name,
            full_name=repository.full_name,
            owner_login=owner,
            html_url=f"https://github.com/{repository.full_name}",
            default_branch=DEFAULT_BRANCH,
            is_private=repository.private,
        )
        statement = pg_insert(Repository).values(**data.model_dump())
        statement = statement.on_conflict_do_update(
            index_elements=[Repository.tenant_id, Repository.github_id],
            # ``default_branch`` fica de fora de propósito: ver a docstring do módulo.
            set_={
                "name": statement.excluded.name,
                "full_name": statement.excluded.full_name,
                "owner_login": statement.excluded.owner_login,
                "html_url": statement.excluded.html_url,
                "is_private": statement.excluded.is_private,
                "updated_at": func.now(),
            },
        )
        await session.execute(statement)

    if repositories:
        logger.info("Repositórios cadastrados pela instalação", extra={"count": len(repositories)})
    return len(repositories)
