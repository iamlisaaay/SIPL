"""Checking verification conditions: Z3 (SMT, integer arithmetic) + bounded search.

* ``proved``          – Z3 showed the negation unsatisfiable (valid for *all* integers)
* ``counterexample``  – a concrete valuation falsifies the condition (confirmed by
                        evaluating the formula with the real functions)
* ``unknown``         – neither; usually non-linear arithmetic. The bounded search then
                        reports how many valuations were tried without a counterexample.

Spec functions (pow, fact, gcd, ...) are uninterpreted functions in Z3 constrained by
their recursive definitions, which is enough for typical loop invariants.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from sipl import ast as A
from sipl.prover.formula import Undefined, eval_b, free_vars

Status = Literal["proved", "counterexample", "unknown"]


@dataclass
class CheckResult:
    status: Status
    counterexample: dict[str, int] | None = None
    method: str = ""
    note: str = ""
    tried: int = 0
    details: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Z3
# ---------------------------------------------------------------------------


def z3_available() -> bool:
    try:
        import z3  # noqa: F401
    except ImportError:  # pragma: no cover - z3-solver is a declared dependency
        return False
    return True


class _Z3:
    def __init__(self) -> None:
        import z3

        self.z3 = z3
        self.vars: dict[str, Any] = {}
        self.funcs: dict[str, Any] = {}
        self.axioms: list[Any] = []

    def var(self, name: str) -> Any:
        if name not in self.vars:
            self.vars[name] = self.z3.Int(name)
        return self.vars[name]

    def func(self, name: str) -> Any:
        z3 = self.z3
        if name in self.funcs:
            return self.funcs[name]
        Int = z3.IntSort()
        if name == "pow":
            f = z3.Function("pow", Int, Int, Int)
            x, n = z3.Ints("x__ n__")
            self.axioms += [
                z3.ForAll([x], f(x, 0) == 1),
                z3.ForAll(
                    [x, n], z3.Implies(n > 0, f(x, n) == x * f(x, n - 1)), patterns=[f(x, n)]
                ),
            ]
        elif name == "fact":
            f = z3.Function("fact", Int, Int)
            n = z3.Int("n__")
            self.axioms += [
                f(0) == 1,
                z3.ForAll([n], z3.Implies(n > 0, f(n) == n * f(n - 1)), patterns=[f(n)]),
            ]
        elif name == "gcd":
            f = z3.Function("gcd", Int, Int, Int)
            m, n = z3.Ints("m__ n__")
            self.axioms += [
                z3.ForAll([m], z3.Implies(m > 0, f(m, m) == m), patterns=[f(m, m)]),
                z3.ForAll(
                    [m, n],
                    z3.Implies(z3.And(m > n, n > 0), f(m, n) == f(m - n, n)),
                    patterns=[f(m, n)],
                ),
                z3.ForAll(
                    [m, n],
                    z3.Implies(z3.And(n > m, m > 0), f(m, n) == f(m, n - m)),
                    patterns=[f(m, n)],
                ),
            ]
        elif name == "abs":
            f = lambda a: z3.If(a >= 0, a, -a)  # noqa: E731
        elif name == "min":
            f = lambda a, b: z3.If(a <= b, a, b)  # noqa: E731
        elif name == "max":
            f = lambda a, b: z3.If(a >= b, a, b)  # noqa: E731
        else:  # pragma: no cover - rejected by spec validation
            raise ValueError(name)
        self.funcs[name] = f
        return f

    def a(self, e: A.Aexp) -> Any:
        if isinstance(e, A.Num):
            return self.z3.IntVal(e.value)
        if isinstance(e, A.Var):
            return self.var(e.name)
        if isinstance(e, A.Call):
            return self.func(e.name)(*(self.a(x) for x in e.args))
        left, right = self.a(e.left), self.a(e.right)
        if e.op == "+":
            return left + right
        if e.op == "-":
            return left - right
        if e.op == "*":
            return left * right
        if e.op == "div":
            return left / right  # SMT-LIB div: Euclidean, same as SIPL
        return left % right

    def b(self, f: A.Bexp) -> Any:
        z3 = self.z3
        if isinstance(f, A.BoolConst):
            return z3.BoolVal(f.value)
        if isinstance(f, A.Compare):
            left, right = self.a(f.left), self.a(f.right)
            return {
                "=": lambda: left == right,
                ">": lambda: left > right,
                ">=": lambda: left >= right,
                "<": lambda: left < right,
                "<=": lambda: left <= right,
                "!=": lambda: left != right,
            }[f.op]()
        if isinstance(f, A.Not):
            return z3.Not(self.b(f.operand))
        left, right = self.b(f.left), self.b(f.right)
        if f.op == "and":
            return z3.And(left, right)
        if f.op == "or":
            return z3.Or(left, right)
        return z3.Implies(left, right)


def check_z3(formula: A.Bexp, timeout_ms: int = 4000) -> CheckResult:
    enc = _Z3()
    z3 = enc.z3
    goal = enc.b(formula)
    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.add(*enc.axioms)
    solver.add(z3.Not(goal))
    answer = solver.check()
    if answer == z3.unsat:
        return CheckResult("proved", method="z3")
    if answer == z3.sat:
        model = solver.model()
        cex = {}
        for name in free_vars(formula):
            val = model.eval(enc.var(name), model_completion=True)
            cex[name] = val.as_long()
        # Z3 only knows the axioms; confirm with the real functions before reporting
        try:
            if not eval_b(formula, cex):
                return CheckResult("counterexample", cex, method="z3")
        except Undefined:
            pass
        return CheckResult(
            "unknown", None, method="z3", note="модель Z3 не підтверджена обчисленням"
        )
    return CheckResult("unknown", method="z3", note=f"Z3: {solver.reason_unknown()}")


# ---------------------------------------------------------------------------
# bounded exhaustive search
# ---------------------------------------------------------------------------


def valuations(names: list[str], lo: int, hi: int, limit: int) -> Iterator[dict[str, int]]:
    """All valuations of ``names`` in [lo, hi], shrinking the box to stay under ``limit``."""
    if not names:
        yield {}
        return
    while (hi - lo + 1) ** len(names) > limit and hi > lo:
        if hi - 1 >= abs(lo):
            hi -= 1
        else:
            lo += 1
    values = range(lo, hi + 1)
    # small absolute values first – counterexamples are easier to read
    ordered = sorted(values, key=lambda v: (abs(v), v < 0))
    for combo in itertools.product(ordered, repeat=len(names)):
        yield dict(zip(names, combo, strict=True))


def check_bounded(formula: A.Bexp, lo: int = -3, hi: int = 6, limit: int = 60_000) -> CheckResult:
    names = free_vars(formula)
    tried = 0
    for env in valuations(names, lo, hi, limit):
        try:
            ok = eval_b(formula, env)
        except Undefined:
            continue
        tried += 1
        if not ok:
            return CheckResult("counterexample", env, method="перебір", tried=tried)
    return CheckResult(
        "unknown",
        method="перебір",
        tried=tried,
        note=f"контрприкладів не знайдено серед {tried} наборів значень",
    )


def check(formula: A.Bexp, *, use_z3: bool = True, lo: int = -3, hi: int = 6) -> CheckResult:
    if use_z3 and z3_available():
        res = check_z3(formula)
        if res.status != "unknown":
            return res
        bounded = check_bounded(formula, lo, hi)
        if bounded.status == "counterexample":
            return bounded
        bounded.note = f"{res.note}; {bounded.note}" if res.note else bounded.note
        return bounded
    return check_bounded(formula, lo, hi)
