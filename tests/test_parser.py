"""CORE-02: typed AST with source spans and syntax diagnostics."""

from __future__ import annotations

import json

import pytest

from sipl import ast as A
from sipl.diagnostics import Diagnostic, SiplError, SiplSyntaxError, caret_excerpt
from sipl.parser import check_dialect, parse, parse_expr, parse_formula, parse_full
from sipl.span import SourceSpan, position_of, span_from_offsets

from .conftest import DATA, GCD, POWER, read


def test_power_ast_structure() -> None:
    p = parse(POWER)
    assert isinstance(p, A.Program)
    body = p.body
    assert isinstance(body, A.Seq) and len(body.items) == 2
    init, loop = body.items
    assert init == A.Assign(A.Var("R"), A.Num(1))
    assert isinstance(loop, A.While)
    assert loop.cond == A.Compare(">", A.Var("Y"), A.Num(0))
    assert isinstance(loop.body, A.Block)
    inner = loop.body.body
    assert inner == A.Seq(
        (
            A.Assign(A.Var("R"), A.BinOp("*", A.Var("R"), A.Var("X"))),
            A.Assign(A.Var("Y"), A.BinOp("-", A.Var("Y"), A.Num(1))),
        )
    )


def test_ast_nodes_are_own_classes_not_lark() -> None:
    p = parse(POWER)
    for node in A.walk(p):
        assert type(node).__module__ == "sipl.ast"


def test_spans_point_into_source() -> None:
    p = parse(POWER)
    loop = p.body.items[1]  # type: ignore[union-attr]
    assert loop.span.line == 3 and loop.span.column == 2
    assert loop.span.text(POWER).startswith("while Y > 0 do")
    assert loop.span.text(POWER).endswith("end")
    assign = loop.body.body.items[0]
    assert assign.span.text(POWER) == "R := R * X"
    assert assign.target.span.text(POWER) == "R"
    assert assign.value.span.text(POWER) == "R * X"
    for node in A.walk(p):
        assert node.span is not None


def test_precedence_and_associativity() -> None:
    e = parse_expr("1 - 2 - 3 * 4")
    assert e == A.BinOp("-", A.BinOp("-", A.Num(1), A.Num(2)), A.BinOp("*", A.Num(3), A.Num(4)))
    b = parse_formula("¬X = 1 ∨ Y > 2 ∧ Z = 3")
    assert b == A.BoolOp(
        "or",
        A.Not(A.Compare("=", A.Var("X"), A.Num(1))),
        A.BoolOp("and", A.Compare(">", A.Var("Y"), A.Num(2)), A.Compare("=", A.Var("Z"), A.Num(3))),
    )


def test_while_binds_tighter_than_semicolon() -> None:
    p = parse("begin while X > 0 do X := X - 1; Y := 1 end")
    assert isinstance(p.body, A.Seq)
    assert isinstance(p.body.items[0], A.While)
    assert isinstance(p.body.items[1], A.Assign)


def test_negative_numbers_and_parens() -> None:
    p = parse("begin X := (Y) - -1 end")
    assert p.body == A.Assign(A.Var("X"), A.BinOp("-", A.Var("Y"), A.Num(-1)))


def test_paren_condition_vs_paren_expression() -> None:
    b1 = parse_formula("(X + 1) > 2")
    b2 = parse_formula("(X > 2)")
    assert isinstance(b1, A.Compare) and isinstance(b2, A.Compare)


@pytest.mark.parametrize("path", sorted((DATA / "valid").glob("*.sipl")), ids=lambda p: p.stem)
def test_unparse_round_trip(path) -> None:
    p = parse(read(path))
    assert parse(A.unparse(p)) == p
    assert parse(A.format_program(p)) == p


def test_unparse_brackets() -> None:
    assert A.unparse(parse_expr("(1 - 2) - (3 - 4)")) == "1 - 2 - (3 - 4)"
    assert A.unparse(parse_expr("(1 + 2) * 3")) == "(1 + 2) * 3"
    assert A.unparse(parse_formula("¬(X = 1 ∨ Y = 2)")) == "¬(X = 1 ∨ Y = 2)"
    assert A.unparse(parse_formula("(A = 1 → B = 1) → C = 1")) == "(A = 1 → B = 1) → C = 1"
    assert A.unparse(parse_formula("A = 1 ∧ (B = 1 ∨ C = 1)")) == "A = 1 ∧ (B = 1 ∨ C = 1)"
    seq_in_if = A.If(A.BoolConst(True), A.Seq((A.Skip(), A.Skip())), A.Skip())
    assert A.unparse(seq_in_if) == "if true then begin skip; skip end else skip"
    assert A.unparse(A.Call("pow", (A.Var("x"), A.Num(2)))) == "pow(x, 2)"
    with pytest.raises(TypeError):
        A.unparse(A.Node())


def test_format_program_layout() -> None:
    text = A.format_program(
        parse(
            "begin if X > 0 then begin X := 1; Y := 2 end else skip; while X > 0 do X := X - 1 end"
        )
    )
    assert text.splitlines()[0] == "begin"
    assert "  if X > 0 then" in text
    assert "    X := 1;" in text


def test_helpers() -> None:
    p = parse(POWER)
    assert A.variables(p) == ["R", "Y", "X"]
    assert A.assigned_variables(p) == ["R", "Y"]
    assert len(A.loops(p)) == 1
    assert A.input_variables(p) == ["Y", "X"]
    branchy = parse("begin if C > 0 then A := 1 else B := 1; X := A + B; while X > 0 do X := Z end")
    assert A.input_variables(branchy) == ["C", "A", "B", "Z"]


def test_ast_json_is_serialisable() -> None:
    data = parse(GCD).to_dict()
    text = json.dumps(data, ensure_ascii=False)
    assert '"node": "While"' in text
    assert data["category"] == "Prog"
    assert data["span"]["line"] == 1


def test_core_dialect_rejects_extensions_with_span() -> None:
    src = "begin X := 7 div 2 end"
    with pytest.raises(SiplSyntaxError) as exc:
        parse(src, dialect="core")
    d = exc.value.diagnostics[0]
    assert d.code == "E201"
    assert d.span is not None and d.span.text(src) == "7 div 2"


def test_spec_only_constructs_rejected_in_programs() -> None:
    with pytest.raises(SiplSyntaxError) as exc:
        parse("begin X := pow(2, 3) end")
    assert exc.value.diagnostics[0].code == "E202"
    prog = A.Program(A.Skip())
    assert check_dialect(prog, "core") == []
    weird = A.Program(
        A.If(A.BoolOp("->", A.BoolConst(True), A.BoolConst(True)), A.Skip(), A.Skip())
    )
    assert [d.code for d in check_dialect(weird, "ext")] == ["E202"]


def test_parse_full_returns_concrete_tree() -> None:
    res = parse_full(POWER)
    assert res.tree.data == "program"
    assert res.source == POWER


def test_formula_errors() -> None:
    with pytest.raises(SiplSyntaxError):
        parse_formula("X = ")
    with pytest.raises(SiplSyntaxError):
        parse_expr("1 +")


def test_diagnostic_formatting() -> None:
    src = "begin\n  X = 1\nend\n"
    with pytest.raises(SiplSyntaxError) as exc:
        parse(src)
    d = exc.value.diagnostics[0]
    text = d.format("prog.sipl", src)
    assert text.startswith("prog.sipl:2:5: error E002")
    assert "підказка" in text
    assert "    ^" in text
    assert d.to_dict()["span"]["column"] == 5
    assert str(exc.value)
    assert str(SiplError()) == "SIPL error"
    assert Diagnostic("X", "m").format() == "<input>: error X: m"


def test_span_helpers() -> None:
    src = "ab\ncd"
    assert position_of(src, 0) == (1, 1)
    assert position_of(src, 3) == (2, 1)
    s1 = span_from_offsets(src, 0, 2)
    s2 = span_from_offsets(src, 3, 5)
    merged = s1.merge(s2)
    assert (merged.start, merged.end, merged.end_line) == (0, 5, 2)
    assert s2.merge(s1) == merged
    assert SourceSpan.from_dict(merged.to_dict()) == merged
    assert str(s1) == "1:1-1:3"
    assert caret_excerpt(src, s2).endswith("^^")
