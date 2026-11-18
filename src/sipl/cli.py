"""Command-line interface: ``sipl <command> FILE [options]``.

Exit codes (stable, see docs/cli.md):

* 0 – success (parsed / checked / evaluated to a state / proved)
* 1 – invalid input: syntax error, bad state or spec, I/O error
* 2 – wrong command-line usage (argparse)
* 3 – negative result: evaluation undefined, correctness refuted or not proved
* 4 – inconclusive: iteration limit reached, proof not decided
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sipl import __version__
from sipl import ast as A
from sipl.diagnostics import Diagnostic, SiplError
from sipl.parser import Dialect, parse_full

EXIT_OK, EXIT_INPUT, EXIT_USAGE, EXIT_NEGATIVE, EXIT_INCONCLUSIVE = 0, 1, 2, 3, 4


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8-sig")


def _emit(text: str, out: str | None) -> None:
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"збережено: {out}", file=sys.stderr)
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _json(data: dict[str, Any], out: str | None = None) -> None:
    _emit(json.dumps(data, ensure_ascii=False, indent=2), out)


def _fail(args: argparse.Namespace, diags: list[Diagnostic], source: str | None) -> int:
    if getattr(args, "json", False):
        _json({"ok": False, "diagnostics": [d.to_dict() for d in diags]})
    else:
        for d in diags:
            print(d.format(args.file, source), file=sys.stderr)
    return EXIT_INPUT


def _dialect(args: argparse.Namespace) -> Dialect:
    return "core" if getattr(args, "strict", False) else "ext"


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_parse(args: argparse.Namespace, source: str) -> int:
    result = parse_full(source, dialect=_dialect(args))
    if args.json:
        _json({"schema": "sipl.ast/1", "ok": True, "ast": result.program.to_dict()}, args.output)
    else:
        _emit(A.format_program(result.program), args.output)
    return EXIT_OK


def cmd_check(args: argparse.Namespace, source: str) -> int:
    result = parse_full(source, dialect=_dialect(args))
    info: dict[str, Any] = {
        "variables": A.variables(result.program),
        "assigned": A.assigned_variables(result.program),
        "loops": len(A.loops(result.program)),
    }
    if args.json:
        _json({"schema": "sipl.check/1", "ok": True, "diagnostics": [], **info})
    else:
        dialect = "БНФ курсу" if args.strict else "SIPL з розширеннями"
        print(f"{args.file}: синтаксично правильна програма ({dialect}).")
        print(f"  змінні: {', '.join(info['variables']) or '–'}; циклів: {info['loops']}")
    return EXIT_OK


def cmd_tree(args: argparse.Namespace, source: str) -> int:
    from sipl.visualization import export
    from sipl.visualization.derivation import derivation_tree

    tree = derivation_tree(source, notation=args.notation)
    renderers: dict[str, Callable[[], str]] = {
        "text": lambda: export.to_text(tree, spans=not args.no_spans),
        "json": lambda: export.to_json(tree),
        "dot": lambda: export.to_dot(tree),
        "svg": lambda: export.to_svg(tree),
        "html": lambda: export.to_html(tree),
    }
    _emit(renderers[args.format](), args.output)
    return EXIT_OK


def cmd_term(args: argparse.Namespace, source: str) -> int:
    from sipl.semantics.build import RULE_SCHEMATA, explain
    from sipl.semantics.terms import render, to_dict

    if args.rules:
        width = max(map(len, RULE_SCHEMATA))
        _emit("\n".join(f"{k:<{width}}  {v}" for k, v in RULE_SCHEMATA.items()), None)
        return EXIT_OK
    program = parse_full(source, dialect=_dialect(args)).program
    exp = explain(program)
    if args.json:
        _json(
            {
                "schema": "sipl.term/1",
                "ok": True,
                "text": render(exp.term),
                "latex": render(exp.term, "latex"),
                "term": to_dict(exp.term),
                "explanation": exp.to_dict(),
            },
            args.output,
        )
        return EXIT_OK
    style = {"text": "unicode", "ascii": "ascii", "latex": "latex"}[args.format]
    if args.explain == "chain":
        text = exp.chain()
    elif args.explain == "steps":
        text = exp.local()
    else:
        text = render(exp.term, style)  # type: ignore[arg-type]
    _emit(text, args.output)
    return EXIT_OK


def cmd_eval(args: argparse.Namespace, source: str) -> int:
    from sipl.semantics.build import sem_P
    from sipl.semantics.evaluate import apply_term
    from sipl.semantics.terms import render
    from sipl.state import format_state, parse_state

    program = parse_full(source, dialect=_dialect(args)).program
    state = parse_state(args.state or "")
    term = sem_P(program)
    result = apply_term(
        term, state, max_iterations=args.max_iterations, trace=args.explain or args.json
    )
    if args.json:
        data = result.to_dict()
        data["ok"] = True
        data["term"] = render(term)
        _json(data, args.output)
    elif args.explain:
        head = f"Семантичний терм: {render(term)}\nst = {format_state(state)}\n\n"
        _emit(head + result.explain(), args.output)
    else:
        _emit(result.summary(), args.output)
    return {"defined": EXIT_OK, "undefined": EXIT_NEGATIVE, "limit": EXIT_INCONCLUSIVE}[
        result.status
    ]


def cmd_prove(args: argparse.Namespace, source: str) -> int:
    from sipl.prover.assistant import prove
    from sipl.prover.spec import load_spec

    program = parse_full(source, dialect=_dialect(args)).program
    spec_path = args.spec or _default_spec(args.file)
    if spec_path is None:
        raise SiplError([Diagnostic("E404", "не вказано файл специфікації (--spec FILE)")])
    spec = load_spec(spec_path)
    if args.mode:
        spec.mode = args.mode
    report = prove(program, spec, use_z3=not args.no_z3)
    if args.json:
        data = report.to_dict()
        data["ok"] = True
        _json(data, args.output)
    else:
        _emit(report.to_text(show_wp=args.wp), args.output)
    return {
        "proved": EXIT_OK,
        "refuted": EXIT_NEGATIVE,
        "not_proved": EXIT_NEGATIVE,
        "unknown": EXIT_INCONCLUSIVE,
    }[report.verdict]


def _default_spec(file: str) -> str | None:
    if file == "-":
        return None
    candidate = Path(file).with_suffix(".spec.toml")
    return str(candidate) if candidate.exists() else None


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sipl",
        description="SIPL Language Toolkit: синтаксис, дерева виводу, семантичні терми, доведення коректності.",
    )
    p.add_argument("--version", action="version", version=f"sipl-toolkit {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def common(sp: argparse.ArgumentParser, json_flag: bool = True) -> None:
        sp.add_argument("file", help="SIPL-файл ('-' – стандартний ввід)")
        sp.add_argument("--strict", action="store_true", help="лише БНФ курсу, без розширень")
        sp.add_argument("-o", "--output", help="записати результат у файл")
        if json_flag:
            sp.add_argument("--json", action="store_true", help="структурований JSON-вивід")

    sp = sub.add_parser("parse", help="розібрати програму і показати AST")
    common(sp)
    sp.set_defaults(func=cmd_parse)

    sp = sub.add_parser("check", help="перевірити синтаксичну правильність")
    common(sp)
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("tree", help="дерево синтаксичного виводу (VIS-01)")
    common(sp, json_flag=False)
    sp.add_argument(
        "-f", "--format", choices=["text", "json", "dot", "svg", "html"], default="text"
    )
    sp.add_argument(
        "--notation",
        choices=["bnf", "math"],
        default="bnf",
        help="bnf: <оператор>, NS1...; math: S, S1...",
    )
    sp.add_argument("--no-spans", action="store_true", help="не показувати позиції в text-форматі")
    sp.set_defaults(func=cmd_tree)

    sp = sub.add_parser("term", help="семантичний терм програми (SEM-01)")
    common(sp)
    sp.add_argument("-f", "--format", choices=["text", "ascii", "latex"], default="text")
    sp.add_argument(
        "--explain",
        choices=["steps", "chain"],
        nargs="?",
        const="steps",
        help="показати застосовані правила (steps) або ланцюжок рівностей (chain)",
    )
    sp.add_argument("--rules", action="store_true", help="вивести схеми правил sem_P/S/A/B")
    sp.set_defaults(func=cmd_term)

    sp = sub.add_parser("eval", help="застосувати семантичний терм до стану (SEM-02)")
    common(sp)
    sp.add_argument("-s", "--state", default="", help='початковий стан, напр. "X=5, Y=2"')
    sp.add_argument("--explain", action="store_true", help="покрокова траса формул AF_*")
    sp.add_argument("--max-iterations", type=int, default=10_000, help="ліміт ітерацій циклів")
    sp.set_defaults(func=cmd_eval)

    sp = sub.add_parser("prove", help="доведення коректності з інваріантами (SEM-04)")
    common(sp)
    sp.add_argument("--spec", help="TOML-специфікація (за замовчуванням FILE.spec.toml)")
    sp.add_argument("--mode", choices=["partial", "total"], help="перевизначити вид коректності")
    sp.add_argument("--no-z3", action="store_true", help="лише обмежений перебір, без Z3")
    sp.add_argument("--wp", action="store_true", help="показати обчислення wp")
    sp.set_defaults(func=cmd_prove)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    source: str | None = None
    try:
        if getattr(args, "rules", False):
            return int(args.func(args, ""))
        source = _read(args.file)
        return int(args.func(args, source))
    except SiplError as exc:
        return _fail(args, exc.diagnostics, source)
    except OSError as exc:
        return _fail(
            args, [Diagnostic("E901", f"не вдалося прочитати файл: {exc.strerror or exc}")], None
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
