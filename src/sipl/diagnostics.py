"""Diagnostics: user-facing errors and warnings bound to a :class:`SourceSpan`."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sipl.span import SourceSpan


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Diagnostic:
    """One message about the source text.

    ``code`` is stable and documented in docs/cli.md (e.g. ``E101``), so tools can
    match on it instead of on the (Ukrainian) message text.
    """

    code: str
    message: str
    span: SourceSpan | None = None
    severity: Severity = Severity.ERROR
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "hint": self.hint,
            "span": self.span.to_dict() if self.span else None,
        }

    def format(self, filename: str = "<input>", source: str | None = None) -> str:
        where = f"{filename}:{self.span.line}:{self.span.column}" if self.span else filename
        text = f"{where}: {self.severity.value} {self.code}: {self.message}"
        if self.hint:
            text += f"\n  підказка: {self.hint}"
        if source is not None and self.span is not None:
            text += "\n" + caret_excerpt(source, self.span)
        return text


def caret_excerpt(source: str, span: SourceSpan) -> str:
    """Render the offending line with ``^^^`` under the span (first line only)."""
    lines = source.splitlines() or [""]
    idx = min(span.line, len(lines)) - 1
    line = lines[idx]
    width = max(1, (span.end_column - span.column) if span.end_line == span.line else 1)
    gutter = f"{span.line:>4} | "
    return f"{gutter}{line}\n{' ' * len(gutter)}{' ' * (span.column - 1)}{'^' * width}"


@dataclass
class SiplError(Exception):
    """Raised when an operation cannot continue; carries one or more diagnostics."""

    diagnostics: list[Diagnostic] = field(default_factory=list)

    def __str__(self) -> str:
        return "; ".join(d.message for d in self.diagnostics) or "SIPL error"


class SiplSyntaxError(SiplError):
    """The text is not a sentence of the (selected dialect of the) SIPL grammar."""
