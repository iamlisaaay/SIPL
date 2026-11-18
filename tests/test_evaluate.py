"""SEM-02: applying semantic terms to states, trace of applied formulas."""

from __future__ import annotations

import json

import pytest

from sipl.diagnostics import SiplError
from sipl.parser import parse
from sipl.semantics.build import sem_A, sem_B, sem_P
from sipl.semantics.evaluate import apply_term, value_of
from sipl.state import apply_basic, euclid_div, euclid_mod, format_state, overwrite, parse_state

from .conftest import DIVISION, GCD, POWER


def run(src: str, state: str, **kw):
    return apply_term(sem_P(parse(src)), parse_state(state), **kw)


def test_power_test_case() -> None:
    # st = [X ↦ 5, Y ↦ 2] gives R = 25
    r = run(POWER, "X=5, Y=2")
    assert r.status == "defined"
    assert r.state == {"X": 5, "Y": 0, "R": 25}
    assert r.iterations == 2


def test_power_trace_follows_formulas() -> None:
    r = run(POWER, "X=5, Y=2")
    rules = [s.rule for s in r.trace]
    assert rules[0] == "AF_SEQ"
    assert rules.count("AF_WH") == 3  # two iterations + exit
    assert rules.count("AF_AS") == 5
    texts = [s.text for s in r.trace]
    assert "AS^R(1)(st) = st∇[R ↦ 1(st)] = st∇[R ↦ 1] = [X ↦ 5, Y ↦ 2, R ↦ 1] = st1" in texts
    assert any("mult(5, 5)" in t and "R ↦ 25" in t for t in texts)
    assert any("gr(0, 0) = false" in t for t in texts)
    assert r.states["st"] == {"X": 5, "Y": 2}
    assert r.trace[1].origin is not None and r.trace[1].origin.line == 2
    out = r.explain()
    assert out.rstrip().endswith("Результат: [X ↦ 5, Y ↦ 0, R ↦ 25]")


def test_division_eval() -> None:
    r = run(DIVISION, "[X ↦ 7, Y ↦ 4]")
    assert r.state == {"X": 3, "Y": 4, "R": 1}


def test_gcd() -> None:
    r = run(GCD, "M=12, N=18")
    assert r.state == {"M": 6, "N": 6}
    assert any(s.rule == "AF_IF" and "другу" in s.text for s in r.trace)


def test_skip_is_identity() -> None:
    r = run("begin skip end", "X=1")
    assert r.state == {"X": 1}
    assert r.trace[0].rule == "AF_ID"


def test_undefined_variable() -> None:
    r = run("begin X := Z + 1 end", "")
    assert r.status == "undefined"
    assert "Z" in (r.reason or "")
    assert r.reason_origin is not None
    assert "невизначено" in r.summary()


def test_division_by_zero_is_undefined() -> None:
    r = run("begin X := 1 div Y end", "Y=0")
    assert r.status == "undefined"
    assert "ділення на нуль" in (r.reason or "")


def test_iteration_limit() -> None:
    r = run(GCD, "M=-5, N=3", max_iterations=50)
    assert r.status == "limit"
    assert r.iterations == 50
    assert "невідомо" in r.summary()


def test_trace_can_be_disabled_and_truncated() -> None:
    assert run(POWER, "X=2, Y=3", trace=False).trace == []
    r = run(POWER, "X=2, Y=50", max_trace=10)
    assert len(r.trace) == 10 and r.trace_truncated
    assert "обрізано" in r.explain()
    assert r.state is not None and r.state["R"] == 2**50


def test_json_result() -> None:
    data = run(POWER, "X=2, Y=1").to_dict()
    assert data["schema"] == "sipl.eval/1"
    assert data["status"] == "defined"
    assert data["result"] == {"X": 2, "Y": 0, "R": 2}
    assert data["trace"][0]["rule"] == "AF_SEQ"
    json.dumps(data, ensure_ascii=False)


def test_value_of() -> None:
    assert value_of(sem_A(parse("begin X := Y * 3 end").body.value), {"Y": 2}) == 6  # type: ignore[union-attr]
    assert (
        value_of(sem_B(parse("begin if Y > 3 then skip else skip end").body.cond), {"Y": 2})
        is False
    )  # type: ignore[union-attr]
    with pytest.raises(ValueError):
        value_of(sem_A(parse("begin X := Y end").body.value), {})  # type: ignore[union-attr]


def test_euclidean_division_matches_smt() -> None:
    assert (euclid_div(7, 2), euclid_mod(7, 2)) == (3, 1)
    assert (euclid_div(-7, 2), euclid_mod(-7, 2)) == (-4, 1)
    assert (euclid_div(7, -2), euclid_mod(7, -2)) == (-3, 1)
    assert (euclid_div(-7, -2), euclid_mod(-7, -2)) == (4, 1)
    for a in range(-9, 10):
        for b in [-3, -2, -1, 1, 2, 3]:
            q, r = euclid_div(a, b), euclid_mod(a, b)
            assert a == b * q + r and 0 <= r < abs(b)


def test_basic_functions() -> None:
    assert apply_basic("neg", [True]) is False
    assert apply_basic("lse", [2, 2]) is True
    assert apply_basic("ls", [2, 2]) is False
    assert apply_basic("neq", [1, 2]) is True
    assert apply_basic("and", [True, False]) is False


def test_state_helpers() -> None:
    assert parse_state("") == {}
    assert parse_state("[X ↦ 5; Y -> -2]") == {"X": 5, "Y": -2}
    with pytest.raises(SiplError):
        parse_state("X == 1")
    st = overwrite({"X": 1, "Y": 2}, "X", 9)
    assert list(st) == ["X", "Y"] and st["X"] == 9
    assert format_state(st) == "[X ↦ 9, Y ↦ 2]"
    assert format_state(st, ascii_only=True) == "[X -> 9, Y -> 2]"
