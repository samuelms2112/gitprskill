"""Revisão automática de PRs e skill de revisão da empresa."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, TenantContext, require_role
from app.core.audit import audit_event
from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.exceptions import AINotConfiguredError, NotFoundError
from app.models.ai_review import AIReviewStatus, PullRequestAIReview, ReviewSkillRule
from app.models.enums import MemberRole
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.schemas.ai_review import (
    AIReviewRead,
    AIReviewRequested,
    ReviewSkillRead,
    SkillRuleRead,
    SkillRuleUpdate,
)
from app.services.pr_review import DEFAULT_SKILL_SLUG, ReviewFinding
from app.services.review_store import ensure_default_skill, request_review, skill_rules
from app.workers.review_tasks import review_pr_task

router = APIRouter(prefix="/tenants/{tenant_slug}", tags=["Revisão de PRs"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
ViewerContext = Annotated[TenantContext, Depends(require_role(MemberRole.VIEWER))]
DeveloperContext = Annotated[TenantContext, Depends(require_role(MemberRole.DEVELOPER))]
OwnerContext = Annotated[TenantContext, Depends(require_role(MemberRole.OWNER))]


@router.get("/reviews", response_model=list[AIReviewRead], summary="Revisões recentes de PRs do tenant")
async def list_reviews(
    context: ViewerContext,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AIReviewRead]:
    rows = await session.execute(
        select(PullRequestAIReview, PullRequest, Repository.full_name)
        .join(PullRequest, PullRequest.id == PullRequestAIReview.pull_request_id)
        .join(Repository, Repository.id == PullRequest.repository_id)
        .where(PullRequestAIReview.tenant_id == context.tenant.id)
        .order_by(PullRequestAIReview.created_at.desc())
        .limit(limit)
    )
    return [_to_read(review, pr, repository) for review, pr, repository in rows.all()]


@router.post(
    "/pull-requests/{pull_request_id}/review",
    response_model=AIReviewRequested,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pede uma nova revisão do PR com as skills da empresa",
)
async def request_pull_request_review(
    pull_request_id: int,
    context: DeveloperContext,
    actor: CurrentUser,
    session: DbSession,
) -> AIReviewRequested:
    settings = get_settings()
    if not settings.ai_configured:
        raise AINotConfiguredError("Integração com IA não configurada no servidor.")
    pull_request = await session.scalar(
        select(PullRequest).where(PullRequest.id == pull_request_id, PullRequest.tenant_id == context.tenant.id)
    )
    if pull_request is None:
        raise NotFoundError("Pull request não encontrado neste tenant.")

    review = await request_review(session, tenant_id=context.tenant.id, pull_request_id=pull_request.id)
    await session.commit()
    audit_event("pr_review_requested", tenant_slug=context.tenant.slug, pull_request_id=pull_request.id, actor_user_id=actor.id)


    review_pr_task.delay(review.id)
    return AIReviewRequested(id=review.id, pull_request_id=pull_request.id, status=review.status)


@router.get("/review-skill", response_model=ReviewSkillRead, summary="Skill de revisão da empresa")
async def get_review_skill(context: ViewerContext, session: DbSession) -> ReviewSkillRead:
    skill = await ensure_default_skill(session, context.tenant.id)
    rules = await skill_rules(session, skill.id)
    return ReviewSkillRead(
        slug=skill.slug,
        name=skill.name,
        rules=[SkillRuleRead(filename=r.filename, content=r.content, updated_at=r.updated_at) for r in rules],
    )


@router.put(
    "/review-skill/rules/{filename}",
    response_model=SkillRuleRead,
    summary="Edita o conteúdo de uma regra da skill (somente OWNER)",
)
async def update_skill_rule(
    filename: str,
    payload: SkillRuleUpdate,
    context: OwnerContext,
    actor: CurrentUser,
    session: DbSession,
) -> SkillRuleRead:
    skill = await ensure_default_skill(session, context.tenant.id)
    rule = await session.scalar(
        select(ReviewSkillRule).where(ReviewSkillRule.skill_id == skill.id, ReviewSkillRule.filename == filename)
    )
    if rule is None:
        raise NotFoundError("Regra não encontrada nesta skill.")
    rule.content = payload.content
    await session.flush()
    audit_event(
        "review_skill_rule_updated",
        tenant_slug=context.tenant.slug,
        skill=DEFAULT_SKILL_SLUG,
        filename=filename,
        actor_user_id=actor.id,
    )
    return SkillRuleRead(filename=rule.filename, content=rule.content, updated_at=rule.updated_at)


def _to_read(review: PullRequestAIReview, pr: PullRequest, repository: str) -> AIReviewRead:
    findings = (
        [ReviewFinding.model_validate(item) for item in review.findings] if review.findings is not None else None
    )
    return AIReviewRead(
        id=review.id,
        pull_request_id=pr.id,
        pr_number=pr.number,
        pr_title=pr.title,
        repository=repository,
        pr_url=pr.html_url,
        status=AIReviewStatus(review.status),
        findings=findings,
        findings_count=review.findings_count,
        error_message=review.error_message,
        publish_error=review.publish_error,
        github_review_url=review.github_review_url,
        created_at=review.created_at,
        finished_at=review.finished_at,
    )
