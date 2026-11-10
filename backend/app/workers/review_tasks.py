"""Tarefa Celery da revisão automática: lê o PR, roda as regras no Claude e publica a review.

Estados em ``pr_ai_reviews``: PENDING (pedida) -> RUNNING -> COMPLETED ou FAILED.
A publicação no GitHub é sempre como ``COMMENT``. Falha de publicação não invalida a revisão:
os apontamentos continuam no portal e o erro fica em ``publish_error``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import redis
from celery import Task
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from app.core.audit import audit_event
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.exceptions import (
    AIError,
    AIRateLimitError,
    AIResponseError,
    AISessionExpiredError,
    GitHubError,
)
from app.core.logging import configure_logging, get_logger
from app.models.ai_review import AIReviewStatus, PullRequestAIReview
from app.models.pull_request import PullRequest
from app.models.tenant import Tenant
from app.services.ai.base import AIProvider
from app.services.ai.factory import open_ai_services
from app.services.claude_session import (
    AUTH_REQUIRED,
    read_auth_state,
    set_auth_required,
)
from app.services.github_client import GitHubClient
from app.services.pr_review import (
    ReviewFinding,
    build_review_prompt,
    commentable_lines,
    parse_findings,
    review_body,
    split_findings,
)
from app.services.review_store import (
    ensure_default_skill,
    latest_rules_version,
    skill_rules,
)
from app.workers.backfill_tasks import _build_app_auth
from app.workers.tasks import (
    AUTH_PAUSE_SECONDS,
    _session_restored,
    _state_redis,
)

logger = get_logger(__name__)

SKIPPED_NO_AI = "skipped_ai_not_configured"


async def run_review(review_id: int) -> str:
    """Executa uma revisão pendente e devolve o estado final."""
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.ai_configured:
        logger.info("Revisão ignorada: IA não configurada", extra={"review_id": review_id})
        return SKIPPED_NO_AI

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        app_auth = _build_app_auth(settings)
        if app_auth is None:
            await _finish(session_factory, review_id, AIReviewStatus.FAILED, error="GitHub App não configurado.")
            return "failed"
        async with open_ai_services(settings) as services:
            return await _execute(session_factory, services.provider, app_auth, review_id)
    finally:
        await engine.dispose()


async def _execute(
    session_factory: async_sessionmaker[AsyncSession],
    provider: AIProvider,
    app_auth: Any,
    review_id: int,
) -> str:
    job = await _start(session_factory, review_id)
    if job is None:
        return "skipped"

    settings = get_settings()
    try:
        token = await app_auth.get_installation_access_token(job["installation_id"])
        async with GitHubClient(
            base_url=settings.github_api_base_url,
            token=token.token,
            timeout=settings.github_request_timeout_seconds,
        ) as gh:
            github_pr = await gh.get_pull_request(job["owner"], job["repo"], job["number"])
            diff = await gh.get_pull_request_diff(job["owner"], job["repo"], job["number"])

            prompt, _truncated = build_review_prompt(
                title=job["title"],
                description=job["body"],
                diff_text=diff,
                rules=job["rules"],
                max_diff_chars=settings.claude_max_diff_chars,
            )
            try:
                text = await provider.generate_text(prompt)
                findings = parse_findings(text)
            except (AISessionExpiredError, AIRateLimitError):
                raise
            except (AIError, AIResponseError) as exc:
                await _finish(session_factory, review_id, AIReviewStatus.FAILED, error=exc.message)
                return "failed"

            publish_url, publish_error = await _publish(gh, job, github_pr.head.sha, diff, findings)
    except GitHubError as exc:
        await _finish(session_factory, review_id, AIReviewStatus.FAILED, error=exc.message)
        return "failed"

    await _finish(
        session_factory,
        review_id,
        AIReviewStatus.COMPLETED,
        findings=[f.model_dump(mode="json") for f in findings],
        rules_version=job["rules_version"],
        publish_url=publish_url,
        publish_error=publish_error,
    )
    audit_event("pr_review_completed", review_id=review_id, findings=len(findings), published=publish_url is not None)
    return "completed"


async def _publish(
    gh: GitHubClient,
    job: dict[str, Any],
    head_sha: str | None,
    diff: str,
    findings: list[ReviewFinding],
) -> tuple[str | None, str | None]:
    """Publica a review como COMMENT. Sem apontamentos, nada é publicado. Se o GitHub recusar os
    comentários em linha, tenta de novo com tudo no corpo da review."""
    if not findings:
        return None, None
    if not head_sha:
        return None, "O GitHub não informou o commit do PR."

    inline, general = split_findings(findings, commentable_lines(diff))
    try:
        url = await gh.create_pull_request_review(
            job["owner"],
            job["repo"],
            job["number"],
            commit_id=head_sha,
            body=review_body(general, total=len(findings)),
            comments=inline,
        )
        return url, None
    except GitHubError:
        logger.info("GitHub recusou comentários em linha; publicando tudo no corpo da review")
    try:
        url = await gh.create_pull_request_review(
            job["owner"],
            job["repo"],
            job["number"],
            commit_id=head_sha,
            body=review_body(findings, total=len(findings)),
            comments=[],
        )
        return url, None
    except GitHubError as exc:
        return None, exc.message


async def _start(session_factory: async_sessionmaker[AsyncSession], review_id: int) -> dict[str, Any] | None:
    """Marca a revisão como RUNNING e reúne o que ela precisa. ``None`` se não há o que fazer."""
    async with session_factory() as session, session.begin():
        review = await session.get(PullRequestAIReview, review_id)
        if review is None or review.status in (AIReviewStatus.COMPLETED, AIReviewStatus.FAILED):
            return None
        pr = await session.get(PullRequest, review.pull_request_id, options=[selectinload(PullRequest.repository)])
        tenant = await session.get(Tenant, review.tenant_id)
        if pr is None or tenant is None or tenant.github_installation_id is None:
            review.status = AIReviewStatus.FAILED
            review.error_message = "PR ou instalação do GitHub não disponível."
            review.finished_at = datetime.now(UTC)
            return None

        skill = await ensure_default_skill(session, tenant.id)
        rules = [(rule.filename, rule.content) for rule in await skill_rules(session, skill.id)]
        review.status = AIReviewStatus.RUNNING
        return {
            "installation_id": tenant.github_installation_id,
            "owner": pr.repository.owner_login,
            "repo": pr.repository.name,
            "number": pr.number,
            "title": pr.title,
            "body": pr.body or "",
            "rules": rules,
            "rules_version": await latest_rules_version(session, skill.id),
        }


async def _finish(
    session_factory: async_sessionmaker[AsyncSession],
    review_id: int,
    status: AIReviewStatus,
    *,
    error: str | None = None,
    findings: list[dict[str, Any]] | None = None,
    rules_version: datetime | None = None,
    publish_url: str | None = None,
    publish_error: str | None = None,
) -> None:
    async with session_factory() as session, session.begin():
        review = await session.get(PullRequestAIReview, review_id)
        if review is None:
            return
        review.status = status
        review.error_message = error
        review.findings = findings
        review.findings_count = len(findings or [])
        review.rules_version = rules_version
        review.github_review_url = publish_url
        review.publish_error = publish_error
        review.finished_at = datetime.now(UTC)


def _review_or_reschedule(self: Task, review_id: int) -> str:
    client: redis.Redis = _state_redis()
    try:
        if read_auth_state(client) == AUTH_REQUIRED and not _session_restored(client):
            # Fila pausada por falta de login: a revisão espera, sem gastar cota.
            raise self.retry(countdown=AUTH_PAUSE_SECONDS, max_retries=None)
        return asyncio.run(run_review(review_id))
    except AISessionExpiredError as exc:
        set_auth_required(client, exc.message)
        audit_event("claude_session_expired", review_id=review_id)
        raise self.retry(exc=exc, countdown=AUTH_PAUSE_SECONDS, max_retries=None) from exc
    except AIRateLimitError as exc:
        logger.warning("Limite da IA atingido; reagendando revisão", extra={"review_id": review_id})
        raise self.retry(exc=exc, countdown=exc.retry_after) from exc
    finally:
        client.close()


@celery_app.task(
    name="review_pr",
    bind=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def review_pr_task(self: Task, review_id: int) -> str:
    """Revisa um PR com as regras da skill da empresa e publica o resultado.

    Args:
        review_id: ``id`` da revisão em ``pr_ai_reviews`` (criada como PENDING por quem pediu).
    """
    return _review_or_reschedule(self, review_id)
