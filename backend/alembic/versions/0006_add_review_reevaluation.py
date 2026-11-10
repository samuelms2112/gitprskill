"""Reavaliação de PRs: motivo do disparo, resposta publicada e ids dos comentários do bot.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Colunas novas são anuláveis: revisões antigas continuam válidas."""
    op.add_column("pr_ai_reviews", sa.Column("trigger", sa.String(length=20), nullable=True))
    op.add_column("pr_ai_reviews", sa.Column("reply_text", sa.Text(), nullable=True))
    op.add_column(
        "pr_ai_reviews",
        sa.Column("github_comment_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pr_ai_reviews", "github_comment_ids")
    op.drop_column("pr_ai_reviews", "reply_text")
    op.drop_column("pr_ai_reviews", "trigger")
