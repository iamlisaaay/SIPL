"""Construction of semantic terms: sem_P, sem_S, sem_A, sem_B (practicum p. 15).

The term is built recursively over the AST.  :func:`explain` additionally records the
rewriting chain the way it is done by hand in the practicum: start from
``sem_P(<program text>)`` and repeatedly replace the leftmost-outermost untranslated
part ``sem_X(...)`` by the right-hand side of the matching rule.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from sipl import ast as A
from sipl.semantics.terms import (
    AssignT,
    Const,
    Denaming,
    Hole,
    IdT,
    IfT,
    ParenT,
    SeqT,
    Sup,
    Term,
    WhileT,
    render,
)

_A_FN = {
    "+": ("add", "NS_A_Add"),
    "-": ("sub", "NS_A_Sub"),
    "*": ("mult", "NS_A_Mult"),
    "div": ("div", "NS_A_Div"),
    "mod": ("mod", "NS_A_Mod"),
}
_B_FN = {
    "=": ("eq", "NS_B_eq"),
    ">": ("gr", "NS_B_gr"),
    ">=": ("gre", "NS_B_gre"),
    "<": ("ls", "NS_B_ls"),
    "<=": ("lse", "NS_B_lse"),
    "!=": ("neq", "NS_B_neq"),
}

#: the rule schemata, for documentation / ``sipl term --rules``
RULE_SCHEMATA: dict[str, str] = {
    "NS_Prog": "sem_P(begin S end) = sem_S(S)",
    "NS_Stm_As": "sem_S(x := a) = AS^x(sem_A(a))",
    "NS_Stm_Seq": "sem_S(S1; S2) = sem_S(S1) · sem_S(S2)",
    "NS_Stm_If": "sem_S(if b then S1 else S2) = IF(sem_B(b), sem_S(S1), sem_S(S2))",
    "NS_Stm_Wh": "sem_S(while b do S) = WH(sem_B(b), sem_S(S))",
    "NS_Stm_BE": "sem_S(begin S end) = (sem_S(S))",
    "NS_Stm_skip": "sem_S(skip) = id",
    "NS_A_Num": "sem_A(n) = n",
    "NS_A_Var": "sem_A(x) = x⇒",
    "NS_A_Add": "sem_A(a1 + a2) = S2(add, sem_A(a1), sem_A(a2))",
    "NS_A_Sub": "sem_A(a1 - a2) = S2(sub, sem_A(a1), sem_A(a2))",
    "NS_A_Mult": "sem_A(a1 * a2) = S2(mult, sem_A(a1), sem_A(a2))",
    "NS_A_Div": "sem_A(a1 div a2) = S2(div, sem_A(a1), sem_A(a2))   [розширення]",
    "NS_A_Mod": "sem_A(a1 mod a2) = S2(mod, sem_A(a1), sem_A(a2))   [розширення]",
    "NS_B_eq": "sem_B(a1 = a2) = S2(eq, sem_A(a1), sem_A(a2))",
    "NS_B_gr": "sem_B(a1 > a2) = S2(gr, sem_A(a1), sem_A(a2))",
    "NS_B_or": "sem_B(b1 ∨ b2) = S2(or, sem_B(b1), sem_B(b2))",
    "NS_B_neg": "sem_B(¬b) = S1(neg, sem_B(b))",
    "NS_B_gre": "sem_B(a1 >= a2) = S2(gre, sem_A(a1), sem_A(a2))   [розширення]",
    "NS_B_ls": "sem_B(a1 < a2) = S2(ls, sem_A(a1), sem_A(a2))   [розширення]",
    "NS_B_lse": "sem_B(a1 <= a2) = S2(lse, sem_A(a1), sem_A(a2))   [розширення]",
    "NS_B_neq": "sem_B(a1 != a2) = S2(neq, sem_A(a1), sem_A(a2))   [розширення]",
    "NS_B_and": "sem_B(b1 ∧ b2) = S2(and, sem_B(b1), sem_B(b2))   [розширення]",
    "NS_B_const": "sem_B(true) = true, sem_B(false) = false   [розширення]",
}


# ---------------------------------------------------------------------------
# one rewriting step: syntax -> (rule, term whose sub-parts are still holes)
# ---------------------------------------------------------------------------


def _hole(kind: str, node: A.Node) -> Hole:
    return Hole(kind, A.unparse(node), node, origin=node.span)  # type: ignore[arg-type]


def expand(kind: str, node: A.Node) -> tuple[str, Term]:
    """Apply exactly one rule to ``sem_<kind>(node)``."""
    o = node.span
    if kind == "P":
        assert isinstance(node, A.Program)
        return "NS_Prog", _hole("S", node.body)
    if kind == "S":
        if isinstance(node, A.Assign):
            return "NS_Stm_As", AssignT(node.target.name, _hole("A", node.value), origin=o)
        if isinstance(node, A.Seq):
            return "NS_Stm_Seq", SeqT(tuple(_hole("S", s) for s in node.items), origin=o)
        if isinstance(node, A.If):
            return "NS_Stm_If", IfT(
                _hole("B", node.cond), _hole("S", node.then), _hole("S", node.orelse), origin=o
            )
        if isinstance(node, A.While):
            return "NS_Stm_Wh", WhileT(_hole("B", node.cond), _hole("S", node.body), origin=o)
        if isinstance(node, A.Block):
            return "NS_Stm_BE", ParenT(_hole("S", node.body), origin=o)
        if isinstance(node, A.Skip):
            return "NS_Stm_skip", IdT(origin=o)
    if kind == "A":
        if isinstance(node, A.Num):
            return "NS_A_Num", Const(node.value, origin=o)
        if isinstance(node, A.Var):
            return "NS_A_Var", Denaming(node.name, origin=o)
        if isinstance(node, A.BinOp):
            fn, rule = _A_FN[node.op]
            return rule, Sup(fn, (_hole("A", node.left), _hole("A", node.right)), origin=o)
    if kind == "B":
        if isinstance(node, A.Compare):
            fn, rule = _B_FN[node.op]
            return rule, Sup(fn, (_hole("A", node.left), _hole("A", node.right)), origin=o)
        if isinstance(node, A.BoolOp) and node.op in ("or", "and"):
            return f"NS_B_{node.op}", Sup(
                node.op, (_hole("B", node.left), _hole("B", node.right)), origin=o
            )
        if isinstance(node, A.Not):
            return "NS_B_neg", Sup("neg", (_hole("B", node.operand),), origin=o)
        if isinstance(node, A.BoolConst):
            return "NS_B_const", Const(node.value, origin=o)
    raise ValueError(
        f"для конструкції '{A.unparse(node)}' немає правила побудови семантичного терму"
    )


# ---------------------------------------------------------------------------
# direct construction
# ---------------------------------------------------------------------------


def fill(t: Term) -> Term:
    """Translate all holes recursively."""
    if isinstance(t, Hole):
        _, rhs = expand(t.kind, t.node)
        return fill(rhs)
    return _map_children(t, fill)


def _map_children(t: Term, f: Any) -> Term:
    if isinstance(t, Sup):
        return dataclasses.replace(t, args=tuple(f(a) for a in t.args))
    if isinstance(t, AssignT):
        return dataclasses.replace(t, value=f(t.value))
    if isinstance(t, SeqT):
        return dataclasses.replace(t, items=tuple(f(i) for i in t.items))
    if isinstance(t, IfT):
        return dataclasses.replace(t, cond=f(t.cond), then=f(t.then), orelse=f(t.orelse))
    if isinstance(t, WhileT):
        return dataclasses.replace(t, cond=f(t.cond), body=f(t.body))
    if isinstance(t, ParenT):
        return dataclasses.replace(t, inner=f(t.inner))
    return t


def sem_P(program: A.Program) -> Term:
    return fill(_hole("P", program))


def sem_S(stm: A.Stm) -> Term:
    return fill(_hole("S", stm))


def sem_A(a: A.Aexp) -> Term:
    return fill(_hole("A", a))


def sem_B(b: A.Bexp) -> Term:
    return fill(_hole("B", b))


# ---------------------------------------------------------------------------
# explanation: the rewriting chain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    rule: str
    lhs: str  # the rewritten part, e.g. "sem_S(R := 1)"
    rhs: str  # its replacement,     e.g. "AS^R(sem_A(1))"
    whole: str  # the whole term after the step

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "lhs": self.lhs, "rhs": self.rhs, "whole": self.whole}


@dataclass
class Explanation:
    start: str
    steps: list[Step]
    term: Term

    def chain(self) -> str:
        """``sem_P(...) = ... = <term>`` one equality per line, with rule names."""
        lines = [self.start]
        for s in self.steps:
            lines.append(f"  = {s.whole}    [{s.rule}]")
        return "\n".join(lines) + "\n"

    def local(self) -> str:
        """One line per rule application, showing only the rewritten part."""
        width = max((len(s.rule) for s in self.steps), default=0)
        lines = [f"{s.rule:<{width}}  {s.lhs} = {s.rhs}" for s in self.steps]
        lines.append("")
        lines.append(f"Семантичний терм: {render(self.term)}")
        return "\n".join(lines) + "\n"

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "steps": [s.to_dict() for s in self.steps]}


def explain(node: A.Node, kind: str = "P") -> Explanation:
    """Rewrite ``sem_<kind>(node)`` step by step until no holes are left."""
    current: Term = _hole(kind, node)
    start = render(current)
    steps: list[Step] = []
    while True:
        result = _rewrite_first(current)
        if result is None:
            break
        current, hole, rule, rhs = result
        steps.append(Step(rule, render(hole), render(rhs), render(current)))
    return Explanation(start, steps, current)


def _rewrite_first(t: Term) -> tuple[Term, Hole, str, Term] | None:
    """Replace the first hole in pre-order; return (new term, hole, rule, replacement)."""
    if isinstance(t, Hole):
        rule, rhs = expand(t.kind, t.node)
        return rhs, t, rule, rhs
    found: list[tuple[Hole, str, Term]] = []

    def visit(child: Term) -> Term:
        if found:
            return child
        r = _rewrite_first(child)
        if r is None:
            return child
        found.append((r[1], r[2], r[3]))
        return r[0]

    new = _map_children(t, visit)
    if not found:
        return None
    hole, rule, rhs = found[0]
    return new, hole, rule, rhs
