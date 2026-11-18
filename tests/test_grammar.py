"""CORE-01: the machine-readable grammar matches the course BNF.

Positive corpus: tests/data/valid (core BNF only) and tests/data/ext (extensions).
Negative corpus: tests/data/invalid with expected error code and position.
"""

from __future__ import annotations

import json

import pytest

from sipl.diagnostics import SiplSyntaxError
from sipl.parser import grammar_text, parse

from .conftest import DATA, read

VALID = sorted((DATA / "valid").glob("*.sipl"))
EXT = sorted((DATA / "ext").glob("*.sipl"))
INVALID = sorted((DATA / "invalid").glob("*.sipl"))
EXPECTED = json.loads(read(DATA / "invalid" / "expected.json"))


def test_corpus_sizes() -> None:
    assert len(VALID) >= 10
    assert len(INVALID) >= 10


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_valid_programs_parse_with_course_bnf(path) -> None:
    parse(read(path), dialect="core")


@pytest.mark.parametrize("path", EXT, ids=lambda p: p.stem)
def test_extension_programs(path) -> None:
    parse(read(path), dialect="ext")
    with pytest.raises(SiplSyntaxError) as exc:
        parse(read(path), dialect="core")
    assert all(d.code == "E201" for d in exc.value.diagnostics)


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_programs(path) -> None:
    expected = EXPECTED[path.name]
    with pytest.raises(SiplSyntaxError) as exc:
        parse(read(path))
    d = exc.value.diagnostics[0]
    assert d.code == expected["code"]
    assert d.span is not None
    assert (d.span.line, d.span.column) == (expected["line"], expected["column"])
    if "hint" in expected:
        assert d.hint and expected["hint"] in d.hint


def test_every_invalid_file_has_expectation() -> None:
    assert {p.name for p in INVALID} == set(EXPECTED)


def test_grammar_mentions_all_bnf_rules() -> None:
    text = grammar_text()
    for rule in [
        "P1",
        "S1",
        "S2",
        "S3",
        "S4",
        "S5",
        "S6",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "B1",
        "B2",
        "B3",
        "B4",
        "B5",
    ]:
        assert f"// {rule}" in text, rule


@pytest.mark.parametrize(
    "src",
    [
        "begin X := 1; Y := 2; Z := 3 end",
        "begin if X > 0 then if Y > 0 then skip else skip else skip end",
        "begin while X > 0 do while Y > 0 do Y := Y - 1 end",
        "begin X := 1 - 2 - 3 end",
        "begin if not not X = 1 then skip else skip end",
    ],
)
def test_more_core_sentences(src: str) -> None:
    parse(src, dialect="core")


@pytest.mark.parametrize(
    "src",
    [
        "begin X := 1;; Y := 2 end",
        "begin if X > 0 then skip; skip else skip end",  # then-branch is a single statement
        "begin while do skip end",
        "begin X := 1 + end",
        "begin X := 0 Y end",
        "BEGIN skip END",  # keywords are lower-case
    ],
)
def test_more_negative_sentences(src: str) -> None:
    with pytest.raises(SiplSyntaxError):
        parse(src)
