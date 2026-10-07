"""Prompt for the declarative flag. The recursive agent prompt is a different file."""

from __future__ import annotations

import re
from pathlib import Path

from declarative_spec import dense_budget
from declarative_spec.example_registry import INDEX_GROUPS as _INDEX_GROUPS
from declarative_spec.example_registry import MORE_EXAMPLES as _MORE_EXAMPLES

_COUNT_SHAPE = """
let mut counts: Vec<u64> = Vec::new();
let mut c: usize = 0;
while c < KEY_CAP_t_k
    invariant
        c <= KEY_CAP_t_k,
        counts@.len() == c as int,
        forall|j: int| 0 <= j < c as int ==> counts@[j] == 0u64,
    decreases KEY_CAP_t_k - c,
{
    counts.push(0u64);
    c = c + 1;
}
let mut i: usize = cols.n;
while i > 0
    invariant
        i <= cols.n,
        valid_cols_t(cols),
        counts@.len() == KEY_CAP_t_k as int,
        forall|kk: int| 0 <= kk < KEY_CAP_t_k as int ==> counts@[kk] as int == group_count(cols.k@, i as int, kk as u64),
    decreases i,
{
    let i_old = i;
    i = i - 1;
    let k = cols.k[i];
    let idx: usize = k as usize;
    let prev = counts[idx];
    proof {
        let keys = cols.k@;
        let start = i_old as int;
        let ii = i as int;
        assert(keys.len() == cols.n as int);
        assert(ii + 1 == start);
        assert(keys[ii] == k);
        assert(0 <= (k as int) && (k as int) < (KEY_CAP_t_k as int));
        assert(idx as int == k as int);
        lemma_group_count_le_suffix(keys, ii, k);
        lemma_group_count_le_suffix(keys, start, k);
        lemma_group_count_witness(keys, start, k);
        assert(prev as int == group_count(keys, start, k));
        assert(group_count(keys, ii, k) == group_count(keys, start, k) + 1);
        assert(prev as int + 1 <= ROW_CAP_t);
    }
    let next = prev + 1;
    counts[idx] = next;
    proof {
        let keys = cols.k@;
        let ii = i as int;
        assert(counts@[k as int] == next);
        assert(next as int == group_count(keys, ii, k));
    }
}
let mut map: HashMapWithView<u64, u64> = HashMapWithView::new();
let mut c2: usize = 0;
while c2 < KEY_CAP_t_k
    invariant
        c2 <= KEY_CAP_t_k,
        counts@.len() == KEY_CAP_t_k as int,
        i == 0,
        forall|kk: int| 0 <= kk < KEY_CAP_t_k as int ==> counts@[kk] as int == group_count(cols.k@, 0, kk as u64),
        forall|k: u64|
            #[trigger] map@.contains_key(k) ==> k < (KEY_CAP_t_k as u64)
                && map@[k] == counts@[k as int]
                && counts@[k as int] > 0,
        forall|kk: int| 0 <= kk < c2 as int && counts@[kk] > 0 ==> map@.contains_key(kk as u64),
    decreases KEY_CAP_t_k - c2,
{
    let v = counts[c2];
    let ghost before = map@;
    if v > 0 {
        map.insert(c2 as u64, v);
    }
    proof {
        assert(counts@[c2 as int] == v);
        if v > 0 {
            assert(map@ == before.insert(c2 as u64, v));
            assert(map@[c2 as u64] == v);
        }
        assert forall|k: u64|
            #[trigger] map@.contains_key(k) ==> k < (KEY_CAP_t_k as u64)
                && map@[k] == counts@[k as int]
                && counts@[k as int] > 0
        by {
            if map@.contains_key(k) {
                if v > 0 && k == (c2 as u64) {
                    assert(map@[k] == v);
                    assert(counts@[c2 as int] == v);
                } else {
                    assert(before.contains_key(k));
                    assert(map@[k] == before[k]);
                }
            }
        };
    }
    c2 = c2 + 1;
}
proof {
    let keys = cols.k@;
    assert(c2 == KEY_CAP_t_k);
    assert forall|k: u64|
        #[trigger] map@.contains_key(k) <==> (exists|j: int| 0 <= j < cols.n as int && keys[j] == k)
    by {
        if map@.contains_key(k) {
            assert(counts@[k as int] as int == group_count(keys, 0, k));
            assert(counts@[k as int] > 0);
            lemma_group_count_witness(keys, 0, k);
        }
        if exists|j: int| 0 <= j < cols.n as int && keys[j] == k {
            let j = choose|j: int| 0 <= j < cols.n as int && keys[j] == k;
            assert(keys[j] == k);
            assert((k as int) < (KEY_CAP_t_k as int));
            lemma_group_count_witness(keys, 0, k);
            assert(group_count(keys, 0, k) > 0);
            assert(counts@[k as int] > 0);
            assert(map@.contains_key(k));
        }
    };
    assert forall|k: u64|
        #[trigger] map@.contains_key(k) ==> map@[k] as int == group_count(keys, 0, k)
    by {
        if map@.contains_key(k) {
            assert(map@[k] == counts@[k as int]);
            assert(counts@[k as int] as int == group_count(keys, 0, k));
        }
    };
}
map
""".strip()


_FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "declarative_proofs"

# Shapes with a verified worked example, by recipe name. The file is a `run_query` body that
# Verus proved against a spec of that shape (column and table names differ in your spec).
_EXAMPLES: dict[str, tuple[str, str]] = {
    "int_map": (
        "int_group_count.rs",
        "one table, integer group key, COUNT(*), result `HashMapWithView<int, u64>`",
    ),
    "string_map": (
        "string_group_count.rs",
        "one table, string group key, COUNT(*), result `StringHashMap<u64>`",
    ),
    "group_count": (
        "group_count_where.rs",
        "one table, filtered GROUP BY, COUNT(*), result `Vec<OutRow>`",
    ),
    "group_sum": (
        "group_sum_where.rs",
        "one table, filtered GROUP BY, SUM, result `Vec<OutRow>`",
    ),
    "join_group_sum": (
        "join_group_sum.rs",
        "two tables joined on a key, GROUP BY, SUM, result `Vec<OutRow>`",
    ),
    "ungrouped_product": (
        "ungrouped_decimal_product_sum.rs",
        "one table, filtered ungrouped SUM of a product of two decimal columns, with a helper lemma",
    ),
    "projection_where": (
        "projection_where.rs",
        "one table, `SELECT cols WHERE ...` (no GROUP BY), result `Vec<OutRow>`",
    ),
    "projection_join": (
        "projection_join.rs",
        "two tables joined, plain projection `SELECT t.a, u.w ... JOIN ...`",
    ),
    "projection_correlated_max": (
        "projection_correlated_max.rs",
        "projection with a correlated scalar subquery `a = (SELECT MAX(a) ... WHERE same key)`",
    ),
    "projection_distinct": (
        "projection_distinct.rs",
        "`SELECT DISTINCT cols ... WHERE ...`",
    ),
    "projection_join_correlated_max": (
        "hard/projection_join_correlated_max_topk.rs",
        "projection over a TWO-table join with a correlated scalar MAX subquery (or a join to a per-key MAX), ORDER BY ... LIMIT k: "
        '"next same-key row" chains and a sorted top-k `Vec` (plain string mode; dictionary mode has its own example '
        "`hard/dict_projection_join_correlated_max_topk.rs`; it proves but is slow: a proof template, not a speed template)",
    ),
    "dict_projection_join_correlated_max": (
        "hard/dict_projection_join_correlated_max_topk.rs",
        "dictionary string mode: projection over a TWO-table join with a per-key MAX (correlated subquery or derived table), "
        "ORDER BY value DESC then two string keys, LIMIT k: per-(adsh, tag) max in a `HashMapWithView` keyed by a packed code pair, "
        "num's dictionary translated to sub's codes once, sub rows chained per code, sorted top-k `Vec` with exec string comparison "
        "(verified against the real SEC catalog spec, not run on the 39M-row table; the per-pair max map grows with the distinct pairs; no table over a product of dictionary sizes)",
    ),
    "projection_top_k": (
        "projection_top_k.rs",
        "projection with `ORDER BY ... LIMIT k` (multiplicity and the omitted-row clause)",
    ),
    "hard_group_strings": (
        "hard/group_decimal_sums_string_keys_sorted.rs",
        "one table, GROUP BY two string columns, several decimal SUMs and COUNT(*), ORDER BY the keys (TPC-H Q1 shape)",
    ),
    "hard_distinct": (
        "hard/string_tuple_count_distinct_sorted.rs",
        "one table, tuple-of-strings GROUP BY, COUNT(*) and COUNT(DISTINCT), ORDER BY the count (sorted `Vec::insert`)",
    ),
    "join_min_probe": (
        "join_min_stringhashmap_probe.rs",
        "two tables joined on a string key, ungrouped MIN/MAX with a string-literal filter (`StringHashMap` probe)",
    ),
    "dict_group": (
        "dict_group_count_dense.rs",
        "dictionary string mode: GROUP BY a string key as a dense array over dictionary codes, `Vec<OutRow>` with the key as a String",
    ),
    "dict_join": (
        "dict_join_probe_sum.rs",
        "dictionary string mode: JOIN ON a string key (one dictionary per table): per-code count array over the small side, "
        "NUM's dictionary translated to its codes once through a `StringHashMap`, then two array reads per row",
    ),
    "dict_anti_join": (
        "hard/dict_anti_join_group_topk.rs",
        "dictionary string mode: NOT EXISTS / LEFT JOIN ... IS NULL anti-join on three string keys into a two-key GROUP BY with HAVING, ORDER BY the count and LIMIT "
        "(the pre dictionaries are translated to num's codes, the pre keys packed into one `HashMapWithView<i128, bool>`; for a positive EXISTS flip the membership test)",
    ),
    "dict_join3": (
        "hard/dict_join3_group_topk.rs",
        "dictionary string mode: a THREE-table join on string keys with a four-key GROUP BY, SUM and COUNT, ORDER BY the sum and LIMIT "
        "(chain the many side by a packed key, group map over packed codes, parallel Vecs, witness-index function for the top-k)",
    ),
    "dict_filter": (
        "dict_string_filter_minmax.rs",
        "dictionary string mode: a string-literal filter becomes one code comparison (literal's code looked up once)",
    ),
    "ungrouped_minmax": (
        "ungrouped_minmax_string_filter.rs",
        "one table, filtered ungrouped MIN and MAX of an integer column, with a string-literal comparison in the filter",
    ),
    "ungrouped": (
        "ungrouped_sum_where.rs",
        "one table, filtered ungrouped SUM, result `Vec<OutRow>` of one row",
    ),
}

# Helper-region file that goes with an example body (a few lines each; the body calls it).
_EXAMPLE_HELPERS: dict[str, str] = {
    "projection_where": "projection_where.helpers.rs",
    "projection_join": "projection_where.helpers.rs",
    "projection_correlated_max": "projection_int_key.helpers.rs",
    "projection_top_k": "projection_top_k.helpers.rs",
}

# Features of a spec for which the host has no worked example. They are not impossible, they are
# long: say so, so that a model does not walk into them blind.
_HARD_FEATURES: tuple[tuple[str, str], ...] = (
    ("count_distinct_", "COUNT(DISTINCT ...) (an existential over earlier rows)"),
    ("sq_", "a scalar or correlated subquery"),
    ("exists_", "EXISTS / IN / NOT EXISTS against another table"),
    ("proj_key", "a projection with no GROUP BY (one result row per input row)"),
    ("avg_", "AVG (a float quotient of a sum and a count)"),
)


def _features(spec_text: str) -> dict:
    """The facts about a spec that pick its recipe (the result kind is a string, the rest are bools)."""
    result = re.search(r"pub fn run_query\([^)]*\)\s*->\s*\(res:\s*([^)]+)\)", spec_text)
    ty = result.group(1).strip() if result else ""
    tables = len(re.findall(r"pub struct Cols_", spec_text))
    head = spec_text.split("pub fn run_query(")[0]
    tail = spec_text.split("pub fn run_query")[-1]
    if ty.startswith("HashMapWithView"):
        kind = "int_map"
    elif ty.startswith("StringHashMap"):
        kind = "string_map"
    elif ty.startswith("Vec<OutRow>"):
        kind = "rows"
    else:
        kind = "other"
    return {
        "ty": ty,
        "tables": tables,
        "kind": kind,
        "dict": "__dict" in spec_text,
        "dense": "KEY_CAP_" in spec_text,
        "proj": "proj_key(" in spec_text,  # a projection: one result row per input row
        "grouped": "out_row_ok(" in spec_text,
        "copies": "out_copies(" in spec_text,  # multiplicity; absent for SELECT DISTINCT
        "sorted": bool(re.search(r"res@\[i \+ 1\]", tail)),  # ORDER BY: the result is a sorted sequence
        "sq": bool(re.search(r"fn sq_\d+\([^)]*\bbound\b", spec_text)),  # a MAX-style scalar subquery with a bound (an uncorrelated AVG has none)
        "exists": bool(re.search(r"\bexists_\d+\(", spec_text)),
        "limit": bool(re.search(r"res@\.len\(\) <= \d+", spec_text)),
        "multi": tables >= 2,
        "multi3": tables >= 3,
        "product": bool(re.search(r"as int\)\)?\s*\*\s*\(", head)),
        "minmax": bool(re.search(r"\b(?:min|max)_\w+\(", head)),
        "count_distinct": bool(re.search(r"\bcount_distinct_", spec_text)),
        "str_tuple": "(Seq<char>, Seq<char>)" in spec_text,
        "sum": bool(re.search(r"\bsum_\w+\(", spec_text)),
    }


# Shape -> recipe, as a table. A rule matches when every feature it names has the value it gives (a feature it does
# not name does not matter); the FIRST matching rule wins, so the rules go from the most specific shape to the most
# general one, and the encoding mode (dictionary or plain) is just one more feature. A dictionary-mode projection used
# to fall into the ungrouped filter recipe because the dictionary test came first and the projection rules were never
# reached; here a projection is decided before any dictionary rule.
_RECIPE_RULES: tuple[tuple[str, dict], ...] = (
    ("int_map", {"kind": "int_map", "dense": False}),
    ("dense_map", {"kind": "int_map", "dense": True}),
    ("string_map", {"kind": "string_map"}),
    # projections (no GROUP BY), plain and dictionary mode alike
    (
        "dict_projection_join_correlated_max",
        {"kind": "rows", "proj": True, "sq": True, "multi": True, "dict": True},
    ),
    (
        "projection_join_correlated_max",
        {"kind": "rows", "proj": True, "sq": True, "multi": True},
    ),
    ("projection_correlated_max", {"kind": "rows", "proj": True, "sq": True}),
    ("projection_distinct", {"kind": "rows", "proj": True, "copies": False}),
    ("projection_top_k", {"kind": "rows", "proj": True, "sorted": True}),
    ("projection_join", {"kind": "rows", "proj": True, "multi": True}),
    ("projection_where", {"kind": "rows", "proj": True}),
    # dictionary-coded strings
    ("dict_anti_join", {"kind": "rows", "dict": True, "multi": True, "exists": True}),
    ("dict_join3", {"kind": "rows", "dict": True, "multi3": True, "limit": True}),
    ("dict_join", {"kind": "rows", "dict": True, "multi": True}),
    ("dict_group", {"kind": "rows", "dict": True, "grouped": True}),
    ("dict_filter", {"kind": "rows", "dict": True}),
    # plain strings: ungrouped aggregates
    ("ungrouped_product", {"kind": "rows", "grouped": False, "product": True}),
    (
        "join_min_probe",
        {"kind": "rows", "grouped": False, "minmax": True, "multi": True},
    ),
    ("ungrouped_minmax", {"kind": "rows", "grouped": False, "minmax": True}),
    ("ungrouped", {"kind": "rows", "grouped": False}),
    # plain strings: grouped aggregates
    ("join_group_sum", {"kind": "rows", "multi": True}),
    ("hard_distinct", {"kind": "rows", "count_distinct": True}),
    ("hard_group_strings", {"kind": "rows", "str_tuple": True}),
    ("group_sum", {"kind": "rows", "sum": True}),
    ("group_count", {"kind": "rows"}),
)


def route(features: dict) -> str:
    """The recipe of a spec's features (`none` when no rule matches)."""
    for recipe, needs in _RECIPE_RULES:
        if all(features[name] == value for name, value in needs.items()):
            return recipe
    return "none"


def spec_shape(spec_text: str) -> dict:
    """Which recipe matches this spec's result type, and which hard features it has."""
    f = _features(spec_text)
    recipe = route(f)
    hard = [what for needle, what in _HARD_FEATURES if re.search(rf"\b{needle}", spec_text)]
    if f["limit"] and recipe in ("group_count", "group_sum", "join_group_sum"):
        hard.append("a LIMIT with ORDER BY over groups (top-K selection)")
    covered = {  # features the recipe's own worked example already covers: no "no worked example" warning for them
        "dict_anti_join": ("EXISTS / IN / NOT EXISTS",),
        "projection_join_correlated_max": (
            "a projection with no GROUP BY",
            "a scalar or correlated subquery",
        ),
        "dict_projection_join_correlated_max": (
            "a projection with no GROUP BY",
            "a scalar or correlated subquery",
        ),
    }
    covered_by_family = ("a projection with no GROUP BY",) if recipe.startswith("projection_") else ()
    hard = [h for h in hard if not h.startswith(covered.get(recipe, ()) + covered_by_family)]
    if f["multi"] and f["count_distinct"]:
        hard.append("a join together with COUNT(DISTINCT ...)")
    return {
        "result_type": f["ty"],
        "recipe": recipe,
        "tables": f["tables"],
        "hard": hard,
        "dict": f["dict"],
    }


def _dict_only(name: str) -> bool:
    return Path(name).name.startswith("dict_")


def registered_examples() -> list[tuple[str, str]]:
    """Every mountable example as (path under the fixtures directory, one line saying what shape it proves)."""
    seen: dict[str, str] = {}
    for name, what in [*_EXAMPLES.values(), *_MORE_EXAMPLES, *_FLOAT_EXAMPLES]:
        seen.setdefault(name, what)
    return sorted(seen.items())


def helper_files() -> list[str]:
    return sorted({*_EXAMPLE_HELPERS.values(), "projection_null_cell.helpers.rs"})


def example_index_markdown(dict_mode_on: bool) -> str:
    """The generated shape -> file -> what-it-proves table for `context/ro/examples/INDEX.md`."""
    groups: dict[str, list[str]] = {title: [] for _pat, title in _INDEX_GROUPS}
    for name, what in registered_examples():
        if _dict_only(name) and not dict_mode_on:
            continue
        lines = len((_FIXTURES / name).read_text().splitlines())
        title = next(t for pat, t in _INDEX_GROUPS if re.search(pat, name))
        groups[title].append(f"| {what} | `{name}` | {lines} |")
    out = [
        "# Worked examples: shape -> file -> what it proves",
        "",
        "Every file is a `run_query` body (plus helpers) that Verus verified against a spec of the shape in the first column; your",
        "table, column and field names differ. Find the closest row, then read THAT file (long ones: the header comment first, then the",
        "loop you need with the Read tool's offset/limit; do not read the whole directory). `parallel_*` and `float_*` rows are techniques",
        "to combine with a base shape. Helper files (`*.helpers.rs`) go in the helper region beside their body.",
    ]
    for title, rows in groups.items():
        if rows:
            out += [
                "",
                f"## {title}",
                "",
                "| shape | file | lines |",
                "|---|---|---|",
                *rows,
            ]
    return "\n".join(out) + "\n"


def mount_examples(ro: Path) -> None:
    """Copy the verified example bodies and a generated `INDEX.md` to ``ro/examples/`` (the prompt points at the index)."""
    from declarative_spec.string_encoding import dict_mode

    dest = ro / "examples"
    dest.mkdir(parents=True, exist_ok=True)
    dict_on = dict_mode()
    for name in [n for n, _w in registered_examples() if dict_on or not _dict_only(n)] + helper_files():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((_FIXTURES / name).read_text())
    (dest / "INDEX.md").write_text(example_index_markdown(dict_on))


_FLOAT_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("float_sum.rs", "ungrouped SUM of a DOUBLE column"),
    ("float_product_sum.rs", "ungrouped SUM of a product of DOUBLE columns"),
    ("float_filter_count.rs", "COUNT under a DOUBLE comparison"),
    ("float_min_max.rs", "MIN and MAX of a DOUBLE column"),
    ("float_avg_int.rs", "ungrouped AVG of an integer column (DOUBLE result)"),
    ("float_avg_decimal.rs", "ungrouped AVG of a DECIMAL column"),
    ("float_avg_float.rs", "ungrouped AVG of a DOUBLE column"),
    ("float_group_sum_having.rs", "GROUP BY, SUM(double), HAVING on the sum"),
    (
        "float_group_sum_order_limit.rs",
        "GROUP BY, SUM(double), ORDER BY the sum, LIMIT",
    ),
    ("float_group_avg_having.rs", "GROUP BY, AVG(double), HAVING on the average"),
    ("float_group_avg_decimal.rs", "GROUP BY, AVG over a DECIMAL column"),
    (
        "float_order_limit.rs",
        "ORDER BY a DOUBLE column, LIMIT (selection by repeated minimum)",
    ),
    (
        "float_avg_group_count_distinct.rs",
        "tuple-of-strings GROUP BY, COUNT, COUNT DISTINCT and AVG (long)",
    ),
)


def _nullable_section(spec_text: str) -> list[str]:
    """Nullable columns: the validity vector is part of the row, `row_hit` already reads it."""
    if "__valid" not in spec_text:
        return []
    return [
        "",
        "## NULLs (this spec has a nullable column)",
        "",
        "A nullable column `c` has a validity vector `c__valid: Vec<bool>` beside its values; where it is false the value",
        "`c[i]` is an arbitrary default and means nothing. The spec already says what SQL says: `row_hit` reads the bit (a",
        "comparison with a NULL cell is not true, `IS NULL` is `!c__valid@[i]`), an aggregate skips NULL cells (its",
        "per-aggregate hit function includes `c__valid@[i]`), and all NULL group keys form ONE group (a key `(false, default)`,",
        "an `Option` output field). In the body test `t.c__valid[i]` wherever the spec does, before comparing or adding",
        "`t.c[i]`; never compare a value cell alone. Add `assert(t.c__valid@.len() == t.n as int)` beside the other length facts.",
    ]


def _float_section(spec_text: str) -> list[str]:
    """Float recipe: floats are exact reals under the host's f64 idealization; list the verified float examples."""
    structs = "".join(re.findall(r"pub struct (?:Cols_\w+|OutRow)\s*\{([^}]*)\}", spec_text))
    if "f64" not in structs and not re.search(r"-> \(res: [^)]*f64", spec_text):
        return []
    lines = [
        "",
        "## Floats (this spec has a DOUBLE column or result)",
        "",
        "A float is exact real arithmetic here (rounding differences against the reference engine are an accepted",
        "limitation; there is no epsilon). Keep `f64_literals_ok()` and `acc as real == <spec fold>` in the loop invariant,",
        "call `lemma_f64_add_defined` / `sub_defined` / `mul_defined` before an operation and `lemma_f64_add_within` /",
        "`sub_within` / `mul_within` after it, compare with `lemma_f64_lt_real` / `gt_real` / ..., divide with",
        "`lemma_f64_div_defined` / `lemma_f64_div_real`, and cast integers with `host_u64_to_f64` / `host_i128_to_f64`.",
        "Verified float examples in `context/ro/examples/`:",
        "",
    ]
    lines += [f"- `{name}`: {what}" for name, what in _FLOAT_EXAMPLES]
    return lines


_ROW_CAP = re.compile(r"pub const ROW_CAP_(\w+): usize = (\d+);")
_BIG_TABLE_ROWS = 1_000_000


def hardware_section() -> list[str]:
    """The machine the timed run happens on, read at prompt-build time: raw `lscpu` (plus /sys cache lines if lscpu has none) and plain guidance.

    Not invented: if `lscpu` cannot be run the section says so. Guidance is guidance, not a measurement."""
    import os
    import subprocess

    from declarative_spec.pipeline import target_cpu

    try:
        out = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ["## Hardware", "", "hardware info unavailable (`lscpu` could not be run on the host that built this prompt); do not assume core counts or cache sizes.", ""]
    keep = [ln for ln in out.splitlines() if ln.split(":")[0].strip() in ("Model name", "CPU(s)", "Thread(s) per core", "Core(s) per socket", "Socket(s)", "L1d cache", "L2 cache", "L3 cache", "NUMA node(s)")]
    if not any(ln.startswith("L1d") for ln in keep):  # some lscpu builds omit the caches
        base = "/sys/devices/system/cpu/cpu0/cache"
        for idx in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            try:
                level, kind, size = (open(f"{base}/{idx}/{f}").read().strip() for f in ("level", "type", "size"))
            except OSError:
                continue
            keep.append(f"L{level} {kind} cache (cpu0): {size}")
    mem = next((ln.split()[1] for ln in open("/proc/meminfo") if ln.startswith("MemTotal:")), "unknown")
    return [
        "## Hardware (this machine; the timed run and the reference engine both run here)",
        "",
        "```",
        *keep,
        f"MemTotal: {mem} kB",
        f"compile target: -C target-cpu={target_cpu()} (the CPU may have more SIMD than this; the binary uses the target only)",
        "reference engine: DuckDB, threads=8, memory_limit=3GB",
        "```",
        "",
        "Guidance, not measurement: about one worker per PHYSICAL core (cores = Core(s) per socket x Socket(s)) for memory-bound scans, since SMT threads add little;",
        "give each worker one contiguous row range and its own accumulators (no shared mutable cell between workers: false sharing); the L3 is far smaller than a large column,",
        "so a big scan is bandwidth-bound and narrower cells and fewer passes help more than arithmetic; keep per-block working sets within L1/L2 (a few thousand elements per chunk);",
        "write the hot loop branch-free (accumulate `acc + (value & mask)` or `count + (hit as u64)` instead of `if hit { .. }`) so the compiler can vectorize it.",
        "The worked parallel example uses 8 workers as a literal; replace it by the worker count you choose, consistently everywhere the example uses it.",
        "",
    ]


def _scale_section(spec_text: str) -> list[str]:
    """The official table sizes (the spec's row caps) and what they mean for a sequential loop versus the all-core bar."""
    caps = {m.group(1): int(m.group(2)) for m in _ROW_CAP.finditer(spec_text)}
    if not caps:
        return []
    from declarative_spec import parallel

    sizes = ", ".join(f"`{t}` {n:,}" for t, n in sorted(caps.items(), key=lambda kv: -kv[1]))
    lines = [
        "## Official size and the bar",
        "",
        f"The timed run is on the full tables (row caps in the spec: {sizes}), not on the 50,000-row iterate cap that",
        "`run_runquery` uses by default: a time or speedup at 50k says nothing about the official run. The bar is the reference",
        "engine on ALL cores. One thread does not beat it on a scan or aggregate over millions of rows.",
    ]
    if max(caps.values()) < _BIG_TABLE_ROWS:
        return lines + [""]
    if parallel.is_parallel(spec_text):
        lines += [
            "Order: (1) get ANY body to `N verified, 0 errors` first; sequential is fine, and `submit_runquery` it as soon as it",
            "verifies (a later submit replaces it, re-submitting costs nothing, and a session killed at the wall saves nothing that was",
            "not submitted). (2) Read the `speedup` field of that run. At or above the bar: you are done. Below the bar: only now try",
            "the parallel recipe below (workers over row ranges) as an upgrade. (3) Submit the parallel body only if it verifies and its",
            "`speedup` is higher; never replace a submitted verified body with an unverified or slower one. If the upgrade does not",
            "verify after a few checks, stop and keep the sequential submission (say its `speedup` is below 1).",
        ]
    else:
        lines += ["This spec has no parallel parameters, so a single-threaded body is all that is available: report the speedup as measured."]
    return lines + [""]


def _group_close_section(spec_text: str) -> list[str]:
    """The host-proved closing lemmas of a grouped query (``declarative_spec/group_close.py``), when the spec has them."""
    if "lemma_group_close_rows" not in spec_text:
        return []
    omitted = "lemma_group_close_omitted" in spec_text
    return [
        "",
        "## Grouped result: host-proved closing lemmas (call by bare name; already proved with the spec)",
        "",
        "The hard part of a grouped query's `ensures` is the four quantified facts about `res@`: every row satisfies `out_row_ok` (an existential over the joined rows),",
        "the rows' keys are pairwise distinct, every group is present unless the result is full, and "
        + ("every group left out of a top-N is not ahead of any returned row. " if omitted else "(no ORDER BY ... LIMIT here, so no omitted-group fact). ")
        + "The host proved all of them from a plain description of what your code built, so you do not prove them from loop invariants of the exec code:",
        "- a ghost `gk: Seq<KeyType>` (the spec's key type, see `lemma_group_close_rows`'s signature) of group keys: pairwise distinct; containing the key of every joined row that passes",
        "  WHERE and HAVING; with a ghost `gw: Seq<(int, ..)>` of witnesses: `gw[g]` is one joined row (its index tuple) that passes WHERE and HAVING and has key `gk[g]` (only `lemma_group_close_rows` takes `gw`; push the witness when you push the group);",
        "- a ghost `used: Seq<bool>` (one flag per group) and `pos: Seq<int>` (for a used group, the result row where it was chosen: `sel[pos[g]] == g`; a plain pointwise fact, no existential)",
        "  taken by `_present` and `_omitted` only (`used` replaces 'appears in sel');",
        "- a ghost `sel: Seq<int>`, one entry per result row: the index into `gk` of the row's group (distinct), with `res@[r]`'s key fields equal to `gk[sel[r]]` and its aggregate",
        "  fields equal to the spec's folds for that key (`HAVING` too); `res@.len()` equals the LIMIT unless every group is `used`;"
        + (" and for every group that is NOT `used`, `res@[r]` is not behind that group in the ORDER BY order (the `omitted` hypothesis)." if omitted else ""),
        "Then at the end of `run_query` call, with `res@`, `gk` and `sel` (get them with `Ghost`/`Tracked` variables or `Seq` built in `proof { }` blocks):",
        "`lemma_group_close_rows(P.., res@, gk, gw, sel)`, `lemma_group_close_distinct(.., gk, sel)`, `lemma_group_close_present(.., gk, sel, used, pos)`" + (", `lemma_group_close_omitted(..)`" if omitted else "") + ";",
        "each ensures exactly the matching `run_query` postcondition. Their `requires` are the bullets above, spelled out (read their signatures in the spec). The order (sortedness) and the",
        "`<= LIMIT` clauses are not covered: keep them as loop invariants of the selection loop. A selection loop that repeatedly takes the best unused group (a 'used' flag per group) keeps",
        "the invariants `sel` distinct, every unused group not ahead of any chosen row, chosen rows in order, which are exactly the hypotheses above.",
        "",
    ]


def _distinct_section(spec_text: str) -> list[str]:
    """The host-proved COUNT(DISTINCT) library over a two-table join (``declarative_spec/distinct_lemmas.py``), when the spec has it."""
    names = sorted(set(re.findall(r"pub open spec fn (\w+)_pset\(", spec_text)))
    if not names:
        return []
    lines = [
        "",
        "## COUNT(DISTINCT) over a join: host-proved library (call by bare name; it is in the spec's host region, already proved)",
        "",
        "The spec counts a pair of rows `(i0, i1)` for a distinct value only when no LATER pair of the same group has that value. Proving a seen set",
        "equal to that is the hard part; the host proved it for you, for these aggregates: " + ", ".join(f"`{n}`" for n in names) + ". For each aggregate `N` (`k` is the group key; absent for an ungrouped query; `P` are the table parameters):",
        "- `N_hit(P, i0, i1, k)` (the fold's hit condition), `N_row_set(P, i0, i1, k)` (values over hit pairs `(i0, j1)`, `j1 >= i1`),",
        "  `N_pset(P, i0, k)` (values over hit pairs with outer index `< i0`: what an ascending loop has seen), `N_set(P, i0, k)` (outer index `>= i0`). All are `ISet`s.",
        "- `lemma_N_set_step(P, i0, k)`: `N_pset(i0 + 1, k) =~= N_pset(i0, k).union(N_row_set(i0, 0, k))` (and the suffix form).",
        "- `lemma_N_row_set_step(P, i0, i1, k)`: `N_row_set(i0, i1)` is `N_row_set(i0, i1 + 1)` plus `V(i0, i1)` exactly when `N_hit(i0, i1, k)` (`V` is `N_val`).",
        "- `lemma_N_set_end(P, k)`: `N_pset(0, k)` is empty. `lemma_N_value(P, k)`: `N(P, 0, k) == N_pset(P, n, k).len()` and that set is finite.",
        "  (`lemma_N_is_set_len(P, i0, k)` is the same fact for the suffix set.) `n` is the outer table's row count.",
        "How to use: loop over the outer table ascending, keep per group key `k` an exec structure whose view equals `N_pset(P, i0, k)`; per outer row add the row's values (the",
        "`N_row_set(i0, 0, k)` values, built by the inner probe of the join) and call `lemma_N_set_step`; at the end `lemma_N_value` gives the count as `.len()`.",
        "To keep a COUNT equal to a set's `.len()` use `vstd::iset::lemma_iset_insert_len` (`broadcast use vstd::iset::group_iset_lemmas;` turns the ISet facts on).",
        "A dictionary column is injective (the `valid_cols` clauses say so), so a distinct code is a distinct value. These are proved by Verus with the spec; you cannot and need not change them.",
        "",
    ]
    return lines


def _parallel_section(spec_text: str, shape: dict) -> list[str]:
    """Parallel-scan recipe, shown only when the spec was emitted with the Arc parameters (LEMMA_PARALLEL_VSTD=1)."""
    from declarative_spec import parallel

    if not parallel.is_parallel(spec_text):
        return []
    lines = [
        "",
        "## Parallel scan (this spec's `run_query` also takes `<table>_arc: &std::sync::Arc<Cols_<table>>`)",
        "",
        "The extra parameter is the same table, shared (`requires **<t>_arc == *<t>`; the `ensures` are unchanged). You may run",
        "workers with `vstd::thread::spawn` and `JoinHandle::join` (vstd's own, not trusted code of ours): each worker owns an",
        "`std::sync::Arc::clone(<t>_arc)` and folds a row RANGE `[lo, hi)`; the host's suffix folds are additive over ranges, so",
        "worker k returns `fold(t, lo_k) - fold(t, hi_k)` and the partials telescope to `fold(t, 0)`. No column is copied.",
        "A scan that is limited by memory bandwidth is the case this is for: on the real 39.4M-row table the parallel SUM was",
        "12.8x faster than the all-core reference engine. Keep the single-threaded body as the first proof,",
        "then upgrade only if it loses. A hash aggregate or a join does not telescope directly, but a GROUP BY over a small code domain does: give each",
        "worker its own DENSE array per aggregate (one slot per dictionary code), merge them slotwise in the join loop, and the slotwise",
        "telescoping is the same proof (dict mode: `context/ro/examples/dict_group_count_sum_parallel.rs`, 13x on the real 39.4M-row table;",
        "a nullable dictionary column with a string filter, COUNT and MIN: `context/ro/examples/parallel_dict_nullable_count_min.rs` (1.8x on real `pre`);",
        "A dense table has one slot per combination of key codes; it is allowed only when the product of the key dictionaries' sizes is within `LEMMA_DENSE_SLOT_BUDGET` (default 2^22 slots). The section \"Dense slot table: allowed or not, for THIS query\" below says which case this query is; otherwise key the groups by a packed code tuple in a `HashMapWithView`;",
        "two dictionary keys, several aggregates, sorted output, a flat m1*m2 slot array: `context/ro/examples/hard/dict_parallel_q1.rs`, TPC-H Q1 at 3.95x).",
        "Every multiplier quoted in this prompt is a manual-prover result for the timed `run_query` ALONE (kernel only) against the reference engine scanning its own storage in place; pin, copy into the vectors and encoding are outside the timer (about a second for tens of millions of rows) and a reference engine holding the same narrow data in memory is about 1.8x to 2.1x slower than our kernel, not 2.4x to 2.9x. `run_runquery` reports the same kernel-only speedup.",
        "The example is the template (SUM; adapt the fold, the filter, the cell bound and the accumulator type):",
        f"`context/ro/examples/{_PAR_EXAMPLE}` (also `parallel_ungrouped_product_sum.rs` for a product with a date filter, and `parallel_ungrouped_min.rs`, `_max.rs`, `_count.rs`: MIN/MAX merge the workers' (value, any) pairs, COUNT is additive).",
    ]
    if shape["recipe"] in ("ungrouped", "ungrouped_product", "ungrouped_minmax"):
        header = [ln for ln in (_FIXTURES / _PAR_EXAMPLE).read_text().splitlines() if ln.startswith("//")]
        lines += ["", "Its header:", "", "```", *header, "```"]
    return lines


_PAR_EXAMPLE = "parallel_ungrouped_sum.rs"
_PAR_EXTRA = (
    "parallel_ungrouped_product_sum.rs",
    "parallel_ungrouped_min.rs",
    "parallel_ungrouped_max.rs",
    "parallel_ungrouped_count.rs",
)


def _recipe_section(shape: dict) -> list[str]:
    recipe = shape["recipe"]
    lines = ["## The recipe for THIS spec", ""]
    lines.append(f"This spec's result type is `{shape['result_type'] or 'unknown'}`.")
    if recipe.startswith("projection_") and shape.get("dict"):
        lines += [
            "DICTIONARY MODE: the example below was proved with plain strings. In this spec a string column is a `Vec<u32>` of codes",
            "beside `<col>__dict: Vec<String>`, and the spec reads a string cell as `col__dict@[col@[i] as int]@`. Keep the example's",
            "loop and proof structure, but where it reads a string cell write `col__dict[col[i] as usize].clone()` and prove the",
            "dictionary index is in range from `valid_cols_<t>` (the `dict_*.rs` examples in `INDEX.md` show the translation).",
            "",
        ]
    if recipe == "dense_map":
        lines += [
            "Dense array of `KEY_CAP_...` counters (fastest: no hashing), then copy the nonzero slots into the",
            "result map. Replace the names `KEY_CAP_t_k`, `ROW_CAP_t`, `valid_cols_t`, `cols.k` with the ones in",
            "this spec, and paste the block otherwise unchanged. If the spec defines `lemma_dense_count_map`,",
            "call it once after the copy loop instead of re-proving the final `ensures` by hand",
            "(`lemma_dense_count_map(keys, counts@, map@, KEY_CAP_... as int);`).",
            "",
            "```rust",
            _COUNT_SHAPE,
            "```",
        ]
    elif recipe == "none":
        lines += ["No worked recipe matches this result type: build it from the lemma index and the vstd docs."]
    else:
        name, what = _EXAMPLES[recipe]
        if name.startswith("hard/"):
            header = [ln for ln in (_FIXTURES / name).read_text().splitlines() if ln.startswith("//")]
            header = header[: next((i for i, ln in enumerate(header) if "AGENT_" in ln), len(header))]
            lines += [
                f"A verified body for a close shape ({what}) is `context/ro/examples/{name}` (hundreds to a few thousand lines, read it",
                "with the Read tool, do not paste it blind). Its header, which says what each technique is for:",
                "",
                "```",
                *header,
                "```",
            ]
            return lines
        lines += [
            f"A verified body for the same shape ({what}) is `context/ro/examples/{name}`, inlined here.",
            "Your table, column and field names differ: rename them, keep the proof structure.",
        ]
        helper = _EXAMPLE_HELPERS.get(recipe)
        if helper:
            lines += [
                f"Its helper (goes between `// AGENT_HELPERS_START` and `// AGENT_HELPERS_END`, file `context/ro/examples/{helper}`):",
                "",
                "```rust",
                (_FIXTURES / helper).read_text().rstrip(),
                "```",
            ]
        lines += [
            "",
            "The body:",
            "",
            "```rust",
            (_FIXTURES / name).read_text().rstrip(),
            "```",
        ]
        if recipe.startswith("projection_"):
            lines += [
                "",
                "Projection recipe: walk the rows from the last to the first and `res.insert(0, row)` each passing row, so",
                "the loop invariant is `out_copies(res@, 0, k) == hits_with(t, i, k)` for every key `k`, plus",
                "`res@.len() == hit_count(t, i)` and `out_row_ok` for every kept row; a join adds a partial fold in an inner",
                "loop to the finished outer suffix. The 12-line shift lemma is the only helper the plain cases need.",
                "`OFFSET` is refused by the host.",
            ]
    return lines


_SHAPE_LIST = """\
## Which shapes have worked examples

`context/ro/examples/INDEX.md` is a generated table of shape -> file -> what it proves (with line counts) over every verified
example: grouped and ungrouped aggregates, joins, projections, floats, TPC-H shapes, parallel scans and, in dictionary mode,
the long published-shape examples. Open the index first, pick the closest row, read that one file (a long one by ranges:
header comment, then the loop you need). Do not read the whole directory.

KNOWN HARD, no worked example: a join whose key repeats on both sides (many-to-many) with `COUNT(DISTINCT ...)`;
`EXISTS`/`IN` joins (outside dictionary mode); multi-key `DISTINCT`; set operations. These need long helper proofs (an
existential witness per group, a selection invariant). Start with the simplest correct loop that proves, make sure a
verified body is submitted, and only then look for speed. Floats are exact reals here (`float_*.rs`).
"""

_SPEED = """\
## Speed (the run is timed on the full table and compared with the reference engine)

One pass over each table. For a MIN or MAX over a join, skip the probe of the other side for rows that cannot improve the aggregate (`!(any && d >= lo)`): that was a 2.6x speedup in the join example. No loop over one table inside a loop over another table. Prefer a dense `Vec` indexed
by a small integer key (`KEY_CAP_...`) over a hash map; use a hash map for a large or string key. Build the
smaller side of a join into a map once, then probe it. For a SUM, accumulate in `u64` inside blocks small enough
that the block sum provably cannot overflow, and widen the block sum into the `i128` total at block boundaries;
if you cannot prove the no-overflow invariant, use a plain `i128` accumulator. Avoid per-row allocation and
`String::clone` on the hot path. The proof must come first: a body that verifies but is slower than the bar is
reported with its speedup, and you may rewrite it.

The bar is the reference engine running on all cores. `run_runquery` also reports the speedup against the same
engine on one thread (`speedup_1t`). A scan that is limited by memory bandwidth (a few wide columns over millions
of rows) may be hard to win on one core: report both numbers, do not trade the proof for it.
A filter that is not predictable is faster branch-free: `let t = if hit { v } else { 0 }; acc = acc + t;` beat
`if hit { acc = acc + v }` by about 1.7x on a large scan. Use `&&`, not `&`, on bools (Verus rejects `&`).
A conjunctive filter written as a short-circuit row test (`a == 1 && b == code && c > 3`) is branch-miss bound on a big scan (it cost 2x on TPC-H Q12).
Scan fixed blocks of 32 rows with a BRANCH-FREE flag (`flag = flag + (if a == 1 {1u8} else {0}) * (if b == code {1u8} else {0})`; Verus rejects bool `&`
and `|`, use u8 0/1 with `+` and `*`), skip the whole block when `flag == 0`, run the exact row loop only on flagged blocks (the proof pattern is in
`context/ro/examples/parallel_dict_filter_count_max_blockskip.rs` and, in dictionary mode, `hard/dict_parallel_q12.rs`). It only wins when blocks rarely flag (about 2x on TPC-H Q12; none on a filter that flags 99 percent of the blocks).
THE HIDDEN COST OF A HOT LOOP IS BOUNDS CHECKS. The compiler cannot see that `col.len() == n`, so every `col[i]` is checked and the loop does not
vectorize. Per block of at most 8192 rows take `vstd::slice::slice_subrange(col.as_slice(), lo, hi)` of each column read and run an ascending inner loop
over the slices with no data-dependent branch (u8 0/1 factors multiplied, `if hit { v } else { 0 }`, a block accumulator whose invariant bounds it so it
cannot overflow within one block), then merge the block into the worker's accumulator once. The same scan went from 20.8 ms to 9.3 ms
(`context/ro/examples/parallel_dict_filter_count_max_slices.rs`; the Q6-class product sum, `parallel_ungrouped_product_sum_slices.rs`, 28 ms to 21 ms).
If the speed bar is not met, look first at bounds checks, then at the bytes per row: with a catalog cap on a column the loaded cell is narrower
(`i8`/`i16`/`i32`, see the struct in the spec) and the scan reads fewer bytes; a scan limited by the BYTES it reads is a tie at best.
Repeat the timed run before judging: this box shows 30 percent noise.
NARROW CELLS (a struct field `Vec<i8>`/`Vec<i16>`/`Vec<i32>` in the spec; the spec itself still reads every cell `as int`):
a filter or arithmetic literal larger than the cell type is a literal of the WIDER type, not of the cell: write `(q as i64) < 70000` or
`(q as i128) * 40000i128`, never `q < 70000`, which does not type-check; a comparison that holds for every cell of that width is proved from the width
(`q as int >= -32768 && q as int <= 32767`) and the cell cap in `valid_cols_<table>`, not tested at run time. A group key stays `i64` in `OutRow`
(`let k = q as i64;`, then `key_at(..) == k as int` follows). The running-total bound of a SUM uses the CAP of the column (the `valid_cols` conjunct
`|cell| < cap`), not the i64 range the wide examples hard-code.
A literal beyond the cell range also makes a comparison constant: `valid_cols` bounds `report` to its cap, so `report > 100000` is never true and a disjunct
with it is dead (prove it from the instantiated bound; do not write the comparison in exec). A literal compared with a narrow cell takes the cell's type (`p == 1`, not `1i64`).
To prove a product of two cells fits in the `i128` accumulator, write a helper with `by (nonlinear_arith)` from the
two cell bounds (worked example: `context/ro/examples/ungrouped_decimal_product_sum.rs`).
"""

_DO_NOT = """\
## Do not (each item is a real failed attempt)

- Verus rejects these in exec code: `sort`/`sort_by`; iterating a `HashMapWithView`/`StringHashMap` (`.iter()`, `.keys()`, `.entry()`, `for (k, v) in &map`; keep the keys in a `Vec` next to the map; `Vec` indexing loops are fine);
  `for x in &mut v`, `.iter_mut()`, `.into_iter()`; `.clone()` on an `OutRow` (write `OutRow { .. }` from fields; `String::clone` is fine);
  `as int`, `as nat` (ghost code only: `proof {}`, invariants, `spec fn`); an `fn`, `proof fn` or `use` nested in the body. Use `while` loops over indices.
- Keep `valid_cols_<t>(t)` in EVERY loop invariant, nested loops included: a loop that drops it loses the length precondition of every `col[i]`.
  Slim it only when the rlimit forces you to (see the rlimit notes below), and then to the specific length facts you use, never to nothing.
- Every `while` has a `decreases`. Use only names that exist: the host spec, the lemma index, vstd (grep `LEMMAS.md`), your own helper region.
- Never replace a failing body with a placeholder (`Vec::new()`) to have something to submit: it fails the postcondition on any data with a matching row.
  Keep the body with the fewest errors and fix the error the host reports.
- Before writing, find the nearest shape in `context/ro/examples/INDEX.md`, read that example and copy its loop structure, invariants and helper lemmas.
"""

_PROOF_HYGIENE = """\
## Proof hygiene that costs people time

- Bind a column before taking its length: `let keys = cols.grp@;` then `keys.len()`; do not write `cols.grp@.len()`.
- Parenthesize a cast in a comparison: `(k as int) < (KEY_CAP_t_k as int)`.
- A loop that walks down: snapshot the old index (`let i_old = i; i = i - 1;`) before using the old suffix.
- Every loop needs `decreases`; keep `valid_cols_<table>(cols)` in every loop invariant (the key and cell bounds
  come from it). Call host lemmas as `proof { lemma_...(); }`. Give a quantifier an explicit `#[trigger]`.
- A quantified loop invariant whose body mentions the NEXT index loops the solver (Z3 matching loop; the profile shows one quantifier with an astronomically large cost):
  `forall|q| #![trigger res@[q]] .. res@[q].total >= res@[q + 1].total` instantiates `res@[q + 1]`, which instantiates it again. Use the two-term trigger
  `#![trigger res@[q], res@[q + 1]]` (the host's own sortedness postcondition is a goal, not a hypothesis, so it is safe).
- Verus itself checks every `u64`/`i128` add for overflow: prove the bound with an `assert` from the host's
  `ROW_CAP_...` and cell caps (`assert(prev as int + 1 <= ROW_CAP_t)`); no fit lemma is needed.
- A long proof (many quantified loop invariants plus asserts in one loop) exhausts the rlimit, and Verus then
  reports a misleading error such as `invariant not satisfied before loop`. Fix: put each invariant bundle in a
  `#[verifier::opaque] spec fn`, and maintain each property in its own small `proof fn` that `reveal`s only that
  bundle; keep the loop invariant to the opaque calls plus the cheap facts.
- There is no `--profile`: to find the rlimit culprit, bisect with whole checks (stub the tail of `run_query` to an
  empty result and see which loop still verifies). Two usual culprits: a lemma whose `ensures` is a quantifier over
  `row_hit` (state it pointwise, with the row index as an argument, and call it from `assert forall ... by`), and
  `valid_cols_<table>(cols)` kept in every loop invariant (its cell-range quantifier then sits in every loop context:
  keep only the plain length and `ROW_CAP_...` facts you use).
- A quantifier or existential over a spec function of a row (`key_at(pre, i0)`) only fires on a ground term: bind
  one (`let w = key_at(pre, i0);`) or take a witness with `choose|r: int| ...` before you assert the instance.
- Only `proof fn` and `spec fn` items are allowed in the helper region: an exec `fn` helper is rejected, so write
  string comparisons and loop bodies inline in `run_query`.
- The host's backward recursive folds fit a single backward pass (`let mut i = t.n; while i > 0 { i -= 1; ... }`)
  with suffix invariants (`acc == fold(rows i..n)`); prefer it to a forward pass.
- A product of two cells needs its own bound assert (for example `price * (100 - disc) <= 2e30` from the cell cap
  1e15); a sum is bounded by (rows seen) * (cell bound).
- Short string keys (1 or 2 characters) are cheapest as small integer codes from `as_bytes` (vstd `utf8.rs`,
  grep `LEMMAS.md` for `as_bytes`) indexing a slot table, not as hashed strings.
- The verifier's rlimit budget is the host's `--rlimit` (3 by default); the error names the main loop even when the
  overrun is in one of its asserts.
- A string literal in a predicate (`uom = 'pure'`): `&str ==` has no spec tying it to `@`, and `reveal_strlit` does not
  help. Build the literal once (`let pure: String = String::from_str("pure");`, ensures `pure@ == "pure"@`), keep
  `pure@ == "pure"@` in the loop invariant, and compare `cols.uom[i] == pure` (`String == String`, vstd `string.rs`).
- `Vec::insert` has the view `Seq::insert`; `Seq::insert_ensures(pos, elt)` (vstd `seq_lib.rs`, call it as `s.insert_ensures(p, x)`) gives its length and element facts. Grep `LEMMAS.md` for a vstd lemma before you write your own.
- Floats (rounding error is accepted: a float is exact real arithmetic here, so a SUM is an exact fold and there
  is no epsilon): one `f64` accumulator with `acc as real == <spec sum>`; before each `+ - *` call
  `lemma_f64_add_defined` / `sub_defined` / `mul_defined`, after it `lemma_f64_add_within` / `sub_within` /
  `mul_within`; compare with `lemma_f64_gt_real` and friends; divide with `lemma_f64_div_defined` / `div_real`;
  cast integers with `host_u64_to_f64` / `host_i128_to_f64`. Keep `f64_literals_ok()` in every loop invariant.
"""


def _error_excerpt(last_error: str) -> str:
    """The first errors, whole: the host already put the summary first and the errors in source order."""
    excerpt = last_error.strip()
    if len(excerpt) > 6000:
        excerpt = excerpt[:6000].rstrip() + "\n... (cut here; the rest is in declarative_build/verify_full.log)"
    return excerpt


_DICT_HARD: tuple[tuple[str, str, str], ...] = (
    (
        "count_distinct_",
        "hard/dict_group_two_keys_count_distinct_avg.rs",
        "two dictionary string keys, COUNT(*), COUNT(DISTINCT x) and AVG (dense slots over the codes, a per-slot seen-set, sorted insert; it assumes u8 dictionary codes for both keys, slot = a*256+b: adapt the slot arithmetic if your spec's code types are wider)",
    ),
    (
        "lemma_group_close_rows",
        "hard/dict_join_group_count_distinct_topn.rs",
        "a two-table join, GROUP BY an int key and a nullable string key, two COUNT(DISTINCT x) and a SUM, ORDER BY the sum DESC LIMIT 20, using the host COUNT(DISTINCT) library and the host closing lemmas: dynamic group table with ghost witnesses, chain index probe, selection loop with `used`/`pos`/`sel` ghost state, the closing calls in small helpers (long; its group key is `(fy, afs)`: adapt the key type and the group-lookup to yours)",
    ),
    (
        "sq_\\d+_groups",
        "hard/dict_having_scalar_subquery.rs",
        "a join GROUP BY SUM with HAVING against an uncorrelated scalar subquery (per-class sums, threshold, top-k by repeated maximum; proof first: group and distinct-key lookups are linear scans, replace them by a dense array over codes for speed)",
    ),
)


def _dict_hard_pointers(spec_text: str) -> list[str]:
    """Pointers to the long dictionary-mode worked examples whose feature this spec has (read them with the Read tool)."""
    if "__dict" not in spec_text:
        return []
    found = [(f, what) for needle, f, what in _DICT_HARD if re.search(rf"\b{needle}", spec_text)]
    return [f"Long verified example for this feature (dictionary mode): `context/ro/examples/{f}`: {what}." for f, what in found] + ([""] if found else [])


def build_declarative_prompt(
    *,
    sql: str,
    spec_path: str,
    edit_path: str,
    lemma_index: str,
    last_error: str = "",
    in_docker: bool = False,
    spec_text: str = "",
    dict_sizes: dict[str, int] | None = None,
    restart_note: str = "",
) -> str:
    """Instructions for this spec style only (the recursive prompt is a different file).

    ``spec_text`` is the emitted spec: it selects the one recipe that matches its result type and the
    list of hard features it contains. ``dict_sizes`` (``<table>.<column>`` -> dictionary entries, measured at prepare time) lets the
    prompt say whether a dense slot table over the group-key dictionaries is allowed. When ``in_docker`` is set, paths are the container mount.
    """
    if in_docker:
        spec_path = "/workspace/context/ro/spec.rs"
        edit_path = "/workspace/runquery_agent.rs"
        index_path = "/workspace/context/ro/lemma_index.md"
        root = "/workspace/context/ro"
    else:
        index_path = "context/ro/lemma_index.md"
        root = "context/ro"
    shape = spec_shape(spec_text)

    sections = [
        "# Declarative run_query",
        "",
        "## What you get",
        "",
        f"- `{edit_path}` already holds the host spec, the host lemmas, the loaders and `run_query`. You edit it.",
        f"- Read-only: `{spec_path}` (same spec), `{root}/query.sql`, `{root}/schema.json`, `{index_path}`,",
        f"  `{root}/examples/` (verified example bodies; start with `INDEX.md` there: shape -> file -> what it proves),",
        f"  `{root}/verus/` (vstd source, Verus guide, small examples;",
        "  read `INDEX.md` first (one grep recipe per common lookup), then grep `LEMMAS.md`, `EXAMPLES_INDEX.md` and `GUIDE_INDEX.md`).",
        '- Look up vstd with one grep, e.g. `grep -n -A5 "^## StringHashMap::" LEMMAS.md` (in `verus/`): `INDEX.md` has a',
        "  recipe per common lookup (`Vec::push`, `String::eq`, `decreases`, `assert forall`, `choose`, broadcast groups).",
        "- Tools: the file edit tool; `run_runquery` (path `runquery_agent.rs`) verifies, compiles and times your",
        "  program on the official table; `submit_runquery` with the returned `run_id`. In Claude Code these are",
        "  `mcp__lemma-host__run_runquery` and `mcp__lemma-host__submit_runquery`; if they are not in your tool list yet, load",
        "  them first with ToolSearch (`select:mcp__lemma-host__run_runquery,mcp__lemma-host__submit_runquery`). A Bash tool",
        "  may exist, but it has no network and Verus is not on its PATH: `run_runquery` is the only Verus you have, so do not",
        "  try `verus`, `npx` or any package install.",
        "- Done means: Verus says `N verified, 0 errors`, the result equals the reference engine's rows, and the timed run beats",
        "  the reference engine (`run_runquery` reports the speedup); if no verified body beats it, the fastest verified one,",
        "  submitted. Submit a verified body as soon as you have one, and again if a later one is better.",
        "",
        "## Regions and rules",
        "",
        "- Two regions are kept, everything else in the file is discarded: the `run_query` body between",
        "  `// AGENT_EDIT_START` and `// AGENT_EDIT_END`, and `proof fn` / `spec fn` helpers between",
        "  `// AGENT_HELPERS_START` and `// AGENT_HELPERS_END` (just above `run_query`). A nested `proof fn` or",
        "  `spec fn` inside the body does not work. A helper may not reuse a name the host spec defines.",
        "- Write no `use` lines: every vstd module is imported by glob; call lemmas by bare name",
        "  (`vstd::map_lib::lemma_map_new_domain` in full; that one name is ambiguous).",
        "  The only allowed line is `broadcast use vstd::<module>::group_<name>;` naming a group listed in",
        f"  `{root}/verus/INDEX.md` (it turns a bundle of vstd lemmas and axioms on for the solver; any vstd group is allowed, including one that lists `axiom_*` members: they are vstd's own trusted core; more groups, more noise), e.g. `broadcast use vstd::seq::group_seq_axioms;`. Write it inside the body or inside a `proof fn` body; at the top level of the helper region it is rejected.",
        "- Forbidden (rejected before Verus runs): `assume(`, `admit(`, `#[verifier::external_body]`, `assume_specification`,",
        "  `unimplemented!`, and any name containing `axiom`, `arbitrary` or `proof_from_false` outside a `broadcast use vstd::<module>::group_<name>;` line (you cannot write an axiom of your own). The hash-key",
        "  axiom is already broadcast: do not name it. `requires`/`ensures` are the host's; changing them has",
        "  no effect.",
        "- `StringHashMap` and `HashMapWithView` are in scope (`new`, `insert`, `contains_key`, `get`; the view key",
        "  is `Seq<char>` for strings). `StringHashMap::new` needs no axiom. Do not call `HashMapWithView::new` on",
        "  a `String` or a tuple key.",
        "",
        "## SQL",
        "",
        "```sql",
        sql.strip(),
        "```",
        "",
    ]
    sections += _scale_section(spec_text)
    sections += hardware_section()
    sections += _recipe_section(shape)
    sections += dense_budget.prompt_section(dense_budget.report(spec_text, dict_sizes)) if "__dict@" in spec_text else []
    sections += _float_section(spec_text)
    sections += _nullable_section(spec_text)
    sections += _parallel_section(spec_text, shape)
    sections += _distinct_section(spec_text)
    sections += _group_close_section(spec_text)
    sections += [""]
    if shape["hard"]:
        sections += [
            "## Warning: this spec has features with no worked example",
            "",
            "Contains: " + "; ".join(shape["hard"]) + ".",
            "Expect a long proof. Get the simplest correct version verified first, and call `run_runquery` early",
            "and often: its error text is the only checker you have.",
            "",
        ]
        sections += _dict_hard_pointers(spec_text)
    sections += [_DO_NOT, _SHAPE_LIST, _SPEED, _PROOF_HYGIENE]
    sections += [
        "## Helper region example",
        "",
        "```rust",
        "// AGENT_HELPERS_START",
        "proof fn plus_zero(x: int) ensures x + 0 == x { }",
        "// AGENT_HELPERS_END",
        "// in the body:  proof { plus_zero(3); }",
        "```",
        "",
        "## Lemma index",
        "",
        lemma_index.rstrip(),
    ]
    if restart_note.strip():
        sections.extend(["", "## This is a restart: where your file stands", "", restart_note.strip()])
    if last_error.strip():
        sections.extend(
            [
                "",
                "## Previous host error",
                "",
                (
                    "These are the first errors of the previous session's LAST attempt (not necessarily the file now in place; see above)."
                    if restart_note.strip()
                    else "The last compile or verify of your edit failed. Fix that edit and call `run_runquery` again."
                ),
                "",
                "```",
                _error_excerpt(last_error),
                "```",
            ]
        )
    sections.extend(
        [
            "",
            "## Do this now",
            "",
            "This is a non-interactive session: nobody answers questions. Do the task now. Never ask the user anything and never",
            "offer options. Do not stop until `run_runquery` shows `N verified, 0 errors` and you have called `submit_runquery`",
            "with the `run_id` of your best verified body (a parallel upgrade, where the spec has one, is tried only after a verified",
            "body exists and is submitted, and only when its `speedup` is below the bar). If you conclude it cannot verify, say plainly why in your",
            "last message; an empty or placeholder body is a failure, not a result.",
        ]
    )
    return "\n".join(sections) + "\n"
