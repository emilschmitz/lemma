#!/usr/bin/env python3
"""Mechanically migrate proved run_query bodies to vstd HashMapWithView / res@ ensures."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research_loop.trusted_families import (
    TRUSTED_FAMILY_MENU,
    bridge_for_family,
    family_by_id,
)
from research_loop.trusted_ret_bridge import (
    structural_bridge_for_spec_type,
)

_FAMILY_IDS = {f.id for f in TRUSTED_FAMILY_MENU}
_METHOD_SPEC_RET_RE = re.compile(r"//\s*MethodSpec returns:\s*(.+)")

_HASHMAP_VIEW_RE = re.compile(r"hashmap_[a-z0-9_]+_view\(([^)]+)\)")
_VEC_VIEW_RE = re.compile(r"vec_[a-z0-9_]+_view\(([^)]+)\)")
_AGG_INNER_VIEW_RE = re.compile(r"agg_step_inner_([a-z0-9_]+)_view")
_HASHSET_VIEW_RE = re.compile(r"hashset_([a-z0-9]+)_view")
_ENSURES_VIEW_RE = re.compile(
    r"ensures\s+hashmap_[a-z0-9_]+_view\((res@)\)\s*=="
)
_ENSURES_VEC_VIEW_RE = re.compile(
    r"ensures\s+vec_[a-z0-9_]+_view\((res@)\)\s*=="
)


def _strip_wrapped_view(match: re.Match[str]) -> str:
    inner = match.group(1).strip()
    if "@" in inner or inner.startswith("old("):
        return inner
    return match.group(0)


def rewrite_views(text: str) -> str:
    text = _AGG_INNER_VIEW_RE.sub(r"agg_step_inner_\1_spec", text)
    text = _HASHSET_VIEW_RE.sub(r"hashset_\1_as_map", text)
    text = _ENSURES_VIEW_RE.sub(r"ensures \1 ==", text)
    text = _ENSURES_VEC_VIEW_RE.sub(r"ensures \1 ==", text)
    text = _HASHMAP_VIEW_RE.sub(_strip_wrapped_view, text)
    text = _VEC_VIEW_RE.sub(_strip_wrapped_view, text)
    return text


def _replace_hashmap_types(text: str, rust_ret: str) -> str:
    out: list[str] = []
    i = 0
    needle = "HashMap<"
    while i < len(text):
        start = text.find(needle, i)
        if start < 0:
            out.append(text[i:])
            break
        if start >= 6 and text[start - 6 : start] == "String":
            out.append(text[i : start + len(needle)])
            i = start + len(needle)
            continue
        if start >= 6 and text[start - 6 : start] == "WithView":
            out.append(text[i : start + len(needle)])
            i = start + len(needle)
            continue
        out.append(text[i:start])
        j = start + len(needle)
        depth = 1
        while j < len(text) and depth:
            ch = text[j]
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
            j += 1
        out.append(rust_ret)
        i = j
    return "".join(out)


def _legacy_hashmap_to_bridge(text: str, rust_ret: str) -> str:
    if "HashMap<" not in text and "std::collections::HashMap" not in text:
        return text
    text = text.replace("std::collections::HashMap", "LEGACY_HASHMAP_PLACEHOLDER")
    text = _replace_hashmap_types(text, rust_ret)
    text = text.replace("LEGACY_HASHMAP_PLACEHOLDER", "std::collections::HashMap")
    return text


def rewrite_imports(text: str, *, needs_map: bool) -> str:
    text = re.sub(r"^use std::collections::HashMap;\n", "", text, flags=re.MULTILINE)
    if not needs_map:
        return text
    if "use vstd::hash_map::" in text:
        return text
    insert_after = "use vstd::prelude::*;\n"
    if insert_after in text:
        return text.replace(
            insert_after,
            insert_after + "use vstd::hash_map::{HashMapWithView, StringHashMap};\n",
            1,
        )
    return text


def _spec_ret_from_agent(text: str, agent_path: Path | None) -> str | None:
    m = _METHOD_SPEC_RET_RE.search(text)
    if m:
        return m.group(1).strip()
    if agent_path is None:
        return None
    spec_path = agent_path.parent / "spec_transpiled.rs"
    if not spec_path.is_file():
        return None
    body = spec_path.read_text(encoding="utf-8")
    sig = re.search(
        r"pub\s+open\s+spec\s+fn\s+method_spec\s*\([^)]*\)\s*->\s*",
        body,
        re.DOTALL,
    )
    if not sig:
        return None
    pos = sig.end()
    depth = 0
    start = pos
    while pos < len(body):
        ch = body[pos]
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif ch == "{" and depth == 0:
            break
        pos += 1
    return body[start:pos].strip()


_AGG_PREFIXES = (
    "agg_new_",
    "agg_add_",
    "agg_put_",
    "agg_step_state_new_",
    "agg_step_inner_",
    "agg_step_project_",
    "agg_step_apply_row_",
    "agg_step_",
)


def _bridge_for(ret_type: str, agent_path: Path | None, text: str):
    if ret_type in _FAMILY_IDS:
        return bridge_for_family(family_by_id(ret_type))
    spec_ret = _spec_ret_from_agent(text, agent_path)
    if spec_ret:
        try:
            return structural_bridge_for_spec_type(spec_ret)
        except ValueError:
            return None
    return None


def _detect_agg_suffix(text: str) -> str | None:
    for prefix in _AGG_PREFIXES:
        m = re.search(rf"\b{re.escape(prefix)}([a-z0-9_]+)(?:_spec)?\(", text)
        if m:
            return m.group(1)
    return None


def _rename_agg_suffixes(text: str, old_suffix: str, new_suffix: str) -> str:
    if not old_suffix or old_suffix == new_suffix:
        return text
    for prefix in _AGG_PREFIXES:
        text = re.sub(
            rf"\b{re.escape(prefix)}{re.escape(old_suffix)}(_spec)?\b",
            lambda m, p=prefix, ns=new_suffix: f"{p}{ns}{m.group(1) or ''}",
            text,
        )
    return text


def _rust_ret_for(ret_type: str, agent_path: Path | None = None, text: str = "") -> str | None:
    bridge = _bridge_for(ret_type, agent_path, text)
    return bridge.rust_ret if bridge else None


def rewrite_agent_rs(text: str, *, ret_type: str | None, agent_path: Path | None = None) -> str:
    out = rewrite_views(text)
    bridge = _bridge_for(ret_type or "", agent_path, text) if ret_type or agent_path else None
    if bridge and bridge.agg_suffix:
        old_suffix = _detect_agg_suffix(out)
        if old_suffix:
            out = _rename_agg_suffixes(out, old_suffix, bridge.agg_suffix)
    needs_map = False
    rust_ret = bridge.rust_ret if bridge else None
    if rust_ret and rust_ret.startswith(("HashMapWithView", "StringHashMap")):
        needs_map = True
        out = _legacy_hashmap_to_bridge(out, rust_ret)
    elif not ret_type:
        needs_map = "HashMapWithView" in out or "StringHashMap" in out or "HashMap<" in out
    out = rewrite_imports(out, needs_map=needs_map)
    return out


def _read_ret_type(agent_path: Path) -> str | None:
    meta = agent_path.parent / "meta.json"
    if not meta.is_file():
        return None
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("ret_type")
    except (json.JSONDecodeError, OSError):
        return None


def rewrite_file(path: Path, *, dry_run: bool = False) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = rewrite_agent_rs(original, ret_type=_read_ret_type(path), agent_path=path)
    if updated == original:
        return False
    if not dry_run:
        path.write_text(updated, encoding="utf-8")
    return True


def collect_agent_paths(root: Path, rounds: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for rnd in rounds:
        for d in sorted(root.glob(f"{rnd}_q*")):
            if rnd == "r11" and d.name == "r11_q19":
                continue
            agent = d / "runquery_agent.rs"
            if agent.is_file():
                paths.append(agent)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT / "research_loop" / "generated" / "prove_loop",
    )
    parser.add_argument("--rounds", nargs="+", default=["r11", "r12"])
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args()

    if args.files:
        paths = [p.resolve() for p in args.files]
    else:
        paths = collect_agent_paths(args.root, tuple(args.rounds))

    changed = 0
    for path in paths:
        if rewrite_file(path, dry_run=args.dry_run):
            changed += 1
            print("updated", path.relative_to(ROOT))
    print(f"done: {changed}/{len(paths)} files changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
