"""Testes unitários das métricas de PR: faixas de tamanho (XS a XL) e tempo até o merge."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import PRSizeCategory
from app.services.pr_metrics import (
    classify_pr_size,
    compute_time_to_merge_seconds,
    total_changes,
)

CREATED = datetime(2026, 1, 10, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("changed_lines", "expected"),
    [
        (0, PRSizeCategory.XS),
        (9, PRSizeCategory.XS),  # último valor de XS
        (10, PRSizeCategory.S),  # primeiro valor de S
        (49, PRSizeCategory.S),  # último valor de S
        (50, PRSizeCategory.M),
        (249, PRSizeCategory.M),
        (250, PRSizeCategory.L),
        (999, PRSizeCategory.L),
        (1000, PRSizeCategory.XL),
        (250_000, PRSizeCategory.XL),
    ],
    ids=lambda v: str(v),
)
def test_size_category_boundaries(changed_lines: int, expected: PRSizeCategory) -> None:
    """Cada limite de faixa cai exatamente na faixa correta (inclusive nos extremos)."""
    assert classify_pr_size(changed_lines) is expected


def test_size_counts_additions_and_deletions_together() -> None:
    """Remover 6 linhas e adicionar 6 soma 12, o que cai em S, não em XS."""
    assert classify_pr_size(total_changes(additions=6, deletions=6)) is PRSizeCategory.S


def test_total_changes_rejects_negative_counts() -> None:
    """Contagens negativas indicam dado corrompido e são recusadas."""
    with pytest.raises(ValueError):
        total_changes(additions=-1, deletions=0)


def test_classify_rejects_negative_total() -> None:
    """Total negativo não tem categoria."""
    with pytest.raises(ValueError):
        classify_pr_size(-1)


def test_time_to_merge_is_difference_in_seconds() -> None:
    """Tempo até o merge é a diferença exata, em segundos inteiros."""
    merged = CREATED + timedelta(hours=2, minutes=30, seconds=15)
    assert compute_time_to_merge_seconds(CREATED, merged) == 9015


def test_time_to_merge_is_none_while_not_merged() -> None:
    """PR ainda não mergeado não tem tempo até o merge."""
    assert compute_time_to_merge_seconds(CREATED, None) is None


def test_time_to_merge_zero_when_merged_at_equals_created_at() -> None:
    """Merge no mesmo instante da abertura é zero, não um erro."""
    assert compute_time_to_merge_seconds(CREATED, CREATED) == 0


def test_time_to_merge_rejects_merge_before_creation() -> None:
    """Merge anterior à abertura é inconsistente e recusado."""
    with pytest.raises(ValueError):
        compute_time_to_merge_seconds(CREATED, CREATED - timedelta(seconds=1))
