"""Derivation (parse) tree of a SIPL program in terms of the *course* BNF.

Lark parses with a precedence-layered grammar; this module maps that concrete tree
back onto the ambiguous course BNF, so the result is exactly the tree a
student draws: metavariables ``<програма>``, ``<оператор>``, ``<вираз>``,
``<умова>``, ``<змінна>``, ``<число>`` and rule names ``NP1``, ``NS1``-``NS6``,
``NA1``-``NA6``, ``NB1``-``NB5``, ``NV``, ``NN``.

``S1; S2; S3`` becomes nested binary ``NS2`` nodes (left-nested), following the
binary BNF rule.  Every node keeps its :class:`SourceSpan`.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Literal

from lark import Token, Tree

from sipl.parser import parse_full
from sipl.span import SourceSpan, span_from_offsets

Notation = Literal["bnf", "math"]

# metavariable per syntactic category, in both notations
LABELS: dict[str, dict[str, str]] = {
    "bnf": {
        "Prog": "<програма>",
        "Stm": "<оператор>",
        "Aexp": "<вираз>",
        "Bexp": "<умова>",
        "Var": "<змінна>",
        "Num": "<число>",
    },
    "math": {"Prog": "P", "Stm": "S", "Aexp": "a", "Bexp": "b", "Var": "x", "Num": "n"},
}

# rule names: (bnf-table name, math-table name, human description)
RULES: dict[str, tuple[str, str, str]] = {
    "program": ("NP1", "P1", "P ::= begin S end"),
    "assign": ("NS1", "S1", "S ::= x := a"),
    "seq": ("NS2", "S2", "S ::= S1 ; S2"),
    "if_stmt": ("NS3", "S3", "S ::= if b then S1 else S2"),
    "while_stmt": ("NS4", "S4", "S ::= while b do S"),
    "block": ("NS5", "S5", "S ::= begin S end"),
    "skip": ("NS6", "S6", "S ::= skip"),
    "num": ("NA1", "A1", "a ::= n"),
    "var": ("NA2", "A2", "a ::= x"),
    "add": ("NA3", "A3", "a ::= a1 + a2"),
    "sub": ("NA4", "A4", "a ::= a1 - a2"),
    "mul": ("NA5", "A5", "a ::= a1 * a2"),
    "paren_a": ("NA6", "A6", "a ::= (a)"),
    "div": ("NA+div", "A+div", "a ::= a1 div a2   [розширення]"),
    "mod": ("NA+mod", "A+mod", "a ::= a1 mod a2   [розширення]"),
    "eq": ("NB1", "B1", "b ::= a1 = a2"),
    "gt": ("NB2", "B2", "b ::= a1 > a2"),
    "or_": ("NB3", "B3", "b ::= b1 ∨ b2"),
    "not_": ("NB4", "B4", "b ::= ¬ b"),
    "paren_b": ("NB5", "B5", "b ::= (b)"),
    "ge": ("NB+ge", "B+ge", "b ::= a1 >= a2   [розширення]"),
    "lt": ("NB+lt", "B+lt", "b ::= a1 < a2   [розширення]"),
    "le": ("NB+le", "B+le", "b ::= a1 <= a2   [розширення]"),
    "ne": ("NB+ne", "B+ne", "b ::= a1 != a2   [розширення]"),
    "and_": ("NB+and", "B+and", "b ::= b1 ∧ b2   [розширення]"),
    "true_": ("NB+true", "B+true", "b ::= true   [розширення]"),
    "false_": ("NB+false", "B+false", "b ::= false   [розширення]"),
    "variable": ("NV", "NV", "x ::= ... | M | N | ..."),
    "number": ("NN", "NN", "n ::= ... | -1 | 0 | 1 | ..."),
}

_CATEGORY = {
    "program": "Prog",
    "assign": "Stm",
    "seq": "Stm",
    "if_stmt": "Stm",
    "while_stmt": "Stm",
    "block": "Stm",
    "skip": "Stm",
    "variable": "Var",
    "number": "Num",
}
_AEXP = {"num", "neg_num", "var", "add", "sub", "mul", "div", "mod", "paren_a"}


@dataclass
class DNode:
    """Node of a derivation tree; terminals have ``kind == "terminal"`` and ``text``."""

    id: int
    kind: Literal["nonterminal", "terminal"]
    label: str
    span: SourceSpan
    rule: str | None = None
    rule_text: str | None = None
    category: str | None = None
    text: str | None = None
    leaf_index: int | None = None  # 1-based order of a terminal in the left-to-right walk
    children: list[DNode] = field(default_factory=list)

    def walk(self) -> Iterator[DNode]:
        yield self
        for c in self.children:
            yield from c.walk()

    def leaves(self) -> list[DNode]:
        return [n for n in self.walk() if n.kind == "terminal"]

    def depth(self) -> int:
        return 1 + max((c.depth() for c in self.children), default=0)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "span": self.span.to_dict(),
        }
        if self.kind == "nonterminal":
            out["rule"] = self.rule
            out["rule_text"] = self.rule_text
            out["category"] = self.category
            out["children"] = [c.to_dict() for c in self.children]
        else:
            out["text"] = self.text
            out["leaf_index"] = self.leaf_index
        return out


@dataclass
class DerivationTree:
    root: DNode
    source: str
    notation: Notation

    def frontier(self) -> list[str]:
        """Terminals read left to right (the yield of the tree)."""
        return [leaf.text or "" for leaf in self.root.leaves()]

    def yield_matches_source(self) -> bool:
        """Syntactic-correctness check.

        Reading the leaves left to right must give back the program text
        (up to whitespace and comments).
        """
        from sipl.parser import _lark

        tokens = [str(t) for t in _lark().lex(self.source)]
        return "".join(self.frontier()) == "".join(tokens)

    def node_at(self, offset: int) -> DNode | None:
        """Deepest node whose span contains ``offset``."""
        best: DNode | None = None
        for n in self.root.walk():
            if n.span.contains(offset) and (
                best is None or (n.span.end - n.span.start) <= (best.span.end - best.span.start)
            ):
                best = n
        return best

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "sipl.derivation/1",
            "notation": self.notation,
            "source": self.source,
            "frontier": self.frontier(),
            "yield_matches_source": self.yield_matches_source(),
            "root": self.root.to_dict(),
        }


def derivation_tree(source: str, *, notation: Notation = "bnf") -> DerivationTree:
    """Parse ``source`` and build its derivation tree by the course BNF."""
    result = parse_full(source)
    builder = _Builder(source, notation)
    root = builder.build(result.tree)
    for i, leaf in enumerate(root.leaves(), start=1):
        leaf.leaf_index = i
    return DerivationTree(root, source, notation)


class _Builder:
    def __init__(self, source: str, notation: Notation) -> None:
        self.source = source
        self.notation: Notation = notation
        self.ids = count()

    # --- node factories ---

    def nt(self, rule_key: str, category: str, children: list[DNode]) -> DNode:
        bnf_name, math_name, text = RULES[rule_key]
        span = children[0].span
        for c in children[1:]:
            span = span.merge(c.span)
        return DNode(
            id=next(self.ids),
            kind="nonterminal",
            label=LABELS[self.notation][category],
            span=span,
            rule=bnf_name if self.notation == "bnf" else math_name,
            rule_text=text,
            category=category,
            children=children,
        )

    def term(self, tok: Token, text: str | None = None) -> DNode:
        start = tok.start_pos or 0
        end = tok.end_pos if tok.end_pos is not None else start + len(tok)
        return DNode(
            id=next(self.ids),
            kind="terminal",
            label=text if text is not None else str(tok),
            text=text if text is not None else str(tok),
            span=span_from_offsets(self.source, start, end),
        )

    # --- conversion ---

    def build(self, node: Tree[Token] | Token) -> DNode:
        if isinstance(node, Token):  # pragma: no cover - tokens are handled by parents
            return self.term(node)
        kind = str(node.data)
        ch = node.children
        if kind == "program":
            return self.nt(
                "program",
                "Prog",
                [self.term(_tok(ch[0])), self.build(ch[1]), self.term(_tok(ch[2]))],
            )
        if kind == "stmts":
            return self.stmts(node)
        if kind == "assign":
            var_tok = ch[0]
            assert isinstance(var_tok, Token)
            var = self.nt("variable", "Var", [self.term(var_tok)])
            return self.nt("assign", "Stm", [var, self.term(_tok(ch[1])), self.build(ch[2])])
        if kind == "block":
            return self.nt(
                "block", "Stm", [self.term(_tok(ch[0])), self.build(ch[1]), self.term(_tok(ch[2]))]
            )
        if kind == "skip":
            return self.nt("skip", "Stm", [self.term(_tok(ch[0]))])
        if kind in ("if_stmt", "while_stmt"):
            return self.nt(kind, "Stm", [self.child(c) for c in ch])
        if kind == "num":
            number = self.nt("number", "Num", [self.term(_tok(ch[0]))])
            return self.nt("num", "Aexp", [number])
        if kind == "neg_num":
            minus, digits = _tok(ch[0]), _tok(ch[1])
            merged = Token(
                "NUMBER", f"-{digits}", start_pos=minus.start_pos, end_pos=digits.end_pos
            )
            number = self.nt("number", "Num", [self.term(merged)])
            return self.nt("num", "Aexp", [number])
        if kind == "var":
            variable = self.nt("variable", "Var", [self.term(_tok(ch[0]))])
            return self.nt("var", "Aexp", [variable])
        category = "Aexp" if kind in _AEXP else "Bexp"
        return self.nt(kind, category, [self.child(c) for c in ch])

    def child(self, c: Tree[Token] | Token) -> DNode:
        return self.term(c) if isinstance(c, Token) else self.build(c)

    def stmts(self, node: Tree[Token]) -> DNode:
        items = [c for c in node.children if isinstance(c, Tree)]
        semis = [c for c in node.children if isinstance(c, Token)]
        acc = self.build(items[0])
        for semi, item in zip(semis, items[1:], strict=True):
            acc = self.nt("seq", "Stm", [acc, self.term(semi), self.build(item)])
        return acc


def _tok(x: Tree[Token] | Token) -> Token:
    assert isinstance(x, Token)
    return x
