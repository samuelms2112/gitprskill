"""Revisão de PRs com as skills da empresa: skills, regras editáveis e o resultado de cada revisão."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AIReviewStatus(StrEnum):
    """Ciclo de vida de uma revisão. ``PENDING`` aparece no card assim que a revisão é pedida."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReviewSkill(TimestampMixin, Base):
    """Skill de revisão de um tenant. Cada tenant tem a sua, editável pelo dono."""

    __tablename__ = "review_skills"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_review_skills_tenant_slug"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class ReviewSkillRule(TimestampMixin, Base):
    """Arquivo de regra de uma skill (ex.: ``magic-numbers.md``). O conteúdo é editável pelo portal."""

    __tablename__ = "review_skill_rules"
    __table_args__ = (UniqueConstraint("skill_id", "filename", name="uq_review_skill_rules_skill_filename"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    skill_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("review_skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class PullRequestAIReview(Base):
    """Uma revisão de um PR. Guarda o status, os apontamentos e a versão das regras usada."""

    __tablename__ = "pr_ai_reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pull_request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[AIReviewStatus] = mapped_column(String(20), nullable=False)
    findings: Mapped[list[dict] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    publish_error: Mapped[str | None] = mapped_column(Text)
    github_review_url: Mapped[str | None] = mapped_column(Text)
    rules_version: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    findings_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
