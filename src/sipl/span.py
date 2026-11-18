"""Source positions shared by every layer (AST, derivation tree, terms, diagnostics)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, order=True)
class SourceSpan:
    """Half-open character range ``[start, end)`` plus 1-based line/column of both ends.

    ``end_line``/``end_column`` point *after* the last character, the same convention
    as LSP ranges, so a span can be fed to an editor without conversion.
    """

    start: int
    end: int
    line: int
    column: int
    end_line: int
    end_column: int

    def to_dict(self) -> dict[str, int]:
        return {
            "start": self.start,
            "end": self.end,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> SourceSpan:
        return SourceSpan(
            int(data["start"]),
            int(data["end"]),
            int(data["line"]),
            int(data["column"]),
            int(data["end_line"]),
            int(data["end_column"]),
        )

    def merge(self, other: SourceSpan) -> SourceSpan:
        first = self if self.start <= other.start else other
        last = self if self.end >= other.end else other
        return SourceSpan(
            first.start, last.end, first.line, first.column, last.end_line, last.end_column
        )

    def contains(self, offset: int) -> bool:
        return self.start <= offset < self.end

    def text(self, source: str) -> str:
        return source[self.start : self.end]

    def __str__(self) -> str:
        return f"{self.line}:{self.column}-{self.end_line}:{self.end_column}"


def position_of(source: str, offset: int) -> tuple[int, int]:
    """1-based (line, column) of a character offset."""
    line = source.count("\n", 0, offset) + 1
    last_nl = source.rfind("\n", 0, offset)
    column = offset - last_nl  # last_nl == -1 gives offset + 1
    return line, column


def span_from_offsets(source: str, start: int, end: int) -> SourceSpan:
    line, column = position_of(source, start)
    end_line, end_column = position_of(source, end)
    return SourceSpan(start, end, line, column, end_line, end_column)
