"""Typed abstract syntax tree of SIPL.

Every node carries a :class:`SourceSpan`; spans are excluded from equality so that
``parse(unparse(tree)) == tree`` can be used as a structural round-trip check.

Syntactic categories follow the practicum notation:
``Prog`` (P), ``Stm`` (S), ``Aexp`` (a), ``Bexp`` (b), ``Var`` (x), ``Num`` (n).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar

from sipl.span import SourceSpan

# ---------------------------------------------------------------------------
# base
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    span: SourceSpan | None = field(default=None, compare=False, repr=False, kw_only=True)

    category: ClassVar[str] = "Node"

    def children(self) -> Iterator[Node]:
        for f in fields(self):
            if f.name == "span":
                continue
            value = getattr(self, f.name)
            if isinstance(value, Node):
                yield value
            elif isinstance(value, tuple):
                yield from (v for v in value if isinstance(v, Node))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"node": type(self).__name__, "category": self.category}
        for f in fields(self):
            if f.name == "span":
                continue
            out[f.name] = _value_to_json(getattr(self, f.name))
        out["span"] = self.span.to_dict() if self.span else None
        return out


def _value_to_json(value: Any) -> Any:
    if isinstance(value, Node):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_value_to_json(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# arithmetic expressions  a ::= n | x | a1 + a2 | a1 - a2 | a1 * a2 | (a)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Num(Node):
    value: int
    category: ClassVar[str] = "Aexp"


@dataclass(frozen=True)
class Var(Node):
    name: str
    category: ClassVar[str] = "Aexp"


ARITH_OPS = ("+", "-", "*", "div", "mod")


@dataclass(frozen=True)
class BinOp(Node):
    op: str  # one of ARITH_OPS
    left: Aexp
    right: Aexp
    category: ClassVar[str] = "Aexp"


@dataclass(frozen=True)
class Call(Node):
    """Function application – allowed only in specification formulas ([SPEC])."""

    name: str
    args: tuple[Aexp, ...]
    category: ClassVar[str] = "Aexp"


Aexp = Num | Var | BinOp | Call

# ---------------------------------------------------------------------------
# conditions  b ::= a1 = a2 | a1 > a2 | b1 ∨ b2 | ¬ b | (b)
# ---------------------------------------------------------------------------

COMPARE_OPS = ("=", ">", ">=", "<", "<=", "!=")
BOOL_OPS = ("or", "and", "->")


@dataclass(frozen=True)
class Compare(Node):
    op: str  # one of COMPARE_OPS
    left: Aexp
    right: Aexp
    category: ClassVar[str] = "Bexp"


@dataclass(frozen=True)
class BoolOp(Node):
    op: str  # one of BOOL_OPS
    left: Bexp
    right: Bexp
    category: ClassVar[str] = "Bexp"


@dataclass(frozen=True)
class Not(Node):
    operand: Bexp
    category: ClassVar[str] = "Bexp"


@dataclass(frozen=True)
class BoolConst(Node):
    value: bool
    category: ClassVar[str] = "Bexp"


Bexp = Compare | BoolOp | Not | BoolConst

# ---------------------------------------------------------------------------
# statements  S ::= x := a | S1; S2 | if b then S1 else S2 | while b do S
#                 | begin S end | skip
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Assign(Node):
    target: Var
    value: Aexp
    category: ClassVar[str] = "Stm"


@dataclass(frozen=True)
class Seq(Node):
    """Sequential composition ``S1; S2; ...; Sn`` (n >= 2).

    The BNF rule ``S ::= S1; S2`` is binary; composition is associative
    (Lemma 1.1 of the textbook), so the AST keeps the flat list.
    """

    items: tuple[Stm, ...]
    category: ClassVar[str] = "Stm"


@dataclass(frozen=True)
class If(Node):
    cond: Bexp
    then: Stm
    orelse: Stm
    category: ClassVar[str] = "Stm"


@dataclass(frozen=True)
class While(Node):
    cond: Bexp
    body: Stm
    category: ClassVar[str] = "Stm"


@dataclass(frozen=True)
class Block(Node):
    body: Stm
    category: ClassVar[str] = "Stm"


@dataclass(frozen=True)
class Skip(Node):
    category: ClassVar[str] = "Stm"


Stm = Assign | Seq | If | While | Block | Skip


@dataclass(frozen=True)
class Program(Node):
    body: Stm
    category: ClassVar[str] = "Prog"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def walk(node: Node) -> Iterator[Node]:
    """Pre-order traversal."""
    yield node
    for child in node.children():
        yield from walk(child)


def variables(node: Node) -> list[str]:
    """Variable names in order of first occurrence."""
    seen: dict[str, None] = {}
    for n in walk(node):
        if isinstance(n, Var):
            seen.setdefault(n.name, None)
    return list(seen)


def assigned_variables(node: Node) -> list[str]:
    seen: dict[str, None] = {}
    for n in walk(node):
        if isinstance(n, Assign):
            seen.setdefault(n.target.name, None)
    return list(seen)


def input_variables(program: Program) -> list[str]:
    """Variables that may be read before any assignment to them (the program's inputs)."""
    found: dict[str, None] = {}

    def reads(e: Node, defined: set[str]) -> None:
        for name in variables(e):
            if name not in defined:
                found.setdefault(name, None)

    def go(s: Stm, defined: set[str]) -> set[str]:
        if isinstance(s, Assign):
            reads(s.value, defined)
            return defined | {s.target.name}
        if isinstance(s, Seq):
            for item in s.items:
                defined = go(item, defined)
            return defined
        if isinstance(s, Block):
            return go(s.body, defined)
        if isinstance(s, If):
            reads(s.cond, defined)
            return go(s.then, set(defined)) & go(s.orelse, set(defined))
        if isinstance(s, While):
            reads(s.cond, defined)
            go(s.body, set(defined))
            return defined
        return defined

    go(program.body, set())
    return list(found)


def loops(node: Node) -> list[While]:
    """All ``while`` statements in source (pre-order) order."""
    return [n for n in walk(node) if isinstance(n, While)]


# ---------------------------------------------------------------------------
# unparse – canonical one-line concrete syntax (ASCII operators of the course)
# ---------------------------------------------------------------------------

_A_PREC = {"+": 1, "-": 1, "*": 2, "div": 2, "mod": 2}
_B_PREC = {"->": 0, "or": 1, "and": 2}
_B_SYMBOL = {"or": "∨", "and": "∧", "->": "→"}


def _a_prec(a: Aexp) -> int:
    return _A_PREC[a.op] if isinstance(a, BinOp) else 3


def unparse_aexp(a: Aexp) -> str:
    if isinstance(a, Num):
        return str(a.value)
    if isinstance(a, Var):
        return a.name
    if isinstance(a, Call):
        return f"{a.name}({', '.join(unparse_aexp(x) for x in a.args)})"
    p = _A_PREC[a.op]
    left = unparse_aexp(a.left)
    if _a_prec(a.left) < p:
        left = f"({left})"
    right = unparse_aexp(a.right)
    if _a_prec(a.right) <= p:
        right = f"({right})"
    return f"{left} {a.op} {right}"


def _b_prec(b: Bexp) -> int:
    if isinstance(b, BoolOp):
        return _B_PREC[b.op]
    if isinstance(b, Not):
        return 3
    return 4


def unparse_bexp(b: Bexp) -> str:
    if isinstance(b, BoolConst):
        return "true" if b.value else "false"
    if isinstance(b, Compare):
        return f"{unparse_aexp(b.left)} {b.op} {unparse_aexp(b.right)}"
    if isinstance(b, Not):
        inner = unparse_bexp(b.operand)
        return f"¬{inner}" if _b_prec(b.operand) >= 3 else f"¬({inner})"
    p = _B_PREC[b.op]
    left, right = unparse_bexp(b.left), unparse_bexp(b.right)
    right_assoc = b.op == "->"
    if _b_prec(b.left) < p or (right_assoc and _b_prec(b.left) == p):
        left = f"({left})"
    if _b_prec(b.right) < p or (not right_assoc and _b_prec(b.right) == p):
        right = f"({right})"
    return f"{left} {_B_SYMBOL[b.op]} {right}"


def unparse_stm(s: Stm) -> str:
    if isinstance(s, Assign):
        return f"{s.target.name} := {unparse_aexp(s.value)}"
    if isinstance(s, Skip):
        return "skip"
    if isinstance(s, Seq):
        return "; ".join(unparse_stm(x) for x in s.items)
    if isinstance(s, Block):
        return f"begin {unparse_stm(s.body)} end"
    if isinstance(s, If):
        return f"if {unparse_bexp(s.cond)} then {_single(s.then)} else {_single(s.orelse)}"
    return f"while {unparse_bexp(s.cond)} do {_single(s.body)}"


def _single(s: Stm) -> str:
    """A statement in a position where the grammar allows only one statement."""
    return f"begin {unparse_stm(s)} end" if isinstance(s, Seq) else unparse_stm(s)


def unparse(node: Node) -> str:
    if isinstance(node, Program):
        return f"begin {unparse_stm(node.body)} end"
    if isinstance(node, (Assign, Seq, If, While, Block, Skip)):
        return unparse_stm(node)
    if isinstance(node, (Compare, BoolOp, Not, BoolConst)):
        return unparse_bexp(node)
    if isinstance(node, (Num, Var, BinOp, Call)):
        return unparse_aexp(node)
    raise TypeError(f"cannot unparse {type(node).__name__}")


def format_program(program: Program, indent: str = "  ") -> str:
    """Multi-line layout in the style of the practicum examples."""
    lines: list[str] = []

    def emit(s: Stm, depth: int, suffix: str = "") -> None:
        pad = indent * depth
        if isinstance(s, Seq):
            for i, item in enumerate(s.items):
                emit(item, depth, ";" if i < len(s.items) - 1 else suffix)
        elif isinstance(s, Block):
            lines.append(f"{pad}begin")
            emit(s.body, depth + 1)
            lines.append(f"{pad}end{suffix}")
        elif isinstance(s, While):
            lines.append(f"{pad}while {unparse_bexp(s.cond)} do")
            emit(_as_block(s.body), depth + 1 if not _blockish(s.body) else depth, suffix)
        elif isinstance(s, If):
            lines.append(f"{pad}if {unparse_bexp(s.cond)} then")
            emit(_as_block(s.then), depth + 1 if not _blockish(s.then) else depth)
            lines.append(f"{pad}else")
            emit(_as_block(s.orelse), depth + 1 if not _blockish(s.orelse) else depth, suffix)
        else:
            lines.append(f"{pad}{unparse_stm(s)}{suffix}")

    lines.append("begin")
    emit(program.body, 1)
    lines.append("end")
    return "\n".join(lines) + "\n"


def _blockish(s: Stm) -> bool:
    return isinstance(s, (Block, Seq))


def _as_block(s: Stm) -> Stm:
    return Block(s, span=s.span) if isinstance(s, Seq) else s
