"""lemma_paper.md -> main.tex for Overleaf: `uv run --with pypandoc_binary python docs/paper/overleaf/make_tex.py [export.json]`.

With an argument (the saved result of the Claude Docs markdown export of the paper doc), first writes lemma_paper.md from it, with the
export's image placeholders replaced by the figures in figures/, and docs/paper/lemma_paper.md (same text, paths from docs/paper).

Math symbols are written as \\ensuremath{...} so the file compiles the same under pdfLaTeX, XeLaTeX and LuaLaTeX
(pdfLaTeX drops characters its fonts lack, e.g. the equivalence sign); long code lines wrap (fvextra).
"""
import base64
import json
import re
import sys
from pathlib import Path

import pypandoc

HERE = Path(__file__).resolve().parent
MATH = {"×": r"\times", "→": r"\rightarrow", "≡": r"\equiv", "⇒": r"\Rightarrow", "⋮": r"\vdots", "↔": r"\leftrightarrow",
        "≈": r"\approx", "µ": r"\mu", "·": r"\cdot"}
HEADER = r"""\usepackage{fvextra}
\DefineVerbatimEnvironment{Highlighting}{Verbatim}{breaklines,breakanywhere,commandchars=\\\{\}}
\fvset{breaklines,breakanywhere}
"""

FIGURES = {"How one query runs": "pipeline.png", "Worked example": "worked_example.png", "Speedup over all-core": "speedup.png"}


def import_export(path: str) -> None:
    data = json.loads([x["text"] for x in json.load(open(path)) if x["text"].startswith("{")][0])["data"]
    md = base64.b64decode(data["bytes_b64"]).decode()

    def figure(m: re.Match) -> str:
        alt = m.group(1)
        return f"![{alt}](figures/{next(v for k, v in FIGURES.items() if alt.startswith(k))})"

    md, n = re.subn(r"&#91;image: (.*?)\\\]", figure, md)
    assert n == md.count("](figures/") and n == len(FIGURES), f"{n} images replaced; expected {len(FIGURES)}"
    (HERE / "lemma_paper.md").write_text(md)
    (HERE.parent / "lemma_paper.md").write_text(md.replace("](figures/", "](overleaf/figures/"))


if len(sys.argv) > 1:
    import_export(sys.argv[1])
(HERE / "header.tex").write_text(HEADER)
tex = pypandoc.convert_file(str(HERE / "lemma_paper.md"), "latex", format="markdown-implicit_figures",
                            extra_args=["--standalone", "-H", str(HERE / "header.tex"), "--resource-path", str(HERE),
                                        "-V", "geometry:margin=1in", "-V", "colorlinks=true", "-V", "fontsize=10pt"])
for ch, cmd in MATH.items():
    tex = tex.replace(ch, rf"\ensuremath{{{cmd}}}")
(HERE / "main.tex").write_text(tex)
(HERE / "header.tex").unlink()
print("wrote", HERE / "main.tex")
