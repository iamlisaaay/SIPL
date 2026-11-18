"""Semantic terms of the program algebra A_Prog.

Term sorts:

* TFA – nominative arithmetic functions:  ``n``, ``x⇒``, ``S2(add, ...)``
* TFB – nominative predicates:            ``S2(gr, ...)``, ``S1(neg, ...)``
* TFS – binominative state transformers:  ``AS^x(..)``, ``f · g``, ``IF(..)``, ``WH(..)``, ``id``

Every term remembers ``origin`` – the span of the AST node it was built from – so the
layers Source -> AST -> Term stay linked.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from sipl.span import SourceSpan

# basic functions of the algebra: name -> (arity, sort of result, infix sign for value display)
BASIC_FUNCTIONS: dict[str, tuple[int, str, str]] = {
    "add": (2, "A", "+"),
    "sub": (2, "A", "-"),
    "mult": (2, "A", "*"),
    "div": (2, "A", "div"),
    "mod": (2, "A", "mod"),
    "eq": (2, "B", "="),
    "gr": (2, "B", ">"),
    "gre": (2, "B", ">="),
    "ls": (2, "B", "<"),
    "lse": (2, "B", "<="),
    "neq": (2, "B", "!="),
    "or": (2, "B", "∨"),
    "and": (2, "B", "∧"),
    "neg": (1, "B", "¬"),
}


@dataclass(frozen=True)
class Term:
    origin: SourceSpan | None = field(default=None, compare=False, repr=False, kw_only=True)

    sort: str = field(default="?", init=False, compare=False, repr=False)

    def children(self) -> tuple[Term, ...]:
        return ()

    def walk(self) -> Iterator[Term]:
        yield self
        for c in self.children():
            yield from c.walk()


# ---- TFA / TFB -----------------------------------------------------------


@dataclass(frozen=True)
class Const(Term):
    """Constant function ``n̄`` (written simply as ``n``)."""

    value: int | bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort", "B" if isinstance(self.value, bool) else "A")


@dataclass(frozen=True)
class Denaming(Term):
    """Denaming function ``x⇒``: ``x⇒(st) = st(x)``."""

    var: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort", "A")


@dataclass(frozen=True)
class Sup(Term):
    """Superposition ``Sn(f, g1, ..., gn)`` of a basic function ``f``."""

    fn: str
    args: tuple[Term, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort", BASIC_FUNCTIONS[self.fn][1])

    def children(self) -> tuple[Term, ...]:
        return self.args


# ---- TFS ------------------------------------------------------------------


@dataclass(frozen=True)
class AssignT(Term):
    """``AS^x(fa)``: ``AS^x(fa)(st) = st ∇ [x ↦ fa(st)]``."""

    var: str
    value: Term

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort", "S")

    def children(self) -> tuple[Term, ...]:
        return (self.value,)


@dataclass(frozen=True)
class SeqT(Term):
    """Sequential composition ``f1 · f2 · ... · fn`` (apply left to right)."""

    items: tuple[Term, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort", "S")

    def children(self) -> tuple[Term, ...]:
        return self.items


@dataclass(frozen=True)
class IfT(Term):
    cond: Term
    then: Term
    orelse: Term

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort", "S")

    def children(self) -> tuple[Term, ...]:
        return (self.cond, self.then, self.orelse)


@dataclass(frozen=True)
class WhileT(Term):
    cond: Term
    body: Term

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort", "S")

    def children(self) -> tuple[Term, ...]:
        return (self.cond, self.body)


@dataclass(frozen=True)
class IdT(Term):
    """Identity ``id(st) = st`` (semantics of ``skip``)."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort", "S")


@dataclass(frozen=True)
class ParenT(Term):
    """``(f)`` produced by rule NS_Stm_BE for ``begin S end``."""

    inner: Term

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort", self.inner.sort)

    def children(self) -> tuple[Term, ...]:
        return (self.inner,)


@dataclass(frozen=True)
class Hole(Term):
    """Not yet translated syntax ``sem_X(text)`` – used in step-by-step explanations."""

    kind: Literal["P", "S", "A", "B"]
    text: str
    node: Any = field(compare=False, repr=False)


TermT = Const | Denaming | Sup | AssignT | SeqT | IfT | WhileT | IdT | ParenT | Hole


def strip(t: Term) -> Term:
    """Remove ``ParenT`` wrappers (they do not change the denoted function)."""
    while isinstance(t, ParenT):
        t = t.inner
    return t


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

Style = Literal["unicode", "ascii", "latex"]

_SYM = {
    "unicode": {"denom": "⇒", "dot": " · ", "sup": lambda x: f"AS^{x}", "sem": "sem_"},
    "ascii": {"denom": "=>", "dot": " . ", "sup": lambda x: f"AS^{x}", "sem": "sem_"},
    "latex": {
        "denom": r"\Rightarrow",
        "dot": r" \cdot ",
        "sup": lambda x: rf"AS^{{{x}}}",
        "sem": r"sem\_",
    },
}


def render(t: Term, style: Style = "unicode") -> str:
    """Render a term in the course notation, e.g. ``AS^R(1) · WH(S2(gr, Y⇒, 0), ...)``."""
    return _render(t, style, parent_is_seq=False)


def _render(t: Term, style: Style, parent_is_seq: bool) -> str:
    sym = _SYM[style]
    if isinstance(t, Const):
        if isinstance(t.value, bool):
            return "true" if t.value else "false"
        return rf"\bar{{{t.value}}}" if style == "latex" else str(t.value)
    if isinstance(t, Denaming):
        return f"{t.var}{sym['denom']}"
    if isinstance(t, Sup):
        args = ", ".join(_render(a, style, False) for a in t.args)
        fn = rf"\mathit{{{t.fn}}}" if style == "latex" else t.fn
        return (
            f"S{len(t.args)}({fn}, {args})"
            if style != "latex"
            else f"S^{{{len(t.args)}}}({fn}, {args})"
        )
    if isinstance(t, AssignT):
        prefix = sym["sup"](t.var)  # type: ignore[operator]
        return f"{prefix}({_render(t.value, style, False)})"
    if isinstance(t, SeqT):
        return str(sym["dot"]).join(_render(i, style, True) for i in t.items)
    if isinstance(t, IfT):
        return (
            f"IF({_render(t.cond, style, False)}, {_render(t.then, style, False)}, "
            f"{_render(t.orelse, style, False)})"
        )
    if isinstance(t, WhileT):
        return f"WH({_render(t.cond, style, False)}, {_render(t.body, style, False)})"
    if isinstance(t, IdT):
        return r"\mathit{id}" if style == "latex" else "id"
    if isinstance(t, ParenT):
        inner = _render(t.inner, style, False)
        # brackets matter only for reading when the block sits inside a composition
        needs = parent_is_seq and isinstance(strip(t.inner), SeqT)
        return f"({inner})" if needs else inner
    if isinstance(t, Hole):
        text = t.text if style != "latex" else rf"\texttt{{{_latex_escape(t.text)}}}"
        return f"{sym['sem']}{t.kind}({text})"
    raise TypeError(type(t).__name__)  # pragma: no cover


def _latex_escape(s: str) -> str:
    for a, b in (
        ("\\", r"\textbackslash{}"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("_", r"\_"),
        ("#", r"\#"),
        ("&", r"\&"),
    ):
        s = s.replace(a, b)
    return s


def to_dict(t: Term) -> dict[str, Any]:
    """Stable JSON form (schema ``sipl.term/1``)."""
    base: dict[str, Any] = {
        "origin": t.origin.to_dict() if t.origin else None,
        "text": render(t),
    }
    if isinstance(t, Const):
        return {"kind": "const", "value": t.value, **base}
    if isinstance(t, Denaming):
        return {"kind": "denaming", "var": t.var, **base}
    if isinstance(t, Sup):
        return {"kind": "superposition", "fn": t.fn, "args": [to_dict(a) for a in t.args], **base}
    if isinstance(t, AssignT):
        return {"kind": "assign", "var": t.var, "value": to_dict(t.value), **base}
    if isinstance(t, SeqT):
        return {"kind": "seq", "items": [to_dict(i) for i in t.items], **base}
    if isinstance(t, IfT):
        return {
            "kind": "if",
            "cond": to_dict(t.cond),
            "then": to_dict(t.then),
            "else": to_dict(t.orelse),
            **base,
        }
    if isinstance(t, WhileT):
        return {"kind": "while", "cond": to_dict(t.cond), "body": to_dict(t.body), **base}
    if isinstance(t, IdT):
        return {"kind": "id", **base}
    if isinstance(t, ParenT):
        return {"kind": "paren", "inner": to_dict(t.inner), **base}
    return {"kind": "hole", "category": t.kind, "syntax": t.text, **base}  # type: ignore[attr-defined]
