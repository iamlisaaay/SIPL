"""States (nominative data ``[x ↦ v, ...]``) and the arithmetic of the basic functions."""

from __future__ import annotations

import re
from collections.abc import Mapping

from sipl.diagnostics import Diagnostic, SiplError

State = dict[str, int]


def format_state(st: Mapping[str, int], *, ascii_only: bool = False) -> str:
    arrow = "->" if ascii_only else "↦"
    return "[" + ", ".join(f"{k} {arrow} {v}" for k, v in st.items()) + "]"


def overwrite(st: Mapping[str, int], var: str, value: int) -> State:
    """``st ∇ [var ↦ value]`` – existing names keep their position, new ones go last."""
    new = dict(st)
    new[var] = value
    return new


_PAIR = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|:=|↦|->|\|->)\s*(-?\d+)\s*$")


def parse_state(text: str) -> State:
    """Parse ``"X=5, Y=2"`` or ``"[X ↦ 5, Y ↦ 2]"`` into a state."""
    body = text.strip()
    if body.startswith("[") and body.endswith("]"):
        body = body[1:-1]
    st: State = {}
    if not body.strip():
        return st
    for part in re.split(r"[,;]", body):
        m = _PAIR.match(part)
        if not m:
            raise SiplError(
                [
                    Diagnostic(
                        "E301",
                        f"не вдалося розібрати пару стану '{part.strip()}'",
                        hint="формат: X=5, Y=2  або  [X ↦ 5, Y ↦ 2]",
                    )
                ]
            )
        st[m.group(1)] = int(m.group(2))
    return st


# ---------------------------------------------------------------------------
# basic functions (shared by the evaluator, the prover and the bounded tester)
# ---------------------------------------------------------------------------


class ArithmeticUndefined(Exception):
    """The basic function is undefined on its arguments (e.g. division by zero)."""


def euclid_div(a: int, b: int) -> int:
    """Euclidean division: the remainder is always ``0 <= r < |b|`` (same as SMT-LIB/Z3)."""
    if b == 0:
        raise ArithmeticUndefined("ділення на нуль")
    q = a // b if b > 0 else -(a // -b)
    if a - b * q < 0:  # pragma: no cover - floor division already guarantees r >= 0 for b > 0
        q += 1 if b > 0 else -1
    return q


def euclid_mod(a: int, b: int) -> int:
    return a - b * euclid_div(a, b)


def apply_basic(fn: str, args: list[int | bool]) -> int | bool:
    """Value of a basic function of the algebra on concrete arguments."""
    if fn == "neg":
        return not args[0]
    a, b = args
    if fn == "add":
        return int(a) + int(b)
    if fn == "sub":
        return int(a) - int(b)
    if fn == "mult":
        return int(a) * int(b)
    if fn == "div":
        return euclid_div(int(a), int(b))
    if fn == "mod":
        return euclid_mod(int(a), int(b))
    if fn == "eq":
        return a == b
    if fn == "gr":
        return int(a) > int(b)
    if fn == "gre":
        return int(a) >= int(b)
    if fn == "ls":
        return int(a) < int(b)
    if fn == "lse":
        return int(a) <= int(b)
    if fn == "neq":
        return a != b
    if fn == "or":
        return bool(a) or bool(b)
    if fn == "and":
        return bool(a) and bool(b)
    raise ValueError(f"unknown basic function {fn}")  # pragma: no cover
