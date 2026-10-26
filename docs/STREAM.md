# Streaming executors (ABI 6, flag `[run] stream`, design 2026-10-25)

Goal: win on FRESH data (first call after a change). Today the extension converts DuckDB's columns into contiguous Rust
`Vec`s before the proved `run_query` runs; that copy costs more than DuckDB's whole query (TPC-H SF10 Q1: ~890 ms of
conversion vs 271 ms for DuckDB). The input cache only hides it for repeated identical inputs on unchanged data, where a
result cache would win as well. A streaming executor consumes DuckDB's scan chunks in place (JetStream-style): DuckDB scans,
filters and decompresses in parallel; the proved code replaces the aggregate/join operators. Every piece of LLM-written code
stays Verus-proved. Emil allowed new trusted items for data loading (2026-10-25); this design needs two (S1, S2).

Prior art in the repo: `[wip] cold_stream` (tag `archive/pin-path-2026-10-07`, `research_loop/menus/pin_path_archive.md`) got
0.65-0.87x of DuckDB on ungrouped sums (DuckDB's scan was 70-90 % of the time); its proved permutation-sum library
`declarative_spec/cold_lib.rs` (`sum_by`, `lemma_sum_by_perm`) is reused here. Its DISTINCT bug cannot recur: we run the scan.

## Contract

One ghost table `T = stream_table_t(id)` per stream (the rows DuckDB's parallel scan of `t` returns in the caller's transaction:
MVCC applied, transaction-local rows included, NO pushed predicate by default, each row exactly once, at the offset an atomic counter
assigned when the chunk was handed out). The spec's WHERE is evaluated by the agent's step (`agg_row` includes `row_hit`): the spike
(2026-10-25) measured a pushed filter at +47 ms on SF10 Q1 (every vector, fixed-width too, wrapped in a selection) against a branch-free
filter in the kernel. A per-table push option (zone-map pruning on sorted data) may come later, default off; a pushed conjunct of the
WHERE is sound either way (the spec re-applies the WHERE to the rows it gets).

Host-emitted per query (all proved, nothing trusted): a spec-only `Agg` struct (one field per aggregate plus `hits`),
`agg_zero`, `agg_plus` (+ on ints; omin/omax on Option), `agg_row(t, i, k, p)`, `agg_rng(t, lo, hi, k, p)` (SUM/COUNT/AVG
fields as differences of the existing suffix folds; MIN/MAX as a new range fold), and the lemmas `lemma_agg_step` (one row),
`lemma_agg_laws` (comm/assoc/identity) and `lemma_agg_total` (the full range agrees with the spec's folds; `hits > 0` iff the
group exists; `min_rng == Some(b) ==> min_m`).

Agent writes (regions AGENT_STATE / HELPERS / INIT / STEP / MERGE / FINISH; admission as for `stateful`):

```rust
pub struct QAcc { .. }                                   // no references, no lifetimes
spec fn qacc_inv(s: &QAcc) -> bool;  spec fn st_val(s: &QAcc, k: Key) -> Agg;
pub fn q_init(p: &Params) -> (s: QAcc) ensures qacc_inv(&s), forall|k| st_val(&s,k) == agg_zero();
pub fn q_step(s: &mut QAcc, c: &Chunk_t, p: &Params) -> (ok: bool)
    requires qacc_inv(old(s)), chunk_ok_t(c)
    ensures ok ==> qacc_inv(s) && forall|k| #[trigger] st_val(s,k) ==
        agg_plus(st_val(old(s),k), agg_rng(&stream_table_t(c.sid), c.off as int, (c.off+c.len) as int, k, p@));
pub fn q_merge(a: QAcc, b: QAcc) -> (r: Option<QAcc>)
    ensures r matches Some(r) ==> qacc_inv(&r) && forall|k| #[trigger] st_val(&r,k) == agg_plus(st_val(&a,k), st_val(&b,k));
pub fn q_finish(s: QAcc, t: Ghost<Cols_t>, p: &Params) -> (res: Option<Vec<OutRow>>)
    requires qacc_inv(&s), valid_cols_t(&t@), forall|k| #[trigger] st_val(&s,k) == agg_rng(&t@, 0, t@.n as int, k, p@)
    ensures res matches Some(r) ==> run_query_ok(&t@, p, r);
```

Host runtime (fixed template, verified with the program): `Exec { sh, acc, segs, gsegs }` with a type invariant
`st_val(acc, k) == seg_fold(T, gsegs, k)`; `exec_step` gets a chunk via S1, calls `q_step`, records the segment; `exec_merge`
concatenates segments; `exec_finish` gets `n` via S2 and checks at run time that the segments tile `[0, n)` exactly (each chunk's
`(j, off)` from one `fetch_add`; every slot filled once, offsets contiguous). A lost, doubled or skipped chunk is an ERROR, never a
wrong answer, so the scheduling glue is not trusted. Generic lemmas (push/concat, permutation invariance for sum/min/max/union,
tiling) are proved once in `research_loop/verus_lib/stream_lib.rs`. ORDER BY / LIMIT / HAVING happen in `q_finish`.

Gate (`declarative_spec/stream.py`): refuses loudly (no auto fallback) rowid, order-dependent aggregates and, in phase 1,
anything that is not a grouped or ungrouped single-table aggregate.

## Trusted items (new, data loading; authorized by Emil 2026-10-25)

* **S1 chunk view.** `chunk_t(sh, raw) -> Chunk_t` (`external_body`): `c.sid == sh.id`, `c.off + c.len <= T.n`; for each fixed-width
  field `c.f@[r] == T.f@[c.off + r]` where the cell is valid (column-file encoding: DATE days, DECIMAL scaled); for nullable fields
  `c.f_valid@[r] == T.f__valid@[c.off + r]`; for VARCHAR `c.g.ents@[c.g.sel@[r]] == T.g@[c.off + r]@` where valid; plus the accessor
  `str_ent(&v, j) -> &str` with `s@ == v.ents@[j]`. Chunks come from DuckDB's own scan loop, read through `UnifiedVectorFormat`
  (FLAT / CONSTANT / DICTIONARY; others flattened), validity read at the physical index; fixed-width cells zero-copy or decoded by the
  tested `DecodeInts` into a 2048-cell per-worker buffer; `string_t` layout pinned by `static_assert` for 1.5.6. The glue checks
  `sel[r] < n_entries`, lengths and UTF-8 (checked, not trusted).
* **S2 stream end.** `stream_end_t(sh) -> (m, n)` (`external_body`): when every worker has returned, `n == T.n` and
  `valid_cols_t(T)`.

## ABI 6 (extension)

`lemma_stream_layout`, `lemma_stream_open(build cols, params)`, `lemma_stream_worker`, `lemma_stream_step(worker, chunk)`,
`lemma_stream_merge(into, from)`, `lemma_stream_seal` (phase 2b), `lemma_stream_finish(worker, out)`, `drop`/`close`. The extension's
`StreamTable` is the `ScanTable` worker loop without destinations/packing/dictionaries: per chunk a `LemmaChunk`, step; at the end
pairwise merge, finish, LMR1 output as today. Dispatch on manifest `abi_version == 6`, `mode: "stream"`. No input cache for v6.
`lemma_last_query` gains `mode`, `chunks`, `threads`.

## Strings

Stream tables use `plain` encoding in the ghost spec (never materialized). Exec side: per chunk, `sel` + `entries` (DuckDB
`string_t`); the agent memoizes entry -> slot once per chunk (`StringHashMap<usize>` lookups by `&str`), then per row an array
index. Phase 3: a host-proved open-addressing byte hash table (equality proved; hash quality needs no proof) instead of SipHash.

## Joins

Inner joins, streamed table outermost (the nested fold keeps "difference of suffix folds"). Phase 2a: build side materialized through
the ABI 5 inputs (`q_build -> QBuild`, read-only in `Shared`). Phase 2b: streamed build stages (`lemma_stream_seal`). The generator
streams the table that is largest after filters.

## Phases

1. Single-table aggregates (TPC-H Q1, Q6). Step 0 spike measures the floor (scan + in-place hand-off vs DuckDB) before contracts.
   Then `stream_lib.rs`, `stream.py` + emission (host scaffold must verify with a stub body), stream `main` + ABI 6 template,
   extension `StreamTable`, install, dev fixtures (Verus-checked, mutants must fail), tests (flag off byte-identical; binary and
   extension differentials incl. every vector form via `force_compression`, deletes/updates/local rows, templates, interrupts),
   measure cold and right after an INSERT, one committed Opus run on Q1. Exit: SF10 Q1 cold below DuckDB, Q6 at or below.
2. Joins (Q12, Q3, SEC q1 with COUNT DISTINCT as a `Set` field).
3. String-heavy SEC (q2, q4, q6, q24): composite string keys, anti-join, two passes, proved hash table.

Risks: DuckDB handing FLAT (not DICTIONARY) vectors for low-cardinality VARCHAR (SipHash per row); Verus `type_invariant` across FFI;
per-query lemma rlimits; agent success with string-keyed state; serial merge for high-cardinality GROUP BY; thread oversubscription.

## Phase 1, spec side: what is emitted (exact API; `declarative_spec/stream.py`, 2026-10-25)

`emit_declarative_spec` with `[run] stream = true` replaces `run_query` (after the decline wrap) by the block below; everything else in the
spec (`Cols_<t>`, `valid_cols_<t>`, `row_hit`, `key_at`, the suffix folds, `run_query_ok`) is unchanged. `<t>` is the table suffix.
Only the three items marked TRUSTED are `external_body`; three `#[verifier::external]` helpers with no spec at all
(`lemma_stream_slice`, `lemma_stream_str_bytes`, `lemma_stream_strings_ok`) are parts of S1's body. No other trusted item was added.

Host, proved (per query):
* `pub struct Params { pub <name>: i32|i64, .. }` (the template parameters, `#[derive(Clone, Copy)]`; empty without templates),
  `params_eq`. The run_query `requires` on parameter ranges are not carried over (they only bounded the old arguments; VARCHAR
  parameters are refused in phase 1).
* `pub type Key = <key_at's type>`, or `()` for an ungrouped aggregate.
* `pub struct Agg` (spec-only, `int` / `Option<int>` fields): one field per suffix fold of the spec, named like the fold (`sum_x`,
  `count_x`, `avg_x_sum`, `avg_x_count`), one `Option<int>` per MIN / MAX predicate (`min_x`, `max_x`), `hits` (rows of group `k`
  that pass the WHERE) and `n_<pred>` per further existence predicate `run_query_ok` mentions (nullable aggregates: `hit_x`).
* `agg_zero()`, `agg_plus(a, b)` (+, `omin`, `omax`), `agg_plus_f()`, `agg_row(t, i0, k, p: &Params)`, `agg_rng(t, lo, hi, k, p)`
  (the spec's suffix folds as differences; MIN/MAX and the counts as host range / suffix folds `stream_<field>`), `lemma_agg_empty`,
  `lemma_agg_step(t, lo, hi, k, p)` (`0 <= lo < hi`: `rng(lo, hi) == plus(rng(lo, hi - 1), row(hi - 1))`), `lemma_agg_laws()`
  (stream_lib's `monoid_laws` and `comm_laws`), `lemma_agg_total(t, k, p)` (the range `[0, t.n)` against the spec's folds;
  `hits > 0 <==> exists a row`; MIN/MAX `None <==> no row` and `Some(b) ==> min_x(.., b)`).
* The `research_loop/verus_lib/stream_lib.rs` slice: `fold_by`, `monoid_laws`, `comm_laws`, `lemma_fold_push/concat/one/remove/perm/bij`,
  `sum_by` + `lemma_sum_by_*`, `omin`/`omax` + `lemma_omin_at`/`lemma_omax_at`, `rng_step_ok`, `lemma_rng_split`, `Seg { j, off, len }`,
  `seg_end`, `tiles_ok`, `lemma_tiles`.

Stream and chunk view (the ABI the extension fills):
```rust
pub uninterp spec fn stream_table_<t>(id: u64) -> Cols_<t>;
pub struct Stream_<t> { pub id: u64, pub raw: usize }           // raw = address of the glue's StreamEnd_<t>
#[repr(C)] pub struct StreamEnd_<t> { pub m: u64, pub n: u64 }   // chunks handed out, rows scanned (final once all workers returned)
#[repr(C)] pub struct StrRaw { pub w0: u64, pub w1: u64 }        // DuckDB string_t, 16 bytes (len u32, 12 inline or prefix + ptr)
pub struct StrCol<'a> { pub sel: &'a [u32], pub raw: &'a [StrRaw], pub ents: Ghost<Seq<Seq<char>>>, pub dict_id: u64 }
pub struct Chunk_<t><'a> { pub sid: u64, pub off: usize, pub len: usize, pub <col>: &'a [i64|i32|..|bool] | StrCol<'a>, .. }
#[repr(C)] pub struct RawChunk_<t> {                             // filled by the glue per chunk, columns in Cols_<t> order
    pub j: u64, pub off: u64, pub len: u64,                      // (j, off) from one fetch_add
    pub <col>: usize,                                            // address of len cells (column-file encoding: DATE i32 days,
                                                                 // DECIMAL scaled i64, bool 1 byte 0/1, <col>__valid as bool cells)
    pub <col>_sel: usize, pub <col>_ents: usize, pub <col>_nents: u64, pub <col>_dict: u64,   // per VARCHAR column
}
pub open spec fn chunk_ok_<t>(c: &Chunk_<t>) -> bool;           // off + len <= T.n; fixed column: len cells, == T's at off + r
                                                                 // (nullable: the value only where valid, the validity always);
                                                                 // VARCHAR: sel in range, ents@[sel@[r]] == T.<col>@[off + r]@
// TRUSTED S1: pub fn chunk_<t><'a>(sh: &Stream_<t>, raw: &'a RawChunk_<t>) -> (c: Option<Chunk_<t><'a>>)
//                 ensures c matches Some(c) ==> c.sid == sh.id && chunk_ok_<t>(&c)    (None: sel out of range or not UTF-8, checked)
// TRUSTED S1: pub fn str_ent<'a>(v: &StrCol<'a>, j: usize) -> (s: &'a str)  requires j < v.ents@.len()  ensures s@ == v.ents@[j]
// TRUSTED S2: pub fn stream_end_<t>(sh: &Stream_<t>) -> (r: (usize, usize))
//                 ensures r.1 == stream_table_<t>(sh.id).n, valid_cols_<t>(&stream_table_<t>(sh.id))
```
`dict_id` is DuckDB's dictionary id of a DICTIONARY vector (0 = FLAT or unknown; the spike saw 92-98 % of VARCHAR chunks reuse the
previous dictionary). It is plain data: nothing is claimed about it, so an entry -> slot memo across chunks keyed by it cannot be proved
yet. That needs one more S1 clause (equal non-zero ids within one stream => equal `ents`), which is NOT authorized and NOT emitted.

Agent (regions; `admit.admit_stream`): `AGENT_STATE` (`pub struct QAcc`, no references or lifetimes), `AGENT_HELPERS`
(`spec fn qacc_inv(s: &QAcc) -> bool`, `spec fn st_val(s: &QAcc, k: Key) -> Agg`, helpers), and the bodies `AGENT_INIT` / `AGENT_STEP` /
`AGENT_MERGE` / `AGENT_FINISH` of the contracts in "Contract" above, with: `p: &Params` used as `p` (not `p@`), `final(s)` for the
post-state in `q_step`, `q_merge` also `requires qacc_inv(&a), qacc_inv(&b)`. No region may name `Exec`, `exec_*`, `StreamOut`, `StrRaw`,
`RawChunk_*`, `StreamEnd_*`, `Stream_*`, `stream_end_*`, `seg_fold`, `seg_agg`, call `chunk_<t>(..)`, read `.raw`, use the S1 helpers or
build a `Chunk_*` / `StrCol` by hand; external_body / assume / admit / unsafe are rejected as for `run_query` bodies.

Runtime (fixed, verified with the program):
```rust
pub enum StreamOut { Rows(Vec<OutRow>), Declined, Error }
pub struct Exec { /* private: sh, p, acc: Option<QAcc> (None = poisoned), err: bool, segs: Vec<Seg> */ }
//   #[verifier::type_invariant]: acc == Some(a) ==> qacc_inv(&a) && forall k: st_val(&a, k) == seg_fold(sh.id, segs@, k, p)
pub fn exec_new(sh: Stream_<t>, p: Params) -> Exec
pub fn exec_ok(e: &Exec) -> bool                                 // not poisoned
pub fn exec_step(e: Exec, raw: &RawChunk_<t>) -> Exec            // S1, q_step, records Seg { j, off, len }; poisons on failure
pub fn exec_merge(a: Exec, b: Exec) -> Exec                      // same stream id and params (checked), q_merge, segs concatenated
pub fn exec_finish(e: Exec) -> StreamOut                         // S2; segs.len() == m, every j < m once, offsets contiguous 0..n
//   ensures r matches StreamOut::Rows(res) ==> run_query_ok(&stream_table_<t>(e.sid()), e.params().<param>.., res)
```
By value (Verus does not let a field of a type-invariant struct be borrowed mutably); the extension keeps one `Exec` per worker and
replaces it with each call's result. `Error` = the glue or the scheduling failed (S1 refused a chunk; a chunk lost, doubled or out of
place; two streams merged); `Declined` = the agent declined (q_step false, q_merge / q_finish None).

Binary mode (`assemble.assemble_stream_program`, for the MCP iterate path and the differential tests without DuckDB): the `main` reads
the column file and checks `valid_cols` on it (what S2 claims), cuts the rows into chunks of random sizes in `[1, chunk_max]` (VARCHAR
alternately FLAT and dictionary-style), runs `threads` workers on one atomic chunk counter through `exec_new` / `exec_step`, merges and
finishes; argv: the template parameters, then optionally `<chunk_max> <threads> <seed>` (default 2048 4 1). It prints `STREAM_CHUNKS`,
`STREAM_THREADS`, the timed-run lines and the rows as the `run_query` main does; a decline prints `LEMMA_DECLINED` and exits 3; `Error`
panics.

Speed note for the prompt (later; from the spike): the fast exact path was 32x32->64-bit products guarded by a per-chunk range check with
an exact i128 fallback (no catalog assumptions) and branch-free masks; the proof covers both paths (the runtime check gives the bounds).

Deviations from the sketch above: `p` instead of `p@`; no separate `gsegs` (the ghost segments are `segs@`); `exec_*` by value;
`exec_finish` returns `StreamOut` (not `Option`); `q_finish`'s requires is stated over `t@`; m (chunks handed out) is untrusted, only
n and `valid_cols` are S2's claim; the gate also refuses DISTINCT, a nullable GROUP BY key, floats, VARCHAR template parameters, map
results, `stateful`, `in_duckdb` and `assumptions = true`.
