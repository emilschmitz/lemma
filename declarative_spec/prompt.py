"""Prompt for the declarative flag. The recursive agent prompt is a different file."""

from __future__ import annotations

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
        lemma_count_step_fits_u64(prev, ROW_CAP_t);
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
) -> str:
    """Instructions for this spec style only.

    When ``in_docker`` is set, paths are the container mount. The recursive
    prompt in ``research_loop.agent_sandbox.build_agent_prompt`` is not used.
    """
    if in_docker:
        spec_path = "/workspace/context/ro/spec.rs"
        edit_path = "/workspace/runquery_agent.rs"
        index_path = "/workspace/context/ro/lemma_index.md"
    else:
        index_path = "context/ro/lemma_index.md"

    sections = [
        "# Declarative run_query",
        "",
        "This session is `LEMMA_SPEC_STYLE=declarative`.",
        "It is not the recursive optimizer prompt. There is no `method_spec` to match.",
        "The spec states conditions on the result. A small helper such as `group_count`",
        "or `matched_sum` is fine. Do not define the query as a spec function that",
        "walks indexes and updates a map.",
        "",
        "## SQL",
        "",
        "```sql",
        sql.strip(),
        "```",
        "",
        "## Edit",
        "",
        f"Read `{spec_path}`. Edit `{edit_path}` with the file edit tool.",
        "The body of `run_query` stays between `// AGENT_EDIT_START` and `// AGENT_EDIT_END`.",
        "You may also add `use vstd::...;` and `broadcast use vstd::...;` lines",
        "for a lemma or a proved `group_` that does not contain `axiom`.",
        "Put those next to the host `use` lines at the top of the file, or inside the edit.",
        "The host hoists them. Only `vstd` imports are kept.",
        "A name containing `axiom`, `arbitrary`, or `proof_from_false` is rejected: that import is an assume.",
        "The hash-key axiom is already broadcast in this file. Do not import it.",
        "Any other text outside the markers is discarded.",
        "The host pastes your body back into the original spec.",
        "Changing `requires` or `ensures` has no effect.",
        "Write an edit before any long plan, then call `run_runquery`.",
        "If this spec has `pub const KEY_CAP_` and returns `HashMapWithView<u64, u64>`,",
        "the first edit is the count below, with names taken from this spec.",
        "If this spec returns `Vec<OutRow>`, do not paste that count.",
        "The shell cannot run in this container. Do not use it.",
        "Do not search outside this workspace. Host lemmas are already in the file",
        f"between `// HOST_LEMMAS_START` and `// HOST_LEMMAS_END`, and in `{index_path}`.",
        "Call those names. Import a vstd lemma that is not in scope.",
        "Do not `assume(` or `admit(` a fact instead of calling the lemma.",
        "",
        "## What you may write",
        "",
        "Any executable loop that meets the `ensures`. `proof { lemma_...( ... ); }` is allowed.",
        "Do not write `proof fn`, `spec fn`, `assume(`, `admit(`, or `#[verifier::external_body]`.",
        "Those are rejected. Do not add a `spec fn`. The host already emitted the helpers.",
        "",
        "Integers. A `u64` or `i128` add equals the mathematical add when the result fits.",
        "Call the host fit lemma under the row cap and the cell cap in the spec.",
        "If the slot is `u64`, call `lemma_count_step_fits_u64` or `lemma_sum_step_fits_u64`.",
        "If the slot is `i128`, call the `i128` lemma. Do not assume the add fits.",
        "Bind the group column from the struct before you use its length.",
        "If the field is `grp`, write `let keys = cols.grp@;` then `keys.len()`.",
        "Do not write `cols.grp@.len()` or any `cols.<field>@.len()`.",
        "Parenthesize a cast in a comparison: `(k as int) < (KEY_CAP_fact_grp as int)`.",
        "Use the `KEY_CAP_...` name from this spec. Do not write `k as int <`.",
        "Snapshot the index before you decrement it. After `i = i - 1` the old suffix",
        "is `i_old`, not `i`.",
        "",
        "A count walks the column from the end. The fit lemma's cap argument is the",
        "`ROW_CAP_...` const in the spec.",
        "If the spec has `pub const KEY_CAP_...: usize`, that is the exclusive key domain.",
        "Allocate `let mut counts: Vec<u64> = Vec::new();` and push a zero once per slot",
        "until `counts.len() == KEY_CAP_...`. Every loaded key is `< KEY_CAP_...`.",
        "The column loop invariant must include `valid_cols_<table>(cols)`.",
        "Without that name in the invariant, the key bound is not in scope.",
        "On each row, `let k = cols.<field>[i];` then call",
        "`lemma_index_key_below_cap(cols, i as int)` and",
        "`assert(k == cols.<field>@[i as int])`.",
        "That lemma ensures `(cols.<field>@[i] as int) < (KEY_CAP_... as int)`.",
        "Do not write a decimal bound such as `<= 255`. Use the `KEY_CAP_...` const.",
        "Read `prev` from `counts[k as usize]`, call",
        "`lemma_count_step_fits_u64(prev, ROW_CAP_...)`, then",
        "`counts[k as usize] = prev + 1`. Leave every other slot unchanged.",
        "After the column loop, `counts[k] as int == group_count(keys, 0, k)` for each",
        "slot. Copy a slot into the result map only when its count is nonzero.",
        "A HashMap update on every row loses the timed run on the large table.",
        "On the copy loop, give the quantifier an explicit trigger:",
        "`forall|k: u64| #[trigger] map@.contains_key(k) ==> ...`",
        "and prove it with `assert forall|k: u64| #[trigger] map@.contains_key(k) ==> ... by { ... }`.",
        "When the spec defines `lemma_dense_count_map`, call it once after that loop",
        "instead of re-proving the final `ensures` by hand:",
        "`lemma_dense_count_map(keys, counts@, map@, KEY_CAP_... as int);`.",
        "If the spec has no `KEY_CAP` const, keep the count in the result map:",
        "`prev` is the map value or 0, then insert `prev + 1`.",
        "",
        "This count verifies when the spec's names are `KEY_CAP_t_k`, `ROW_CAP_t`,",
        "`valid_cols_t`, and `cols.k`. Replace those four with the names in this spec.",
        "If the spec already uses them, paste the block unchanged. Do not rewrite the proof.",
        "Skip this block when the spec returns `Vec<OutRow>`.",
        "",
        "```rust",
        _COUNT_SHAPE,
        "```",
        "",
        "## Vec<OutRow>",
        "",
        "The result is one `OutRow` per group the ensures accept.",
        "`key_at` is the group key. `row_hit` is the row predicate, including filters.",
        "A string key uses `StringHashMap`. A tuple of strings uses nested `StringHashMap`.",
        "`StringHashMap::new` and `insert` need no hash axiom: `insert` ensures",
        "`final(self)@ == old(self)@.insert(k@, v)`.",
        "Do not call `HashMapWithView::new` on `String` or on a tuple. That `new`",
        "requires `obeys_key_model`, and importing an axiom is rejected.",
        "An integer group column is the one case for `HashMapWithView`: the spec",
        "broadcasts `axiom_<that integer>_obeys_hash_table_key_model`. Do not import it.",
        "One pass over the driving table. For a join or `EXISTS`, insert the other",
        "table's keys into a map first and probe it. A loop over one table inside a",
        "loop over another loses the timed run.",
        "Keep the groups the having condition accepts, sort by the order columns,",
        "and stop at the limit in the ensures.",
        "A one-table count defines `lemma_<count>_step` and `lemma_<count>_bound`.",
        "Call those. Do not re-prove the one-row equation or the row bound.",
        "Integer slots call the host fit lemma under the row cap.",
        "Float slots use one `f64` accumulator per group and call",
        "`lemma_f64_add_defined`, `lemma_f64_left_fold_push`, and",
        "`lemma_f64_sum_within_eps` with `FLOAT_ABS_EPS`.",
        "",
        "Floats. The spec is the real sum of the loaded floats, within `FLOAT_ABS_EPS`.",
        "Use one `f64` accumulator per group, added left to right.",
        "Call `lemma_f64_add_defined` before the add, then `lemma_f64_left_fold_push`,",
        "then `lemma_f64_sum_within_eps`. Pass `FLOAT_ABS_EPS`. Do not write a numeric",
        "epsilon. Do not unfold an `f64` add. Do not truncate the float to an integer.",
        "",
        "A join sum contains a group when some row of each side shares the join key",
        "and the group column has that value. The value is the sum of the loaded",
        "measure over those pairs. If the spec's sum cap is one side's row cap times",
        "the cell cap, the other side's key is unique. Use that cap in the fit lemma.",
        "",
        "## Tools",
        "",
        "lemma-host MCP is already approved (`--approve-mcps`).",
        f"1. Edit `{edit_path}`.",
        "2. Call `run_runquery` with `path` `runquery_agent.rs`.",
        "   That call verifies, compiles, and runs this declarative program.",
        "   It does not look for `method_spec`.",
        "3. Call `submit_runquery` with the returned `run_id`.",
        "Do this before the session ends. If `run_runquery` returns an error, fix the",
        "edit and call it again. Do not search the image for another copy of the lemma.",
        "",
        "## Lemma index",
        "",
        lemma_index.rstrip(),
        "",
        "## Other spec style",
        "",
        "The recursive product path uses a spec function that recurses on two indexes",
        "and defines the result map in spec code, with `ensures res == that function`.",
        "That is the other spec style. Do not write that here.",
    ]
    if last_error.strip():
        sections.extend(
            [
                "",
                "## Previous host error",
                "",
                "The last compile or verify of your edit failed. Fix that edit and call",
                "`run_runquery` again.",
                "",
                "```",
                _error_excerpt(last_error),
                "```",
            ]
        )
    return "\n".join(sections) + "\n"
