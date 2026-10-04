"""Greppable indexes over the pinned vstd source and the fetched Verus examples.

`LEMMAS.md`: one entry per `pub proof fn`, `pub broadcast group`, `pub [open|closed|uninterp] spec fn`
and exec `pub fn` in vstd (path, signature, first requires/ensures lines, doc first line).
`EXAMPLES_INDEX.md`: one line per example/test program with the Verus features it demonstrates.
The downloaded docs come from `research_loop/scripts/fetch_verus_docs.sh` (host side only).
"""

from __future__ import annotations

import re
from pathlib import Path

DOCS_CACHE = Path(__file__).resolve().parent.parent / "research_loop" / "vendor" / "verus_docs"

_ITEM = re.compile(
    r"^(?P<indent>\s*)pub\s+(?:(?:open|closed|uninterp)\s+)?(?:(?:broadcast\s+)?proof\s+fn|spec\s+fn|fn|exec\s+fn)\s+(?P<name>\w+)"
)
_GROUP = re.compile(r"^\s*pub\s+broadcast\s+group\s+(group_\w+)")
_CLAUSE_LINES = 3


def _doc_first_line(lines: list[str], i: int) -> str:
    j = i - 1
    while j >= 0 and lines[j].lstrip().startswith(("#[", "#!")):
        j -= 1
    docs = []
    while j >= 0 and lines[j].lstrip().startswith("///"):
        docs.append(lines[j].lstrip()[3:].strip())
        j -= 1
    return docs[-1] if docs else ""


def _signature_and_clauses(lines: list[str], i: int) -> tuple[str, dict[str, list[str]]]:
    sig: list[str] = []
    clauses: dict[str, list[str]] = {"requires": [], "ensures": []}
    current: list[str] | None = None
    for line in lines[i : i + 80]:
        stripped = line.strip()
        word = stripped.split(" ")[0].rstrip(",")
        if word in clauses:
            current = clauses[word]
            stripped = stripped[len(word) :].strip()
        elif word in ("decreases", "opens_invariants", "no_unwind", "returns"):
            current = []
        elif stripped.startswith("{") or stripped.endswith("{") and current is None and sig:
            break
        if stripped.startswith("{"):
            break
        if current is None:
            sig.append(stripped)
            if stripped.endswith(("{", ";")):
                break
        elif stripped and len(current) < _CLAUSE_LINES:
            current.append(stripped)
    signature = " ".join(sig).rstrip("{; ").strip()
    return signature, clauses


def lemmas_markdown(vstd: Path) -> str:
    """Grep-friendly index of the vstd source tree. One `## name` entry per item."""
    out = [
        "# vstd index (generated)",
        "",
        "One entry per item. Grep a name or a concept: `grep -n -A6 'lemma_seq_.*subrange' LEMMAS.md`.",
        "Open the file in `vstd/` for the proof body.",
        "",
    ]
    for path in sorted(vstd.rglob("*.rs")):
        rel = path.relative_to(vstd)
        lines = path.read_text().splitlines()
        for i, line in enumerate(lines):
            group = _GROUP.match(line)
            if group:
                members: list[str] = []
                for member in lines[i + 1 : i + 80]:
                    if member.strip().startswith("}"):
                        break
                    members.append(member.strip().rstrip(","))
                out += [f"## {group.group(1)}", f"- path: vstd/{rel}  (broadcast group)", f"- members: {' '.join(members)}", ""]
                continue
            item = _ITEM.match(line)
            if not item:
                continue
            name = item.group("name")
            kind = "proof fn" if "proof fn" in line else "spec fn" if "spec fn" in line else "fn"
            if kind == "proof fn" and not name.startswith("lemma_"):
                continue
            signature, clauses = _signature_and_clauses(lines, i)
            out.append(f"## {name}")
            out.append(f"- path: vstd/{rel}:{i + 1}  ({kind})")
            out.append(f"- sig: `{signature}`")
            for key, vals in clauses.items():
                if vals:
                    out.append(f"- {key}: {' '.join(vals)}")
            doc = _doc_first_line(lines, i)
            if doc:
                out.append(f"- doc: {doc}")
            out.append("")
    return "\n".join(out)


# keyword -> regex, so the agent greps for a feature and gets file names.
_FEATURES: dict[str, str] = {
    "invariant": r"\binvariant\b",
    "decreases": r"\bdecreases\b",
    "assert forall": r"assert\s+forall|assert\(\s*forall|assert forall",
    "forall": r"\bforall\s*\|",
    "exists": r"\bexists\s*\|",
    "trigger": r"#\[trigger\]|#!\[trigger",
    "assert-by": r"assert\s*\([^;]*\)\s*by\b",
    "nonlinear_arith": r"nonlinear_arith",
    "bit_vector": r"bit_vector",
    "compute": r"by\s*\(compute",
    "broadcast use": r"broadcast\s+use",
    "broadcast group": r"broadcast\s+group",
    "calc!": r"\bcalc!",
    "Seq": r"\bSeq\b",
    "Map": r"\bMap\b",
    "Set": r"\bSet\b",
    "Multiset": r"\bMultiset\b",
    "Vec": r"\bVec\b",
    "HashMapWithView": r"HashMapWithView",
    "StringHashMap": r"StringHashMap",
    "HashMap": r"\bHashMap\b",
    "String": r"\bString\b|\bstr_view\b|\bas_str\b",
    "while loop": r"\bwhile\b",
    "for loop": r"\bfor\s+\w+\s+in\b",
    "spec fn": r"\bspec\s+fn\b",
    "proof fn": r"\bproof\s+fn\b",
    "reveal": r"\breveal(_with_fuel)?\b",
    "opaque": r"#\[verifier::opaque\]|\bclosed\s+spec\b",
    "ghost/tracked": r"\bGhost\b|\bTracked\b|\btracked\b",
    "choose": r"\bchoose\b",
    "fold_left": r"fold_left|fold_right",
    "subrange": r"\bsubrange\b|\.take\(|\.skip\(",
    "view (@)": r"\.view\(\)|@\b",
    "external_body": r"external_body",
    "assume": r"\bassume\(",
    "int overflow/as": r"\bas\s+(int|u64|u32|u128|i64)\b",
}


def _program_text(path: Path) -> str:
    return path.read_text(errors="replace")


def examples_index_markdown(docs: Path) -> str:
    """One line per program under ``docs/{examples,tests}``: path, size, features found."""
    out = [
        "# Verus example index (generated)",
        "",
        "Each line: `path (lines): features`. Grep a feature to find a small program that uses it:",
        "`grep -n 'assert forall' EXAMPLES_INDEX.md | sort -t'(' -k2 -n`, then Read the file.",
        "Paths are relative to this directory. Files under `tests/` hold Verus code inside",
        "`verus_code! { ... }`; `examples/` files are plain Verus programs.",
        "",
    ]
    for sub in ("examples", "tests"):
        for path in sorted((docs / sub).rglob("*.rs")):
            text = _program_text(path)
            feats = [name for name, rx in _FEATURES.items() if re.search(rx, text)]
            n = text.count("\n") + 1
            out.append(f"{path.relative_to(docs)} ({n}): {', '.join(feats)}")
    return "\n".join(out) + "\n"
