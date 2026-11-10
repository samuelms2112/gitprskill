"""Revisão de PRs com skills por empresa: skills, regras editáveis e revisões com status.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Cria as tabelas da revisão automática. Não altera dados existentes."""
    op.create_table(
        "review_skills",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_review_skills_tenant_slug"),
    )
    op.create_index("ix_review_skills_tenant_id", "review_skills", ["tenant_id"])

    op.create_table(
        "review_skill_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("skill_id", sa.BigInteger(), sa.ForeignKey("review_skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("skill_id", "filename", name="uq_review_skill_rules_skill_filename"),
    )
    op.create_index("ix_review_skill_rules_skill_id", "review_skill_rules", ["skill_id"])

    op.create_table(
        "pr_ai_reviews",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "pull_request_id",
            sa.BigInteger(),
            sa.ForeignKey("pull_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("findings_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("publish_error", sa.Text(), nullable=True),
        sa.Column("github_review_url", sa.Text(), nullable=True),
        sa.Column("rules_version", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pr_ai_reviews_tenant_id", "pr_ai_reviews", ["tenant_id"])
    op.create_index("ix_pr_ai_reviews_pull_request_id", "pr_ai_reviews", ["pull_request_id"])
    op.create_index("ix_pr_ai_reviews_created_at", "pr_ai_reviews", ["created_at"])


def downgrade() -> None:
    """Remove as tabelas da revisão automática, com as revisões e as regras editadas."""
    op.drop_table("pr_ai_reviews")
    op.drop_table("review_skill_rules")
    op.drop_table("review_skills")
