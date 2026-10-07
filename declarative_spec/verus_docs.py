"""Greppable indexes over the pinned vstd source and the fetched Verus examples.

`LEMMAS.md`: one entry per `pub proof fn`, `pub broadcast group`, `pub [open|closed|uninterp] spec fn`,
exec `pub fn` and `assume_specification[ ... ]` (the std exec specs: `Vec::push`, `String::eq`, ...) in
vstd (path, signature, first requires/ensures lines, doc first line). Methods are named `Owner::name`.
`EXAMPLES_INDEX.md`: one line per example/test program with the Verus features it demonstrates.
`GUIDE_INDEX.md`: one line per guide page with its headings.
`INDEX.md` (see `drive.py`) carries one grep recipe per common lookup; `LOOKUPS` below is its source.
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
_CLAUSE_LINES = 5
# `pub broadcast proof fn name<A>()`: no value parameters. Verus rejects a direct call ("cannot call a broadcast_forall function with 0 arguments
# directly"); two Sonnet attempts on one query both wrote `lemma_set_empty_len::<Seq<char>>();` and lost a check each time.
_NO_VALUE_PARAMS = re.compile(r"fn\s+\w+\s*\(\s*\)")  # applied to the signature with its generics stripped (nested `<A: Foo<B>>` included)
_GROUP_BLOCK = re.compile(r"^pub broadcast group (group_\w+)\s*\{([^}]*)\}", re.M)
NOT_CALLABLE_NOTE = (
    "NOT callable by name: a broadcast proof fn with no value arguments cannot be called (Verus: 'cannot call a broadcast_forall function with 0 "
    "arguments directly'). It takes effect only through a `broadcast use` of a vstd group that lists it (every group is allowed)"
)
NO_GROUP_NOTE = "; no allowed group lists it, so the fact is not available: prove it yourself with an `assert` or a lemma of your own (never `assume` or an axiom)."


def _allowed_groups_by_member(vstd: Path) -> dict[str, list[str]]:
    """Member lemma name -> `vstd::<module>::<group>` for every vstd broadcast group (all are allowed, including groups that list `axiom_*` items: vstd's own trusted core)."""
    out: dict[str, list[str]] = {}
    for path in sorted(vstd.rglob("*.rs")):
        module = "::".join(path.relative_to(vstd).with_suffix("").parts)
        for m in _GROUP_BLOCK.finditer(path.read_text()):
            members = [x.strip() for x in m.group(2).split(",") if x.strip()]
            for member in members:
                out.setdefault(member, []).append(f"vstd::{module}::{m.group(1)}")
    return out


def _not_callable_note(name: str, groups: dict[str, list[str]]) -> str:
    found = groups.get(name)
    if found:
        return f"{NOT_CALLABLE_NOTE}; it is a member of {', '.join(f'`{g}`' for g in found)}: write `broadcast use {found[0]};` and the fact is available."
    return NOT_CALLABLE_NOTE + NO_GROUP_NOTE
_IMPL = re.compile(r"^(?P<indent>\s*)(?:unsafe\s+)?impl\b(?P<rest>.*)")
_TRAIT = re.compile(r"^(?P<indent>\s*)pub\s+trait\s+(?P<name>\w+)")
_ASSUME = re.compile(r"^(?P<indent>\s*)pub\s+assume_specification\b[^\[]*\[\s*(?P<target>[^\]]+?)\s*\]")


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


def _assume_signature_and_clauses(lines: list[str], i: int) -> tuple[str, dict[str, list[str]]]:
    """Like `_signature_and_clauses` for a body-less `assume_specification[ ... ](...) ... ;` item."""
    sig: list[str] = []
    clauses: dict[str, list[str]] = {"requires": [], "ensures": []}
    current: list[str] | None = None
    for line in lines[i : i + 60]:
        stripped = line.strip()
        if stripped == ";":
            break
        word = stripped.split(" ")[0].rstrip(",")
        if word in clauses:
            current = clauses[word]
            stripped = stripped[len(word) :].strip()
        elif word in ("decreases", "opens_invariants", "no_unwind", "returns"):
            current = []
        ended = stripped.endswith(";")
        stripped = stripped.rstrip(";").strip()
        if current is None:
            sig.append(stripped)
        elif stripped and len(current) < _CLAUSE_LINES:
            current.append(stripped)
        if ended:
            break
    return " ".join(sig).strip(), clauses


def _strip_generics(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"::<[^<>]*>|<[^<>]*>", "", text)
    return text


def _impl_owner(rest: str) -> str | None:
    """The type an `impl` block is for: `impl<K> View for Foo<K> where ...` and `impl<K> Foo<K>` give `Foo`."""
    rest = rest.strip()
    if rest.startswith("<"):
        depth = 0
        for i, ch in enumerate(rest):
            depth += ch == "<"
            depth -= ch == ">"
            if depth == 0:
                rest = rest[i + 1 :].strip()
                break
    if " for " in rest:
        rest = rest.split(" for ", 1)[1]
    m = re.match(r"[&\w:]+", rest.strip())
    return m.group(0).lstrip("&").split("::")[-1] if m else None


def _assume_name(target: str) -> tuple[str, str]:
    """`Vec::<T, A>::push` -> (`Vec::push`, ``); `<String as PartialEq>::eq` -> (`String::eq`, `PartialEq`)."""
    m = re.match(r"<(.+?)\s+as\s+(.+)>::(\w+)$", target)
    if m:
        return f"{_strip_generics(m.group(1)).strip()}::{m.group(3)}", _strip_generics(m.group(2)).strip()
    return _strip_generics(target).replace(" ", ""), ""


def lemmas_markdown(vstd: Path) -> str:
    """Grep-friendly index of the vstd source tree. One `## name` entry per item.

    Methods are `## Owner::name` (`HashMapWithView::insert`), std exec specs are
    `## Vec::push` / `## String::eq` (from `assume_specification[ ... ]`).
    """
    groups = _allowed_groups_by_member(vstd)
    out = [
        "# vstd index (generated)",
        "",
        "One entry per item. Grep a name or a concept: `grep -n -A6 'lemma_seq_.*subrange' LEMMAS.md`.",
        "Methods are `## Owner::name`: `grep -n -A5 '^## Vec::' LEMMAS.md` lists the Vec exec specs.",
        "Open the file in `vstd/` for the proof body.",
        "",
    ]
    for path in sorted(vstd.rglob("*.rs")):
        rel = path.relative_to(vstd)
        lines = path.read_text().splitlines()
        owner: str | None = None
        owner_indent = -1
        for i, line in enumerate(lines):
            if owner is not None and line.strip() == "}" and len(line) - len(line.lstrip()) == owner_indent:
                owner = None
            impl = _IMPL.match(line)
            trait = _TRAIT.match(line)
            if impl:
                owner, owner_indent = _impl_owner(impl.group("rest").split("{")[0]), len(impl.group("indent"))
            elif trait:
                owner, owner_indent = trait.group("name"), len(trait.group("indent"))
            group = _GROUP.match(line)
            if group:
                members: list[str] = []
                for member in lines[i + 1 : i + 80]:
                    if member.strip().startswith("}"):
                        break
                    members.append(member.strip().rstrip(","))
                out += [f"## {group.group(1)}", f"- path: vstd/{rel}  (broadcast group)", f"- members: {' '.join(members)}", ""]
                continue
            assume = _ASSUME.match(line)
            if assume and "$" in assume.group("target"):
                continue  # macro template, no concrete name
            if assume:
                name, trait_name = _assume_name(assume.group("target"))
                signature, clauses = _assume_signature_and_clauses(lines, i)
                out += [f"## {name}", f"- path: vstd/{rel}:{i + 1}  (exec spec, assume_specification)"]
                if trait_name:
                    out.append(f"- trait: {trait_name}")
                out.append(f"- sig: `{signature}`")
                for key, vals in clauses.items():
                    if vals:
                        out.append(f"- {key}: {' '.join(vals)}")
                doc = _doc_first_line(lines, i)
                if doc:
                    out.append(f"- doc: {doc}")
                out.append("")
                continue
            item = _ITEM.match(line)
            if not item:
                continue
            name = item.group("name")
            kind = "proof fn" if "proof fn" in line else "spec fn" if "spec fn" in line else "fn"
            if kind == "proof fn" and not name.startswith("lemma_") and "broadcast" not in line:
                continue
            qualified = f"{owner}::{name}" if owner and len(item.group("indent")) > owner_indent else name
            signature, clauses = _signature_and_clauses(lines, i)
            out.append(f"## {qualified}")
            out.append(f"- path: vstd/{rel}:{i + 1}  ({kind})")
            out.append(f"- sig: `{signature}`")
            if kind == "proof fn" and "broadcast" in line and _NO_VALUE_PARAMS.search(_strip_generics(signature)):
                out.append(f"- note: {_not_callable_note(name, groups)}")
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
    "loop invariant forall": r"\binvariant\b(?:(?!\bdecreases\b)[\s\S]){0,500}?\bforall\s*\|[^\n]*\[",
    "Vec push": r"\.push\(",
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


def guide_index_markdown(guide: Path) -> str:
    """One line per guide page: `path: # title | ## heading | ...`, so a concept word finds its page."""
    out = [
        "# Verus guide index (generated)",
        "",
        "One line per guide page: title and section headings. `grep -n 'decreases' GUIDE_INDEX.md`, then Read the page.",
        "",
    ]
    for path in sorted(guide.rglob("*.md")):
        heads = [
            ln.lstrip("#").strip()
            for ln in path.read_text(errors="replace").splitlines()
            if re.match(r"#{1,2}\s", ln)
        ]
        out.append(f"guide/{path.relative_to(guide)}: " + " | ".join(heads)[:300])
    return "\n".join(out) + "\n"


# (task, grep arguments run from `context/ro/verus/`, text the output must contain).
# Source of the lookup table in INDEX.md and of tests/test_declarative_audit.py.
LOOKUPS: tuple[tuple[str, str, str], ...] = (
    ("Seq::subrange length lemma", '-n -A4 "lemma_seq_subrange_len" LEMMAS.md', "s.subrange(j, k).len() == k - j"),
    ("`decreases` of a while loop: guide page", '-n "decreases" guide/recursion_loops.md', "decreases"),
    ("`decreases` of a while loop: example programs", '-n "decreases.*while loop" EXAMPLES_INDEX.md', ".rs"),
    ("HashMapWithView insert/get/contains_key specs", '-n -A5 "^## HashMapWithView::" LEMMAS.md', "final(self)@ == old(self)@.insert(k@, v)"),
    ("StringHashMap API", '-n -A5 "^## StringHashMap::" LEMMAS.md', "StringHashMap::insert"),
    ("String equality in exec code", '-n -A5 "^## String::eq" LEMMAS.md', "res == (s@ == other@)"),
    ("Vec::push and its view", '-n -A5 "^## Vec::push" LEMMAS.md', "final(vec)@ == old(vec)@.push(value)"),
    ("`assert forall ... by`: guide pages", '-n "assert forall" GUIDE_INDEX.md', "reference-assert-forall-by.md"),
    ("`assert forall ... by`: example programs", '-n "assert forall" EXAMPLES_INDEX.md', ".rs"),
    ("`by (nonlinear_arith)`: guide pages", '-n "nonlinear" GUIDE_INDEX.md', "nonlinear.md"),
    ("`by (nonlinear_arith)`: example programs", '-n "nonlinear_arith" EXAMPLES_INDEX.md', ".rs"),
    ("`broadcast use` groups and their members", '-n -A2 "^## group_" LEMMAS.md', "- members:"),
    ("`reveal` and `opaque`: guide pages", '-n -i "reveal\\|opaque" GUIDE_INDEX.md', "opaque.md"),
    ("`reveal` and `opaque`: example programs", '-n "reveal.*opaque\\|opaque.*reveal" EXAMPLES_INDEX.md', ".rs"),
    ("`choose`: guide pages", '-n "choose" GUIDE_INDEX.md', "exists.md"),
    ("`choose`: example programs", '-n "choose" EXAMPLES_INDEX.md', ".rs"),
    ("loop invariant with a quantifier over a Seq", '-n "loop invariant forall" EXAMPLES_INDEX.md', ".rs"),
)


def lookups_markdown() -> str:
    return "\n".join(f"- {task}: `grep {args}`" for task, args, _ in LOOKUPS)
