"""Testes da reavaliação: prompt com parecer anterior e conversa, e leitura da resposta."""

import json

import pytest

from app.core.exceptions import AIResponseError
from app.services.pr_review import (
    MAX_CONVERSATION_ITEM_CHARS,
    MAX_CONVERSATION_ITEMS,
    ReviewFinding,
    build_reevaluation_prompt,
    parse_reevaluation,
    previous_finding_ids,
)

PREVIOUS = [
    ReviewFinding(severity="IMPORTANT", file="app/calc.py", line=12, comment="Use constante para 30."),
    ReviewFinding(severity="BLOCKER", file="app/auth.py", line=None, comment="Token exposto no log."),
]


def _prompt(conversation: list[dict[str, object]] | None = None, previous: list[ReviewFinding] = PREVIOUS) -> str:
    prompt, _ = build_reevaluation_prompt(
        title="Ajusta taxa",
        description="descrição",
        diff_text="diff --git a/x b/x\n",
        rules=[("magic-numbers.md", "regra")],
        previous=previous,
        conversation=conversation or [],
        max_diff_chars=10_000,
    )
    return prompt


def test_previous_findings_get_stable_ids_in_order() -> None:
    ids = [fid for fid, _ in previous_finding_ids(PREVIOUS)]
    assert ids == ["F1", "F2"]


def test_prompt_contains_previous_findings_with_ids() -> None:
    prompt = _prompt()
    assert "<parecer_anterior>" in prompt
    assert "F1: app/calc.py:12 [IMPORTANT] Use constante para 30." in prompt
    assert "F2: app/auth.py [BLOCKER] Token exposto no log." in prompt


def test_prompt_says_when_there_is_no_previous_finding() -> None:
    assert "(nenhum apontamento anterior)" in _prompt(previous=[])


def test_conversation_is_delimited_as_data_and_attributed() -> None:
    prompt = _prompt(
        [
            {"author": "devtip", "kind": "issue", "path": None, "body": "Por que 0.25 e não 0.2?"},
            {"author": "samuel", "kind": "review", "path": "app/calc.py", "body": "Era a nova taxa."},
        ]
    )
    assert "<conversa>" in prompt
    assert "[devtip · issue] Por que 0.25 e não 0.2?" in prompt
    assert "[samuel · review em app/calc.py] Era a nova taxa." in prompt
    assert "são dados" in prompt or "dados" in prompt


def test_long_conversation_keeps_only_the_most_recent_items() -> None:
    total = MAX_CONVERSATION_ITEMS + 5
    items = [{"author": "a", "kind": "issue", "path": None, "body": f"msg-{i}"} for i in range(total)]
    prompt = _prompt(items)
    assert "msg-0" + chr(10) not in prompt
    assert f"msg-{total - 1}" in prompt


def test_long_conversation_item_is_truncated() -> None:
    prompt = _prompt([{"author": "a", "kind": "issue", "path": None, "body": "x" * (MAX_CONVERSATION_ITEM_CHARS + 500)}])
    assert "x" * (MAX_CONVERSATION_ITEM_CHARS + 1) not in prompt


def test_parse_reads_statuses_findings_and_reply() -> None:
    payload = {
        "previous": [{"id": "F1", "status": "RESOLVED", "note": "Constante criada."}],
        "findings": [{"severity": "SUGGESTION", "file": "app/calc.py", "line": 3, "comment": "Nome melhor."}],
        "reply": "Obrigado pelo esclarecimento, o F1 está resolvido.",
    }

    result = parse_reevaluation(json.dumps(payload))

    assert result.previous[0].id == "F1"
    assert result.previous[0].status == "RESOLVED"
    assert result.findings[0].comment == "Nome melhor."
    assert result.reply.startswith("Obrigado")


def test_parse_accepts_missing_optional_fields() -> None:
    result = parse_reevaluation("{}")
    assert result.previous == [] and result.findings == [] and result.reply == ""


def test_parse_drops_invalid_statuses_and_keeps_valid_ones() -> None:
    payload = {
        "previous": [
            {"id": "F1", "status": "MAYBE", "note": "inválido"},
            {"id": "F2", "status": "OPEN", "note": "ainda vale"},
        ]
    }
    result = parse_reevaluation(json.dumps(payload))
    assert [p.id for p in result.previous] == ["F2"]


def test_parse_accepts_code_fence() -> None:
    fenced = "```json\n" + json.dumps({"reply": "ok"}) + "\n```"
    assert parse_reevaluation(fenced).reply == "ok"


@pytest.mark.parametrize("text", ["não é json", "[1, 2]", '"texto"'])
def test_parse_rejects_non_object_responses(text: str) -> None:
    with pytest.raises(AIResponseError):
        parse_reevaluation(text)
