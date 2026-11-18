from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data"
EXAMPLES = ROOT / "examples"
GOLDEN = ROOT / "tests" / "golden"

POWER = """begin
 R := 1;
 while Y > 0 do
 begin
 R := R * X;
 Y := Y - 1
 end
end"""

GCD = "begin while ¬M=N do if M>N then M:=M-N else N:=N-M end"

DIVISION = "begin R := 0; while X >= Y do begin X := X - Y; R := R + 1 end end"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def power_src() -> str:
    return POWER
