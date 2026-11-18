"""Proof assistant for partial/total correctness of loop programs (SEM-04).

Pipeline::

    program + spec ──► semantic term (sem_P)
                   ├─► verification conditions (vcgen, wp)  ──► Z3 / bounded search
                   │        └─ counterexamples are *replayed* on the semantic term
                   └─► bounded testing of the whole program on states satisfying pre

The assistant never claims more than it checked: a condition Z3 could not decide is
reported as ``unknown`` together with the size of the bounded search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sipl import ast as A
from sipl.prover.formula import Undefined, eval_a, eval_b, free_vars
from sipl.prover.solver import CheckResult, check, valuations, z3_available
from sipl.prover.spec import Spec
from sipl.prover.vcgen import VC, VCResult, generate
from sipl.semantics.build import sem_P, sem_S
from sipl.semantics.evaluate import apply_term
from sipl.semantics.terms import WhileT, render
from sipl.state import State, format_state

Verdict = Literal["proved", "refuted", "not_proved", "unknown"]

_KIND_ORDER = {"init": 0, "defined": 1, "preserve": 2, "exit": 3, "bound": 4, "decrease": 5}


@dataclass
class VCReport:
    vc: VC
    result: CheckResult
    explanation: list[str] = field(default_factory=list)
    #: the replay showed that the *program* (not just the annotation) is wrong
    refutes_program: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.vc.kind,
            "loop": self.vc.loop,
            "title": self.vc.title,
            "formula": self.vc.text,
            "status": self.result.status,
            "method": self.result.method,
            "counterexample": self.result.counterexample,
            "note": self.result.note,
            "tried": self.result.tried,
            "explanation": self.explanation,
        }


@dataclass
class TestFailure:
    initial: State
    reason: str
    result: State | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"initial": self.initial, "result": self.result, "reason": self.reason}


@dataclass
class TestReport:
    tried: int = 0
    passed: int = 0
    skipped: int = 0
    failures: list[TestFailure] = field(default_factory=list)
    lo: int = 0
    hi: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "range": [self.lo, self.hi],
            "tried": self.tried,
            "passed": self.passed,
            "skipped": self.skipped,
            "failures": [f.to_dict() for f in self.failures],
        }


@dataclass
class ProofReport:
    program: A.Program
    spec: Spec
    term: str
    loops: list[dict[str, Any]]
    vcs: list[VCReport]
    testing: TestReport
    wp_steps: list[dict[str, str]]
    z3: bool

    @property
    def verdict(self) -> Verdict:
        if self.testing.failures or any(r.refutes_program for r in self.vcs):
            return "refuted"  # a concrete run violates the specification
        if any(r.result.status == "counterexample" for r in self.vcs):
            return "not_proved"  # a verification condition is false: weak invariant/variant or bug
        if all(r.result.status == "proved" for r in self.vcs):
            return "proved"
        return "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "sipl.proof/1",
            "mode": self.spec.mode,
            "verdict": self.verdict,
            "pre": A.unparse_bexp(self.spec.pre),
            "post": A.unparse_bexp(self.spec.post),
            "term": self.term,
            "loops": self.loops,
            "conditions": [r.to_dict() for r in self.vcs],
            "testing": self.testing.to_dict(),
            "wp_steps": self.wp_steps,
            "solver": "z3" if self.z3 else "bounded",
        }

    def to_text(self, *, show_wp: bool = False) -> str:
        mode = "повна" if self.spec.mode == "total" else "часткова"
        pre, post = A.unparse_bexp(self.spec.pre), A.unparse_bexp(self.spec.post)
        L: list[str] = []
        L.append(f"Твердження ({mode} коректність):")
        if self.spec.mode == "total":
            L.append(f"  для кожного стану st, де {pre}, значення sem_P(P)(st) визначене")
            L.append(f"  і в результуючому стані виконується {post}.")
        else:
            L.append(f"  для кожного стану st, де {pre}: якщо sem_P(P)(st)↓ = str,")
            L.append(f"  то в стані str виконується {post}.")
        L.append("")
        L.append(f"Семантичний терм: {self.term}")
        for lp in self.loops:
            L.append("")
            L.append(f"Цикл {lp['index']} (рядок {lp['line']}): WH(fb, fs)")
            L.append(f"  fb = {lp['cond_term']}")
            L.append(f"  fs = {lp['body_term']}")
            L.append(f"  інваріант I: {lp['invariant']}")
            if lp["variant"]:
                L.append(f"  варіант V:   {lp['variant']}")
        L.append("")
        L.append("Умови перевірки:")
        marks = {"proved": "✓", "counterexample": "✗", "unknown": "?"}
        for i, r in enumerate(self.vcs, start=1):
            L.append(f" [{marks[r.result.status]}] VC{i}. {r.vc.title}")
            L.append(f"      {r.vc.text}")
            if r.result.status == "proved":
                L.append("      доведено (Z3, для всіх цілих значень)")
            elif r.result.status == "counterexample":
                cex = ", ".join(f"{k} = {v}" for k, v in (r.result.counterexample or {}).items())
                L.append(f"      КОНТРПРИКЛАД ({r.result.method}): {cex}")
            else:
                L.append(f"      не вирішено: {r.result.note}")
            for line in r.explanation:
                L.append(f"      {line}")
        if show_wp and self.wp_steps:
            L.append("")
            L.append("Обчислення найслабших передумов (wp):")
            for s in self.wp_steps:
                L.append(f"  wp({s['stm']}, {s['post']})")
                L.append(f"    = {s['result']}    [{s['rule']}]")
        t = self.testing
        L.append("")
        L.append(
            f"Тестування (аплікація терму) на станах з передумовою, значення у [{t.lo}, {t.hi}]: "
            f"{t.passed} з {t.tried} пройшли" + (f", {t.skipped} пропущено" if t.skipped else "")
        )
        for f in t.failures:
            res = format_state(f.result) if f.result is not None else "–"
            L.append(f"  ✗ st = {format_state(f.initial)} → {res}: {f.reason}")
        L.append("")
        verdict = {
            "proved": "ДОВЕДЕНО: усі умови перевірки істинні.",
            "refuted": "СПРОСТОВАНО: програма порушує специфікацію на конкретному вході (див. вище).",
            "not_proved": "НЕ ДОВЕДЕНО: умова перевірки хибна. Інваріант або варіант не підходить "
            "(занадто слабкий чи хибний), або в програмі помилка; тестування помилок програми "
            "не виявило.",
            "unknown": "НЕ ВИРІШЕНО: частину умов не вдалося ні довести, ні спростувати.",
        }[self.verdict]
        L.append(f"Висновок: {verdict}")
        if self.verdict == "proved" and self.spec.mode == "partial":
            L.append(
                "  (доведено часткову коректність; завершуваність не перевірялась – додайте variant)"
            )
        return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------


def prove(program: A.Program, spec: Spec, *, use_z3: bool = True) -> ProofReport:
    vcres: VCResult = generate(program, spec)
    program_vars = set(A.variables(program))
    term = sem_P(program)

    loops_info = []
    for i, (w, ann) in enumerate(vcres.loops, start=1):
        wt = sem_S(w)
        assert isinstance(wt, WhileT)
        loops_info.append(
            {
                "index": i,
                "line": w.span.line if w.span else None,
                "cond_term": render(wt.cond),
                "body_term": render(wt.body),
                "invariant": A.unparse_bexp(ann.invariant),
                "variant": A.unparse_aexp(ann.variant) if ann.variant else None,
            }
        )

    reports: list[VCReport] = []
    for vc in sorted(vcres.vcs, key=lambda v: (v.loop or 0, _KIND_ORDER[v.kind])):
        res = check(vc.formula, use_z3=use_z3, lo=min(spec.test_min, -3), hi=max(spec.test_max, 6))
        rep = VCReport(vc, res)
        if res.status == "counterexample" and res.counterexample is not None:
            rep.explanation, rep.refutes_program = _replay(
                vc, res.counterexample, program, spec, program_vars, vcres
            )
        reports.append(rep)

    testing = _test(program, spec, program_vars)
    wp_steps = [
        {"rule": s.rule, "stm": s.stm, "post": s.post, "result": s.result} for s in vcres.wp_steps
    ]
    return ProofReport(
        program,
        spec,
        render(term),
        loops_info,
        reports,
        testing,
        wp_steps,
        use_z3 and z3_available(),
    )


def _split(cex: dict[str, int], program_vars: set[str]) -> tuple[State, dict[str, int]]:
    st = {k: v for k, v in cex.items() if k in program_vars}
    return st, cex


def _replay(
    vc: VC,
    cex: dict[str, int],
    program: A.Program,
    spec: Spec,
    program_vars: set[str],
    vcres: VCResult,
) -> tuple[list[str], bool]:
    """Explain a counterexample by applying the semantic term to the concrete state."""
    st, env = _split(cex, program_vars)
    lines = [f"стан st = {format_state(st)}" + _logical(env, program_vars)]
    if vc.kind == "init":
        if _holds(spec.pre, env):
            run = apply_term(sem_P(program), st, max_iterations=5000, trace=False)
            if run.defined and run.state is not None:
                after = {**env, **run.state}
                lines.append(f"передумова істинна; sem_P(P)(st) = {format_state(run.state)}")
                if not _holds(spec.post, after):
                    lines.append("а післяумова в цьому стані хибна – програма неправильна")
                    return lines, True
                else:
                    lines.append(
                        "післяумова тут істинна: ймовірно, слабкий інваріант (не випливає з передумови)"
                    )
            else:
                lines.append(f"sem_P(P)(st): {run.summary().removeprefix('Результат: ')}")
        return lines, False
    assert vc.loop is not None
    w, ann = vcres.loops[vc.loop - 1]
    body = sem_S(w.body)
    if vc.kind in ("preserve", "decrease"):
        run = apply_term(body, st, max_iterations=5000, trace=False)
        if not run.defined or run.state is None:
            lines.append(f"fs(st): {run.summary().removeprefix('Результат: ')}")
            return lines, False
        after = {**env, **run.state}
        lines.append(f"I(st) = true, fb(st) = true; fs(st) = {format_state(run.state)}")
        if vc.kind == "preserve":
            lines.append(f"I(fs(st)) = {_truth(ann.invariant, after)} – інваріант не зберігається")
        elif ann.variant is not None:
            before_v, after_v = _val(ann.variant, env), _val(ann.variant, after)
            lines.append(f"V(st) = {before_v}, V(fs(st)) = {after_v} – варіант не спадає")
    elif vc.kind == "exit":
        lines.append("I(st) = true, fb(st) = false, але потрібна далі умова хибна")
    elif vc.kind == "bound" and ann.variant is not None:
        lines.append(f"I(st) = true, fb(st) = true, але V(st) = {_val(ann.variant, env)} < 0")
    return lines, False


def _logical(env: dict[str, int], program_vars: set[str]) -> str:
    logical = {k: v for k, v in env.items() if k not in program_vars}
    if not logical:
        return ""
    return "; логічні змінні: " + ", ".join(f"{k} = {v}" for k, v in logical.items())


def _holds(f: A.Bexp, env: dict[str, int]) -> bool:
    try:
        return eval_b(f, env)
    except Undefined:
        return False


def _truth(f: A.Bexp, env: dict[str, int]) -> str:
    try:
        return "true" if eval_b(f, env) else "false"
    except Undefined as exc:
        return f"невизначено ({exc})"


def _val(e: A.Aexp, env: dict[str, int]) -> str:
    try:
        return str(eval_a(e, env))
    except Undefined as exc:
        return f"невизначено ({exc})"


def _test(program: A.Program, spec: Spec, program_vars: set[str]) -> TestReport:
    rep = TestReport(lo=spec.test_min, hi=spec.test_max)
    term = sem_P(program)
    names = free_vars(spec.pre)
    names += [v for v in A.input_variables(program) if v not in names]
    for env in valuations(names, spec.test_min, spec.test_max, 4000):
        try:
            if not eval_b(spec.pre, env):
                continue
        except Undefined:
            continue
        rep.tried += 1
        st = {k: v for k, v in env.items() if k in program_vars}
        run = apply_term(term, st, max_iterations=2000, trace=False)
        if run.status == "defined" and run.state is not None:
            after = {**env, **run.state}
            try:
                ok = eval_b(spec.post, after)
            except Undefined as exc:
                ok = False
                reason = f"післяумова невизначена: {exc}"
            else:
                reason = "післяумова хибна"
            if ok:
                rep.passed += 1
            elif len(rep.failures) < 5:
                rep.failures.append(TestFailure(st, reason, run.state))
            continue
        if spec.mode == "partial":
            rep.skipped += 1  # partial correctness says nothing about such inputs
            continue
        if len(rep.failures) < 5:
            rep.failures.append(TestFailure(st, run.reason or "невизначено"))
    return rep
