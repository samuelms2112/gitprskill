"""Modelos ORM da aplicação.

Todos os modelos são importados aqui para que ``Base.metadata`` conheça o
esquema completo, requisito para o autogenerate do Alembic.
"""

from app.models.ai_review import PullRequestAIReview, ReviewSkill, ReviewSkillRule
from app.models.base import Base
from app.models.contributor import Contributor
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.review import Review
from app.models.tenant import Tenant
from app.models.tenant_member import TenantMember
from app.models.user import User

__all__ = [
    "Base",
    "Contributor",
    "PullRequest",
    "PullRequestAIReview",
    "Repository",
    "Review",
    "ReviewSkill",
    "ReviewSkillRule",
    "Tenant",
    "TenantMember",
    "User",
]
