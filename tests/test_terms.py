"""SEM-01: semantic terms, golden tests."""

from __future__ import annotations

import json

import pytest

from sipl import ast as A
from sipl.parser import parse
from sipl.semantics.build import RULE_SCHEMATA, expand, explain, sem_A, sem_B, sem_P, sem_S
from sipl.semantics.terms import (
    AssignT,
    Const,
    IdT,
    ParenT,
    SeqT,
    WhileT,
    render,
    strip,
    to_dict,
)

from .conftest import DATA, DIVISION, GCD, GOLDEN, POWER, read


def test_power_term() -> None:
    assert render(sem_P(parse(POWER))) == (
        "AS^R(1) · WH(S2(gr, Y⇒, 0), AS^R(S2(mult, R⇒, X⇒)) · AS^Y(S2(sub, Y⇒, 1)))"
    )


def test_gcd_term() -> None:
    assert render(sem_P(parse(GCD))) == (
        "WH(S1(neg, S2(eq, M⇒, N⇒)), IF(S2(gr, M⇒, N⇒), AS^M(S2(sub, M⇒, N⇒)), "
        "AS^N(S2(sub, N⇒, M⇒))))"
    )


def test_division_term() -> None:
    # uses the extension >= (gre)
    assert render(sem_P(parse(DIVISION))) == (
        "AS^R(0) · WH(S2(gre, X⇒, Y⇒), AS^X(S2(sub, X⇒, Y⇒)) · AS^R(S2(add, R⇒, 1)))"
    )


GOLDEN_CASES = sorted(GOLDEN.glob("*.term"))


@pytest.mark.parametrize("golden", GOLDEN_CASES, ids=lambda p: p.stem)
def test_golden_terms(golden) -> None:
    src = DATA / "valid" / f"{golden.stem}.sipl"
    if not src.exists():
        src = DATA / "ext" / f"{golden.stem}.sipl"
    assert render(sem_P(parse(read(src)))) == read(golden).strip()


def test_all_basic_operators_supported() -> None:
    src = (
        "begin X := 1 + 2 - 3 * 4 div 5 mod 6; "
        "if X = 1 ∨ X > 2 ∧ ¬ X >= 3 ∨ X < 4 ∨ X <= 5 ∨ X != 6 ∨ true ∨ false "
        "then begin skip end else while false do skip end"
    )
    text = render(sem_P(parse(src)))
    for fn in [
        "add",
        "sub",
        "mult",
        "div",
        "mod",
        "eq",
        "gr",
        "gre",
        "ls",
        "lse",
        "neq",
        "or",
        "and",
        "neg",
    ]:
        assert f"({fn}," in text, fn
    assert "IF(" in text and "WH(false, id)" in text


def test_term_keeps_origin_spans() -> None:
    term = sem_P(parse(POWER))
    assert isinstance(term, SeqT)
    loop = term.items[1]
    assert isinstance(loop, WhileT)
    assert loop.origin is not None and loop.origin.line == 3
    for t in term.walk():
        assert t.origin is not None


def test_component_builders() -> None:
    assert render(sem_A(A.BinOp("+", A.Var("X"), A.Num(1)))) == "S2(add, X⇒, 1)"
    assert render(sem_B(A.Not(A.Compare("=", A.Var("X"), A.Num(1))))) == "S1(neg, S2(eq, X⇒, 1))"
    assert sem_S(A.Skip()) == IdT()
    assert sem_S(A.Assign(A.Var("X"), A.Num(2))) == AssignT("X", Const(2))
    with pytest.raises(ValueError):
        expand("A", A.Call("pow", (A.Num(2), A.Num(3))))


def test_block_brackets_only_inside_composition() -> None:
    t = sem_P(parse("begin A := 1; begin B := 2; C := 3 end end"))
    assert render(t) == "AS^A(1) · (AS^B(2) · AS^C(3))"
    assert isinstance(strip(ParenT(ParenT(IdT()))), IdT)


def test_render_styles() -> None:
    t = sem_P(parse(POWER))
    assert render(t, "ascii").startswith("AS^R(1) . WH(S2(gr, Y=>, 0)")
    latex = render(t, "latex")
    assert r"AS^{R}(\bar{1}) \cdot WH(" in latex
    assert r"S^{2}(\mathit{gr}, Y\Rightarrow, \bar{0})" in latex


def test_explanation_chain() -> None:
    exp = explain(parse(POWER))
    assert exp.start.startswith("sem_P(begin R := 1;")
    rules = [s.rule for s in exp.steps]
    assert rules[:5] == ["NS_Prog", "NS_Stm_Seq", "NS_Stm_As", "NS_A_Num", "NS_Stm_Wh"]
    assert exp.steps[2].lhs == "sem_S(R := 1)" and exp.steps[2].rhs == "AS^R(sem_A(1))"
    assert exp.steps[-1].whole == render(sem_P(parse(POWER)))
    assert all(r in RULE_SCHEMATA for r in rules)
    assert "[NS_Stm_BE]" in exp.chain()
    assert exp.local().strip().endswith(render(exp.term))
    assert json.dumps(exp.to_dict(), ensure_ascii=False)


def test_explain_ends_with_same_term_on_corpus() -> None:
    for path in sorted((DATA / "valid").glob("*.sipl")):
        program = parse(read(path))
        assert explain(program).term == sem_P(program)


def test_term_json() -> None:
    data = to_dict(sem_P(parse(GCD)))
    assert data["kind"] == "while"
    assert data["cond"]["fn"] == "neg"
    assert data["body"]["kind"] == "if"
    assert data["origin"]["line"] == 1
    hole_data = to_dict(explain(parse("begin skip end")).term)
    assert hole_data["kind"] == "id"
    paren = to_dict(sem_P(parse("begin begin skip end end")))
    assert paren["kind"] == "paren"
    seq = to_dict(sem_P(parse("begin X := 1; Y := X end")))
    assert seq["kind"] == "seq" and seq["items"][1]["value"]["kind"] == "denaming"
