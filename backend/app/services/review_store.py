"""Acesso ao banco da revisão automática: skill padrão por empresa, regras e revisões pendentes."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_review import (
    AIReviewStatus,
    PullRequestAIReview,
    ReviewSkill,
    ReviewSkillRule,
)
from app.services.pr_review import (
    DEFAULT_SKILL_NAME,
    DEFAULT_SKILL_SLUG,
    load_default_rules,
)


async def ensure_default_skill(session: AsyncSession, tenant_id: int) -> ReviewSkill:
    """Skill padrão da empresa. Na primeira vez, cria a skill com as regras da pasta do sistema."""
    skill = await session.scalar(
        select(ReviewSkill).where(ReviewSkill.tenant_id == tenant_id, ReviewSkill.slug == DEFAULT_SKILL_SLUG)
    )
    if skill is not None:
        return skill
    skill = ReviewSkill(tenant_id=tenant_id, slug=DEFAULT_SKILL_SLUG, name=DEFAULT_SKILL_NAME)
    session.add(skill)
    await session.flush()
    for filename, content in load_default_rules():
        session.add(ReviewSkillRule(skill_id=skill.id, filename=filename, content=content))
    await session.flush()
    return skill


async def skill_rules(session: AsyncSession, skill_id: int) -> list[ReviewSkillRule]:
    rows = await session.scalars(
        select(ReviewSkillRule).where(ReviewSkillRule.skill_id == skill_id).order_by(ReviewSkillRule.filename)
    )
    return list(rows.all())


async def latest_rules_version(session: AsyncSession, skill_id: int) -> datetime | None:
    """Data da última edição de alguma regra: identifica a versão das regras usada numa revisão."""
    return await session.scalar(
        select(func.max(ReviewSkillRule.updated_at)).where(ReviewSkillRule.skill_id == skill_id)
    )


async def request_review(
    session: AsyncSession, *, tenant_id: int, pull_request_id: int, trigger: str | None = None
) -> PullRequestAIReview:
    """Registra uma revisão pendente. O card do PR passa a mostrar 'Revisando' já neste momento."""
    review = PullRequestAIReview(
        tenant_id=tenant_id,
        pull_request_id=pull_request_id,
        status=AIReviewStatus.PENDING,
        findings_count=0,
        trigger=trigger,
    )
    session.add(review)
    await session.flush()
    return review


async def bot_comment_ids(session: AsyncSession, pull_request_id: int) -> frozenset[int]:
    """Ids dos comentários que a plataforma já publicou neste PR, para reconhecer respostas às threads dela."""
    rows = await session.scalars(
        select(PullRequestAIReview.github_comment_ids).where(
            PullRequestAIReview.pull_request_id == pull_request_id,
            PullRequestAIReview.github_comment_ids.is_not(None),
        )
    )
    ids: set[int] = set()
    for values in rows.all():
        ids.update(value for value in values if isinstance(value, int))
    return frozenset(ids)
