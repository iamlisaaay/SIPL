"""VIS-01: derivation tree by the course BNF, text/JSON/DOT/SVG/HTML exports."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from sipl.visualization import export
from sipl.visualization.derivation import derivation_tree

from .conftest import DATA, POWER, read


def test_frontier_matches_practicum_figure() -> None:
    tree = derivation_tree(POWER)
    # Рис. 1 of the practicum numbers the leaves 1..24 in exactly this order
    assert tree.frontier() == [
        "begin",
        "R",
        ":=",
        "1",
        ";",
        "while",
        "Y",
        ">",
        "0",
        "do",
        "begin",
        "R",
        ":=",
        "R",
        "*",
        "X",
        ";",
        "Y",
        ":=",
        "Y",
        "-",
        "1",
        "end",
        "end",
    ]
    assert [leaf.leaf_index for leaf in tree.root.leaves()] == list(range(1, 25))
    assert tree.yield_matches_source()


def test_rules_and_labels() -> None:
    tree = derivation_tree(POWER)
    root = tree.root
    assert (root.label, root.rule) == ("<програма>", "NP1")
    seq = root.children[1]
    assert (seq.label, seq.rule) == ("<оператор>", "NS2")
    rules = [n.rule for n in root.walk() if n.kind == "nonterminal"]
    for r in ["NS1", "NS4", "NS5", "NA1", "NA2", "NA4", "NA5", "NB2", "NV", "NN"]:
        assert r in rules


def test_math_notation() -> None:
    tree = derivation_tree(POWER, notation="math")
    assert (tree.root.label, tree.root.rule) == ("P", "P1")
    assert {n.label for n in tree.root.walk() if n.kind == "nonterminal"} == {
        "P",
        "S",
        "a",
        "b",
        "x",
        "n",
    }


def test_sequence_is_left_nested_binary() -> None:
    tree = derivation_tree("begin A := 1; B := 2; C := 3 end")
    top = tree.root.children[1]
    assert top.rule == "NS2"
    assert top.children[0].rule == "NS2"  # (A; B); C
    assert top.children[2].rule == "NS1"


def test_nodes_linked_to_source() -> None:
    tree = derivation_tree(POWER)
    for n in tree.root.walk():
        assert n.span.end > n.span.start
        if n.kind == "terminal":
            assert n.span.text(POWER) == n.text
    loop = next(n for n in tree.root.walk() if n.rule == "NS4")
    assert loop.span.text(POWER).startswith("while")
    offset = POWER.index("X;")
    node = tree.node_at(offset)
    assert node is not None and node.text == "X"
    assert tree.node_at(10_000) is None


def test_negative_number_is_one_leaf() -> None:
    tree = derivation_tree("begin X := -1 end")
    assert "-1" in tree.frontier()
    assert tree.yield_matches_source()


@pytest.mark.parametrize(
    "path",
    sorted((DATA / "valid").glob("*.sipl")) + sorted((DATA / "ext").glob("*.sipl")),
    ids=lambda p: p.stem,
)
def test_yield_check_on_corpus(path) -> None:
    tree = derivation_tree(read(path))
    assert tree.yield_matches_source()


def test_extension_rules_are_marked() -> None:
    tree = derivation_tree("begin if X >= 1 and true then Q := X div 2 else skip end")
    rules = {n.rule for n in tree.root.walk()}
    assert {"NB+ge", "NB+and", "NB+true", "NA+div"} <= rules


def test_text_export() -> None:
    text = export.to_text(derivation_tree(POWER))
    assert text.startswith("<програма> [NP1]")
    assert "└── end  (24)" in text
    assert "збігається" in text
    assert "@" not in export.to_text(derivation_tree(POWER), spans=False)


def test_json_export() -> None:
    data = json.loads(export.to_json(derivation_tree(POWER)))
    assert data["schema"] == "sipl.derivation/1"
    assert data["root"]["rule"] == "NP1"
    assert data["root"]["children"][0]["kind"] == "terminal"
    assert data["yield_matches_source"] is True
    assert len(data["frontier"]) == 24


def test_dot_export() -> None:
    dot = export.to_dot(derivation_tree(POWER))
    assert dot.startswith("digraph derivation {")
    assert "rank=same" in dot
    assert dot.count("->") == sum(len(n.children) for n in derivation_tree(POWER).root.walk())


def test_svg_export_is_valid_xml() -> None:
    svg = export.to_svg(derivation_tree(POWER))
    root = ET.fromstring(svg.split("?>", 1)[1])
    assert root.tag.endswith("svg")
    nodes = [g for g in root.iter() if g.tag.endswith("g") and "node" in (g.get("class") or "")]
    assert len(nodes) == sum(1 for _ in derivation_tree(POWER).root.walk())
    assert all(g.get("data-s") is not None for g in nodes)


def test_svg_layout_has_no_overlaps() -> None:
    tree = derivation_tree(POWER)
    boxes, _, _ = export.layout(tree)
    rows: dict[float, list[tuple[float, float]]] = {}
    for b in boxes.values():
        rows.setdefault(b.y, []).append((b.x - b.w / 2, b.x + b.w / 2))
    for intervals in rows.values():
        intervals.sort()
        for (_, r1), (l2, _) in zip(intervals, intervals[1:], strict=False):
            assert r1 <= l2 + 0.01


def test_html_export() -> None:
    html = export.to_html(derivation_tree(POWER))
    assert html.startswith("<!doctype html>")
    assert 'class="tok"' in html and "data-leaf" in html
    assert "const NODES" in html
    assert "prefers-color-scheme: dark" in html
