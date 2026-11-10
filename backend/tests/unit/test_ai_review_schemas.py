"""Validação do payload de edição de regra da skill de revisão."""

import pytest
from pydantic import ValidationError

from app.schemas.ai_review import MAX_RULE_CONTENT_CHARS, SkillRuleUpdate


def test_rule_content_is_required_and_stripped() -> None:
    assert SkillRuleUpdate(content="  regra  ").content == "regra"


@pytest.mark.parametrize("content", ["", "   "])
def test_empty_rule_is_rejected(content: str) -> None:
    with pytest.raises(ValidationError):
        SkillRuleUpdate(content=content)


def test_oversized_rule_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SkillRuleUpdate(content="x" * (MAX_RULE_CONTENT_CHARS + 1))


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SkillRuleUpdate(content="ok", filename="outro.md")
