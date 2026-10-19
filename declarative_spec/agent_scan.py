"""Agent-chosen scans (lemma.toml [run] ``agent_scan``): the agent may ask DuckDB for the rows of a table that satisfy a predicate.

Owner authorization (Emil, 2026-10-17, relayed by the orchestrator): "we can add a trusted that DuckDB filters correctly". This module
emits exactly ONE trusted family per table, ``scan_where_<t>`` (docs/TRUSTED_FAMILIES.md, "DuckDB filters correctly"):

* ``ScanCol_<t>``: the integer-valued columns of ``Cols_<t>`` (integers, dates as days, DECIMALs as scaled integers; not strings,
  dictionary codes, floats or booleans);
* ``ScanAtom_<t>``: ``Range(col, lo, hi)`` (``lo <= cell <= hi``; covers = < <= > >= BETWEEN) or ``In(col, values)``; a NULL cell of
  a nullable column satisfies no atom (SQL: a comparison with NULL is not TRUE);
* ``scan_holds_<t>(c, pred, i)``: every atom of ``pred`` holds of row ``i``; ``scan_rows_<t>(c, pred, n)``: the rows ``i < n`` that
  satisfy it, in table order (a plain recursive filter);
* ``Scan_<t>`` (an opaque handle) with the uninterpreted ``scan_full_<t>(s)``: the full table the handle scans. ``run_query`` gets
  one handle per table and ``requires scan_full_<t>(<t>_scan) == *<t>``: the handle scans exactly the table the spec is about;
* the trusted item ``scan_where_<t>(s, pred) -> (Cols_<t>, Ghost<Seq<int>>)``: the returned columns are the rows
  ``scan_rows_<t>(scan_full_<t>(s), pred, n)`` of the full table, in order (dictionaries are the full table's own);
* ``lemma_scan_rows_<t>`` (host-PROVED, not trusted): those rows are in range, strictly increasing, satisfy the predicate,
  and every satisfying row is among them.

The spec's ``ensures`` is unchanged: it still states the query over the full table ``<t>``. A predicate that drops a row the
query needs therefore fails the proof. The exec body of ``scan_where_<t>`` serializes the predicate and reads the column file
the host exported with ``WHERE <pushed> AND <translation of pred>`` (``research_loop/scan_export.py``); a missing file is
exported on demand by that fixed host program. Flag off: the spec is byte-identical to before.
"""

from __future__ import annotations

import re

import lemma_config

_INT = ("i8", "i16", "i32", "i64", "i128", "u8", "u16", "u32", "u64", "usize")
_FIELD = re.compile(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>")


def enabled() -> bool:
    return bool(lemma_config.get("agent_scan"))


def scan_columns(fields: list[tuple[str, str]]) -> list[tuple[str, str, bool]]:
    """(field, type, nullable) of the fields a predicate may test: integer cells that are not dictionary codes."""
    names = {f for f, _ in fields}
    out = []
    for fname, fty in fields:
        if fname.endswith("__valid") or fname.endswith("__dict") or fty not in _INT or f"{fname}__dict" in names:
            continue
        out.append((fname, fty, f"{fname}__valid" in names))
    return out


def _items(suffix: str, fields: list[tuple[str, str]]) -> str:
    t = suffix
    cols = scan_columns(fields)
    variants = ", ".join(f for f, _, _ in cols) or "NoColumn"
    cell_arms = "\n".join(f"        ScanCol_{t}::{f} => c.{f}@[i] as int," for f, _, _ in cols) or f"        ScanCol_{t}::NoColumn => 0int,"
    ok_arms = "\n".join(
        f"        ScanCol_{t}::{f} => {f'c.{f}__valid@[i]' if nullable else 'true'}," for f, _, nullable in cols
    ) or f"        ScanCol_{t}::NoColumn => false,"
    key_arms = "\n".join(f'        ScanCol_{t}::{f} => "{f.removeprefix("r#")}",' for f, _, _ in cols) or f'        ScanCol_{t}::NoColumn => "",'
    ens: list[str] = []
    for fname, _fty in fields:
        if fname.endswith("__dict"):
            ens.append(f"        out.0.{fname}@ == scan_full_{t}(s).{fname}@,")
        else:
            ens.append(f"        out.0.{fname}@.len() == out.0.n as int,")
            ens.append(
                f"        forall|k: int| #![trigger out.0.{fname}@[k]] 0 <= k < out.0.n as int ==> out.0.{fname}@[k] == scan_full_{t}(s).{fname}@[out.1@[k]],"
            )
    ensures = "\n".join(ens)
    from declarative_spec.assemble import _local_ident, _read_column_prelude

    prelude, args = _read_column_prelude("LEMMA_SCAN_PATH", t, fields)
    prelude = prelude.replace('std::fs::read("LEMMA_SCAN_PATH")', "std::fs::read(path)")
    init = ", ".join([f"n: n_{t}"] + [f"{f}: {t}_{_local_ident(f)}" for f, _ in fields])
    del args
    clone = ", ".join(["n: c.n"] + [f"{f}: c.{f}.clone()" for f, _ in fields])
    return f"""
// ---- AGENT_SCAN {t}: the one DuckDB-filter trust (docs/TRUSTED_FAMILIES.md; authorized by Emil 2026-10-17) ----
// Ask DuckDB for the rows of `{t}` that satisfy a conjunction of atoms over integer columns:
//     let mut pred: Vec<ScanAtom_{t}> = Vec::new();
//     pred.push(ScanAtom_{t}::Range(ScanCol_{t}::<column>, lo, hi));        // lo <= cell <= hi
//     let out = scan_where_{t}(<p>_scan, &pred);   // <p>: the run_query parameter of type &Cols_{t}; out.0: the rows, out.1@: their row numbers
//     proof {{ lemma_scan_rows_{t}(<p>, pred@, <p>.n as int); }}
// run_query requires `scan_full_{t}(<p>_scan) == *<p>`, so out.0 holds exactly the rows i of `<p>` with scan_holds_{t}(<p>, pred@, i), in order.
// The ensures of run_query is unchanged: rows the predicate drops must be rows the query does not need, or the proof fails.
#[allow(non_camel_case_types)]
pub enum ScanCol_{t} {{ {variants} }}

#[allow(non_camel_case_types)]
pub enum ScanAtom_{t} {{
    Range(ScanCol_{t}, i128, i128),
    In(ScanCol_{t}, Vec<i128>),
}}

pub open spec fn scan_cell_{t}(c: &Cols_{t}, col: ScanCol_{t}, i: int) -> int {{
    match col {{
{cell_arms}
    }}
}}

pub open spec fn scan_cell_ok_{t}(c: &Cols_{t}, col: ScanCol_{t}, i: int) -> bool {{
    match col {{
{ok_arms}
    }}
}}

pub open spec fn scan_atom_holds_{t}(c: &Cols_{t}, a: ScanAtom_{t}, i: int) -> bool {{
    match a {{
        ScanAtom_{t}::Range(col, lo, hi) => scan_cell_ok_{t}(c, col, i) && lo as int <= scan_cell_{t}(c, col, i) && scan_cell_{t}(c, col, i) <= hi as int,
        ScanAtom_{t}::In(col, vs) => scan_cell_ok_{t}(c, col, i) && exists|j: int| 0 <= j < vs@.len() && vs@[j] as int == scan_cell_{t}(c, col, i),
    }}
}}

pub open spec fn scan_holds_{t}(c: &Cols_{t}, pred: Seq<ScanAtom_{t}>, i: int) -> bool {{
    forall|k: int| #![trigger pred[k]] 0 <= k < pred.len() ==> scan_atom_holds_{t}(c, pred[k], i)
}}

pub open spec fn scan_rows_{t}(c: &Cols_{t}, pred: Seq<ScanAtom_{t}>, n: int) -> Seq<int>
    decreases n,
{{
    if n <= 0 {{
        Seq::<int>::empty()
    }} else if scan_holds_{t}(c, pred, n - 1) {{
        scan_rows_{t}(c, pred, n - 1).push(n - 1)
    }} else {{
        scan_rows_{t}(c, pred, n - 1)
    }}
}}

// Host-proved (not trusted): what the row list is.
pub proof fn lemma_scan_rows_{t}(c: &Cols_{t}, pred: Seq<ScanAtom_{t}>, n: int)
    requires
        0 <= n,
    ensures
        forall|k: int| 0 <= k < scan_rows_{t}(c, pred, n).len() ==> 0 <= #[trigger] scan_rows_{t}(c, pred, n)[k] < n,
        forall|k: int| 0 <= k < scan_rows_{t}(c, pred, n).len() ==> scan_holds_{t}(c, pred, #[trigger] scan_rows_{t}(c, pred, n)[k]),
        forall|k1: int, k2: int| 0 <= k1 < k2 < scan_rows_{t}(c, pred, n).len() ==> #[trigger] scan_rows_{t}(c, pred, n)[k1] < #[trigger] scan_rows_{t}(c, pred, n)[k2],
        forall|i: int| 0 <= i < n && #[trigger] scan_holds_{t}(c, pred, i) ==> exists|k: int| 0 <= k < scan_rows_{t}(c, pred, n).len() && scan_rows_{t}(c, pred, n)[k] == i,
    decreases n,
{{
    if n > 0 {{
        lemma_scan_rows_{t}(c, pred, n - 1);
        let r = scan_rows_{t}(c, pred, n - 1);
        if scan_holds_{t}(c, pred, n - 1) {{
            let s = r.push(n - 1);
            assert(scan_rows_{t}(c, pred, n) == s);
            assert forall|i: int| 0 <= i < n && #[trigger] scan_holds_{t}(c, pred, i) implies exists|k: int| 0 <= k < s.len() && s[k] == i by {{
                if i == n - 1 {{
                    assert(s[s.len() - 1] == i);
                }} else {{
                    let k = choose|k: int| 0 <= k < r.len() && r[k] == i;
                    assert(s[k] == i);
                }}
            }}
        }} else {{
            assert(scan_rows_{t}(c, pred, n) == r);
            assert forall|i: int| 0 <= i < n && #[trigger] scan_holds_{t}(c, pred, i) implies exists|k: int| 0 <= k < r.len() && r[k] == i by {{
                assert(i != n - 1);
                assert(0 <= i < n - 1 && scan_holds_{t}(c, pred, i));
            }}
        }}
    }}
}}

#[verifier::external_body]
pub struct Scan_{t} {{
    dir: String,
    cache: std::cell::RefCell<std::collections::HashMap<String, Cols_{t}>>,
}}

pub uninterp spec fn scan_full_{t}(s: &Scan_{t}) -> Cols_{t};

// TRUSTED (the one authorized DuckDB-filter item): DuckDB returns exactly the rows of the full table that satisfy `pred`, in table order.
#[verifier::external_body]
pub fn scan_where_{t}(s: &Scan_{t}, pred: &Vec<ScanAtom_{t}>) -> (out: (Cols_{t}, Ghost<Seq<int>>))
    ensures
        out.1@ == scan_rows_{t}(&scan_full_{t}(s), pred@, scan_full_{t}(s).n as int),
        out.0.n as int == out.1@.len(),
{ensures}
{{
    let key = scan_key_{t}(pred);
    let mut cache = s.cache.borrow_mut();
    let c = cache.entry(key.clone()).or_insert_with(|| scan_read_{t}(&lemma_scan_file(&s.dir, "{t}", &key)));
    (Cols_{t} {{ {clone} }}, Ghost::assume_new())
}}

#[verifier::external]
fn scan_key_{t}(pred: &Vec<ScanAtom_{t}>) -> String {{
    let mut parts: Vec<String> = Vec::new();
    for a in pred.iter() {{
        parts.push(match a {{
            ScanAtom_{t}::Range(col, lo, hi) => format!("R:{{}}:{{}}:{{}}", scan_col_name_{t}(col), lo, hi),
            ScanAtom_{t}::In(col, vs) => format!("I:{{}}:{{}}", scan_col_name_{t}(col), vs.iter().map(|v| v.to_string()).collect::<Vec<_>>().join(",")),
        }});
    }}
    parts.join(";")
}}

#[verifier::external]
fn scan_col_name_{t}(col: &ScanCol_{t}) -> &'static str {{
    match col {{
{key_arms}
    }}
}}

#[verifier::external]
fn scan_read_{t}(path: &str) -> Cols_{t} {{
{prelude}    Cols_{t} {{ {init} }}
}}

#[verifier::external]
pub fn scan_open_{t}(dir: &str) -> Scan_{t} {{
    Scan_{t} {{ dir: dir.to_string(), cache: std::cell::RefCell::new(std::collections::HashMap::new()) }}
}}
"""


_RUNTIME = """
// ---- AGENT_SCAN runtime (fixed host code, part of the DuckDB-filter trust): the column file of one scan ----
// scan_<table>_<fnv64 of key>.bin in the data directory, written by research_loop/scan_export.py (the `.key` file beside it holds the
// key, checked here). A missing file is exported on demand: `<dir>/scan_cmd` holds the working directory and the command, one per line.
#[verifier::external]
fn lemma_scan_file(dir: &str, table: &str, key: &str) -> String {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in key.as_bytes() {
        h ^= *b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    let base = format!("{}/scan_{}_{:016x}", dir, table, h);
    let bin = format!("{}.bin", base);
    if !std::path::Path::new(&bin).exists() {
        let cmd = std::fs::read_to_string(format!("{}/scan_cmd", dir)).expect("scan_cmd: the host did not prepare agent scans");
        let lines: Vec<&str> = cmd.lines().collect();
        let status = std::process::Command::new(lines[1])
            .args(&lines[2..])
            .args(["--table", table, "--key", key])
            .current_dir(lines[0])
            .status()
            .expect("scan export did not start");
        assert!(status.success(), "scan export failed for {} {}", table, key);
    }
    let stored = std::fs::read_to_string(format!("{}.key", base)).expect("scan key file");
    assert!(stored == key, "scan file {} holds key {:?}, not {:?}", bin, stored, key);
    bin
}
"""


SCAN_START = "// AGENT_SCAN_START"
SCAN_END = "// AGENT_SCAN_END"


def without_scans(spec: str) -> str:
    """The spec minus the scan block and handles: what the transpiler states without ``agent_scan`` (tests of the emitter's own trust surface)."""
    start, end = spec.find(SCAN_START), spec.find(SCAN_END)
    if start == -1:
        return spec
    out = spec[:start] + spec[end + len(SCAN_END) + 1 :]
    out = re.sub(r", \w+_scan: &Scan_\w+", "", out)
    return re.sub(r"        scan_full_\w+\(\w+_scan\) == \*\w+,\n", "", out)


def fnv64(key: str) -> str:
    """The file-name hash of a scan key (the same FNV-1a the binary computes)."""
    h = 0xCBF29CE484222325
    for b in key.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001B3) % (1 << 64)
    return f"{h:016x}"


def add_scans(spec: str) -> str:
    """The spec with one scan family per table and one ``<t>_scan: &Scan_<t>`` parameter per table (``requires`` ties it to ``<t>``)."""
    structs = re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", spec)
    sig = re.search(r"pub fn run_query\(([^)]*)\)", spec)
    if not structs or sig is None or "// AGENT_HELPERS_START" not in spec:
        return spec
    params = re.findall(r"(\w+):\s*&Cols_([A-Za-z0-9_]+)", sig.group(1))
    if len({s for _p, s in params}) != len(params):
        return spec  # a self join: two parameters share one table; no scan handles (one handle per parameter would be ambiguous)
    blocks = [_RUNTIME]
    for struct, body in structs:
        blocks.append(_items(struct.removeprefix("Cols_"), _FIELD.findall(body)))
    out = spec.replace("// AGENT_HELPERS_START", f"{SCAN_START}{''.join(blocks)}{SCAN_END}\n// AGENT_HELPERS_START", 1)
    extra = ", ".join(f"{p}_scan: &Scan_{s}" for p, s in params)
    new_sig = f"pub fn run_query({sig.group(1)}, {extra})"
    out = out.replace(sig.group(0), new_sig, 1)
    req = "".join(f"        scan_full_{s}({p}_scan) == *{p},\n" for p, s in params)
    head, sep, tail = out.partition(new_sig)
    tail = re.sub(r"\n    requires\n", "\n    requires\n" + req, tail, count=1)
    return head + sep + tail
