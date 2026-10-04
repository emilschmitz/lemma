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
    "ungrouped": ("ungrouped_sum_where.rs", "one table, filtered ungrouped SUM, result `Vec<OutRow>` of one row"),
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
    elif ty.startswith("Vec<OutRow>"):
        if "out_row_ok(" not in spec_text:
            head = spec_text.split("pub fn run_query(")[0]
            recipe = "ungrouped_product" if re.search(r"as int\)\)?\s*\*\s*\(", head) else "ungrouped"
        elif tables >= 2:
            recipe = "join_group_sum"
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
    for name, _what in _EXAMPLES.values():
        (dest / name).write_text((_FIXTURES / name).read_text())
    for path in sorted(_FIXTURES.glob("float_*.rs")):  # the float shapes (exact reals, the f64 idealization lemmas)
        (dest / path.name).write_text(path.read_text())


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
        lines += [
            f"A verified body for the same shape ({what}) is `context/ro/examples/{name}`, inlined here.",
            "Your table, column and field names differ: rename them, keep the proof structure.",
            "",
            "```rust",
            (_FIXTURES / name).read_text().rstrip(),
            "```",
        ]
    return lines


_SHAPE_LIST = """\
## Which shapes have worked examples

Worked, verified examples exist (`context/ro/examples/`) for: one-table `GROUP BY` COUNT with an integer key
(`HashMapWithView`) or a string key (`StringHashMap`); one-table filtered `GROUP BY` COUNT or SUM into
`Vec<OutRow>`; one filtered ungrouped SUM; a two-table join `GROUP BY` SUM; a filtered ungrouped SUM of a product of two decimal columns (with a
`nonlinear_arith` bound helper).

KNOWN HARD, no worked example: a join whose join key repeats on both sides (many-to-many) with
`COUNT(DISTINCT ...)`; top-K (`ORDER BY ... LIMIT`) over groups; correlated or scalar subqueries; `EXISTS`/`IN`
joins; string-tuple group keys; `AVG` with a float result. These need long helper proofs (an existential
witness per group, a selection invariant). Start with the simplest correct loop that proves, make sure the
result is submitted, and only then look for speed. Float comparisons, float `ORDER BY`, float MIN/MAX,
products and averages over `DOUBLE` columns are in scope (floats are exact reals here; `float_*.rs` examples).
"""

_SPEED = """\
## Speed (the run is timed on the full table and compared with the reference engine)

One pass over each table. No loop over one table inside a loop over another table. Prefer a dense `Vec` indexed
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
- Integer `+` needs no overflow lemma: Verus checks it, so keep the running bound in the loop invariant.
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
        f"  `{root}/verus/INDEX.md` (it turns a bundle of vstd lemmas on for the solver; more groups, more noise), e.g. `broadcast use vstd::seq::group_seq_axioms;`.",
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
