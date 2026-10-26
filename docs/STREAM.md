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

One ghost table `T = stream_table_t(id)` per stream (the rows DuckDB's parallel scan of `t` returns in the caller's transaction,
pushed predicate applied, each row exactly once, at the offset an atomic counter assigned when the chunk was handed out).

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
