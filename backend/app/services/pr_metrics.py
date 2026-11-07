"""Métricas de engenharia de Pull Requests: tamanho (XS a XL) e tempo até o merge.

Funções puras, sem I/O: são usadas pela ingestão ao gravar o PR e pelo schema para
garantir que os valores persistidos sejam consistentes com os dados brutos.

Faixas de tamanho (linhas adicionadas + removidas):
    XS: < 10   |   S: 10-49   |   M: 50-249   |   L: 250-999   |   XL: >= 1000
"""

from datetime import datetime

from app.models.enums import PRSizeCategory

# Limites superiores inclusivos de cada faixa, em linhas alteradas.
_XS_MAX = 9
_S_MAX = 49
_M_MAX = 249
_L_MAX = 999


def total_changes(additions: int, deletions: int) -> int:
    """Soma de linhas adicionadas e removidas.

    Raises:
        ValueError: Se algum dos valores for negativo.
    """
    if additions < 0 or deletions < 0:
        raise ValueError("Contagens de linhas não podem ser negativas.")
    return additions + deletions


def classify_pr_size(changed_lines: int) -> PRSizeCategory:
    """Classifica um PR pelo total de linhas alteradas.

    Raises:
        ValueError: Se ``changed_lines`` for negativo.
    """
    if changed_lines < 0:
        raise ValueError("O total de linhas alteradas não pode ser negativo.")
    if changed_lines <= _XS_MAX:
        return PRSizeCategory.XS
    if changed_lines <= _S_MAX:
        return PRSizeCategory.S
    if changed_lines <= _M_MAX:
        return PRSizeCategory.M
    if changed_lines <= _L_MAX:
        return PRSizeCategory.L
    return PRSizeCategory.XL


def compute_time_to_merge_seconds(created_at: datetime, merged_at: datetime | None) -> int | None:
    """Segundos entre a abertura e o merge. ``None`` enquanto o PR não foi mergeado.

    Raises:
        ValueError: Se ``merged_at`` for anterior a ``created_at``.
    """
    if merged_at is None:
        return None
    delta = merged_at - created_at
    if delta.total_seconds() < 0:
        raise ValueError("merged_at não pode ser anterior a created_at.")
    return int(delta.total_seconds())
