"""Formulas of the specification language and their concrete semantics.

Formulas reuse the condition AST (:mod:`sipl.ast`) extended with ``∧``, ``→`` and
calls of a few mathematical functions that SIPL itself does not have.  Free variables
are either program variables (upper-case by convention, e.g. ``X``) or logical
constants denoting initial values (e.g. ``x``); both are universally quantified.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping

from sipl import ast as A
from sipl.state import ArithmeticUndefined, euclid_div, euclid_mod

TRUE = A.BoolConst(True)
FALSE = A.BoolConst(False)


class Undefined(Exception):
    """A formula has no truth value on the given valuation (e.g. ``pow(2, -1)``)."""


def _pow(x: int, n: int) -> int:
    if n < 0:
        raise Undefined("pow з від'ємним показником")
    if abs(x) > 1 and n > 4096:
        raise Undefined("pow: надто великий показник")
    return int(x**n)


def _fact(n: int) -> int:
    if n < 0:
        raise Undefined("fact від'ємного числа")
    if n > 2000:
        raise Undefined("fact: надто великий аргумент")
    return math.factorial(n)


#: spec functions: name -> (arity, implementation, description)
FUNCTIONS: dict[str, tuple[int, Callable[..., int], str]] = {
    "pow": (2, _pow, "pow(x, n) = x^n, n ≥ 0"),
    "fact": (1, _fact, "fact(n) = n!, n ≥ 0"),
    "gcd": (2, lambda a, b: math.gcd(a, b), "найбільший спільний дільник"),
    "abs": (1, abs, "модуль"),
    "min": (2, min, "мінімум"),
    "max": (2, max, "максимум"),
}


# ---------------------------------------------------------------------------
# smart constructors (keep generated conditions readable)
# ---------------------------------------------------------------------------


def conj(*parts: A.Bexp) -> A.Bexp:
    items = [p for p in parts if p != TRUE]
    if any(p == FALSE for p in items):
        return FALSE
    if not items:
        return TRUE
    out = items[0]
    for p in items[1:]:
        out = A.BoolOp("and", out, p)
    return out


def implies(a: A.Bexp, b: A.Bexp) -> A.Bexp:
    if a == TRUE:
        return b
    if b == TRUE or a == FALSE:
        return TRUE
    return A.BoolOp("->", a, b)


def neg(a: A.Bexp) -> A.Bexp:
    if isinstance(a, A.BoolConst):
        return A.BoolConst(not a.value)
    if isinstance(a, A.Not):
        return a.operand  # ¬¬b = b
    return A.Not(a)


# ---------------------------------------------------------------------------
# substitution  Q[a/x]
# ---------------------------------------------------------------------------


def subst_a(e: A.Aexp, var: str, by: A.Aexp) -> A.Aexp:
    if isinstance(e, A.Var):
        return by if e.name == var else e
    if isinstance(e, A.Num):
        return e
    if isinstance(e, A.BinOp):
        return A.BinOp(e.op, subst_a(e.left, var, by), subst_a(e.right, var, by))
    return A.Call(e.name, tuple(subst_a(x, var, by) for x in e.args))


def subst(f: A.Bexp, var: str, by: A.Aexp) -> A.Bexp:
    if isinstance(f, A.BoolConst):
        return f
    if isinstance(f, A.Compare):
        return A.Compare(f.op, subst_a(f.left, var, by), subst_a(f.right, var, by))
    if isinstance(f, A.Not):
        return A.Not(subst(f.operand, var, by))
    return A.BoolOp(f.op, subst(f.left, var, by), subst(f.right, var, by))


def definedness(node: A.Node) -> A.Bexp:
    """Conditions under which every ``div``/``mod`` in ``node`` is defined."""
    conds: list[A.Bexp] = []
    for n in A.walk(node):
        if isinstance(n, A.BinOp) and n.op in ("div", "mod"):
            c = A.Compare("!=", n.right, A.Num(0))
            if c not in conds:
                conds.append(c)
    return conj(*conds)


def free_vars(node: A.Node) -> list[str]:
    return A.variables(node)


# ---------------------------------------------------------------------------
# concrete evaluation
# ---------------------------------------------------------------------------


def eval_a(e: A.Aexp, env: Mapping[str, int]) -> int:
    if isinstance(e, A.Num):
        return e.value
    if isinstance(e, A.Var):
        if e.name not in env:
            raise Undefined(f"змінна {e.name} не має значення")
        return env[e.name]
    if isinstance(e, A.Call):
        if e.name not in FUNCTIONS:
            raise Undefined(f"невідома функція {e.name}")
        arity, impl, _ = FUNCTIONS[e.name]
        if len(e.args) != arity:
            raise Undefined(f"{e.name} очікує {arity} аргумент(и)")
        return impl(*(eval_a(a, env) for a in e.args))
    a, b = eval_a(e.left, env), eval_a(e.right, env)
    if e.op == "+":
        return a + b
    if e.op == "-":
        return a - b
    if e.op == "*":
        return a * b
    try:
        return euclid_div(a, b) if e.op == "div" else euclid_mod(a, b)
    except ArithmeticUndefined as exc:
        raise Undefined(str(exc)) from None


def eval_b(f: A.Bexp, env: Mapping[str, int]) -> bool:
    if isinstance(f, A.BoolConst):
        return f.value
    if isinstance(f, A.Compare):
        a, b = eval_a(f.left, env), eval_a(f.right, env)
        return {
            "=": a == b,
            ">": a > b,
            ">=": a >= b,
            "<": a < b,
            "<=": a <= b,
            "!=": a != b,
        }[f.op]
    if isinstance(f, A.Not):
        return not eval_b(f.operand, env)
    if f.op == "->":
        return (not eval_b(f.left, env)) or eval_b(f.right, env)
    left = eval_b(f.left, env)
    if f.op == "and":
        return left and eval_b(f.right, env)
    return left or eval_b(f.right, env)


def check_functions(node: A.Node) -> list[str]:
    """Names of unknown functions or calls with a wrong number of arguments."""
    problems = []
    for n in A.walk(node):
        if isinstance(n, A.Call):
            if n.name not in FUNCTIONS:
                problems.append(f"невідома функція '{n.name}' (доступні: {', '.join(FUNCTIONS)})")
            elif len(n.args) != FUNCTIONS[n.name][0]:
                problems.append(f"функція '{n.name}' очікує {FUNCTIONS[n.name][0]} аргумент(и)")
    return problems
