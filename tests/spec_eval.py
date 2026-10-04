"""Rows-level check of an emitted declarative spec: Verus evaluates the spec on concrete data.

``prove_facts`` appends a ``proof fn`` to the spec that assumes the table columns are exactly the given rows
and ensures facts such as ``count_c(a, b, 0, 0) == 3int``. A fact computed from DuckDB's own answer that Verus
proves shows the spec's helper functions mean what SQL means on that data; a fact that mis-binds an alias,
or states a wrong value, fails. The run_query body is ``assume(false)``: only the spec and the witness are checked.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from declarative_spec.assemble import assemble_declarative_program

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"
VERUS = Path("/home/emil/tools/verus/verus")

_SUFFIX = {"bool": "", "i64": "i64", "u64": "u64", "i32": "i32", "u32": "u32", "i128": "i128", "i16": "i16"}


def _struct_fields(spec: str, struct: str) -> list[tuple[str, str]]:
    body = re.search(rf"pub struct {struct} \{{(.*?)\n\}}", spec, re.S).group(1)
    fields = re.findall(r"pub\s+((?:r#)?\w+):\s+Vec<([^>]+)>", body)
    return [(c, "bool" if t == "bool" else t) for c, t in fields]


def _exists_hints(spec: str, params: list[tuple[str, str]], tables: dict[str, list[dict]]) -> str:
    """Terms ``f(args, i) || !f(args, i)`` for every ``*_row_hit`` fn at every row index, so that the solver can
    pick the witness of an ``exists`` over that predicate (IN subqueries)."""
    import itertools

    lines: list[str] = []
    for name, sig in re.findall(r"spec fn (\w*(?:row_hit|key_at|_val))\(([^)]*)\) -> (?:bool|int|Seq<char>|real)", spec):
        parts = [p.strip().split(": ") for p in sig.split(",")]
        structs = [ty.removeprefix("&") for _n, ty in parts if ty.startswith("&")]
        n_idx = sum(1 for _n, ty in parts if ty == "int")
        ranges = [range(len(tables[st.removeprefix("Cols_")])) for st in structs[:n_idx]]
        by_struct = {}
        for param, struct in params:
            by_struct.setdefault(struct, param)
        args = [by_struct[st] for st in structs]
        for combo in itertools.product(*ranges):
            call = f"{name}({', '.join(args + [str(i) for i in combo])})"
            lines.append(f"    assert({call} == {call});\n")
    return "".join(lines)


def prove_facts(
    spec: str,
    tables: dict[str, list[dict]],
    facts: list[str],
    *,
    fuel: int = 8,
    funs: list[str] | None = None,
    extra: str = "",
) -> tuple[bool, str]:
    """True when Verus proves every fact. ``funs`` are the recursive spec fns to unfold; default: every
    ``spec fn`` of the emitted spec that has a ``decreases`` clause."""
    if funs is None:
        funs = re.findall(r"spec fn (\w+)\([^{;]*?decreases", spec, re.S)
    sig = re.search(r"pub fn run_query\(([^)]*)\)", spec).group(1)
    params = re.findall(r"(\w+): &(Cols_\w+)", sig)
    requires: list[str] = []
    for param, struct in params:
        table = struct.removeprefix("Cols_")
        rows = tables[table]
        requires.append(f"{param}.n == {len(rows)}")
        for col, ty in _struct_fields(spec, struct):
            name = col.removeprefix("r#")
            if name.endswith("__valid"):
                # a validity vector: false where the table row (a dict) holds None (a NULL cell)
                values = ", ".join("false" if r[name.removesuffix("__valid")] is None else "true" for r in rows)
                requires.append(f"{param}.{col}@ =~= seq![{values}]")
                continue
            # a NULL cell's value is arbitrary: 0 is written (the exporter's default)
            values = ", ".join(f"{0 if r[name] is None else r[name]}{_SUFFIX[ty]}" for r in rows)
            requires.append(f"{param}.{col}@ =~= seq![{values}]")
    hints = _exists_hints(spec, params, tables)
    witness = (
        "\nproof fn witness("
        + ", ".join(f"{p}: &{s}" for p, s in params)
        + ")\n    requires\n        "
        + ",\n        ".join(requires)
        + ",\n    ensures\n        "
        + ",\n        ".join(facts)
        + ",\n{\n"
        + "".join(f"    reveal_with_fuel({f}, {fuel});\n" for f in funs)
        + hints
        + extra
        + "}\n"
    )
    spec = spec.replace("// AGENT_HELPERS_START", witness + "// AGENT_HELPERS_START", 1)
    program = assemble_declarative_program(
        spec, "    assume(false);\n    loop invariant true decreases 0int { assume(false); }"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as handle:
        handle.write(program)
    proc = subprocess.run(
        [str(GUARD), handle.name, "--triggers-mode", "silent"], capture_output=True, text=True, check=False
    )
    out = proc.stdout + proc.stderr
    return bool(re.search(r"verification results:: \d+ verified, 0 errors", out)), out
