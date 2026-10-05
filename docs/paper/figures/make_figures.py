"""Generate the paper figures from one description: TikZ (for the paper) and SVG (for a quick look).

    python3 docs/paper/figures/make_figures.py   # writes lemma_overview_tikz.tex/.svg, lemma_listing_tikz.tex/.svg

No dependencies. Coordinates are centimetres, y up. The TikZ is plain pdflatex (tikz + arrows.meta).
"""
from __future__ import annotations

import html
from pathlib import Path

OUT = Path(__file__).resolve().parent
PX = 40.0  # svg pixels per cm
FONT_SERIF = "Linux Libertine O, Libertinus Serif, Liberation Serif, DejaVu Serif, serif"
FONT_MONO = "Liberation Mono, DejaVu Sans Mono, monospace"


# ---------- markup: `code` is monospace, everything else serif ----------
def segs(s: str):
    parts = s.split("`")
    return [(p, i % 2 == 1) for i, p in enumerate(parts) if p]


def tex_escape(s: str, mono: bool) -> str:
    s = s.replace("\\", r"\textbackslash{}")
    for a, b in (("_", r"\_"), ("&", r"\&"), ("%", r"\%"), ("#", r"\#"), ("$", r"\$")):
        s = s.replace(a, b)
    if not mono:
        s = s.replace("->", r"$\rightarrow$")
    return s


def tex_line(s: str, bold: bool = False) -> str:
    out = "".join((r"\texttt{%s}" if m else "%s") % tex_escape(t, m) for t, m in segs(s))
    return r"\textbf{%s}" % out if bold else out


def svg_line_spans(s: str, bold: bool) -> str:
    out = []
    for t, m in segs(s):
        fam = FONT_MONO if m else FONT_SERIF
        w = ' font-weight="bold"' if bold else ""
        out.append(f'<tspan font-family="{fam}"{w}>{html.escape(t)}</tspan>')
    return "".join(out)


# ---------- styles (grayscale safe: fill / border weight / dash) ----------
STYLES = {
    # name: (tikz options, svg fill, svg stroke-width, svg dasharray)
    "trusted": ("fill=black!15, line width=0.8pt", "#d9d9d9", 1.2, ""),
    "proved": ("fill=white, line width=1.6pt", "#ffffff", 2.4, ""),
    "checked": ("fill=white, dashed, line width=0.9pt", "#ffffff", 1.4, "6,4"),
    "untrusted": ("fill=white, densely dotted, line width=0.9pt", "#ffffff", 1.4, "1.5,3"),
    "plain": ("fill=white, line width=0.5pt", "#ffffff", 0.8, ""),
}


class Fig:
    def __init__(self, w: float, h: float):
        self.w, self.h = w, h
        self.tex: list[str] = []
        self.svg: list[str] = []

    def sy(self, y: float) -> float:
        return (self.h - y) * PX

    def box(self, x0, y0, x1, y1, style, title=None, lines=(), badge=None, size=8.0, rounded=True, lh=0.38):
        topts, fill, sw, dash = STYLES[style]
        r = ", rounded corners=2pt" if rounded else ""
        self.tex.append(rf"\draw[{topts}{r}] ({x0:.2f},{y0:.2f}) rectangle ({x1:.2f},{y1:.2f});")
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.svg.append(
            f'<rect x="{x0*PX:.1f}" y="{self.sy(y1):.1f}" width="{(x1-x0)*PX:.1f}" height="{(y1-y0)*PX:.1f}" '
            f'rx="{3 if rounded else 0}" fill="{fill}" stroke="#000" stroke-width="{sw}"{da}/>'
        )
        rows = ([(title, True)] if title else []) + [(l, False) for l in lines]
        if rows:
            cx = (x0 + x1) / 2
            ytop = (y0 + y1) / 2 + len(rows) * lh / 2
            for i, (t, b) in enumerate(rows):
                self.text(cx, ytop - lh * (i + 0.5), t, b, size)
        if badge:
            self.badge(x1 - 0.05, y1 - 0.05, badge)

    def text(self, x, y, s, bold=False, size=8.0, anchor="middle", fill_bg=False):
        cmd = {8.0: r"\footnotesize", 6.5: r"\scriptsize", 9.5: r"\small"}[size]
        al = {"middle": "", "start": "anchor=west, ", "end": "anchor=east, "}[anchor]
        bg = "fill=white, inner sep=1pt, " if fill_bg else "inner sep=0pt, "
        self.tex.append(rf"\node[{al}{bg}text=black] at ({x:.2f},{y:.2f}) {{{cmd} {tex_line(s, bold)}}};")
        px = size * 1.406
        a = {"middle": "middle", "start": "start", "end": "end"}[anchor]
        bgsvg = ""
        if fill_bg:
            wch = sum(len(t) for t, _ in segs(s)) * px * 0.5
            bx = x * PX - (wch / 2 if anchor == "middle" else 0)
            bgsvg = f'<rect x="{bx-2:.1f}" y="{self.sy(y)-px*0.8:.1f}" width="{wch+4:.1f}" height="{px*1.15:.1f}" fill="#fff"/>'
        self.svg.append(
            bgsvg + f'<text x="{x*PX:.1f}" y="{self.sy(y)+px*0.33:.1f}" font-size="{px:.1f}" text-anchor="{a}" xml:space="preserve">'
            f"{svg_line_spans(s, bold)}</text>"
        )

    def badge(self, x, y, s):
        r = 0.2 if len(s) == 1 else 0.3
        self.tex.append(
            rf"\node[draw, circle, fill=white, inner sep=0.6pt, line width=0.6pt] at ({x-r:.2f},{y:.2f}) {{\scriptsize\textbf{{{s}}}}};"
        )
        self.svg.append(
            f'<circle cx="{(x-r)*PX:.1f}" cy="{self.sy(y):.1f}" r="{(r+0.04)*PX:.1f}" fill="#fff" stroke="#000" stroke-width="0.9"/>'
            f'<text x="{(x-r)*PX:.1f}" y="{self.sy(y)+3.6:.1f}" font-size="9.5" font-weight="bold" text-anchor="middle" font-family="{FONT_SERIF}">{s}</text>'
        )

    def arrow(self, pts, dashed=False, both=False, width=0.9):
        tip = "<->" if both else "->"
        d = ", dashed" if dashed else ""
        coords = " -- ".join(f"({x:.2f},{y:.2f})" for x, y in pts)
        self.tex.append(rf"\draw[{tip}, line width={width}pt{d}] {coords};")
        da = ' stroke-dasharray="6,4"' if dashed else ""
        path = " ".join(("M" if i == 0 else "L") + f"{x*PX:.1f},{self.sy(y):.1f}" for i, (x, y) in enumerate(pts))
        ms = ' marker-start="url(#ah)"' if both else ""
        self.svg.append(f'<path d="{path}" fill="none" stroke="#000" stroke-width="{width*1.3}"{da} marker-end="url(#ah)"{ms}/>')

    def write(self, name: str):
        body = "\n".join(self.tex)
        (OUT / f"{name}_tikz.tex").write_text(
            "% Generated by make_figures.py (do not edit by hand).\n"
            "% Needs \\usepackage{tikz} and \\usetikzlibrary{arrows.meta} in the preamble.\n"
            "\\begingroup\\centering\n"
            "\\begin{tikzpicture}[x=1cm,y=1cm,>={Stealth[length=4pt,width=3.5pt]}]\n" + body + "\n\\end{tikzpicture}\\par\\endgroup\n"
        )
        defs = ('<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                '<path d="M0,0 L10,5 L0,10 z" fill="#000"/></marker></defs>')
        (OUT / f"{name}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w*PX:.0f}" height="{self.h*PX:.0f}" '
            f'viewBox="0 0 {self.w*PX:.0f} {self.h*PX:.0f}" font-family="{FONT_SERIF}">{defs}'
            f'<rect width="100%" height="100%" fill="#fff"/>\n' + "\n".join(self.svg) + "\n</svg>\n"
        )


def overview() -> None:
    f = Fig(17.5, 8.8)
    # legend row
    ly = 8.5
    items = [("trusted", "Trusted (small, fixed)"), ("proved", "Proved by Verus"),
             ("checked", "Checked at run time"), ("untrusted", "Untrusted (LLM output)")]
    for i, (st, lab) in enumerate(items):
        x = 0.1 + i * 4.4
        f.box(x, ly - 0.17, x + 0.5, ly + 0.17, st, rounded=False)
        f.text(x + 0.65, ly, lab, size=8.0, anchor="start")

    Y0, Y1 = 4.1, 6.9  # spine boxes
    # 1 SQL + catalog (the assumptions are checked at load time)
    f.box(0.05, Y0, 3.05, Y1, "checked", "SQL query", ["+ catalog:", "schema and", "assumption package", "(caps measured on", "the data, user-approved)"])
    # 2 spec
    f.box(4.25, Y0, 7.85, Y1, "trusted", "Formal spec", ["from the transpiler:", "`valid_cols` (catalog caps)", "`run_query` `requires`,", "`ensures`: the ground truth", "(host-owned, agent-read-only)"], badge="T")
    # container around the agent
    f.box(9.05, 2.75, 13.05, 7.75, "plain")
    f.text(11.05, 7.5, "Docker sandbox", True, 8.0)
    f.box(9.3, Y0, 12.8, Y1, "untrusted", "Agent (Claude Code)", ["writes Rust:", "`run_query` body", "+ proof helpers", "(one editable file)"])
    f.text(11.05, 3.65, "`--network none`; egress to the", size=6.5)
    f.text(11.05, 3.3, "model API only; MCP socket to host", size=6.5)
    f.text(11.05, 2.95, "context mounted read-only", size=6.5)
    # 4 assembly
    f.box(14.25, Y0, 17.45, Y1, "proved", "Assembly (host)", ["admission lint, rebuild", "from marked regions", "Verus: body meets", "`ensures`, N verified,", "0 errors; compile"], badge="T P")
    # spine arrows
    ym = 5.5
    f.arrow([(3.05, ym), (4.25, ym)])
    f.text(3.65, ym + 0.45, "emit", size=6.5)
    f.arrow([(7.85, ym), (9.05, ym)])
    f.text(8.45, ym + 0.95, "spec,", size=6.5)
    f.text(8.45, ym + 0.65, "prompt,", size=6.5)
    f.text(8.45, ym + 0.35, "docs", size=6.5)
    f.arrow([(13.05, ym), (14.25, ym)])
    f.text(13.65, ym + 0.65, "marked", size=6.5)
    f.text(13.65, ym + 0.35, "regions", size=6.5)
    # feedback: verdict returns to the agent
    f.arrow([(14.9, Y0), (14.9, 2.35), (11.05, 2.35), (11.05, 2.75)], dashed=True)
    f.text(13.0, 2.35, "verdict via MCP (`run_runquery`; `submit_runquery`)", size=6.5, fill_bg=True)
    # execute panel
    f.box(7.6, 0.45, 17.45, 1.9, "checked", "Then, on the host (not in the sandbox)", ["pinned DuckDB columns are loaded; the loader re-checks every cap; output rows are", "compared with DuckDB's; the binary is timed against all-core DuckDB"], badge="C", lh=0.36)
    f.arrow([(16.6, Y0), (16.6, 1.9)])
    # adversary gate
    f.box(0.05, 0.45, 7.2, 1.9, "plain", "Adversary gate", ["a new trusted lemma or bridge enters the", "trusted base only with a written verdict"], lh=0.36)
    f.arrow([(5.4, 1.9), (5.4, Y0)], dashed=True)
    f.text(5.45, 3.0, "adds to", size=6.5, anchor="start", fill_bg=True)
    f.write("lemma_overview")


# ---------- listing ----------
LISTING = [
    ("host", "Host-owned spec", "(fixed; the agent\ncannot edit it)", [
        "pub struct Cols_pre { pub n: usize, pub line: Vec<i64> }",
        "pub open spec fn valid_cols_pre(pre: &Cols_pre) -> bool {",
        "    &&& pre.line@.len() == pre.n as int",
        "    &&& pre.n as int <= ROW_CAP_pre as int            // catalog cap, re-checked at load",
        "    &&& forall|i: int| 0 <= i < pre.n as int ==>              // catalog value bounds, re-checked at load",
        "            pre.line@[i] as int >= -8191 && pre.line@[i] as int <= 8191",
        "}",
        "pub open spec fn sum_total(pre: &Cols_pre, i0: int) -> int   // the SQL, as a fold",
        "    decreases pre.n as int - i0",
        "{ if i0 < 0 || i0 >= pre.n as int { 0int }",
        "  else { (if row_hit(pre, i0) { sum_total_val(pre, i0) } else { 0int }) + sum_total(pre, i0 + 1) } }",
    ]),
    ("trusted", "Trusted host lemmas", "(fixed menu;\nnone for this query)", [
        "// HOST_LEMMAS_START  ...  // HOST_LEMMAS_END",
    ]),
    ("agent", "Agent helpers", "(proof fn / spec fn\nonly; empty here)", [
        "// AGENT_HELPERS_START",
        "// AGENT_HELPERS_END",
    ]),
    ("host", "Host-owned signature", "(the contract)", [
        "pub fn run_query(pre: &Cols_pre) -> (res: Vec<OutRow>)",
        "    requires valid_cols_pre(pre),",
        "    ensures res@.len() == 1,                  // shown split; emitted as one conjunction",
        "        (exists|i0: int| row_hit(pre, i0)) ==> res@[0].total is Some",
        "            && res@[0].total->Some_0 as int == sum_total(pre, 0),",
        "        !(exists|i0: int| row_hit(pre, i0)) ==> res@[0].total is None,",
        "{",
    ]),
    ("agent", "Agent-owned body", "(Haiku 4.5; Verus:\n5 verified, 0 errors)", [
        "// AGENT_EDIT_START",
        "    let mut acc: i128 = 0;  let mut any: bool = false;  let mut i: usize = pre.n;",
        "    while i > 0",
        "        invariant",
        "            i <= pre.n, valid_cols_pre(pre),",
        "            acc as int == sum_total(pre, i as int),",
        "            -((pre.n - i) as int) * 0x8000_0000_0000_0000int <= acc as int,",
        "            acc as int <= ((pre.n - i) as int) * 0x8000_0000_0000_0000int,",
        "            any <==> exists|i0: int| i as int <= i0 && row_hit(pre, i0),",
        "        decreases i,",
        "    {",
        "        i -= 1;  let line = pre.line[i];",
        "        proof { /* three asserts elided */ reveal_with_fuel(sum_total, 2); }",
        "        if line > 5 { acc = acc + (line as i128);  any = true; }",
        "    }",
        "    let mut res: Vec<OutRow> = Vec::new();",
        "    res.push(OutRow { total: if any { Some(acc) } else { None } });  res",
        "// AGENT_EDIT_END",
        "}",
    ]),
]


def listing() -> None:
    tex = ["% Generated by make_figures.py. Needs \\usepackage{listings}.",
           "\\lstdefinestyle{lemmacode}{basicstyle=\\ttfamily\\scriptsize, columns=fullflexible, keepspaces=true,",
           "  aboveskip=0pt, belowskip=0pt, xleftmargin=0pt, showstringspaces=false}",
           "\\noindent\\hrule height 0.6pt\\vspace{2pt}"]
    for kind, title, note, code in LISTING:
        note_tex = " \\\\ ".join(tex_escape(n, False) for n in note.split("\n"))
        mark = {"host": "H", "trusted": "T", "agent": "A"}[kind]
        rule = "1.6pt" if kind == "agent" else "0.4pt"
        tex.append("\\noindent\\begin{minipage}[c]{0.2\\textwidth}\\raggedleft\\footnotesize")
        tex.append(f"\\textbf{{[{mark}] {tex_escape(title, False)}}} \\\\ {{\\scriptsize {note_tex}}}\\end{{minipage}}\\hspace{{4pt}}\\vrule width {rule}\\hspace{{4pt}}%")
        tex.append("\\begin{minipage}[c]{0.74\\textwidth}")
        tex.append("\\begin{lstlisting}[style=lemmacode]")
        tex.extend(code)
        tex.append("\\end{lstlisting}\\end{minipage}\\par\\vspace{2pt}\\hrule height 0.3pt\\vspace{2pt}")
    (OUT / "lemma_listing_tikz.tex").write_text("\n".join(tex) + "\n")

    lh = 0.40
    width = 17.5
    labw = 3.6
    rows = sum(len(c) for _, _, _, c in LISTING)
    H = rows * lh + len(LISTING) * 0.45 + 0.2
    f = Fig(width, H)
    y = H - 0.1
    for kind, title, note, code in LISTING:
        bh = len(code) * lh + 0.2
        fill = {"host": "#e6e6e6", "trusted": "#cfcfcf", "agent": "#ffffff"}[kind]
        sw = 2.4 if kind == "agent" else 0.8
        f.svg.append(f'<rect x="{(labw+0.2)*PX:.1f}" y="{f.sy(y):.1f}" width="{(width-labw-0.3)*PX:.1f}" height="{bh*PX:.1f}" fill="{fill}" stroke="#000" stroke-width="{sw}"/>')
        mark = {"host": "H", "trusted": "T", "agent": "A"}[kind]
        f.text(labw, y - bh / 2 + 0.3, f"[{mark}] {title}", True, 8.0, anchor="end")
        for k, n in enumerate(note.split("\n")):
            f.text(labw, y - bh / 2 - 0.05 - k * 0.32, n, False, 6.5, anchor="end")
        px = 8.2 * 1.406 * 0.78
        for k, line in enumerate(code):
            ty = y - 0.1 - lh * (k + 0.75)
            f.svg.append(f'<text x="{(labw+0.35)*PX:.1f}" y="{f.sy(ty):.1f}" font-size="{px:.1f}" font-family="{FONT_MONO}" xml:space="preserve">{html.escape(line)}</text>')
        y -= bh + 0.25
    (OUT / "lemma_listing.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width*PX:.0f}" height="{H*PX:.0f}" viewBox="0 0 {width*PX:.0f} {H*PX:.0f}">'
        f'<rect width="100%" height="100%" fill="#fff"/>\n' + "\n".join(f.svg) + "\n</svg>\n")


if __name__ == "__main__":
    overview()
    listing()
    print("ok")
