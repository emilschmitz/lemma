"""Prompt for the declarative flag. The recursive agent prompt is a different file."""

from __future__ import annotations

import re
from pathlib import Path

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
    "int_map": ("int_group_count.rs", "one table, integer group key, COUNT(*), result `HashMapWithView<int, u64>`"),
    "string_map": ("string_group_count.rs", "one table, string group key, COUNT(*), result `StringHashMap<u64>`"),
    "group_count": ("group_count_where.rs", "one table, filtered GROUP BY, COUNT(*), result `Vec<OutRow>`"),
    "group_sum": ("group_sum_where.rs", "one table, filtered GROUP BY, SUM, result `Vec<OutRow>`"),
    "join_group_sum": ("join_group_sum.rs", "two tables joined on a key, GROUP BY, SUM, result `Vec<OutRow>`"),
    "ungrouped_product": (
        "ungrouped_decimal_product_sum.rs",
        "one table, filtered ungrouped SUM of a product of two decimal columns, with a helper lemma",
    ),
    "projection_where": ("projection_where.rs", "one table, `SELECT cols WHERE ...` (no GROUP BY), result `Vec<OutRow>`"),
    "projection_join": ("projection_join.rs", "two tables joined, plain projection `SELECT t.a, u.w ... JOIN ...`"),
    "projection_correlated_max": (
        "projection_correlated_max.rs",
        "projection with a correlated scalar subquery `a = (SELECT MAX(a) ... WHERE same key)`",
    ),
    "projection_distinct": ("projection_distinct.rs", "`SELECT DISTINCT cols ... WHERE ...`"),
    "projection_top_k": ("projection_top_k.rs", "projection with `ORDER BY ... LIMIT k` (multiplicity and the omitted-row clause)"),
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
    "ungrouped_minmax": (
        "ungrouped_minmax_string_filter.rs",
        "one table, filtered ungrouped MIN and MAX of an integer column, with a string-literal comparison in the filter",
    ),
    "ungrouped": ("ungrouped_sum_where.rs", "one table, filtered ungrouped SUM, result `Vec<OutRow>` of one row"),
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


def spec_shape(spec_text: str) -> dict:
    """Which recipe matches this spec's result type, and which hard features it has."""
    result = re.search(r"pub fn run_query\([^)]*\)\s*->\s*\(res:\s*([^)]+)\)", spec_text)
    ty = result.group(1).strip() if result else ""
    tables = len(re.findall(r"pub struct Cols_", spec_text))
    if ty.startswith("HashMapWithView"):
        recipe = "dense_map" if "KEY_CAP_" in spec_text else "int_map"
    elif ty.startswith("StringHashMap"):
        recipe = "string_map"
    elif ty.startswith("Vec<OutRow>") and "proj_key(" in spec_text:
        if "sq_" in spec_text:
            recipe = "projection_correlated_max"
        elif "out_copies(" not in spec_text:
            recipe = "projection_distinct"
        elif re.search(r"res@\[i \+ 1\]", spec_text.split("pub fn run_query")[-1]):
            recipe = "projection_top_k"
        elif tables >= 2:
            recipe = "projection_join"
        else:
            recipe = "projection_where"
    elif ty.startswith("Vec<OutRow>"):
        if "out_row_ok(" not in spec_text:
            head = spec_text.split("pub fn run_query(")[0]
            if re.search(r"as int\)\)?\s*\*\s*\(", head):
                recipe = "ungrouped_product"
            elif re.search(r"\b(?:min|max)_\w+\(", head):
                recipe = "join_min_probe" if tables >= 2 else "ungrouped_minmax"
            else:
                recipe = "ungrouped"
        elif tables >= 2:
            recipe = "join_group_sum"
        elif re.search(r"\bcount_distinct_", spec_text):
            recipe = "hard_distinct"
        elif "(Seq<char>, Seq<char>)" in spec_text:
            recipe = "hard_group_strings"
        elif re.search(r"\bsum_\w+\(", spec_text):
            recipe = "group_sum"
        else:
            recipe = "group_count"
    else:
        recipe = "none"
    hard = [what for needle, what in _HARD_FEATURES if re.search(rf"\b{needle}", spec_text)]
    if re.search(r"res@\.len\(\) <= \d+", spec_text) and recipe in ("group_count", "group_sum", "join_group_sum"):
        hard.append("a LIMIT with ORDER BY over groups (top-K selection)")
    if tables >= 2 and "count_distinct_" in spec_text:
        hard.append("a join together with COUNT(DISTINCT ...)")
    return {"result_type": ty, "recipe": recipe, "tables": tables, "hard": hard}


def mount_examples(ro: Path) -> None:
    """Copy the verified example bodies to ``ro/examples/`` (the prompt names them)."""
    dest = ro / "examples"
    dest.mkdir(parents=True, exist_ok=True)
    for name in [n for n, _w in _EXAMPLES.values()] + sorted(set(_EXAMPLE_HELPERS.values())):
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((_FIXTURES / name).read_text())
    for path in sorted(_FIXTURES.glob("float_*.rs")):  # the float shapes (exact reals, the f64 idealization lemmas)
        (dest / path.name).write_text(path.read_text())


_FLOAT_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("float_sum.rs", "ungrouped SUM of a DOUBLE column"),
    ("float_product_sum.rs", "ungrouped SUM of a product of DOUBLE columns"),
    ("float_filter_count.rs", "COUNT under a DOUBLE comparison"),
    ("float_min_max.rs", "MIN and MAX of a DOUBLE column"),
    ("float_avg_int.rs", "ungrouped AVG of an integer column (DOUBLE result)"),
    ("float_avg_decimal.rs", "ungrouped AVG of a DECIMAL column"),
    ("float_avg_float.rs", "ungrouped AVG of a DOUBLE column"),
    ("float_group_sum_having.rs", "GROUP BY, SUM(double), HAVING on the sum"),
    ("float_group_sum_order_limit.rs", "GROUP BY, SUM(double), ORDER BY the sum, LIMIT"),
    ("float_group_avg_having.rs", "GROUP BY, AVG(double), HAVING on the average"),
    ("float_group_avg_decimal.rs", "GROUP BY, AVG over a DECIMAL column"),
    ("float_order_limit.rs", "ORDER BY a DOUBLE column, LIMIT (selection by repeated minimum)"),
    ("float_avg_group_count_distinct.rs", "tuple-of-strings GROUP BY, COUNT, COUNT DISTINCT and AVG (long)"),
)


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


def _recipe_section(shape: dict) -> list[str]:
    recipe = shape["recipe"]
    lines = ["## The recipe for THIS spec", ""]
    lines.append(f"This spec's result type is `{shape['result_type'] or 'unknown'}`.")
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
                f"A verified body for a close shape ({what}) is `context/ro/examples/{name}` (about 550 lines, read it",
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
                "Its helper (goes between `// AGENT_HELPERS_START` and `// AGENT_HELPERS_END`, file "
                f"`context/ro/examples/{helper}`):",
                "",
                "```rust",
                (_FIXTURES / helper).read_text().rstrip(),
                "```",
            ]
        lines += ["", "The body:", "", "```rust", (_FIXTURES / name).read_text().rstrip(), "```"]
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

Verified examples exist (`context/ro/examples/`, `hard/` for the long ones) for: one-table `GROUP BY` COUNT with an
integer key (`HashMapWithView`) or a string key (`StringHashMap`); one-table filtered `GROUP BY` COUNT or SUM into
`Vec<OutRow>`; a filtered ungrouped SUM (also of a product of decimals, with a `nonlinear_arith` bound helper) and
ungrouped MIN/MAX with a string-literal comparison; a two-table join `GROUP BY` SUM; projections into `Vec<OutRow>`
(plain, join, correlated `MAX` subquery, `DISTINCT`, `ORDER BY ... LIMIT k`); and, too long to inline, a
tuple-of-strings `GROUP BY` with `COUNT(DISTINCT ...)` and a sorted result (O(groups x rows): a speed loser with many
groups) and a TPC-H Q1 shape (two string keys, several decimal SUMs, sorted output, one pass).

KNOWN HARD, no worked example: a join whose key repeats on both sides (many-to-many) with `COUNT(DISTINCT ...)`;
`EXISTS`/`IN` joins; `HAVING` against a scalar subquery; multi-key `DISTINCT`; set operations. These need long helper
proofs (an existential witness per group, a selection invariant). Start with the simplest correct loop that proves,
make sure the result is submitted, and only then look for speed. Float comparisons, float `ORDER BY`, float MIN/MAX,
products and averages over `DOUBLE` columns are in scope (floats are exact reals here; `float_*.rs` examples).
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
To prove a product of two cells fits in the `i128` accumulator, write a helper with `by (nonlinear_arith)` from the
two cell bounds (worked example: `context/ro/examples/ungrouped_decimal_product_sum.rs`).
"""

_PROOF_HYGIENE = """\
## Proof hygiene that costs people time

- Bind a column before taking its length: `let keys = cols.grp@;` then `keys.len()`; do not write `cols.grp@.len()`.
- Parenthesize a cast in a comparison: `(k as int) < (KEY_CAP_t_k as int)`.
- A loop that walks down: snapshot the old index (`let i_old = i; i = i - 1;`) before using the old suffix.
- Every loop needs `decreases`; keep `valid_cols_<table>(cols)` in every loop invariant (the key and cell bounds
  come from it). Call host lemmas as `proof { lemma_...(); }`. Give a quantifier an explicit `#[trigger]`.
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
    excerpt = last_error.strip()[-4000:]
    newline = excerpt.find("\n")
    if newline != -1 and newline < 200:
        excerpt = excerpt[newline + 1 :]
    return excerpt


def build_declarative_prompt(
    *,
    sql: str,
    spec_path: str,
    edit_path: str,
    lemma_index: str,
    last_error: str = "",
    in_docker: bool = False,
    spec_text: str = "",
) -> str:
    """Instructions for this spec style only (the recursive prompt is a different file).

    ``spec_text`` is the emitted spec: it selects the one recipe that matches its result type and the
    list of hard features it contains. When ``in_docker`` is set, paths are the container mount.
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
        f"  `{root}/examples/` (verified example bodies), `{root}/verus/` (vstd source, Verus guide, small examples;",
        "  read `INDEX.md` first (one grep recipe per common lookup), then grep `LEMMAS.md`, `EXAMPLES_INDEX.md` and `GUIDE_INDEX.md`).",
        "- Look up vstd with one grep, e.g. `grep -n -A5 \"^## StringHashMap::\" LEMMAS.md` (in `verus/`): `INDEX.md` has a",
        "  recipe per common lookup (`Vec::push`, `String::eq`, `decreases`, `assert forall`, `choose`, broadcast groups).",
        "- Tools: the file edit tool; `run_runquery` (path `runquery_agent.rs`) verifies, compiles and times your",
        "  program on the official table; `submit_runquery` with the returned `run_id`. You cannot run Verus or a shell.",
        "- Done means: Verus says `N verified, 0 errors`, the result equals the reference engine's rows, and the timed run beats",
        "  the reference engine (`run_runquery` reports the speedup). Submit before the session ends.",
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
        f"  `{root}/verus/INDEX.md` (it turns a bundle of vstd lemmas on for the solver; more groups, more noise), e.g. `broadcast use vstd::seq::group_seq_axioms;`. Write it inside the body or inside a `proof fn` body; at the top level of the helper region it is rejected.",
        "- Forbidden (rejected before Verus runs): `assume(`, `admit(`, `#[verifier::external_body]`, `assume_specification`,",
        "  `unimplemented!`, and any name containing `axiom`, `arbitrary` or `proof_from_false`. The hash-key",
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
    sections += _recipe_section(shape)
    sections += _float_section(spec_text)
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
    sections += [_SHAPE_LIST, _SPEED, _PROOF_HYGIENE]
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
    if last_error.strip():
        sections.extend(
            [
                "",
                "## Previous host error",
                "",
                "The last compile or verify of your edit failed. Fix that edit and call `run_runquery` again.",
                "",
                "```",
                _error_excerpt(last_error),
                "```",
            ]
        )
    return "\n".join(sections) + "\n"
