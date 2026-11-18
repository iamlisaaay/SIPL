"""CLI integration tests: commands, exit codes and the JSON contract."""

from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest

from sipl import __version__
from sipl.cli import main

from .conftest import EXAMPLES, POWER


@pytest.fixture
def power_file(tmp_path):
    p = tmp_path / "power.sipl"
    p.write_text(POWER, encoding="utf-8")
    return p


@pytest.fixture
def bad_file(tmp_path):
    p = tmp_path / "bad.sipl"
    p.write_text("begin\n  X := 1;\nend\n", encoding="utf-8")
    return p


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_check_ok(capsys, power_file) -> None:
    code, out, _ = run(capsys, "check", str(power_file))
    assert code == 0 and "синтаксично правильна" in out


def test_check_json(capsys, power_file) -> None:
    code, out, _ = run(capsys, "check", str(power_file), "--json", "--strict")
    data = json.loads(out)
    assert code == 0 and data["ok"] is True and data["loops"] == 1
    assert data["variables"] == ["R", "Y", "X"]


def test_syntax_error_exit_code_and_message(capsys, bad_file) -> None:
    code, out, err = run(capsys, "check", str(bad_file))
    assert code == 1 and out == ""
    assert f"{bad_file}:3:1: error E002" in err
    assert "зайва ';'" in err


def test_syntax_error_json(capsys, bad_file) -> None:
    code, out, _ = run(capsys, "parse", str(bad_file), "--json")
    data = json.loads(out)
    assert code == 1 and data["ok"] is False
    d = data["diagnostics"][0]
    assert d["code"] == "E002" and d["span"]["line"] == 3 and d["span"]["column"] == 1


def test_strict_rejects_extension(capsys) -> None:
    code, _, err = run(capsys, "check", str(EXAMPLES / "division.sipl"), "--strict")
    assert code == 1 and "E201" in err


def test_parse(capsys, power_file) -> None:
    code, out, _ = run(capsys, "parse", str(power_file))
    assert code == 0 and out.startswith("begin\n  R := 1;")
    code, out, _ = run(capsys, "parse", str(power_file), "--json")
    data = json.loads(out)
    assert data["schema"] == "sipl.ast/1" and data["ast"]["node"] == "Program"


@pytest.mark.parametrize(
    "fmt,marker",
    [
        ("text", "<програма> [NP1]"),
        ("json", '"schema"'),
        ("dot", "digraph"),
        ("svg", "<svg"),
        ("html", "<!doctype html>"),
    ],
)
def test_tree_formats(capsys, power_file, fmt, marker) -> None:
    code, out, _ = run(capsys, "tree", str(power_file), "-f", fmt)
    assert code == 0 and marker in out


def test_tree_to_file(capsys, power_file, tmp_path) -> None:
    target = tmp_path / "t.svg"
    code, _, err = run(
        capsys, "tree", str(power_file), "-f", "svg", "-o", str(target), "--notation", "math"
    )
    assert code == 0 and target.read_text(encoding="utf-8").count("<g ") > 10
    assert "збережено" in err
    code, out, _ = run(capsys, "tree", str(power_file), "--no-spans")
    assert "@" not in out


def test_term(capsys, power_file) -> None:
    code, out, _ = run(capsys, "term", str(power_file))
    assert (
        out.strip() == "AS^R(1) · WH(S2(gr, Y⇒, 0), AS^R(S2(mult, R⇒, X⇒)) · AS^Y(S2(sub, Y⇒, 1)))"
    )
    _, out, _ = run(capsys, "term", str(power_file), "--explain")
    assert "NS_Stm_Wh" in out and "Семантичний терм" in out
    _, out, _ = run(capsys, "term", str(power_file), "--explain", "chain")
    assert out.startswith("sem_P(")
    _, out, _ = run(capsys, "term", str(power_file), "-f", "latex")
    assert r"\cdot" in out
    _, out, _ = run(capsys, "term", str(power_file), "--json")
    data = json.loads(out)
    assert data["term"]["kind"] == "seq" and data["explanation"]["steps"]
    _, out, _ = run(capsys, "term", "-", "--rules")
    assert "NS_Stm_Wh" in out


def test_eval(capsys, power_file) -> None:
    code, out, _ = run(capsys, "eval", str(power_file), "-s", "X=5, Y=2")
    assert code == 0 and out.strip() == "Результат: [X ↦ 5, Y ↦ 0, R ↦ 25]"
    _, out, _ = run(capsys, "eval", str(power_file), "-s", "X=5, Y=2", "--explain")
    assert "[AF_WH]" in out and "st = [X ↦ 5, Y ↦ 2]" in out
    _, out, _ = run(capsys, "eval", str(power_file), "-s", "X=5, Y=2", "--json")
    data = json.loads(out)
    assert data["result"]["R"] == 25 and data["ok"] is True


def test_eval_exit_codes(capsys, tmp_path) -> None:
    p = tmp_path / "loop.sipl"
    p.write_text("begin while X > 0 do X := X + 1 end", encoding="utf-8")
    code, out, _ = run(capsys, "eval", str(p), "-s", "X=1", "--max-iterations", "20")
    assert code == 4 and "ліміт" in out
    code, out, _ = run(capsys, "eval", str(p), "-s", "")
    assert code == 3 and "невизначено" in out
    code, _, err = run(capsys, "eval", str(p), "-s", "X")
    assert code == 1 and "E301" in err


def test_prove(capsys) -> None:
    code, out, _ = run(capsys, "prove", str(EXAMPLES / "power.sipl"))  # spec found next to the file
    assert code == 0 and "ДОВЕДЕНО" in out
    code, out, _ = run(capsys, "prove", str(EXAMPLES / "power_bug.sipl"), "--json")
    data = json.loads(out)
    assert code == 3 and data["verdict"] == "refuted"
    code, out, _ = run(
        capsys, "prove", str(EXAMPLES / "power.sipl"), "--no-z3", "--wp", "--mode", "partial"
    )
    assert code == 4 and "НЕ ВИРІШЕНО" in out and "wp(" in out


def test_prove_without_spec(capsys, power_file) -> None:
    code, _, err = run(capsys, "prove", str(power_file))
    assert code == 1 and "E404" in err


def test_missing_file(capsys, tmp_path) -> None:
    code, _, err = run(capsys, "check", str(tmp_path / "nope.sipl"))
    assert code == 1 and "E901" in err


def test_stdin(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("begin X := 2 end"))
    code, out, _ = run(capsys, "eval", "-", "-s", "")
    assert code == 0 and "X ↦ 2" in out


def test_usage_error_and_version(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["frobnicate"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_console_script_runs_as_module() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "sipl.cli", "term", str(EXAMPLES / "gcd.sipl")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.startswith("WH(S1(neg, S2(eq, M⇒, N⇒))")
