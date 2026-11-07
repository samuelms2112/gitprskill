"""Memória semântica e parecer PM/PO: extensão pgvector, vetor do resumo e índice HNSW.

Todas as colunas novas são anuláveis: PRs já existentes ficam sem parecer e sem vetor até
serem reenriquecidos. A extensão ``vector`` não é removida no downgrade, porque outras tabelas
podem passar a depender dela.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 768


def upgrade() -> None:
    """Habilita pgvector, adiciona as colunas e o índice de similaridade."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("pull_requests", sa.Column("ai_product_opinion", sa.Text(), nullable=True))
    op.add_column(
        "pull_requests",
        sa.Column("ai_embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
    )
    op.create_index(
        "ix_pull_requests_ai_embedding",
        "pull_requests",
        ["ai_embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"ai_embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    """Remove o índice e as colunas. A extensão permanece instalada."""
    op.drop_index("ix_pull_requests_ai_embedding", table_name="pull_requests")
    op.drop_column("pull_requests", "ai_embedding")
    op.drop_column("pull_requests", "ai_product_opinion")
