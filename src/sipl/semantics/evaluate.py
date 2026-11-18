"""Application of a semantic term to a state (practicum, practical work 2).

The evaluator follows the formulas of the program algebra literally and records which
formula was applied at every step:

* ``AF_S``   – ``Sn(f, g1..gn)(st) = f(g1(st), ..., gn(st))``
* ``AF_AS``  – ``AS^x(fa)(st) = st ∇ [x ↦ fa(st)]``
* ``AF_SEQ`` – ``(f1 · f2)(st) = f2(f1(st))``
* ``AF_IF``  – ``IF(fb, f1, f2)(st) = f1(st) if fb(st) = true, f2(st) if false``
* ``AF_WH``  – ``WH(fb, fs)(st) = st_n`` where ``st_{i+1} = fs(st_i)``, fb true before, false at ``st_n``
* ``AF_DNM`` – ``x⇒(st) = st(x)``
* ``AF_ID``  – ``id(st) = st``

Partiality is explicit: the result is either a state, *undefined* (unknown variable,
division by zero) or *limit* (the iteration budget ran out – a possible infinite loop;
non-termination itself cannot be decided in general).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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
from sipl.span import SourceSpan
from sipl.state import ArithmeticUndefined, State, apply_basic, format_state, overwrite

Status = Literal["defined", "undefined", "limit"]


@dataclass(frozen=True)
class TraceStep:
    rule: str
    depth: int
    text: str
    origin: SourceSpan | None = None
    state_in: str | None = None
    state_out: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "depth": self.depth,
            "text": self.text,
            "origin": self.origin.to_dict() if self.origin else None,
            "state_in": self.state_in,
            "state_out": self.state_out,
        }


@dataclass
class EvalResult:
    status: Status
    state: State | None
    initial: State
    reason: str | None = None
    reason_origin: SourceSpan | None = None
    iterations: int = 0
    trace: list[TraceStep] = field(default_factory=list)
    states: dict[str, State] = field(default_factory=dict)
    trace_truncated: bool = False

    @property
    def defined(self) -> bool:
        return self.status == "defined"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "sipl.eval/1",
            "status": self.status,
            "initial": self.initial,
            "result": self.state,
            "reason": self.reason,
            "reason_origin": self.reason_origin.to_dict() if self.reason_origin else None,
            "iterations": self.iterations,
            "states": self.states,
            "trace": [s.to_dict() for s in self.trace],
            "trace_truncated": self.trace_truncated,
        }

    def explain(self, *, indent: str = "  ") -> str:
        lines = [f"{indent * s.depth}[{s.rule}] {s.text}" for s in self.trace]
        if self.trace_truncated:
            lines.append("... (трасу обрізано)")
        lines.append("")
        lines.append(self.summary())
        return "\n".join(lines) + "\n"

    def summary(self) -> str:
        if self.status == "defined":
            assert self.state is not None
            return f"Результат: {format_state(self.state)}"
        if self.status == "undefined":
            return f"Результат: невизначено – {self.reason}"
        return f"Результат: невідомо – {self.reason}"


class _Undefined(Exception):
    def __init__(self, reason: str, origin: SourceSpan | None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.origin = origin


class _Limit(Exception):
    pass


class _Evaluator:
    def __init__(self, max_iterations: int, trace: bool, max_trace: int) -> None:
        self.max_iterations = max_iterations
        self.tracing = trace
        self.max_trace = max_trace
        self.iterations = 0
        self.trace: list[TraceStep] = []
        self.truncated = False
        self.states: dict[str, State] = {}
        self.counter = 0

    # --- bookkeeping ---

    def name(self, st: State) -> str:
        self.counter += 1
        n = f"st{self.counter}"
        self.states[n] = st
        return n

    def log(
        self, rule: str, depth: int, text: str, t: Term, st_in: str | None, st_out: str | None
    ) -> None:
        if not self.tracing:
            return
        if len(self.trace) >= self.max_trace:
            self.truncated = True
            return
        self.trace.append(TraceStep(rule, depth, text, t.origin, st_in, st_out))

    # --- TFA / TFB ---

    def value(self, t: Term, st: State) -> int | bool:
        t = _strip(t)
        if isinstance(t, Const):
            return t.value
        if isinstance(t, Denaming):
            if t.var not in st:
                raise _Undefined(
                    f"змінна {t.var} не має значення у стані (x⇒ невизначена)", t.origin
                )
            return st[t.var]
        if isinstance(t, Sup):
            args = [self.value(a, st) for a in t.args]
            try:
                return apply_basic(t.fn, args)
            except ArithmeticUndefined as exc:
                raise _Undefined(
                    f"{t.fn}({', '.join(map(_v, args))}) невизначено: {exc}", t.origin
                ) from None
        raise TypeError(f"{render(t)} не є функцією на станах")  # pragma: no cover

    def shown(self, t: Term, st: State) -> str:
        """``mult(R⇒(st), X⇒(st))`` with denamings replaced by their values: ``mult(1, 5)``."""
        t = _strip(t)
        if isinstance(t, Const):
            return _v(t.value)
        if isinstance(t, Denaming):
            return _v(st[t.var]) if t.var in st else f"{t.var}⇒(⊥)"
        if isinstance(t, Sup):
            return f"{t.fn}({', '.join(self.shown(a, st) for a in t.args)})"
        return render(t)  # pragma: no cover

    def calc(self, t: Term, st: State, name: str) -> tuple[int | bool, str]:
        """Value plus the practicum-style chain ``f(st) = mult(1, 5) = 5``."""
        v = self.value(t, st)
        shown = self.shown(t, st)
        chain = f"{render(t)}({name})"
        if not isinstance(_strip(t), Const):
            chain += f" = {shown}" if shown != _v(v) else ""
            chain += f" = {_v(v)}"
        else:
            chain += f" = {_v(v)}"
        return v, chain

    # --- TFS ---

    def run(self, t: Term, st: State, name: str, depth: int) -> tuple[State, str]:
        t0 = t
        t = _strip(t)
        if isinstance(t, IdT):
            self.log("AF_ID", depth, f"id({name}) = {name}", t0, name, name)
            return st, name
        if isinstance(t, AssignT):
            v = self.value(t.value, st)
            shown = self.shown(t.value, st)
            new = overwrite(st, t.var, int(v))
            out = self.name(new)
            text = f"{render(t)}({name}) = {name}∇[{t.var} ↦ {render(t.value)}({name})]"
            if shown != _v(v):
                text += f" = {name}∇[{t.var} ↦ {shown}]"
            text += f" = {name}∇[{t.var} ↦ {_v(v)}] = {format_state(new)} = {out}"
            self.log("AF_AS", depth, text, t, name, out)
            return new, out
        if isinstance(t, SeqT):
            items = list(t.items)
            self.log(
                "AF_SEQ",
                depth,
                f"({render(t)})({name}) = {_seq_apply(items, name)}",
                t,
                name,
                None,
            )
            cur_st, cur_name = st, name
            for item in items:
                cur_st, cur_name = self.run(item, cur_st, cur_name, depth + 1)
            return cur_st, cur_name
        if isinstance(t, IfT):
            b, chain = self.calc(t.cond, st, name)
            branch = t.then if b else t.orelse
            self.log(
                "AF_IF",
                depth,
                f"{chain} → обираємо {'першу' if b else 'другу'} гілку: {_applied(branch, name)}",
                t,
                name,
                None,
            )
            return self.run(branch, st, name, depth + 1)
        if isinstance(t, WhileT):
            return self.loop(t, st, name, depth)
        if isinstance(t, Hole):  # pragma: no cover - holes never reach the evaluator
            raise TypeError("терм містить неперекладені частини")
        raise TypeError(f"{render(t)} не є перетворювачем станів")  # pragma: no cover

    def loop(self, t: WhileT, st: State, name: str, depth: int) -> tuple[State, str]:
        start_name = name
        k = 0
        while True:
            b, chain = self.calc(t.cond, st, name)
            if not b:
                self.log(
                    "AF_WH",
                    depth,
                    f"{chain} → цикл завершено після {k} ітерацій: "
                    f"WH(...)({start_name}) = {name} = {format_state(st)}",
                    t,
                    start_name,
                    name,
                )
                return st, name
            if self.iterations >= self.max_iterations:
                raise _Limit()
            self.iterations += 1
            k += 1
            self.log(
                "AF_WH", depth, f"{chain} → ітерація {k}: {_applied(t.body, name)}", t, name, None
            )
            st, name = self.run(t.body, st, name, depth + 1)


def _seq_apply(items: list[Term], name: str) -> str:
    out = name
    for item in items:
        out = _applied(item, out)
    return out


def _applied(t: Term, arg: str) -> str:
    """``f(st)``, with brackets around a composition: ``(f · g)(st)``."""
    text = render(t)
    return f"({text})({arg})" if isinstance(_strip(t), SeqT) else f"{text}({arg})"


def _strip(t: Term) -> Term:
    while isinstance(t, ParenT):
        t = t.inner
    return t


def _v(x: int | bool) -> str:
    if isinstance(x, bool):
        return "true" if x else "false"
    return str(x)


def apply_term(
    term: Term,
    state: State,
    *,
    max_iterations: int = 10_000,
    trace: bool = True,
    max_trace: int = 20_000,
) -> EvalResult:
    """Apply a TFS term to ``state``; never raises on undefinedness."""
    ev = _Evaluator(max_iterations, trace, max_trace)
    ev.states["st"] = dict(state)
    try:
        final, _ = ev.run(term, dict(state), "st", 0)
    except _Undefined as exc:
        return EvalResult(
            "undefined",
            None,
            dict(state),
            exc.reason,
            exc.origin,
            ev.iterations,
            ev.trace,
            ev.states,
            ev.truncated,
        )
    except _Limit:
        return EvalResult(
            "limit",
            None,
            dict(state),
            f"перевищено ліміт {max_iterations} ітерацій циклів (можливо, цикл не завершується)",
            None,
            ev.iterations,
            ev.trace,
            ev.states,
            ev.truncated,
        )
    return EvalResult(
        "defined", final, dict(state), None, None, ev.iterations, ev.trace, ev.states, ev.truncated
    )


def value_of(term: Term, state: State) -> int | bool:
    """Value of a TFA/TFB term on a state (raises ``ValueError`` if undefined)."""
    try:
        return _Evaluator(0, False, 0).value(term, state)
    except _Undefined as exc:
        raise ValueError(exc.reason) from None
