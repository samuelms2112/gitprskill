"""Enumerações de domínio compartilhadas entre modelos e schemas."""

from enum import StrEnum


class PullRequestState(StrEnum):
    """Estado de um Pull Request conforme a API do GitHub."""

    OPEN = "open"
    CLOSED = "closed"


class PRSizeCategory(StrEnum):
    """Categoria de tamanho de PR (XS a XL), calculada pelo motor de métricas."""

    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class MemberRole(StrEnum):
    """Papéis de acesso dentro de um tenant, do menos ao mais privilegiado."""

    VIEWER = "VIEWER"
    DEVELOPER = "DEVELOPER"
    OWNER = "OWNER"

    @property
    def rank(self) -> int:
        """Nível hierárquico usado nas checagens de permissão."""
        return _ROLE_RANKS[self]

    def includes(self, required: "MemberRole") -> bool:
        """Indica se este papel atende ao mínimo exigido."""
        return self.rank >= required.rank


_ROLE_RANKS: dict[MemberRole, int] = {
    MemberRole.VIEWER: 0,
    MemberRole.DEVELOPER: 1,
    MemberRole.OWNER: 2,
}


class AICategory(StrEnum):
    """Categoria principal de um PR, atribuída pelo modelo de IA."""

    FEATURE = "FEATURE"
    BUGFIX = "BUGFIX"
    REFACTOR = "REFACTOR"
    SECURITY = "SECURITY"
    CHORE = "CHORE"


class AIRiskLevel(StrEnum):
    """Avaliação de impacto/risco de um PR, atribuída pelo modelo de IA."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReviewState(StrEnum):
    """Estados de revisão reportados pelo GitHub."""

    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    COMMENTED = "COMMENTED"
