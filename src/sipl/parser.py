"""SIPL parser: text -> typed AST (:mod:`sipl.ast`) with source spans.

The concrete grammar lives in ``grammar/sipl.lark``.  Lark is an implementation
detail: callers get our own AST nodes and :class:`Diagnostic` objects, never raw
Lark trees or exceptions (the concrete tree is exposed only through
:class:`ParseResult` for the derivation-tree visualiser).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Literal

from lark import Lark, Token, Tree
from lark.exceptions import UnexpectedCharacters, UnexpectedInput, UnexpectedToken

from sipl import ast as A
from sipl.diagnostics import Diagnostic, Severity, SiplSyntaxError
from sipl.span import SourceSpan, span_from_offsets

Dialect = Literal["core", "ext"]

#: human-readable names of grammar terminals for error messages
TERMINAL_NAMES: dict[str, str] = {
    "BEGIN": "'begin'",
    "END": "'end'",
    "IF": "'if'",
    "THEN": "'then'",
    "ELSE": "'else'",
    "WHILE": "'while'",
    "DO": "'do'",
    "SKIP": "'skip'",
    "DIV": "'div'",
    "MOD": "'mod'",
    "TRUE": "'true'",
    "FALSE": "'false'",
    "OR": "'∨'",
    "AND": "'∧'",
    "NOT": "'¬'",
    "IMPLIES": "'→'",
    "ASSIGN": "':='",
    "SEMI": "';'",
    "COMMA": "','",
    "LPAR": "'('",
    "RPAR": "')'",
    "PLUS": "'+'",
    "MINUS": "'-'",
    "STAR": "'*'",
    "GE": "'>='",
    "LE": "'<='",
    "NE": "'!='",
    "EQ": "'='",
    "GT": "'>'",
    "LT": "'<'",
    "VAR": "змінна",
    "NUMBER": "число",
    "$END": "кінець тексту",
}

# terminals that are never useful to suggest in a program context
_SPEC_ONLY = {"IMPLIES", "COMMA"}


@lru_cache(maxsize=1)
def grammar_text() -> str:
    return resources.files("sipl.grammar").joinpath("sipl.lark").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _lark() -> Lark:
    return Lark(
        grammar_text(),
        parser="earley",
        lexer="basic",
        start=["start", "formula", "expr"],
        propagate_positions=True,
        keep_all_tokens=True,
        ambiguity="resolve",
    )


@dataclass
class ParseResult:
    program: A.Program
    tree: Tree[Token]
    source: str
    warnings: list[Diagnostic] = field(default_factory=list)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def parse(source: str, *, dialect: Dialect = "ext") -> A.Program:
    """Parse a SIPL program; raise :class:`SiplSyntaxError` with diagnostics."""
    return parse_full(source, dialect=dialect).program


def parse_full(source: str, *, dialect: Dialect = "ext") -> ParseResult:
    tree = _run(source, "start")
    program_tree = tree.children[0]
    assert isinstance(program_tree, Tree)
    program = _Builder(source).program(program_tree)
    errors = check_dialect(program, dialect)
    if any(d.severity is Severity.ERROR for d in errors):
        raise SiplSyntaxError(errors)
    return ParseResult(program, program_tree, source, errors)


def parse_formula(source: str) -> A.Bexp:
    """Parse a specification formula (condition language + ∧, →, function calls)."""
    tree = _run(source, "formula")
    return _Builder(source).bexp(_only_child(tree))


def parse_expr(source: str) -> A.Aexp:
    """Parse an arithmetic expression (used for loop variants)."""
    tree = _run(source, "expr")
    return _Builder(source).aexp(_only_child(tree))


def check_dialect(program: A.Node, dialect: Dialect) -> list[Diagnostic]:
    """Report constructs outside the course BNF (``core``) or outside programs."""
    out: list[Diagnostic] = []
    for node in A.walk(program):
        ext = _extension_name(node)
        if isinstance(node, A.Call) or (isinstance(node, A.BoolOp) and node.op == "->"):
            what = f"виклик функції {node.name}(...)" if isinstance(node, A.Call) else "імплікація"
            out.append(
                Diagnostic(
                    "E202",
                    f"{what} дозволена лише у формулах специфікації, а не в програмі",
                    node.span,
                )
            )
        elif ext and dialect == "core":
            out.append(
                Diagnostic(
                    "E201",
                    f"{ext} не входить у БНФ курсу (це розширення SIPL-ext)",
                    node.span,
                    hint="запустіть без --strict або перепишіть через =, >, ∨, ¬, +, -, *",
                )
            )
    return out


def _extension_name(node: A.Node) -> str | None:
    if isinstance(node, A.BinOp) and node.op in ("div", "mod"):
        return f"операція '{node.op}'"
    if isinstance(node, A.Compare) and node.op not in ("=", ">"):
        return f"порівняння '{node.op}'"
    if isinstance(node, A.BoolOp) and node.op == "and":
        return "кон'юнкція '∧'"
    if isinstance(node, A.BoolConst):
        return "логічна константа"
    return None


# ---------------------------------------------------------------------------
# Lark invocation and error translation
# ---------------------------------------------------------------------------


def _run(source: str, start: str) -> Tree[Token]:
    try:
        return _lark().parse(source, start=start)
    except UnexpectedInput as exc:
        raise SiplSyntaxError([_diagnostic(source, exc, start)]) from None


def _only_child(tree: Tree[Token]) -> Tree[Token] | Token:
    return tree.children[0]


def _expected_names(expected: set[str] | frozenset[str] | list[str], start: str) -> list[str]:
    names = []
    for term in sorted(expected):
        if start == "start" and term in _SPEC_ONLY:
            continue
        names.append(TERMINAL_NAMES.get(term, term))
    return sorted(set(names))


def _diagnostic(source: str, exc: UnexpectedInput, start: str) -> Diagnostic:
    if isinstance(exc, UnexpectedCharacters):
        pos = exc.pos_in_stream or 0
        char = source[pos] if pos < len(source) else ""
        return Diagnostic(
            "E001",
            f"недопустимий символ '{char}'",
            span_from_offsets(source, pos, pos + 1),
            hint=_hint_for_char(char),
        )
    if isinstance(exc, UnexpectedToken) and exc.token.type != "$END":
        tok: Token = exc.token
        start_pos = tok.start_pos or 0
        end_pos = tok.end_pos if tok.end_pos is not None else start_pos + len(tok)
        expected = _expected_names(exc.expected, start)
        found = TERMINAL_NAMES.get(tok.type, tok.type)
        if tok.type in ("VAR", "NUMBER"):
            found = f"{found} '{tok}'"
        if not expected or expected == [TERMINAL_NAMES["$END"]]:
            return Diagnostic(
                "E004",
                f"зайвий текст після завершення програми: {found}",
                span_from_offsets(source, start_pos, end_pos),
                hint="програма – це один блок begin ... end; перевірте парність begin/end",
            )
        return Diagnostic(
            "E002",
            f"неочікувано: {found}; очікувалось: {', '.join(expected)}",
            span_from_offsets(source, start_pos, end_pos),
            hint=_hint_for_token(tok.type, set(exc.expected)),
        )
    # end of input reached too early
    expected_set: set[str] = set(getattr(exc, "expected", None) or [])
    expected = _expected_names(expected_set, start)
    end = len(source.rstrip())
    return Diagnostic(
        "E003",
        "несподіваний кінець тексту"
        + (f"; очікувалось: {', '.join(expected)}" if expected else ""),
        span_from_offsets(source, max(0, end - 1), end) if end else span_from_offsets(source, 0, 0),
        hint="перевірте, чи кожному 'begin' відповідає 'end'" if "END" in expected_set else None,
    )


def _hint_for_char(char: str) -> str | None:
    if char == ":":
        return "присвоювання записується як ':='"
    if char in "{}[]":
        return "для групування операторів використовуйте begin ... end"
    if char == "!":
        return "заперечення записується як '¬' або 'not'"
    return None


def _hint_for_token(found: str, expected: set[str]) -> str | None:
    if found == "END" and "VAR" in expected:
        return "зайва ';' перед 'end': у SIPL ';' розділяє оператори, а не завершує їх"
    if "SEMI" in expected and found in ("VAR", "IF", "WHILE", "BEGIN", "SKIP"):
        return "можливо, пропущено ';' між операторами"
    if "ELSE" in expected:
        return "у SIPL умовний оператор завжди має гілку else (за потреби: else skip)"
    if found == "EQ" and "ASSIGN" in expected:
        return "присвоювання записується як ':=', а '=' – це порівняння"
    if found == "ASSIGN":
        return "у позиції умови потрібне порівняння '=', а не присвоювання ':='"
    if found == "SEMI" and "ELSE" not in expected and "END" in expected:
        return None
    return None


# ---------------------------------------------------------------------------
# concrete tree -> AST
# ---------------------------------------------------------------------------

_BIN = {"add": "+", "sub": "-", "mul": "*", "div": "div", "mod": "mod"}
_CMP = {"eq": "=", "gt": ">", "ge": ">=", "lt": "<", "le": "<=", "ne": "!="}


class _Builder:
    def __init__(self, source: str) -> None:
        self.source = source

    def span(self, node: Tree[Token] | Token) -> SourceSpan:
        if isinstance(node, Token):
            start = node.start_pos or 0
            end = node.end_pos if node.end_pos is not None else start + len(node)
        else:
            start, end = node.meta.start_pos, node.meta.end_pos
        return span_from_offsets(self.source, start, end)

    @staticmethod
    def subtrees(tree: Tree[Token]) -> list[Tree[Token] | Token]:
        """Children that are not punctuation/keyword tokens."""
        return [c for c in tree.children if isinstance(c, Tree) or c.type in ("VAR", "NUMBER")]

    # --- program / statements ---

    def program(self, tree: Tree[Token]) -> A.Program:
        (stmts,) = self.subtrees(tree)
        assert isinstance(stmts, Tree)
        return A.Program(self.stmts(stmts), span=self.span(tree))

    def stmts(self, tree: Tree[Token]) -> A.Stm:
        items = [self.stm(c) for c in self.subtrees(tree)]
        if len(items) == 1:
            return items[0]
        return A.Seq(tuple(items), span=self.span(tree))

    def stm(self, tree: Tree[Token] | Token) -> A.Stm:
        assert isinstance(tree, Tree)
        kind = tree.data
        parts = self.subtrees(tree)
        sp = self.span(tree)
        if kind == "assign":
            var_tok, value = parts
            assert isinstance(var_tok, Token)
            return A.Assign(A.Var(str(var_tok), span=self.span(var_tok)), self.aexp(value), span=sp)
        if kind == "if_stmt":
            cond, then, orelse = parts
            return A.If(self.bexp(cond), self.stm(then), self.stm(orelse), span=sp)
        if kind == "while_stmt":
            cond, body = parts
            return A.While(self.bexp(cond), self.stm(body), span=sp)
        if kind == "block":
            (body,) = parts
            assert isinstance(body, Tree)
            return A.Block(self.stmts(body), span=sp)
        if kind == "skip":
            return A.Skip(span=sp)
        raise AssertionError(f"unexpected statement node {kind}")  # pragma: no cover

    # --- expressions ---

    def aexp(self, node: Tree[Token] | Token) -> A.Aexp:
        if isinstance(node, Token):  # pragma: no cover - grammar always wraps tokens
            raise AssertionError(f"bare token {node!r}")
        kind = node.data
        parts = self.subtrees(node)
        sp = self.span(node)
        if kind == "num":
            return A.Num(int(str(parts[0])), span=sp)
        if kind == "neg_num":
            return A.Num(-int(str(parts[0])), span=sp)
        if kind == "var":
            return A.Var(str(parts[0]), span=sp)
        if kind == "paren_a":
            return self.aexp(parts[0])
        if kind == "call":
            name, args = parts
            assert isinstance(args, Tree)
            return A.Call(str(name), tuple(self.aexp(a) for a in self.subtrees(args)), span=sp)
        if kind == "expr":
            return self.aexp(parts[0])
        left, right = parts
        return A.BinOp(_BIN[str(kind)], self.aexp(left), self.aexp(right), span=sp)

    def bexp(self, node: Tree[Token] | Token) -> A.Bexp:
        if isinstance(node, Token):
            if node.type in ("TRUE", "FALSE"):  # pragma: no cover - aliased in grammar
                return A.BoolConst(node.type == "TRUE", span=self.span(node))
            raise AssertionError(f"bare token {node!r}")  # pragma: no cover
        kind = str(node.data)
        sp = self.span(node)
        parts = self.subtrees(node)
        if kind in _CMP:
            left, right = parts
            return A.Compare(_CMP[kind], self.aexp(left), self.aexp(right), span=sp)
        if kind in ("or_", "and_", "implies"):
            left, right = parts
            op = {"or_": "or", "and_": "and", "implies": "->"}[kind]
            return A.BoolOp(op, self.bexp(left), self.bexp(right), span=sp)
        if kind == "not_":
            return A.Not(self.bexp(parts[0]), span=sp)
        if kind in ("true_", "false_"):
            return A.BoolConst(kind == "true_", span=sp)
        if kind in ("paren_b", "formula"):
            return self.bexp(parts[0])
        raise AssertionError(f"unexpected condition node {kind}")  # pragma: no cover
