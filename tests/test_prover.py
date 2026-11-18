"""SEM-04: correctness-proof assistant (invariants, variants, counterexamples)."""

from __future__ import annotations

import json

import pytest

from sipl import ast as A
from sipl.diagnostics import SiplError
from sipl.parser import parse, parse_formula
from sipl.prover import formula as F
from sipl.prover.assistant import prove
from sipl.prover.solver import check, check_bounded, check_z3, valuations
from sipl.prover.spec import load_spec, spec_from_dict
from sipl.prover.vcgen import generate

from .conftest import EXAMPLES, GCD, POWER, read

POWER_SPEC = {
    "pre": "X = x ∧ Y = y ∧ y >= 0",
    "post": "R = pow(x, y)",
    "loop": [{"invariant": "R * pow(X, Y) = pow(x, y) ∧ Y >= 0 ∧ X = x", "variant": "Y"}],
}


def test_power_total_correctness_proved() -> None:
    report = prove(parse(POWER), spec_from_dict(POWER_SPEC))
    assert report.verdict == "proved"
    kinds = [r.vc.kind for r in report.vcs]
    assert kinds == ["init", "preserve", "exit", "bound", "decrease"]
    assert all(r.result.status == "proved" for r in report.vcs)
    assert report.testing.tried > 0 and report.testing.passed == report.testing.tried
    text = report.to_text(show_wp=True)
    assert "база індукції" in text and "крок індукції" in text
    assert "Висновок: ДОВЕДЕНО" in text
    assert "wp(" in text


def test_vc_formulas_are_the_textbook_conditions() -> None:
    vcs = generate(parse(POWER), spec_from_dict(POWER_SPEC)).vcs
    by_kind = {v.kind: v.text for v in vcs}
    assert by_kind["init"] == "X = x ∧ Y = y ∧ y >= 0 → 1 * pow(X, Y) = pow(x, y) ∧ Y >= 0 ∧ X = x"
    assert by_kind["preserve"].endswith("→ R * X * pow(X, Y - 1) = pow(x, y) ∧ Y - 1 >= 0 ∧ X = x")
    assert by_kind["exit"].endswith("∧ ¬Y > 0 → R = pow(x, y)")


def test_gcd_textbook_theorem() -> None:
    spec = load_spec(EXAMPLES / "gcd.spec.toml")
    assert prove(parse(GCD), spec).verdict == "proved"


def test_buggy_program_is_refuted_with_replay() -> None:
    report = prove(parse(read(EXAMPLES / "power_bug.sipl")), spec_from_dict(POWER_SPEC))
    assert report.verdict == "refuted"
    bad = [r for r in report.vcs if r.result.status == "counterexample"]
    assert bad and bad[0].vc.kind == "preserve"
    explanation = "\n".join(bad[0].explanation)
    assert "fs(st) =" in explanation and "інваріант не зберігається" in explanation
    assert report.testing.failures
    assert "КОНТРПРИКЛАД" in report.to_text()


@pytest.mark.parametrize(
    "name",
    ["power", "gcd", "division", "factorial", "progression", "parity"],
)
def test_examples_are_proved(name: str) -> None:
    report = prove(
        parse(read(EXAMPLES / f"{name}.sipl")), load_spec(EXAMPLES / f"{name}.spec.toml")
    )
    assert report.verdict == "proved", report.to_text()


def test_partial_mode_and_skipped_inputs() -> None:
    spec = spec_from_dict(
        {
            "pre": "M = m ∧ N = n",
            "post": "M = N",
            "mode": "partial",
            "loop": [{"invariant": "true"}],
        }
    )
    report = prove(parse(GCD), spec)
    assert report.spec.mode == "partial"
    assert [r.vc.kind for r in report.vcs] == ["init", "preserve", "exit"]
    assert report.verdict == "proved"
    assert (
        report.testing.skipped > 0
    )  # non-terminating inputs say nothing about partial correctness
    assert "часткову коректність" in report.to_text()


def test_variant_counterexamples() -> None:
    src = "begin while X > 0 do X := X + 1 end"
    spec = spec_from_dict(
        {"pre": "X = x", "post": "X <= 0", "loop": [{"invariant": "true", "variant": "X - 5"}]}
    )
    report = prove(parse(src), spec)
    statuses = {r.vc.kind: r for r in report.vcs}
    assert statuses["bound"].result.status == "counterexample"
    assert any("V(st)" in line for line in statuses["bound"].explanation)
    assert statuses["decrease"].result.status == "counterexample"
    assert any("не спадає" in line for line in statuses["decrease"].explanation)
    assert report.verdict == "refuted"
    assert report.testing.failures  # does not terminate within the limit


def test_init_and_exit_counterexamples() -> None:
    src = "begin R := 0; while X > 0 do X := X - 1 end"
    spec = spec_from_dict(
        {"pre": "X = x", "post": "R = 1", "loop": [{"invariant": "X >= 0", "variant": "X"}]}
    )
    report = prove(parse(src), spec)
    by_kind = {r.vc.kind: r for r in report.vcs}
    assert by_kind["init"].result.status == "counterexample"
    assert by_kind["exit"].result.status == "counterexample"
    assert any("I(st) = true, fb(st) = false" in line for line in by_kind["exit"].explanation)
    init_text = " ".join(by_kind["init"].explanation)
    assert "стан st" in init_text


def test_init_replay_shows_wrong_result() -> None:
    src = "begin R := X + 1 end"
    spec = spec_from_dict({"pre": "X = x", "post": "R = x"})
    report = prove(parse(src), spec)
    assert report.verdict == "refuted"
    assert any("післяумова в цьому стані хибна" in line for line in report.vcs[0].explanation)


def test_definedness_condition_for_div() -> None:
    src = "begin Q := 0; while X >= Y do begin X := X - Y; Q := Q + 1 end; R := X mod Y end"
    spec = spec_from_dict(
        {
            "pre": "X = x ∧ Y = y ∧ x >= 0 ∧ y > 0",
            "post": "R = x mod y",
            "loop": [{"invariant": "x = Q * y + X ∧ X >= 0 ∧ Y = y ∧ y > 0", "variant": "X"}],
        }
    )
    vcs = generate(parse(src), spec).vcs
    # wp(R := X mod Y, Q) = Y != 0 ∧ Q[...]: the divisor must be defined after the loop
    assert any("Y != 0" in v.text for v in vcs if v.kind == "exit")
    cond = "begin while 10 div X > 0 do X := X + 1 end"
    spec2 = spec_from_dict(
        {"pre": "X > 0", "post": "true", "loop": [{"invariant": "X > 0", "variant": "10 - X"}]}
    )
    kinds = [v.kind for v in generate(parse(cond), spec2).vcs]
    assert "defined" in kinds


def test_if_without_loops_and_nested_loops() -> None:
    spec = spec_from_dict({"pre": "true", "post": "M >= X ∧ M >= Y"})
    assert prove(parse("begin if X > Y then M := X else M := Y end"), spec).verdict == "proved"
    nested = parse(
        "begin I := 0; S := 0; while N > I do begin J := 0; "
        "while I > J do begin S := S + 1; J := J + 1 end; I := I + 1 end end"
    )
    spec = spec_from_dict(
        {
            "pre": "N = n ∧ n >= 0",
            "post": "2 * S = n * (n - 1)",
            "loop": [
                {"invariant": "2 * S = I * (I - 1) ∧ I >= 0 ∧ ¬ I > N ∧ N = n", "variant": "N - I"},
                {
                    "invariant": "2 * S = I * (I - 1) + 2 * J ∧ J >= 0 ∧ ¬ J > I ∧ N > I ∧ I >= 0 ∧ N = n",
                    "variant": "I - J",
                },
            ],
        }
    )
    report = prove(nested, spec)
    assert report.verdict == "proved", report.to_text()
    assert len(report.loops) == 2


def test_annotation_by_line() -> None:
    src = "begin\n  X := 0;\n  while X > 5 do X := X - 1\nend"
    spec = spec_from_dict(
        {
            "pre": "true",
            "post": "X = 0",
            "loop": [{"line": 3, "invariant": "X = 0", "variant": "X"}],
        }
    )
    assert prove(parse(src), spec).verdict == "proved"


def test_spec_errors() -> None:
    with pytest.raises(SiplError) as e1:
        prove(parse(POWER), spec_from_dict({"pre": "true", "post": "true"}))
    assert e1.value.diagnostics[0].code == "E401"
    with pytest.raises(SiplError) as e2:
        prove(
            parse(POWER),
            spec_from_dict(
                {"pre": "true", "post": "true", "mode": "total", "loop": [{"invariant": "true"}]}
            ),
        )
    assert e2.value.diagnostics[0].code == "E407"
    with pytest.raises(SiplError) as e3:
        prove(
            parse(POWER),
            spec_from_dict(
                {
                    "pre": "true",
                    "post": "true",
                    "loop": [{"invariant": "true"}, {"invariant": "true"}],
                }
            ),
        )
    assert e3.value.diagnostics[0].code == "E406"
    with pytest.raises(SiplError) as e4:
        spec_from_dict({"pre": "X = ", "post": "true"})
    assert e4.value.diagnostics[0].code == "E402"
    with pytest.raises(SiplError) as e5:
        spec_from_dict({"pre": "foo(X) = 1", "post": "true"})
    assert e5.value.diagnostics[0].code == "E403"
    with pytest.raises(SiplError) as e6:
        spec_from_dict({"pre": "true"})
    assert e6.value.diagnostics[0].code == "E404"
    for bad in [
        {"pre": "true", "post": "true", "mode": "weird"},
        {"pre": "true", "post": "true", "loop": [{"variant": "X"}]},
    ]:
        with pytest.raises(SiplError):
            spec_from_dict(bad)
    with pytest.raises(SiplError):
        spec_from_dict(
            {"pre": "true", "post": "true", "loop": [{"invariant": "true", "variant": "X +"}]}
        )
    with pytest.raises(SiplError):
        spec_from_dict(
            {"pre": "true", "post": "true", "loop": [{"invariant": "true", "variant": "pow(X)"}]}
        )


def test_load_spec_bad_toml(tmp_path) -> None:
    p = tmp_path / "bad.toml"
    p.write_text("pre = ", encoding="utf-8")
    with pytest.raises(SiplError) as exc:
        load_spec(p)
    assert exc.value.diagnostics[0].code == "E405"


def test_without_z3_bounded_only() -> None:
    ok = prove(parse(POWER), spec_from_dict(POWER_SPEC), use_z3=False)
    assert ok.verdict == "unknown"  # bounded search cannot prove, only fail to refute
    assert all(r.result.method == "перебір" for r in ok.vcs)
    bug = prove(parse(read(EXAMPLES / "power_bug.sipl")), spec_from_dict(POWER_SPEC), use_z3=False)
    assert bug.verdict == "refuted"
    assert "НЕ ВИРІШЕНО" in ok.to_text()


def test_json_report() -> None:
    data = prove(parse(POWER), spec_from_dict(POWER_SPEC)).to_dict()
    assert data["schema"] == "sipl.proof/1"
    assert data["verdict"] == "proved"
    assert data["conditions"][0]["kind"] == "init"
    assert data["loops"][0]["variant"] == "Y"
    json.dumps(data, ensure_ascii=False)


# --- formulas and solver ----------------------------------------------------


def test_formula_evaluation() -> None:
    env = {"X": 3, "n": 4}
    assert F.eval_b(parse_formula("pow(X, 2) = 9 ∧ fact(n) = 24 ∧ gcd(12, 18) = 6"), env)
    assert F.eval_b(parse_formula("abs(-2) = 2 ∧ min(1, 2) = 1 ∧ max(1, 2) = 2"), env)
    assert F.eval_b(parse_formula("X = 1 → false"), env)
    assert F.eval_b(parse_formula("7 div 2 = 3 ∧ 7 mod 2 = 1"), env)
    for bad in [
        "pow(2, -1) = 0",
        "fact(-1) = 1",
        "Z = 1",
        "1 div 0 = 1",
        "pow(2, 5000) = 1",
        "fact(5000) = 1",
    ]:
        with pytest.raises(F.Undefined):
            F.eval_b(parse_formula(bad), env)
    with pytest.raises(F.Undefined):
        F.eval_a(A.Call("nope", ()), {})
    with pytest.raises(F.Undefined):
        F.eval_a(A.Call("pow", (A.Num(1),)), {})
    assert F.check_functions(parse_formula("pow(1) = 1"))


def test_smart_constructors() -> None:
    x = parse_formula("X = 1")
    assert F.conj() == F.TRUE
    assert F.conj(F.TRUE, x) == x
    assert F.conj(x, F.FALSE) == F.FALSE
    assert F.implies(F.TRUE, x) == x
    assert F.implies(x, F.TRUE) == F.TRUE
    assert F.neg(F.TRUE) == F.FALSE
    assert F.neg(F.neg(x)) == x
    assert F.subst(parse_formula("¬X = 1 ∨ true"), "X", A.Num(2)) == parse_formula("¬2 = 1 ∨ true")
    assert F.subst_a(A.Call("pow", (A.Var("X"),)), "X", A.Num(3)) == A.Call("pow", (A.Num(3),))


def test_solver_paths() -> None:
    assert check_z3(parse_formula("X > 0 → X >= 1")).status == "proved"
    cex = check_z3(parse_formula("X > 0 → X > 1"))
    assert cex.status == "counterexample" and cex.counterexample == {"X": 1}
    assert check_bounded(parse_formula("X > 0 → X > 1")).counterexample == {"X": 1}
    assert check_bounded(parse_formula("X >= 0 ∨ X < 0")).status == "unknown"
    assert check(parse_formula("X > 0 → X > 1"), use_z3=False).status == "counterexample"
    assert (
        check_z3(parse_formula("X div Y = Q ∧ X mod Y = R ∧ Y > 0 → X = Q * Y + R")).status
        == "proved"
    )
    assert check_z3(parse_formula("abs(X) >= 0 ∧ min(X, Y) <= max(X, Y)")).status == "proved"
    assert check_z3(parse_formula("fact(3) = 6")).status == "proved"


def test_valuations_shrink_to_limit() -> None:
    vals = list(valuations(["a", "b", "c"], -10, 10, 1000))
    assert len(vals) <= 1000
    assert vals[0] == {"a": 0, "b": 0, "c": 0}
    assert list(valuations([], 0, 1, 10)) == [{}]


def test_weak_invariant_is_not_a_refutation() -> None:
    # the program is correct, only the invariant lacks "Y >= 0"
    src = "begin R := 0; while Y > 0 do begin R := R + X; Y := Y - 1 end end"
    spec = spec_from_dict(
        {
            "pre": "X = x ∧ Y = y ∧ y >= 0",
            "post": "R = x * y",
            "loop": [{"invariant": "R + X * Y = x * y", "variant": "Y"}],
        }
    )
    report = prove(parse(src), spec)
    assert report.verdict == "not_proved"
    assert not report.testing.failures
    bad = [r for r in report.vcs if r.result.status == "counterexample"]
    assert [r.vc.kind for r in bad] == ["exit"]
    assert "НЕ ДОВЕДЕНО" in report.to_text()
