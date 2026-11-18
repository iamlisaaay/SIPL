"""Exporters for derivation trees: text, JSON, Graphviz DOT, standalone SVG, HTML viewer.

All formats are generated from the real :class:`DerivationTree` – nothing is drawn by
hand.  The SVG layout is computed here (no Graphviz installation needed); DOT is
provided for users who prefer ``dot -Tpng``.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass

from sipl.visualization.derivation import DerivationTree, DNode

# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------


def to_text(tree: DerivationTree, *, spans: bool = True) -> str:
    lines: list[str] = []

    def label(n: DNode) -> str:
        s = f"{n.text!s}  ({n.leaf_index})" if n.kind == "terminal" else f"{n.label} [{n.rule}]"
        return f"{s}  @{n.span}" if spans else s

    def rec(n: DNode, prefix: str, last: bool, root: bool) -> None:
        if root:
            lines.append(label(n))
            child_prefix = ""
        else:
            lines.append(f"{prefix}{'└── ' if last else '├── '}{label(n)}")
            child_prefix = prefix + ("    " if last else "│   ")
        for i, c in enumerate(n.children):
            rec(c, child_prefix, i == len(n.children) - 1, False)

    rec(tree.root, "", True, True)
    lines.append("")
    lines.append("Обхід листків зліва направо:")
    lines.append(" ".join(f"{i}:{t}" for i, t in enumerate(tree.frontier(), start=1)))
    verdict = "збігається" if tree.yield_matches_source() else "НЕ збігається"
    lines.append(f"Отримане слово {verdict} з текстом програми.")
    return "\n".join(lines) + "\n"


def to_json(tree: DerivationTree, *, indent: int | None = 2) -> str:
    return json.dumps(tree.to_dict(), ensure_ascii=False, indent=indent)


# ---------------------------------------------------------------------------
# DOT
# ---------------------------------------------------------------------------


def _dot_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def to_dot(tree: DerivationTree) -> str:
    out = [
        "digraph derivation {",
        '  graph [ordering=out, fontname="Helvetica"];',
        '  node [fontname="Helvetica", fontsize=11];',
    ]
    for n in tree.root.walk():
        tip = _dot_escape(f"{n.span}: {n.span.text(tree.source)}")
        if n.kind == "terminal":
            lab = _dot_escape(f"{n.text}\n({n.leaf_index})")
            out.append(
                f'  n{n.id} [label="{lab}", shape=plaintext, fontname="Courier", tooltip="{tip}"];'
            )
        else:
            lab = _dot_escape(f"{n.label}\n{n.rule}")
            out.append(f'  n{n.id} [label="{lab}", shape=box, style="rounded", tooltip="{tip}"];')
    for n in tree.root.walk():
        for c in n.children:
            out.append(f"  n{n.id} -> n{c.id};")
    # all terminals on one rank: the frontier reads left to right like in the practicum
    leaves = " ".join(f"n{leaf.id};" for leaf in tree.root.leaves())
    out.append(f"  {{ rank=same; {leaves} }}")
    out.append("}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# SVG layout
# ---------------------------------------------------------------------------

CHAR_W = 7.6
NODE_H = 34
LEAF_H = 24
H_GAP = 10
V_GAP = 30
MARGIN = 16


@dataclass
class _Box:
    x: float  # centre
    y: float  # top
    w: float
    h: float


def _own_width(n: DNode) -> float:
    if n.kind == "terminal":
        return max(26.0, len(n.text or "") * CHAR_W + 12)
    return max(len(n.label), len(n.rule or "")) * CHAR_W + 18


def layout(tree: DerivationTree) -> tuple[dict[int, _Box], float, float]:
    """Compute boxes.

    Every subtree owns a disjoint horizontal interval, so edges never cross and the
    terminals still read left to right in program order.  A terminal sits one level
    below its parent (not on a common bottom row), which keeps all edges short.
    """
    widths: dict[int, float] = {}

    def measure(n: DNode) -> float:
        kids = sum(measure(c) for c in n.children) + H_GAP * max(0, len(n.children) - 1)
        widths[n.id] = max(_own_width(n), kids)
        return widths[n.id]

    measure(tree.root)
    depth = tree.root.depth()
    boxes: dict[int, _Box] = {}

    def row_y(level: int) -> float:
        return MARGIN + level * (NODE_H + V_GAP)

    def place(n: DNode, left: float, level: int) -> None:
        w = widths[n.id]
        own = _own_width(n)
        if n.kind == "terminal":
            boxes[n.id] = _Box(left + w / 2, row_y(level) + (NODE_H - LEAF_H) / 2, own, LEAF_H)
            return
        kids_w = sum(widths[c.id] for c in n.children) + H_GAP * max(0, len(n.children) - 1)
        cursor = left + (w - kids_w) / 2
        for c in n.children:
            place(c, cursor, level + 1)
            cursor += widths[c.id] + H_GAP
        # centre over the first and last child, but stay inside the own interval
        centre = (boxes[n.children[0].id].x + boxes[n.children[-1].id].x) / 2
        centre = min(max(centre, left + own / 2), left + w - own / 2)
        boxes[n.id] = _Box(centre, row_y(level), own, NODE_H)

    place(tree.root, MARGIN, 0)
    total_w = widths[tree.root.id] + 2 * MARGIN
    total_h = row_y(depth - 1) + NODE_H + 14 + MARGIN
    return boxes, total_w, total_h


_SVG_STYLE = """
  .edge { stroke: var(--edge, #8a8f98); stroke-width: 1.2; fill: none; }
  .nt rect { fill: var(--nt-bg, #eef3fb); stroke: var(--nt-border, #4a6fa5); stroke-width: 1.2; }
  .nt .lab { font: 600 12px system-ui, sans-serif; fill: var(--fg, #1d2330); }
  .nt .rule { font: 10px system-ui, sans-serif; fill: var(--muted, #5b6472); }
  .t rect { fill: var(--t-bg, #fff7e6); stroke: var(--t-border, #c58b1b); stroke-width: 1; }
  .t .lab { font: 12px ui-monospace, Consolas, monospace; fill: var(--fg, #1d2330); }
  .t .idx { font: 9px system-ui, sans-serif; fill: var(--muted, #5b6472); }
  .node { cursor: pointer; }
  .node.sel rect { stroke: var(--accent, #d0342c); stroke-width: 2.4; }
  .node.sub rect { stroke: var(--accent, #d0342c); }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --fg: #e6e9ef; --muted: #a3abb9; --edge: #6b7280;
      --nt-bg: #1f2a3c; --nt-border: #7fa3d6; --t-bg: #33281a; --t-border: #d9a441;
      --accent: #ff6b5e;
    }
  }
"""


def to_svg(tree: DerivationTree, *, standalone: bool = True) -> str:
    boxes, w, h = layout(tree)
    parts: list[str] = []
    if standalone:
        parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
        f'width="{w:.0f}" height="{h:.0f}" role="img" '
        f'aria-label="Дерево синтаксичного виводу SIPL-програми">'
    )
    if standalone:
        parts.append(f"<style>{_SVG_STYLE}</style>")
    for n in tree.root.walk():
        b = boxes[n.id]
        for c in n.children:
            cb = boxes[c.id]
            parts.append(
                f'<path class="edge" d="M{b.x:.1f},{b.y + b.h:.1f} L{cb.x:.1f},{cb.y:.1f}"/>'
            )
    for n in tree.root.walk():
        b = boxes[n.id]
        x0 = b.x - b.w / 2
        title = html.escape(f"{n.rule_text or n.text}  [{n.span}]")
        attrs = (
            f'class="node {"t" if n.kind == "terminal" else "nt"}" data-id="{n.id}" '
            f'data-s="{n.span.start}" data-e="{n.span.end}"'
        )
        parts.append(f"<g {attrs}><title>{title}</title>")
        parts.append(
            f'<rect x="{x0:.1f}" y="{b.y:.1f}" width="{b.w:.1f}" height="{b.h:.1f}" rx="6"/>'
        )
        if n.kind == "terminal":
            parts.append(
                f'<text class="lab" x="{b.x:.1f}" y="{b.y + 16:.1f}" text-anchor="middle">'
                f"{html.escape(n.text or '')}</text>"
            )
            parts.append(
                f'<text class="idx" x="{b.x:.1f}" y="{b.y + b.h + 11:.1f}" '
                f'text-anchor="middle">{n.leaf_index}</text>'
            )
        else:
            parts.append(
                f'<text class="lab" x="{b.x:.1f}" y="{b.y + 15:.1f}" text-anchor="middle">'
                f"{html.escape(n.label)}</text>"
            )
            parts.append(
                f'<text class="rule" x="{b.x:.1f}" y="{b.y + 28:.1f}" text-anchor="middle">'
                f"{html.escape(n.rule or '')}</text>"
            )
        parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# HTML viewer (source <-> tree linking)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Дерево виводу SIPL</title>
<style>
:root {
  --bg: #ffffff; --fg: #1d2330; --muted: #5b6472; --panel: #f6f7f9; --border: #d8dce3;
  --hl: #ffe08a; --accent: #d0342c;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14171c; --fg: #e6e9ef; --muted: #a3abb9; --panel: #1c2027; --border: #313844;
    --hl: #6b5310; --accent: #ff6b5e;
  }
}
:root[data-theme="dark"] {
  --bg: #14171c; --fg: #e6e9ef; --muted: #a3abb9; --panel: #1c2027; --border: #313844;
  --hl: #6b5310; --accent: #ff6b5e;
  --edge: #6b7280; --nt-bg: #1f2a3c; --nt-border: #7fa3d6; --t-bg: #33281a; --t-border: #d9a441;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.5 system-ui, sans-serif; }
header { padding: 12px 16px; border-bottom: 1px solid var(--border); }
header h1 { font-size: 17px; margin: 0; }
header p { margin: 2px 0 0; color: var(--muted); font-size: 13px; }
main { display: grid; grid-template-columns: minmax(240px, 32%) 1fr; gap: 0; min-height: calc(100vh - 60px); }
@media (max-width: 760px) { main { grid-template-columns: 1fr; } }
#side { border-right: 1px solid var(--border); padding: 12px 16px; background: var(--panel); }
pre#src { font: 13px/1.6 ui-monospace, Consolas, monospace; white-space: pre-wrap; margin: 0 0 12px;
  padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); overflow-x: auto; }
pre#src span.tok { cursor: pointer; border-radius: 3px; }
pre#src span.tok.on { background: var(--hl); }
#info { font-size: 13px; }
#info code { font: 12px ui-monospace, Consolas, monospace; }
#info .k { color: var(--muted); }
button { font: inherit; padding: 4px 10px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg); color: var(--fg); cursor: pointer; }
#tree { overflow: auto; padding: 8px; }
.status { font-size: 13px; margin-top: 10px; }
</style>
</head>
<body>
<header>
  <h1>Дерево синтаксичного виводу</h1>
  <p>Клацніть вузол, щоб підсвітити відповідний фрагмент коду; клацніть токен у коді, щоб знайти його вузол.</p>
</header>
<main>
  <section id="side">
    <pre id="src">__SOURCE__</pre>
    <div><button id="up" type="button">↑ батьківський вузол</button></div>
    <div id="info"><p class="k">Нічого не вибрано.</p></div>
    <p class="status">Обхід листків зліва направо: <code>__FRONTIER__</code><br>__VERDICT__</p>
  </section>
  <section id="tree">__SVG__</section>
</main>
<script>
const NODES = __NODES__;
const SOURCE = __SOURCE_JSON__;
const byId = new Map(NODES.map(n => [n.id, n]));
let current = null;
function esc(s) { return s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function isDesc(n, anc) { while (n) { if (n.id === anc.id) return true; n = byId.get(n.parent); } return false; }
function select(id) {
  const n = byId.get(id); if (!n) return; current = n;
  document.querySelectorAll('.node').forEach(g => {
    const m = byId.get(+g.dataset.id);
    g.classList.toggle('sel', m.id === n.id);
    g.classList.toggle('sub', m.id !== n.id && isDesc(m, n));
  });
  document.querySelectorAll('#src .tok').forEach(t => {
    t.classList.toggle('on', +t.dataset.s >= n.s && +t.dataset.e <= n.e);
  });
  const frag = SOURCE.slice(n.s, n.e);
  document.getElementById('info').innerHTML =
    `<p><b>${esc(n.label)}</b> ${n.rule ? '<span class="k">правило</span> <code>' + esc(n.rule) + '</code>' : '<span class="k">термінал</span>'}</p>` +
    (n.rule_text ? `<p><code>${esc(n.rule_text)}</code></p>` : '') +
    `<p><span class="k">позиція</span> ${n.span}</p><p><span class="k">фрагмент</span><br><code>${esc(frag)}</code></p>`;
  const g = document.querySelector(`.node[data-id="${id}"]`);
  if (g && g.scrollIntoView) g.scrollIntoView({block: 'nearest', inline: 'center'});
}
document.querySelectorAll('.node').forEach(g => g.addEventListener('click', () => select(+g.dataset.id)));
document.querySelectorAll('#src .tok').forEach(t => t.addEventListener('click', () => select(+t.dataset.leaf)));
document.getElementById('up').addEventListener('click', () => { if (current && current.parent !== null) select(current.parent); });
// show the root (<програма>) first: scroll the tree pane horizontally to it
window.addEventListener('load', () => {
  const pane = document.getElementById('tree');
  const root = document.querySelector(`.node[data-id="${NODES[0].id}"]`);
  if (pane && root) {
    const r = root.getBoundingClientRect(), p = pane.getBoundingClientRect();
    pane.scrollLeft += (r.left + r.width / 2) - (p.left + p.width / 2);
  }
});
</script>
</body>
</html>
"""


def to_html(tree: DerivationTree) -> str:
    flat = []

    def rec(n: DNode, parent: int | None) -> None:
        flat.append(
            {
                "id": n.id,
                "parent": parent,
                "label": n.label if n.kind == "nonterminal" else (n.text or ""),
                "rule": n.rule,
                "rule_text": n.rule_text,
                "s": n.span.start,
                "e": n.span.end,
                "span": str(n.span),
            }
        )
        for c in n.children:
            rec(c, n.id)

    rec(tree.root, None)

    # source with each terminal wrapped in a clickable span
    pieces: list[str] = []
    pos = 0
    for leaf in tree.root.leaves():
        pieces.append(html.escape(tree.source[pos : leaf.span.start]))
        pieces.append(
            f'<span class="tok" data-s="{leaf.span.start}" data-e="{leaf.span.end}" '
            f'data-leaf="{leaf.id}">{html.escape(leaf.span.text(tree.source))}</span>'
        )
        pos = leaf.span.end
    pieces.append(html.escape(tree.source[pos:]))

    svg = to_svg(tree, standalone=False).replace("<svg ", f"<svg style='{_inline_vars()}' ", 1)
    verdict = (
        "Слово збігається з текстом програми – програма синтаксично правильна."
        if tree.yield_matches_source()
        else "Слово НЕ збігається з текстом програми."
    )
    return (
        _HTML_TEMPLATE.replace("__SVG__", f"<style>{_SVG_STYLE}</style>{svg}")
        .replace("__SOURCE__", "".join(pieces))
        .replace("__FRONTIER__", html.escape(" ".join(tree.frontier())))
        .replace("__VERDICT__", verdict)
        .replace("__NODES__", json.dumps(flat, ensure_ascii=False).replace("</", "<\\/"))
        .replace(
            "__SOURCE_JSON__", json.dumps(tree.source, ensure_ascii=False).replace("</", "<\\/")
        )
    )


def _inline_vars() -> str:
    return "max-width:none"
