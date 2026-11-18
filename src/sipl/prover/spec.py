"""Correctness specifications: pre/post-conditions and loop annotations.

A spec is a TOML file (or a dict)::

    pre  = "X = x ∧ Y = y ∧ y >= 0"
    post = "R = pow(x, y)"
    mode = "total"            # or "partial"; default: total if every loop has a variant

    [[loop]]                  # one table per while, in source order (or give `line`)
    invariant = "R * pow(X, Y) = pow(x, y) ∧ Y >= 0 ∧ X = x"
    variant   = "Y"

    [testing]                 # optional bounded testing of the whole program
    min = -2
    max = 6
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sipl import ast as A
from sipl.diagnostics import Diagnostic, SiplError, SiplSyntaxError
from sipl.parser import parse_expr, parse_formula
from sipl.prover.formula import check_functions

Mode = Literal["partial", "total"]


@dataclass
class LoopAnnotation:
    invariant: A.Bexp
    variant: A.Aexp | None = None
    line: int | None = None
    invariant_text: str = ""
    variant_text: str | None = None


@dataclass
class Spec:
    pre: A.Bexp
    post: A.Bexp
    loops: list[LoopAnnotation] = field(default_factory=list)
    mode: Mode = "total"
    test_min: int = -2
    test_max: int = 6
    pre_text: str = ""
    post_text: str = ""


def _formula(text: str, where: str) -> A.Bexp:
    try:
        f = parse_formula(text)
    except SiplSyntaxError as exc:
        d = exc.diagnostics[0]
        raise SiplError(
            [Diagnostic("E402", f"{where}: {d.message} (у формулі '{text}')", None, hint=d.hint)]
        ) from None
    problems = check_functions(f)
    if problems:
        raise SiplError([Diagnostic("E403", f"{where}: {problems[0]}")])
    return f


def _expr(text: str, where: str) -> A.Aexp:
    try:
        e = parse_expr(text)
    except SiplSyntaxError as exc:
        d = exc.diagnostics[0]
        raise SiplError([Diagnostic("E402", f"{where}: {d.message} (у виразі '{text}')")]) from None
    problems = check_functions(e)
    if problems:
        raise SiplError([Diagnostic("E403", f"{where}: {problems[0]}")])
    return e


def spec_from_dict(data: dict[str, Any]) -> Spec:
    if "pre" not in data or "post" not in data:
        raise SiplError([Diagnostic("E404", "специфікація повинна містити поля 'pre' і 'post'")])
    loops: list[LoopAnnotation] = []
    for i, item in enumerate(data.get("loop", []), start=1):
        if "invariant" not in item:
            raise SiplError([Diagnostic("E404", f"loop #{i}: відсутнє поле 'invariant'")])
        variant_text = item.get("variant")
        loops.append(
            LoopAnnotation(
                invariant=_formula(str(item["invariant"]), f"інваріант циклу #{i}"),
                variant=_expr(str(variant_text), f"варіант циклу #{i}") if variant_text else None,
                line=int(item["line"]) if "line" in item else None,
                invariant_text=str(item["invariant"]),
                variant_text=str(variant_text) if variant_text else None,
            )
        )
    default_mode: Mode = "total" if loops and all(lp.variant for lp in loops) else "partial"
    if not loops:
        default_mode = "total"
    mode = data.get("mode", default_mode)
    if mode not in ("partial", "total"):
        raise SiplError([Diagnostic("E404", "mode має бути 'partial' або 'total'")])
    testing = data.get("testing", {})
    return Spec(
        pre=_formula(str(data["pre"]), "передумова"),
        post=_formula(str(data["post"]), "післяумова"),
        loops=loops,
        mode=mode,
        test_min=int(testing.get("min", -2)),
        test_max=int(testing.get("max", 6)),
        pre_text=str(data["pre"]),
        post_text=str(data["post"]),
    )


def load_spec(path: str | Path) -> Spec:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise SiplError([Diagnostic("E405", f"некоректний TOML у {path}: {exc}")]) from None
    return spec_from_dict(data)
