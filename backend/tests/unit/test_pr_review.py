"""Testes unitários da revisão automática: prompt, leitura da resposta, linhas do diff e publicação."""

import json

import pytest

from app.core.exceptions import AIResponseError
from app.services.pr_review import (
    MAX_FINDINGS,
    Severity,
    build_review_prompt,
    commentable_lines,
    load_default_rules,
    parse_findings,
    review_body,
    split_findings,
)

DIFF = """diff --git a/app/calc.py b/app/calc.py
index 111..222 100644
--- a/app/calc.py
+++ b/app/calc.py
@@ -10,5 +10,6 @@ def total(items):
     subtotal = 0
-    tax = 0.2
+    tax = 0.25
+    discount = 30
     for item in items:
         subtotal += item
     return subtotal
"""


def test_default_skill_ships_the_five_rules() -> None:
    names = [name for name, _ in load_default_rules()]
    assert names == [
        "dead-code.md",
        "debug-code.md",
        "hardcoded-secrets.md",
        "magic-numbers.md",
        "queries-in-loops.md",
    ]
    assert all(content.strip() for _, content in load_default_rules())


def test_prompt_treats_pr_rules_and_diff_as_data() -> None:
    prompt, truncated = build_review_prompt(
        title="Ajusta taxa",
        description="",
        diff_text=DIFF,
        rules=[("magic-numbers.md", "regra de teste")],
        max_diff_chars=10_000,
    )
    assert truncated is False
    assert "<regras>" in prompt and "regra de teste" in prompt
    assert "<diff>" in prompt and "tax = 0.25" in prompt
    assert "são dados" in prompt
    assert "(sem descrição)" in prompt


def test_prompt_marks_truncated_diff() -> None:
    _, truncated = build_review_prompt(
        title="t", description="d", diff_text="x" * 5000, rules=[], max_diff_chars=1000
    )
    assert truncated is True


def test_parse_accepts_plain_json() -> None:
    payload = {"findings": [{"severity": "IMPORTANT", "file": "app/calc.py", "line": 12, "comment": "Use constante."}]}

    findings = parse_findings(json.dumps(payload))

    assert findings[0].severity is Severity.IMPORTANT
    assert findings[0].line == 12


def test_parse_accepts_code_fence() -> None:
    fenced = "```json\n" + json.dumps({"findings": []}) + "\n```"
    assert parse_findings(fenced) == []


def test_parse_drops_invalid_items_and_keeps_valid_ones() -> None:
    payload = {
        "findings": [
            {"severity": "NOPE", "file": "a.py", "line": 1, "comment": "severidade inválida"},
            {"severity": "SUGGESTION", "file": "a.py", "line": None, "comment": "ok"},
        ]
    }
    findings = parse_findings(json.dumps(payload))
    assert [f.comment for f in findings] == ["ok"]


def test_parse_caps_the_number_of_findings() -> None:
    items = [{"severity": "QUESTION", "file": "a.py", "line": 1, "comment": f"c{i}"} for i in range(MAX_FINDINGS + 10)]
    assert len(parse_findings(json.dumps({"findings": items}))) == MAX_FINDINGS


@pytest.mark.parametrize("text", ["não é json", '{"outra": []}', "[1, 2]"])
def test_parse_rejects_responses_outside_the_format(text: str) -> None:
    with pytest.raises(AIResponseError):
        parse_findings(text)


def test_commentable_lines_include_added_and_context_lines_of_new_file() -> None:
    lines = commentable_lines(DIFF)

    # Linha 10 e 13 a 15: contexto; 11 e 12: adicionadas; a removida não conta.
    assert lines["app/calc.py"] == {10, 11, 12, 13, 14, 15}


def test_commentable_lines_ignore_files_deleted_in_the_diff() -> None:
    deleted = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n"
    assert commentable_lines(deleted) == {}


def test_split_sends_lines_in_the_diff_inline_and_the_rest_to_the_body() -> None:
    findings = parse_findings(
        json.dumps(
            {
                "findings": [
                    {"severity": "IMPORTANT", "file": "app/calc.py", "line": 12, "comment": "dentro"},
                    {"severity": "QUESTION", "file": "app/calc.py", "line": 99, "comment": "fora do diff"},
                    {"severity": "SUGGESTION", "file": "outro.py", "line": None, "comment": "geral"},
                ]
            }
        )
    )

    inline, general = split_findings(findings, commentable_lines(DIFF))

    assert len(inline) == 1
    assert inline[0]["path"] == "app/calc.py" and inline[0]["line"] == 12
    assert inline[0]["side"] == "RIGHT"
    assert "Importante" in inline[0]["body"]
    assert [f.comment for f in general] == ["fora do diff", "geral"]


def test_review_body_lists_general_findings_with_location() -> None:
    findings = parse_findings(
        json.dumps({"findings": [{"severity": "BLOCKER", "file": "a.py", "line": 3, "comment": "vaza token"}]})
    )
    body = review_body(findings, total=1)
    assert "1 apontamento" in body
    assert "`a.py`:3" in body and "vaza token" in body
