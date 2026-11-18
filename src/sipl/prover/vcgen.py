"""Verification-condition generation by weakest preconditions.

For an annotated program the method reduces correctness to a finite list of
first-order conditions.  Each loop condition corresponds to a part of the inductive
proof from the course (induction on the number of iterations ``NumItWH``):

=============  =================================================================
``init``       pre ⇒ wp(program, post): in particular, before the first iteration
               the invariant holds – the *base* of the induction (k = 0)
``preserve``   I ∧ b ⇒ wp(body, I) – the *step* k → k+1
``exit``       I ∧ ¬b ⇒ (what the rest of the program needs) – ``fb(st_k) = false``
``bound``      I ∧ b ⇒ V ≥ 0                      (total correctness)
``decrease``   I ∧ b ∧ V = v₀ ⇒ wp(body, V < v₀)  (total correctness)
=============  =================================================================

``bound`` and ``decrease`` give a strictly decreasing sequence of naturals, which
cannot be infinite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sipl import ast as A
from sipl.diagnostics import Diagnostic, SiplError
from sipl.prover.formula import TRUE, conj, definedness, implies, neg, subst
from sipl.prover.spec import LoopAnnotation, Spec

VCKind = Literal["init", "preserve", "exit", "defined", "bound", "decrease"]

VC_TITLES: dict[str, str] = {
    "init": "Початкова умова (база індукції, k = 0)",
    "preserve": "Збереження інваріанта (крок індукції k → k+1)",
    "exit": "Вихід із циклу (fb(st_k) = false)",
    "defined": "Визначеність умови циклу",
    "bound": "Обмеженість варіанта (V ≥ 0, поки цикл працює)",
    "decrease": "Спадання варіанта (кожна ітерація зменшує V)",
}


@dataclass
class VC:
    kind: VCKind
    formula: A.Bexp
    loop: int | None = None  # 1-based loop number
    origin: A.Node | None = None

    @property
    def title(self) -> str:
        t = VC_TITLES[self.kind]
        return f"{t}, цикл {self.loop}" if self.loop else t

    @property
    def text(self) -> str:
        return A.unparse_bexp(self.formula)


@dataclass
class WpStep:
    rule: str
    stm: str
    post: str
    result: str


@dataclass
class VCResult:
    vcs: list[VC]
    wp_steps: list[WpStep] = field(default_factory=list)
    loops: list[tuple[A.While, LoopAnnotation]] = field(default_factory=list)


def match_loops(program: A.Program, spec: Spec) -> list[tuple[A.While, LoopAnnotation]]:
    """Attach annotations to loops: by ``line`` when given, otherwise in source order."""
    loops = A.loops(program)
    by_line = [a for a in spec.loops if a.line is not None]
    in_order = [a for a in spec.loops if a.line is None]
    pairs: list[tuple[A.While, LoopAnnotation]] = []
    missing: list[Diagnostic] = []
    for w in loops:
        line = w.span.line if w.span else None
        ann = next((a for a in by_line if a.line == line), None)
        if ann is None and in_order:
            ann = in_order.pop(0)
        if ann is None:
            missing.append(
                Diagnostic(
                    "E401",
                    f"для циклу '{A.unparse_stm(w)[:40]}...' не задано інваріант",
                    w.span,
                    hint="додайте таблицю [[loop]] з полем invariant у файл специфікації",
                )
            )
            continue
        pairs.append((w, ann))
    if missing:
        raise SiplError(missing)
    if in_order or any(a not in [p[1] for p in pairs] for a in by_line):
        raise SiplError(
            [Diagnostic("E406", "у специфікації більше анотацій [[loop]], ніж циклів у програмі")]
        )
    return pairs


def generate(program: A.Program, spec: Spec) -> VCResult:
    pairs = match_loops(program, spec)
    numbering = {id(w): i for i, (w, _) in enumerate(pairs, start=1)}
    annotations = {id(w): a for w, a in pairs}
    used = set(A.variables(program)) | set(A.variables(spec.pre)) | set(A.variables(spec.post))
    out = VCResult([], [], pairs)

    def fresh(base: str) -> str:
        i = 0
        while f"{base}{i}" in used:
            i += 1
        used.add(f"{base}{i}")
        return f"{base}{i}"

    def wp(s: A.Stm, q: A.Bexp) -> A.Bexp:
        if isinstance(s, A.Skip):
            res = q
            rule = "wp(skip, Q) = Q"
        elif isinstance(s, A.Assign):
            res = conj(definedness(s.value), subst(q, s.target.name, s.value))
            rule = "wp(x := a, Q) = Q[a/x]"
        elif isinstance(s, A.Seq):
            res = q
            for item in reversed(s.items):
                res = wp(item, res)
            return res
        elif isinstance(s, A.Block):
            return wp(s.body, q)
        elif isinstance(s, A.If):
            res = conj(
                definedness(s.cond),
                implies(s.cond, wp(s.then, q)),
                implies(neg(s.cond), wp(s.orelse, q)),
            )
            rule = "wp(if b then S1 else S2, Q) = (b → wp(S1, Q)) ∧ (¬b → wp(S2, Q))"
        else:
            assert isinstance(s, A.While)
            res = loop(s, q)
            rule = "wp(while b do S, Q) = I   (+ умови перевірки циклу; для вкладеного циклу – вбудовані)"
        out.wp_steps.append(WpStep(rule, A.unparse_stm(s), A.unparse_bexp(q), A.unparse_bexp(res)))
        return res

    depth = 0  # how many enclosing loop bodies we are in

    def loop(w: A.While, q: A.Bexp) -> A.Bexp:
        nonlocal depth
        n = numbering[id(w)]
        ann = annotations[id(w)]
        inv, b = ann.invariant, w.cond
        if spec.mode == "total" and ann.variant is None:
            raise SiplError(
                [
                    Diagnostic(
                        "E407",
                        f"для повної коректності циклу {n} потрібен варіант (поле variant)",
                        w.span,
                    )
                ]
            )
        depth += 1
        side: list[VC] = []
        d = definedness(b)
        if d != TRUE:
            side.append(VC("defined", implies(inv, d), n, w))
        side.append(VC("preserve", implies(conj(inv, b), wp(w.body, inv)), n, w))
        side.append(VC("exit", implies(conj(inv, neg(b)), q), n, w))
        if spec.mode == "total" and ann.variant is not None:
            v = ann.variant
            side.append(VC("bound", implies(conj(inv, b), A.Compare(">=", v, A.Num(0))), n, w))
            v0 = A.Var(fresh("v"))
            side.append(
                VC(
                    "decrease",
                    implies(conj(inv, b, A.Compare("=", v, v0)), wp(w.body, A.Compare("<", v, v0))),
                    n,
                    w,
                )
            )
        depth -= 1
        if depth == 0:
            # an outermost loop: its conditions are separate VCs (base / step / exit ...)
            out.vcs.extend(side)
            return inv
        # a nested loop: its conditions must hold in the context of the enclosing body,
        # for arbitrary values of the variables the loop changes (∀ in a positive position
        # of a validity goal = fresh constants)
        renamed = conj(*(vc.formula for vc in side))
        for var in A.assigned_variables(w):
            renamed = subst(renamed, var, A.Var(fresh(f"{var}'")))
        return conj(inv, renamed)

    main = wp(program.body, spec.post)
    out.vcs.insert(0, VC("init", implies(spec.pre, main), None, program))
    return out
