"""lemma_paper.md -> main.tex for Overleaf: `uv run --with pypandoc_binary python docs/paper/overleaf/make_tex.py`.

Math symbols are written as \\ensuremath{...} so the file compiles the same under pdfLaTeX, XeLaTeX and LuaLaTeX
(pdfLaTeX drops characters its fonts lack, e.g. the equivalence sign); long code lines wrap (fvextra).
"""
from pathlib import Path

import pypandoc

HERE = Path(__file__).resolve().parent
MATH = {"×": r"\times", "→": r"\rightarrow", "≡": r"\equiv", "⇒": r"\Rightarrow", "⋮": r"\vdots", "↔": r"\leftrightarrow",
        "≈": r"\approx", "µ": r"\mu", "·": r"\cdot"}
HEADER = r"""\usepackage{fvextra}
\DefineVerbatimEnvironment{Highlighting}{Verbatim}{breaklines,breakanywhere,commandchars=\\\{\}}
\fvset{breaklines,breakanywhere}
"""

(HERE / "header.tex").write_text(HEADER)
tex = pypandoc.convert_file(str(HERE / "lemma_paper.md"), "latex", format="markdown-implicit_figures",
                            extra_args=["--standalone", "-H", str(HERE / "header.tex"), "--resource-path", str(HERE),
                                        "-V", "geometry:margin=1in", "-V", "colorlinks=true", "-V", "fontsize=10pt"])
for ch, cmd in MATH.items():
    tex = tex.replace(ch, rf"\ensuremath{{{cmd}}}")
(HERE / "main.tex").write_text(tex)
(HERE / "header.tex").unlink()
print("wrote", HERE / "main.tex")
