# Declarative run_query

## What you get

- `/workspace/runquery_agent.rs` already holds the host spec, the host lemmas, the loaders and `run_query`. You edit it.
- Read-only: `/workspace/context/ro/spec.rs` (same spec), `/workspace/context/ro/query.sql`, `/workspace/context/ro/schema.json`, `/workspace/context/ro/lemma_index.md`,
  `/workspace/context/ro/examples/` (verified example bodies; start with `INDEX.md` there: shape -> file -> what it proves),
  `/workspace/context/ro/verus/` (vstd source, Verus guide, small examples;
  read `INDEX.md` first (one grep recipe per common lookup), then grep `LEMMAS.md`, `EXAMPLES_INDEX.md` and `GUIDE_INDEX.md`).
- Look up vstd with one grep, e.g. `grep -n -A5 "^## StringHashMap::" LEMMAS.md` (in `verus/`): `INDEX.md` has a
  recipe per common lookup (`Vec::push`, `String::eq`, `decreases`, `assert forall`, `choose`, broadcast groups).
- Tools: the file edit tool; `run_runquery` (path `runquery_agent.rs`) verifies, compiles and times your
  program on the official table; `submit_runquery` with the returned `run_id`. In Claude Code these are
  `mcp__lemma-host__run_runquery` and `mcp__lemma-host__submit_runquery`; if they are not in your tool list yet, load
  them first with ToolSearch (`select:mcp__lemma-host__run_runquery,mcp__lemma-host__submit_runquery`). A Bash tool
  may exist, but it has no network and Verus is not on its PATH: `run_runquery` is the only Verus you have, so do not
  try `verus`, `npx` or any package install.
- Done means: Verus says `N verified, 0 errors`, the result equals the reference engine's rows, and the timed run beats
  the reference engine (`run_runquery` reports the speedup). `submit_runquery` accepts only a run that is `ok`, i.e. one that also
  beats the reference engine: a verified body below the bar is reported as `proved but below the speed bar`, is refused by
  `submit_runquery`, and still counts as your best proved run. Keep it aside as your base (copy the file), then make it faster.
  Submit a body as soon as it verifies and beats the bar, and again if a later one is better.

## Regions and rules

- Two regions are kept, everything else in the file is discarded: the `run_query` body between
  `// AGENT_EDIT_START` and `// AGENT_EDIT_END`, and `proof fn` / `spec fn` / exec `fn` helpers between
  `// AGENT_HELPERS_START` and `// AGENT_HELPERS_END` (just above `run_query`). A nested `proof fn` or
  `spec fn` inside the body does not work. A helper may not reuse a name the host spec defines.
- Write no `use` lines: every vstd module is imported by glob; call lemmas by bare name
  (`vstd::map_lib::lemma_map_new_domain` in full; that one name is ambiguous).
  The only allowed line is `broadcast use vstd::<module>::group_<name>;` naming a group listed in
  `/workspace/context/ro/verus/INDEX.md` (it turns a bundle of vstd lemmas and axioms on for the solver; any vstd group is allowed, including one that lists `axiom_*` members: they are vstd's own trusted core; more groups, more noise), e.g. `broadcast use vstd::seq::group_seq_axioms;`. Write it inside the body or inside a `proof fn` body; at the top level of the helper region it is rejected.
- Forbidden (rejected before Verus runs): `assume(`, `admit(`, `#[verifier::external_body]`, `assume_specification`,
  `unimplemented!`, any attribute other than `#[verifier::opaque|rlimit|loop_isolation|spinoff_prover|truncate|inline|memoize|trigger|auto]` / `#[trigger]` (so no `external*`, `exec_allows_no_decreases_clause`, `cfg`, `derive`), `impl` / `trait` / `macro_rules!` / `static`, and any name containing `axiom`, `arbitrary` or `proof_from_false` outside a `broadcast use vstd::<module>::group_<name>;` line (you cannot write an axiom of your own). The hash-key
  axiom is already broadcast: do not name it. `requires`/`ensures` are the host's; changing them has
  no effect.
- `StringHashMap` and `HashMapWithView` are in scope (`new`, `insert`, `contains_key`, `get`; the view key
  is `Seq<char>` for strings). `StringHashMap::new` needs no axiom. Do not call `HashMapWithView::new` on
  a `String` or a tuple key.

## SQL

```sql
select sum(lo_revenue), d_year, p_brand1
from lineorder, date, part, supplier
where lo_orderdate = d_datekey and lo_partkey = p_partkey and lo_suppkey = s_suppkey and p_category = 'MFGR#12' and s_region = 'AMERICA'
group by d_year, p_brand1
order by d_year, p_brand1
```

## Official size and the bar

The timed run is on the full tables (row caps in the spec: `lineorder` 33,554,432, `part` 1,048,576, `date` 16,384, `supplier` 8,192), not on the 50,000-row iterate cap that
`run_runquery` uses by default: a time or speedup at 50k says nothing about the official run. The bar is the reference
engine on ALL cores. One thread does not beat it on a scan or aggregate over millions of rows.
Order: (1) get ANY body to `N verified, 0 errors` first; sequential is fine, and `submit_runquery` it as soon as it
verifies (a later submit replaces it, re-submitting costs nothing, and a session killed at the wall saves nothing that was
not submitted; a verified run below the bar is refused by `submit_runquery`: keep that file as your base). (2) Read the `speedup` field of that run. At or above the bar: you are done. Below the bar: only now try
the parallel recipe below (workers over row ranges) as an upgrade. (3) Submit the parallel body only if it verifies and its
`speedup` is higher; never replace a submitted verified body with an unverified or slower one. If the upgrade does not
verify after a few checks, stop and keep the sequential submission (say its `speedup` is below 1).

## Hardware (this machine; the timed run and the reference engine both run here)

```
CPU(s):                                  8
Model name:                              AMD Ryzen AI 5 330 w/ Radeon 820M
Thread(s) per core:                      2
Core(s) per socket:                      4
Socket(s):                               1
L1d cache:                               192 KiB (4 instances)
L2 cache:                                4 MiB (4 instances)
L3 cache:                                8 MiB (1 instance)
NUMA node(s):                            1
MemTotal: 15453564 kB
compile target: -C target-cpu=x86-64-v3 (the CPU may have more SIMD than this; the binary uses the target only)
reference engine: DuckDB, threads=8, memory_limit=3GB
```

Guidance, not measurement: about one worker per PHYSICAL core (cores = Core(s) per socket x Socket(s)) for memory-bound scans, since SMT threads add little;
give each worker one contiguous row range and its own accumulators (no shared mutable cell between workers: false sharing); the L3 is far smaller than a large column,
so a big scan is bandwidth-bound and narrower cells and fewer passes help more than arithmetic; keep per-block working sets within L1/L2 (a few thousand elements per chunk);
write the hot loop branch-free (accumulate `acc + (value & mask)` or `count + (hit as u64)` instead of `if hit { .. }`) so the compiler can vectorize it.
The worked parallel example uses 8 workers as a literal; replace it by the worker count you choose, consistently everywhere the example uses it.

## The recipe for THIS spec

This spec's result type is `Vec<OutRow>`.
A verified body for a close shape (dictionary string mode, STAR JOIN (SSB Q4.1): a fact table scanned once, four unique-key dimension tables reached through arrays indexed by key, GROUP BY an int and a dictionary string, SUM of an expression, ORDER BY both keys; uses the host lemma `lemma_<fold>_row` (LEMMA_JOIN_CHAIN)) is `context/ro/examples/hard/dict_star_join_group_sum_sorted.rs` (hundreds to a few thousand lines, read it
with the Read tool, do not paste it blind). Its header, which says what each technique is for:

```
// Worked example (hard; dict + LEMMA_JOIN_CHAIN=1, sequential): SSB Q4.1, a STAR JOIN: one fact table (`lineorder`, 6M rows) and four dimension tables joined on their
// unique keys, GROUP BY an integer (`d_year`) and a dictionary string (`c_nation`), SUM of an expression, ORDER BY both keys (the string by `seq_le`).
//   select d_year, c_nation, sum(lo_revenue - lo_supplycost) as profit
//   from date, customer, supplier, part, lineorder
//   where lo_custkey = c_custkey and lo_suppkey = s_suppkey and lo_partkey = p_partkey and lo_orderdate = d_datekey
//     and c_region = 'AMERICA' and s_region = 'AMERICA' and (p_mfgr = 'MFGR#1' or p_mfgr = 'MFGR#2')
//   group by d_year, c_nation order by d_year, c_nation
// SSB SF1 (lineorder 6,001,215 rows): 62 verified, 0 errors; 35.1 ms (median) vs 36.1 ms for the all-core DuckDB (1.03x, one thread; the box was busy with other runs).
// Why this is short: with LEMMA_JOIN_CHAIN=1 the spec nests the FACT table first and `valid_cols` says each dimension key is UNIQUE, and the host proves
// `lemma_sum_profit_row(.., j, k)`: for every hit tuple y of fact row j, the fold of row j equals the term of y; with no hit it is 0. So the proof never counts matches.
// Plan: (1) per dimension, a row-level value `*val` (65535 = 0 means the row fails its filters; otherwise code+1) and `build_index` turns it into an array indexed by key+offset
//   (`arr_fwd`: every passing row is found; `arr_bwd`: every non-empty cell comes from a row). (2) One pass over the fact rows: four array reads; if all are non-empty the tuple
//   (j, d, c, s, p) is the unique hit (`row_hit` unfolds to the key equalities and the filters), its slot `yc * m + nation_code` gets the value and `pres[slot] = true`;
//   invariants per slot: `acc[slot] == fold(0, key) - fold(j, key)` (so at the end the whole fold), a magnitude bound for the i64 add, `pres => wit` (a hit tuple exists),
//   and "every hit tuple of a row below j is present" (coverage). `lemma_step_hit` / `lemma_step_none` are the per-row step from the host lemma. (3) The dictionary codes
//   are sorted once by string (`ord`, insertion with `str_le`, `ord_ok`), then rows are emitted by year and sorted code, so the output is sorted and duplicate-free by construction.
// Other star queries: change the filters (`*_pass`, the literal codes), the dimension list, and the key (`kyc`, `sl`); a group key that is a dimension STRING needs its own code array.
```

## Dense slot table: allowed or not, for THIS query

- Key domains: part.p_brand1 (1000) = 1000 slots, within the budget of 4194304 (LEMMA_DENSE_SLOT_BUDGET). A dense table (one slot per code
  combination) IS allowed here; a packed-key `HashMapWithView` also works.

## Star / chain join: what the host has already proved (this spec nests the FACT table first)

The first parameter is the fact table, and every other table has a UNIQUE key in its `valid_cols_<t>` (a catalog assumption the loader checks):
at most ONE row of each other table matches a fact row, so you never count matches.
- `lemma_chain_hit_unique(P.., j, a1.., b1..)`: two tuples that both satisfy `row_hit` for fact row `j` are equal.
- `lemma_sum_sum_row``(P.., j, k)`: for EVERY tuple `y` with `row_hit(P.., j, y..)`: `sum_sum_d1(P.., j, 0, k) == chain_term_sum_sum(P.., j, y.., k)` (the term is the value if the key of `y` is `k`, else 0);
  and if no tuple is a hit, `sum_sum_d1(P.., j, 0, k) == 0`. The fold of the whole table then steps by unfolding: `sum_sum(P.., j, k) == sum_sum_d1(P.., j, 0, k) + sum_sum(P.., j + 1, k)`.
- `lemma_sum_sum_zero_dL` / `lemma_sum_sum_single_dL`: the per-level lemmas behind it, for a different shape of argument.
Plan: one pass over the FACT table; for each dimension an array indexed by `key + offset` (the offset from the `valid_cols` bound of that key column) holding what the
group key and the filters need (build it once from the dimension rows, with a magnitude `arr_fwd` / `arr_bwd` pair as in the example); if every lookup finds a row, that tuple
IS the hit of fact row `j` and the step lemma above gives the fold of row `j`; if one lookup fails, no tuple is a hit. Never loop over a dimension inside the fact loop.
Because each fact row contributes at most ONE tuple, a SUM is at most (fact rows) x (largest term): that is the overflow bound of your accumulator (the cell magnitudes are in `valid_cols_<t>`;
the examples keep `-(rows seen) * M <= acc <= (rows seen) * M` per slot). Without the unique keys the join could have 2^100 tuples and no `i128` could hold the sum; here it cannot.

## Parallel scan (this spec's `run_query` also takes `<table>_arc: &std::sync::Arc<Cols_<table>>`)

The extra parameter is the same table, shared (`requires **<t>_arc == *<t>`; the `ensures` are unchanged). You may run
workers with `vstd::thread::spawn` and `JoinHandle::join` (vstd's own, not trusted code of ours): each worker owns an
`std::sync::Arc::clone(<t>_arc)` and folds a row RANGE `[lo, hi)`; the host's suffix folds are additive over ranges, so
worker k returns `fold(t, lo_k) - fold(t, hi_k)` and the partials telescope to `fold(t, 0)`. No column is copied.
A scan that is limited by memory bandwidth is the case this is for: on the real 39.4M-row table the parallel SUM was
12.8x faster than the all-core reference engine. Keep the single-threaded body as the first proof,
then upgrade only if it loses. A hash aggregate or a join does not telescope directly, but a GROUP BY over a small code domain does: give each
worker its own DENSE array per aggregate (one slot per dictionary code), merge them slotwise in the join loop, and the slotwise
telescoping is the same proof (dict mode: `context/ro/examples/dict_group_count_sum_parallel.rs`, 13x on the real 39.4M-row table;
a nullable dictionary column with a string filter, COUNT and MIN: `context/ro/examples/parallel_dict_nullable_count_min.rs` (1.8x on real `pre`);
A dense table has one slot per combination of key codes; it is allowed only when the product of the key dictionaries' sizes is within `LEMMA_DENSE_SLOT_BUDGET` (default 2^22 slots). The section "Dense slot table: allowed or not, for THIS query" below says which case this query is; otherwise key the groups by a packed code tuple in a `HashMapWithView`;
two dictionary keys, several aggregates, sorted output, a flat m1*m2 slot array: `context/ro/examples/hard/dict_parallel_q1.rs`, TPC-H Q1 at 3.95x).
Every multiplier quoted in this prompt is a manual-prover result for the timed `run_query` ALONE (kernel only) against the reference engine scanning its own storage in place; pin, copy into the vectors and encoding are outside the timer (about a second for tens of millions of rows) and a reference engine holding the same narrow data in memory is about 1.8x to 2.1x slower than our kernel, not 2.4x to 2.9x. `run_runquery` reports the same kernel-only speedup.
The example is the template (SUM; adapt the fold, the filter, the cell bound and the accumulator type):
`context/ro/examples/parallel_ungrouped_sum.rs` (also `parallel_ungrouped_product_sum.rs` for a product with a date filter, and `parallel_ungrouped_min.rs`, `_max.rs`, `_count.rs`: MIN/MAX merge the workers' (value, any) pairs, COUNT is additive).
A parallel STAR JOIN (a fact table split over 8 workers; the dimension arrays are built once and shared through `Arc`; each worker returns a flat slot array pair that the join loop merges):
`context/ro/examples/hard/dict_parallel_star_join_group_sum_sorted.rs` (SSB Q4.1: 2.7x the all-core engine, against 1.03x for the single-threaded `dict_star_join_group_sum_sorted.rs`). Turn the sequential
fact loop into the nested `fn scan(.., lo, hi)` of that file and keep the rest. Two dictionary group keys, a WHERE-bounded year and ORDER BY a year then a SUM descending:
`context/ro/examples/hard/dict_parallel_star_join_two_keys_revenue_order.rs` (SSB Q3.1, 2.4x). Two string keys from two dimensions with ORDER BY the strings:
`context/ro/examples/hard/dict_parallel_star_join_two_keys_string_order.rs` (SSB Q4.2, 2.25x).
A parallel HASH GROUP BY with a merge (an integer key too wide for a dense array; per-worker hash tables, merged by key; then the top-N selection and the host closing lemmas):
`context/ro/examples/hard/dict_parallel_hash_group_topn.rs` (1.46x on the real 39.4M-row table). Notes from it: the helper region also admits exec `fn`s, but this file keeps the worker's
fold and the merge step are NESTED `fn`s at the top of the `run_query` body; a `struct` is not admitted either (use a tuple); a postcondition on a `&mut` parameter uses `final(x)` / `old(x)`.

## Grouped result: host-proved closing lemmas (call by bare name; already proved with the spec)

The hard part of a grouped query's `ensures` is the four quantified facts about `res@`: every row satisfies `out_row_ok` (an existential over the joined rows),
the rows' keys are pairwise distinct, every group is present unless the result is full, and (no ORDER BY ... LIMIT here, so no omitted-group fact). The host proved all of them from a plain description of what your code built, so you do not prove them from loop invariants of the exec code:
- a ghost `gk: Seq<KeyType>` (the spec's key type, see `lemma_group_close_rows`'s signature) of group keys: pairwise distinct; containing the key of every joined row that passes
  WHERE and HAVING; with a ghost `gw: Seq<(int, ..)>` of witnesses: `gw[g]` is one joined row (its index tuple) that passes WHERE and HAVING and has key `gk[g]` (only `lemma_group_close_rows` takes `gw`; push the witness when you push the group);
- a ghost `used: Seq<bool>` (one flag per group) and `pos: Seq<int>` (for a used group, the result row where it was chosen: `sel[pos[g]] == g`; a plain pointwise fact, no existential)
  taken by `_present` and `_omitted` only (`used` replaces 'appears in sel');
- a ghost `sel: Seq<int>`, one entry per result row: the index into `gk` of the row's group (distinct), with `res@[r]`'s key fields equal to `gk[sel[r]]` and its aggregate
  fields equal to the spec's folds for that key (`HAVING` too); `res@.len()` equals the LIMIT unless every group is `used`;
Then at the end of `run_query` call, with `res@`, `gk` and `sel` (get them with `Ghost`/`Tracked` variables or `Seq` built in `proof { }` blocks):
`lemma_group_close_rows(P.., res@, gk, gw, sel)`, `lemma_group_close_distinct(.., gk, sel)`, `lemma_group_close_present(.., gk, sel, used, pos)`;
each ensures exactly the matching `run_query` postcondition. Their `requires` are the bullets above, spelled out (read their signatures in the spec). Call EACH closing lemma from its own small helper proof fn (one fact per helper, with only the hypotheses it needs, in the helpers region) and call `_omitted` FIRST: the combined call inside `run_query` or one big helper exceeds the rlimit. The order (sortedness) and the
`<= LIMIT` clauses are not covered: keep them as loop invariants of the selection loop. A selection loop that repeatedly takes the best unused group (a 'used' flag per group) keeps
the invariants `sel` distinct, every unused group not ahead of any chosen row, chosen rows in order, which are exactly the hypotheses above.
Outline of the long worked example `hard/dict_join_group_count_distinct_topn.rs` (its helper region is the bulk; port the pieces, not the file): (1) a build pass over the
dimension table creating the dynamic group table (a `Vec` of group keys with a witness row per group, a lookup by linear scan or hash map) and the chain index of dimension
rows per join code; (2) one pass over the fact table: probe the chain, add to the group's total, insert into the group's seen set (per group a `HashMapWithView` keyed by the
distinct value's code or integer, or a `Vec<bool>` over a dictionary whose length the catalog caps), each step tied to the spec fold by the host lemmas (`N_set` steps, the fold's own
unfolding for SUM/AVG parts); (3) the selection loop with `used`/`pos`/`sel` and two-term-trigger sortedness invariants; (4) the closing calls in separate small helpers (`_omitted` first).
Do not give up on a long example: write the whole body in pieces, run the check, and fix the first failing clause; every piece is an ordinary loop invariant.


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

## Which shapes have worked examples

`context/ro/examples/INDEX.md` is a generated table of shape -> file -> what it proves (with line counts) over every verified
example: grouped and ungrouped aggregates, joins, projections, floats, TPC-H shapes, parallel scans and, in dictionary mode,
the long published-shape examples. Open the index first, pick the closest row, read that one file (a long one by ranges:
header comment, then the loop you need). Do not read the whole directory.

KNOWN HARD, no worked example: a join whose key repeats on both sides (many-to-many) with `COUNT(DISTINCT ...)`;
`EXISTS`/`IN` joins (outside dictionary mode); multi-key `DISTINCT`; set operations. These need long helper proofs (an
existential witness per group, a selection invariant). Start with the simplest correct loop that proves, make sure a
verified body is submitted, and only then look for speed. Floats are exact reals here (`float_*.rs`).

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

## Proof hygiene that costs people time

- Bind a column before taking its length: `let keys = cols.grp@;` then `keys.len()`; do not write `cols.grp@.len()`.
- Parenthesize a cast in a comparison: `(k as int) < (KEY_CAP_t_k as int)`.
- A loop that walks down: snapshot the old index (`let i_old = i; i = i - 1;`) before using the old suffix.
- Every loop needs `decreases`; keep `valid_cols_<table>(cols)` in every loop invariant (the key and cell bounds
  come from it). Call host lemmas as `proof { lemma_...(); }`. Give a quantifier an explicit `#[trigger]`.
- A quantified loop invariant whose body mentions the NEXT index loops the solver (Z3 matching loop; the profile shows one quantifier with an astronomically large cost):
  `forall|q| #![trigger res@[q]] .. res@[q].total >= res@[q + 1].total` instantiates `res@[q + 1]`, which instantiates it again. Use the two-term trigger
  `#![trigger res@[q], res@[q + 1]]` (the host's own sortedness postcondition is a goal, not a hypothesis, so it is safe).
- A fact about a ghost `Seq` (or any variable) that the loop does not modify is NOT remembered across the loop: repeat it in the loop's `invariant` (e.g. `gk.len() == gw.len()`, the group-table facts), or the loop-body and the code after the loop lose it.
- `#[verifier::rlimit(N)]` on a helper proof fn is accepted by the admission lint and raises that one function's budget; use it on a single closing helper that is genuinely just large, not to hide a matching loop (profile first when you can).
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
- The helper region takes `proof fn`, `spec fn` and plain exec `fn` items. An exec helper is verified by Verus against its
  own `requires` / `ensures` (give it a `decreases` on every loop and recursion; the no-decreases attribute is rejected),
  and `run_query` may rely only on those `ensures`. No `struct`, `impl`, `trait`, `macro_rules!`, `static` or `use` there.
- The host's backward recursive folds fit a single backward pass (`let mut i = t.n; while i > 0 { i -= 1; ... }`)
  with suffix invariants (`acc == fold(rows i..n)`); prefer it to a forward pass.
- A product of two cells needs its own bound assert (for example `price * (100 - disc) <= 2e30` from the cell cap
  1e15); a sum is bounded by (rows seen) * (cell bound).
- Short string keys (1 or 2 characters) are cheapest as small integer codes from `as_bytes` (vstd `utf8.rs`,
  grep `LEMMAS.md` for `as_bytes`) indexing a slot table, not as hashed strings.
- The verifier's rlimit budget is the host's `--rlimit` (16 by default); the error names the main loop even when the
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

## Helper region example

```rust
// AGENT_HELPERS_START
proof fn plus_zero(x: int) ensures x + 0 == x { }
// AGENT_HELPERS_END
// in the body:  proof { plus_zero(3); }
```

## Lemma index

# Declarative spec lemma index

Write the `run_query` edit before you read the rest of this index.
Every vstd module is already imported by glob. Write no `use` lines.
The one allowed line is `broadcast use vstd::<module>::group_<name>;` (exact name, see
`context/ro/verus/INDEX.md` for the list).
Still forbidden: `assume(`, `admit(`, `#[verifier::external_body]`, and a name containing
`axiom`, `arbitrary`, or `proof_from_false`.
A new `spec fn` or `proof fn` goes between `// AGENT_HELPERS_START` and `// AGENT_HELPERS_END`.
`proof { lemma_...(); }` is allowed.

Host lemmas (call these; the integer adds need none, Verus checks overflow itself):

- `lemma_dense_count_map(keys, counts, map, key_cap)`, when this spec defines it. Once every slot of `counts` equals `group_count(keys, 0, k)` and `map` holds exactly the nonzero slots, the map meets the `ensures`. Call it after the copy loop. Pass `KEY_CAP_... as int`.

vstd items the declarative spec uses:

- `HashMapWithView::<K, V>::new`, `insert`, `contains_key`, `get` (vstd::hash_map). `insert` ensures the view is `old(self)@.insert(k@, v)`.

- `StringHashMap::<V>::new`, `insert`, `contains_key`, `get` for string keys; view key is `Seq<char>`.

- `Map::contains_key`, `Map::insert`, `Map::empty` (vstd::map) as the spec view.

- The host already broadcasts `vstd::std_specs::hash::axiom_u64_obeys_hash_table_key_model` (and the i64 and i128 variants) for the group key. Do not use it by name. A name containing `axiom` is rejected except inside `broadcast use vstd::<module>::group_<name>;`, which is allowed for every vstd group.

- `Seq::len`, `Seq::index`, `Seq::skip`, `Seq::push`.

You may call these and other vstd lemmas by bare name; look them up in `context/ro/verus/` when unsure. Do not use a name containing `axiom`, `arbitrary`, or `proof_from_false`. Do not `assume(` or `admit(` a fact. Write helper `spec fn` / `proof fn` items only in the helper region.

Dictionary-encoded string columns (this spec has `<col>__dict` fields):

- A string column `c` is two vectors: `t.c` (one small integer CODE per row) and `t.c__dict` (the distinct strings).
  The spec reads a cell as `t.c__dict@[t.c@[i] as int]@`; `valid_cols` gives you that every code is below
  `t.c__dict@.len()` and that dictionary entries are pairwise distinct. Nothing about `t.c[i]` itself is a string.
- `c = 'lit'` becomes a code comparison. Look the literal's code up ONCE before the row loop (scan `t.c__dict` with
  `String == String`, keep `found` and `code`); distinctness makes it the only entry equal to the literal, so the
  cell equals the literal exactly when `found && (t.c[i] as usize) == code`. The row loop then reads one small
  integer per row. A worked body: `context/ro/examples/dict_string_filter_minmax.rs`.
- GROUP BY a string key: use a dense array indexed by the code (`counts: Vec<u64>` of length `t.c__dict.len()`),
  then build the result from the nonzero slots; the dictionary entry is the key string. The result is a `Vec<OutRow>`
  whose key field is a `String`. A worked, verified body (counts backwards to match the suffix fold, a ghost slot
  sequence for the output rows, `lemma_count_pos` for 'count > 0 means a witness row'):
  `context/ro/examples/dict_group_count_dense.rs`.

## Do this now

This is a non-interactive session: nobody answers questions. Do the task now. Never ask the user anything and never
offer options. Do not stop until `run_runquery` shows `N verified, 0 errors` and you have called `submit_runquery`
with the `run_id` of your best verified body (a parallel upgrade, where the spec has one, is tried only after a verified
body exists and is submitted, and only when its `speedup` is below the bar). A verified body that stays below the bar cannot be
submitted (the host refuses it): keep improving it until the wall, and leave your best verified file in place. If you conclude it cannot verify, say plainly why in your
last message; an empty or placeholder body is a failure, not a result.
