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

The main reads the column file front to back through a buffer and keeps a VARCHAR column as one `u32` code per row into its distinct
strings (each once as a `StrRaw`), not one `String` per row: SF10 lineitem has 120M string cells, which as `String`s alone exceed the
9 GB scope.

Agent and MCP (2026-10-26): `prompt.build_declarative_prompt` hands a stream spec to `declarative_spec/stream_prompt.py` (flag off:
every prompt byte-identical, `tests/fixtures/stream_prompt_flag_off_golden.json`). It states the six regions, the four contracts
verbatim from the spec, what S1 gives, the host lemmas, the proof shape and the timing; with `examples = "none"` the technique advice
(per-chunk entry memo for string keys, branch-free step, checked fast path with an exact `i128` fallback) is left out like every other
recipe. `examples = full | principles` mount the two fixtures of `tests/fixtures/declarative_proofs/stream/` (on the invented table
`t`) and nothing else. `run_runquery` / `verify_functions` / `submit_runquery` and the host's end-of-session measure admit with
`admit_stream` and build with `assemble_stream_program`; the binary gets `<params> 2048 <duck_threads> 1` (one worker per DuckDB
thread of the reference measure) in session and in every official round, and every result carries `stream_measure`: the
binary-mode main over the exported column file, NOT yet the in-DuckDB ABI 6 measure. First run: `configs/experiments/stream_q1_opus.toml`.

Speed note for the prompt (later; from the spike): the fast exact path was 32x32->64-bit products guarded by a per-chunk range check with
an exact i128 fallback (no catalog assumptions) and branch-free masks; the proof covers both paths (the runtime check gives the bounds).

Deviations from the sketch above: `p` instead of `p@`; no separate `gsegs` (the ghost segments are `segs@`); `exec_*` by value;
`exec_finish` returns `StreamOut` (not `Option`); `q_finish`'s requires is stated over `t@`; m (chunks handed out) is untrusted, only
n and `valid_cols` are S2's claim; the gate also refuses DISTINCT, a nullable GROUP BY key, floats, VARCHAR template parameters, map
results, `stateful` and `assumptions = true` (`in_duckdb` composes since the ABI 6 template below exists).

## Phase 1, execution side: ABI 6 in DuckDB (built 2026-10-26)

Library (`declarative_spec/assemble_library.py` `assemble_stream_library_program`; C side `db_extension/duckdb_ext/src/include/lemma_abi.h`
"ABI 6"): the `verus!` part of `assemble_stream_program` byte for byte, then a fixed template instead of the binary-mode `main`. Per query
only the `RawChunk_<t>` fill (one line per column), the `Params` fill (decoded and range-checked as `lemma_run` does), the layouts and the
LMR1 encoders are generated. No `impl` outside `verus!`; ten `unsafe` blocks, each `// UNSAFE n/10` with its caller's contract (C arrays,
parameter / bool bytes, `out` write / free, the stream / worker / chunk handles, the S2 `StreamEnd` write, close). Entry points:
```c
uint32_t lemma_abi_version(void);                       // 6
const char *lemma_stream_layout(void);                  // per chunk column: "<field> <rust type> <bytes per cell>" | "<field> String str"
LemmaStream *lemma_stream_open(const LemmaCol *build, uint64_t nbuild, const LemmaParam *params, uint64_t nparams, LemmaOut *err);
LemmaWorker *lemma_stream_worker(LemmaStream *s, LemmaOut *err);          // exec_new
int32_t lemma_stream_step(LemmaWorker *w, const LemmaChunk *c);          // exec_step: 0 go on, 1 poisoned, 2 glue error
int32_t lemma_stream_merge(LemmaWorker *into, LemmaWorker *from);        // exec_merge, `from` consumed
int32_t lemma_stream_finish(LemmaWorker *w, uint64_t m, uint64_t n, LemmaOut *out);  // StreamEnd = (m, n), exec_finish: LMR1 / decline / error
void lemma_stream_drop(LemmaWorker *w); void lemma_stream_close(LemmaStream *s); void lemma_free_out(LemmaOut *out);
typedef struct { const uint8_t *data; const uint32_t *sel; uint64_t nents; uint64_t dict; } LemmaVec;   // one column of a chunk
typedef struct { uint64_t j, off, len, ncols; const LemmaVec *cols; } LemmaChunk;
```
(plus `lemma_query_sql` / `lemma_input_layout` / `lemma_output_layout` / `lemma_param_layout` as ABI 5). The glue checks the column count,
null / misaligned buffers and that bool cells are 0 or 1 before building `RawChunk_<t>`; S1's body keeps its own checks (selection range,
UTF-8). `nbuild` must be 0 in phase 1. A panic never crosses the boundary; a worker whose call panicked or whose chunk the glue refused
has no `Exec` any more, and finishing anything merged with it is an ERROR.

Extension (`StreamRun` in `lemma_extension.cpp`): manifest `abi_version` 6 with `mode: "stream"` (each implies the other) and a `stream`
section (`layout`, `pushdown: false`); reached from `lemma_query`, `lemma(...)` and `lemma_mode` like ABI 4/5. The `ScanTable` sources
(committed row groups with MVCC in the caller's transaction, then its own uncommitted rows), no pushed predicate, one worker per thread
(`lemma_scan_threads`, default DuckDB's `threads`, at most the row groups + sources). Per chunk a `LemmaChunk`: fixed-width columns in
place when the vector is FLAT, of the target width and signedness and not rescaled (a nullable column even with NULLs: its NULL cells are
not promised), else decoded by the tested `DecodeIntegers` into a 2048-cell per-worker buffer; `__valid` from the validity at the physical
index; VARCHAR in place for FLAT without NULLs (identity selection) and for DICTIONARY of known size over a FLAT child without NULLs (its
selection, its entries, its id hashed to u64); DICTIONARY over a FLAT child WITH NULL entries (every storage dictionary: dictionary and
dict_fsst compression keep entry 0 as a NULL entry, whose `string_t` dictionary compression never writes) hands DuckDB's selection in
place with a per-worker copy of the entries, each NULL entry the empty string, made once per dictionary and reused while the next
chunk's dictionary is the same object (same non-empty id, a random UUID per `CreateReusableDictionary`; same entry array and size;
DuckDB writes those entries once, when a segment's scan creates the dictionary), a row selecting a NULL entry being a NULL cell; else
the rows' `string_t` gathered (a NULL row: the empty string). `(j, off)` from one
`fetch_add` of a 64-bit counter (j in the high 28 bits, off in the low 36). `context.interrupted` is checked per chunk; a poisoned step
stops the scan. Then a pairwise merge (each round on its own threads), finish with the counter's final `(m, n)`, LMR1 as today.
`lemma_last_query()` gains `mode` (`batch` / `stream`), `chunks`, `threads`; the input cache says `skip: streaming executor`;
`lemma_scan_inputs` refuses a stream executor. TEST ONLY: `SET lemma_stream_fault = 'drop' | 'duplicate' | 'shift' | 'count'` injects a
lost, doubled or misplaced chunk or a wrong row count; the proved runtime answers ERROR (tests/test_in_duckdb_stream.py).

Install (`research_loop/in_duckdb.install_executor`): a stream spec is admitted with `admit_stream`, assembled with the ABI 6 template,
verified and compiled as a cdylib; no pushdown.

## Host overhead, SF10 Q1 (profiled 2026-10-26)

The first agent-written proved Q1 executor (run `20261026T114511Z_q688622_a770af30`, 104 verified) ran in DuckDB in ~290 ms, DuckDB
~290 ms (threads 8, memory_limit 1500MB). Per-phase timers in `StreamRun` (no perf on this box; CPU summed over the 8 workers): DuckDB's
scan 330-390 ms, building the `LemmaChunk`s 260-300 ms, `lemma_stream_step` 1600-1800 ms. Cause: l_returnflag / l_linestatus come as
DICTIONARY vectors in 29290 of 29291 chunks, but a storage dictionary's entry 0 is NULL, so the in-place condition (child all valid)
never held: every chunk gathered 2048 `string_t` per column, S1 checked 2048 entries for UTF-8, and the agent's per-chunk entry memo
walked 2048 entries instead of ~4. Fixed in the glue (the entry copy above; no trusted item). Also: the panic hook is installed once,
not per call; S1's selection check is a branch-free maximum.

After (same settings, `in_duckdb_bench`, 5 interleaved rounds): cold 110 ms vs DuckDB 237 ms (2.16x), warm 124 vs 250 ms (2.02x); right
after an `INSERT` of ~100k committed, not checkpointed lineitem rows (a copy of the database, 6 rounds): 119 vs 247 ms (before the fix
283 vs 248 ms). CPU split: scan ~295 ms, chunk build ~28 ms, step ~490 ms, of which S1 and the glue ~85 ms and the agent's `q_step`
the rest (rdtsc inside a timing copy of the body: `fold_rows` 90 %, the per-chunk entry memo `build_codes` 6 %, `merge_loc` 2 %,
`max_sel` 2 %). Wall: scan alone 40-46 ms, + chunk build 50-56 ms, + S1 and glue 60-66 ms, + `q_step` 103-110 ms. 8 workers beat 6
(124 ms) and 4 (147 ms) on this 4-core / 8-thread machine.

Trust not added (it would not buy time here): (a) VARCHAR is valid UTF-8 (DuckDB validates on ingest): with dictionaries handed in
place the check covers ~4 entries per chunk, unmeasurable against noise (a build without it: 112 vs 113 ms); (b) a dictionary-id
clause (equal ids within a stream => equal `ents`, so a memo across chunks): it would save the agent's `build_codes`, ~6 % of
`q_step` (~3 ms wall). Both may matter for FLAT high-cardinality strings or large SEC dictionaries; measure there first.
