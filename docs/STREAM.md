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
the ABI 5 inputs (`q_build -> QBuild`, read-only in the `Pool`; built 2026-10-26, see "Phase 2a" below). Phase 2b: streamed build
stages (`lemma_stream_seal`). The generator streams the table that is largest after filters.

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
n and `valid_cols` are S2's claim; the gate also refuses DISTINCT other than COUNT(DISTINCT x) and a nullable GROUP BY key (both stated since 2026-10-27, see "NULL group keys and COUNT DISTINCT"), floats, VARCHAR template parameters, map
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

Product (`lemma optimize`, `lemma generate`; lemma.toml `[product] executor`, default `auto`, docs/FLAGS.md "Product executor kind"):
the CLI emits the query's stream spec before generation and proves a streaming executor when this gate accepts it, else a batch
(ABI 5) executor; a stream proof failure is a failed run, never retried as batch. Research runs keep `[run] stream` as written.

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
place the check covers ~4 entries per chunk, within run-to-run noise (builds with and without it: 113 vs 112 ms); (b) a dictionary-id
clause (equal ids within a stream => equal `ents`, so a memo across chunks): it would save the agent's `build_codes`, ~6 % of
`q_step` (~3 ms wall). Both may matter for FLAT high-cardinality strings or large SEC dictionaries; measure there first.

## Phase 2a, spec and binary side: inner equi-joins (`declarative_spec/stream_join.py`, 2026-10-26)

One STREAMED table and one or more MATERIALIZED build tables, under the same flag (`[run] stream`). No trusted item was added: the
chunk view, S1 and S2 are phase 1's, for the stream table only. Phase 1 specs and prompts are byte-identical
(`tests/fixtures/stream_phase1_flag_on_golden.json`, besides the flag-off goldens).

**The stream table** is named by a `-- stream: <table>` line of the SQL text. Rule (`stream_join.choose_stream_table`, deterministic):
the table with the most rows after its own single-table filter conjuncts (WHERE and every ON; found as the data profile finds them) on
the run's database; a tie goes to the table first in FROM. `drive.run_declarative_optimization_loop` writes the line once from
`LEMMA_MEASURE_DB` (a template: its first binding's literals) and records `<run dir>/stream_choice.json` (table, counts, rule, db); the
line is part of the query text from then on, so prepare, every session, the official measure and an install emit the same spec (the
spec's SQL comment shows it). A join without the line is refused (no default). TPC-H Q12 on SF10: orders 15,000,000 rows, lineitem
310,803 after its filters: stream orders, build the filtered lineitem (the spike's direction A). SEC q3 on `sec_edgar_dec`: num
33,234,006, sub 27,333 (fy = 2022): stream num, build sub. `stream_join.outermost` puts the stream table first in FROM (inner joins
commute) and `rewrite_comma_joins` connects the builds through their equalities, so the emitter states the join with the stream table as
the OUTER fold: `X(t, b, i0, k) = X_d1(t, b, i0, 0, k) + X(t, b, i0 + 1, k)`.

Gate (`stream_join.check_sql`, then the spec reader): refused loudly are outer / semi / anti / cross / natural / asof / positional joins,
USING, subqueries (IN / EXISTS / scalar / derived tables), CTEs, set operations, self joins, a join without an ON equality, MIN / MAX
over a join, and (as in phase 1) DISTINCT other than COUNT(DISTINCT x), rowid, order-dependent aggregates, floats, VARCHAR template
parameters, map results. NULL join keys follow the emitter's rule (`<col> IS NOT NULL` in the WHERE). Cells: phase 1's types plus
`i128` (DECIMAL(38, s), DuckDB HUGEINT; binary mode only, the ABI 6 glue does not hand 16-byte cells yet).

What is emitted (`to_stream_join`, replacing `run_query` after the decline wrap; everything else in the spec unchanged). Variable names:
the stream table is `t`, a build table `<b>` is `b_<b>` (a bare table name such as `sub` can clash with a glob-imported vstd function):
* host, proved: `Params`, `Key`, `Agg` (SUM / COUNT / AVG folds, `hits` = PAIRS of rows in group `k` passing the WHERE and the ON,
  `n_hit_*`), `agg_zero`, `agg_plus`, `agg_plus_f`, `agg_row(t, b_.., i0, k, p)` (zero outside the table; inside, the spec's own inner
  folds at the row: `sum_x: sum_x_d1(t, b_u, i0, 0, k)`, `hits: stream_hits_d1(t, b_u, i0, 0, k, p)`), the count folds
  `stream_<c>_d<j>` (nested over build j) and `stream_<c>` (over the stream rows) with their positivity lemmas, `agg_rng` (differences
  of suffix folds), `lemma_agg_empty`, `lemma_agg_step`, `lemma_agg_laws`, `lemma_agg_total(t, b_.., k, p)` (folds field by field;
  `hits > 0 <==> exists|i0, i1, ..| row_hit(..) && key_at(..) == k`);
* the chunk view of the stream table, S1, S2 (phase 1, unchanged);
* the agent: AGENT_STATE (`QAcc` and `QBuild`), AGENT_HELPERS (`qbuild_inv(bld, b_.., p)`, `qacc_inv(s, bld)`, `st_val(s, bld, k)`),
  and the bodies AGENT_BUILD / INIT / STEP / MERGE / FINISH of
```rust
pub fn q_build(b_u: &Cols_u, p: &Params) -> (r: Option<QBuild>)
    requires valid_cols_u(b_u), ensures r matches Some(bld) ==> qbuild_inv(&bld, b_u, p);
pub fn q_init(bld: &QBuild, b_u: &Cols_u, p: &Params) -> (s: QAcc)
    requires valid_cols_u(b_u), qbuild_inv(bld, b_u, p), ensures qacc_inv(&s, bld), forall|k| st_val(&s, bld, k) == agg_zero();
pub fn q_step(s: &mut QAcc, c: &Chunk_t, bld: &QBuild, b_u: &Cols_u, p: &Params) -> (ok: bool)
    requires qacc_inv(old(s), bld), chunk_ok_t(c), valid_cols_u(b_u), qbuild_inv(bld, b_u, p),
    ensures ok ==> qacc_inv(final(s), bld) && forall|k| st_val(final(s), bld, k)
        == agg_plus(st_val(old(s), bld, k), agg_rng(&stream_table_t(c.sid), b_u, c.off as int, c.off + c.len, k, p));
pub fn q_merge(a: QAcc, b: QAcc, bld: &QBuild, b_u: &Cols_u, p: &Params) -> (r: Option<QAcc>)   // both qacc_inv(_, bld)
pub fn q_finish(s: QAcc, t: Ghost<Cols_t>, bld: &QBuild, b_u: &Cols_u, p: &Params) -> (res: Option<Vec<OutRow>>)
    requires .., forall|k| st_val(&s, bld, k) == agg_rng(&t@, b_u, 0, t@.n as int, k, p), ensures res matches Some(r) ==> run_query_ok(&t@, b_u, r);
```
  No uniqueness assumption: the agent proves its build structure from the build table's cells (duplicates handled, or a decline).
  Admission (`admit_stream(.., build=..)`): QBuild and qbuild_inv required; no region may name `Pool`, `PoolOpen`, `Slot`, `SlotPred`,
  `pool_*`, `cols_ok_*`, `load_cols_*` (besides phase 1's internals).
* the host runtime of a join, `Pool` (replaces phase 1's per-worker `Exec`). Why: merging two workers' states is sound only if both
  were folded against the same build, and no run-time check short of comparing the build tables proves that (vstd has no spec for an
  `Arc` pointer comparison; one would be a new trusted item). So ONE `Pool` per stream holds the build tables, the `QBuild` and one
  `vstd::rwlock::RwLock<Slot, SlotPred>` per worker (`Slot { acc: Option<QAcc>, err, segs }`; the lock's predicate: the state is the
  fold of its segments against this pool's build); the type invariant says every slot's predicate names the pool's build.
```rust
pub enum PoolOpen { Ready(Pool), Declined, Error }
pub fn cols_ok_u(x: &Cols_u) -> (r: bool) ensures r ==> valid_cols_u(x)     // lengths and the row bound, checked at run time
pub fn pool_open(sh: Stream_t, b_u: Cols_u, p: Params, nslots: usize) -> (r: PoolOpen)  // cols_ok_*, q_build once, q_init per slot
    ensures r matches PoolOpen::Ready(pl) ==> pl.sid() == sh.id && pl.params() == p && pl.build_u() == b_u && pl.nslots() == nslots
pub fn pool_step(pl: &Pool, w: usize, raw: &RawChunk_t) -> (r: u8)        // worker w's slot: 0 go on, 1 poisoned, 2 no slot w
pub fn pool_finish(pl: Pool) -> (r: StreamOut)                             // S2, merge all slots (q_merge), tiling check, q_finish
    ensures r matches StreamOut::Rows(res) ==> run_query_ok(&stream_table_t(pl.sid()), &pl.build_u(), res)
```

Binary mode (`assemble._assemble_stream_join_program`): the stream table is read as in phase 1; each build table is read from its
column file as `run_query`'s main reads it (the `valid_cols` checks) and loaded by its verified loader `load_cols_<b>` (in `verus!`)
before each timed run (not timed: a copy of the columns); the timed run is `pool_open` (q_build), `threads` workers stepping their own
slot from one atomic chunk counter, `pool_finish`. Prints `STREAM_BUILD_US` (median of `pool_open`) besides phase 1's lines.

For the extension agent (ABI 6 with builds; not wired yet, `assemble_stream_library_program` still refuses a join spec):
`lemma_stream_open(build, nbuild, params, ..)` must hand every build table's columns in `Cols_<b>` order of the spec (the ABI 5 input
layout of `lemma_input_layout`, one `LemmaCol` per field), build tables in `q_build`'s parameter order; the template loads each with `load_cols_<b>` (its `requires` checked by asserts as in ABI 5; `pool_open` re-checks lengths) and
calls `pool_open(Stream_t { id, raw: end }, b_.., p, nslots)` with `nslots` = the number of scan workers it will start (a worker is a
slot index `w < nslots`, one per scan thread; two threads on one slot are serialized by the lock, not wrong). `Declined` / `Error` at
open answer DECLINED / ERROR before any scan. Per chunk `pool_step(&pool, w, &raw)`; there is no `exec_merge`: `lemma_stream_merge`
has nothing to do for a join (the merge is inside `pool_finish`). After every worker has returned: set `StreamEnd (m, n)`, then
`pool_finish(pool)` by value. A panic inside `pool_step` leaves that slot's lock held: `pool_finish` would then wait forever, so after a
panicked step the template must answer ERROR without calling `pool_finish`. The build rows may be the build table's rows that pass its
own single-table conjuncts (pushdown): the spec re-applies the WHERE, and Q12's build is then 310,803 rows instead of 59,986,052.
The manifest should record the stream table and the builds (the spec's `// LEMMA_STREAM_JOIN:` line, `stream_choice.json`).

Prompt (`stream_prompt.py`, join specs only): seven regions, the five contracts verbatim, the join's `agg_row` as the inner fold, the
build-side facts (keys repeat, may be NULL, may match nothing; no uniqueness assumption) and the proof shape (a skip lemma by induction
over the inner fold); RECIPE (left out with `examples = none`): probe structures (a key -> first-row map with a `next` chain built from
the last row, or a dense table over an integer key's run-time range, declining when too wide; group slots per build row; a per-chunk
entry memo for a streamed string key). Example `stream/join_group_build_key.rs` (mounted with the stream examples).

Gate checks (Verus, a stub agent, `tests/test_stream_join.py`): the invented join, TPC-H Q12 streaming orders and streaming lineitem,
SEC q3 without its HAVING subquery (subqueries are refused) all `N verified, 0 errors`.

## NULL group keys and COUNT DISTINCT (`declarative_spec/stream_distinct.py`, 2026-10-27)

Both were refused before; they blocked every GenDB SEC join query (a GROUP BY over `pre.stmt`, `pre.plabel`, `sub.sic` or `tag.tlabel`,
all nullable in `sec_edgar_dec.duckdb`; SEC q4 and q1 have COUNT DISTINCT). No trusted item was added; phase 1 and phase 2a specs and
prompts without them are byte-identical (`stream_phase1_flag_on_golden.json`, the flag-off goldens).

**A nullable GROUP BY key** is the batch spec's pair: `key_at` gives `(true, v)` for a value and `(false, <the type's empty value>)` for
NULL, so `Key` is e.g. `(bool, Seq<char>)` (a tuple component per nullable column) and all NULL rows are one group of their own, apart
from every value group. Nothing else changes: S1 already gives each nullable column's `__valid` cells and promises the value only
where the cell is valid, and `key_at` reads a value only under its own validity bit. The gate (`stream.check_key_guards`, one table and
joins) checks exactly that: every nullable column `key_at` reads is inside `(if t.c__valid@[i] { (true, ..) } else { (false, <no cell>) })`,
or `row_hit` tests its bit (the emitter's form for `WHERE c IS NOT NULL`); anything else is refused. The ABI 6 glue needed no change:
a nullable VARCHAR's `__valid` comes from the validity at the physical index, a NULL row's entry is the empty string (FLAT with NULLs:
gathered; a storage dictionary's NULL entry: its copy), and the proved code keeps the NULL group apart from the empty string's
(`tests/test_in_duckdb_stream_null_distinct.py`, every vector form).

**COUNT(DISTINCT x)** is stated by the batch spec as a last-occurrence fold (a row, or a tuple of rows over a join, counts when no
lexicographically later one of its group has the same value); that is not a difference of suffix folds, so the stream `Agg` gets a SET
field `set_<fold>: Set<V>` instead of an int: `agg_zero` the empty set, `agg_plus` the union, `agg_row` the row's values (one table: a
singleton when the row passes the fold's predicate, `hit_x` for a nullable x, and has key k, else empty; a join: the values of the
row's matching build tuples), `agg_rng` the range fold `stream_set_<fold>`. Host, proved, per COUNT DISTINCT fold over m build tables:
`set_<fold>_d<e>` (the values of the hit tuples whose first e indices are fixed and whose index e is at least i_e; level 0 is the
stream table), `lemma_set_<fold>_d<e>_mem` (membership = some such tuple has the value), `lemma_set_<fold>_d<e>_count` (the spec's
count fold at level e = the size of that set minus the values of the tuples after the block, by induction over the nesting: the
last-occurrence count is the number of distinct values), `lemma_stream_set_<fold>`; `lemma_agg_laws` gains the sets' extensional
equalities and `lemma_agg_total` states `agg_rng(.., 0, n, k, p).set_<fold>.len() == <fold>(.., 0, k)`. `q_finish` takes the size. The
gate accepts the fold only in the emitter's exact text (`stream_distinct.parse_term`; the join's middle levels plain nested sums) and
still refuses SELECT DISTINCT, SUM / AVG(DISTINCT ..) and a DISTINCT over several expressions.

Prompt (`stream_prompt.py`, only when the spec has a nullable key or a set field): the NULL key is its own group (pair, test the bit
first, a slot of its own, `None` in the output row); a distinct field is a set merged by union, the size taken in `q_finish`, an exec set
whose view is it (`HashSetWithView` / `StringHashSet`); RECIPE (left out with `examples = none`): insert a value into a group's set once
per chunk (a per-chunk memo per dictionary entry for a string value), merge the smaller set into the larger. Examples (mounted with the
stream examples): `stream/group_nullable_key_count_sum.rs`, `stream/group_count_distinct.rs`.

Gate check (Verus, stub agent, `tests/test_stream_null_distinct.py`): SEC q6 and q4 streaming `num` (the stream_join rule on
`sec_edgar_dec.duckdb`: q6 num 33,234,006 rows after its filters, pre 1,767,049, sub 26,612; q4 num 33,234,006, tag 1,070,662, pre
1,242,132, sub 5,242) `N verified, 0 errors`. Survey of every GenDB SEC query (configs/queries/sec_edgar, holdout queries_all.sql) with
the rule's stream table: accepted and `N verified, 0 errors` with a stub: Q1 (one table, COUNT DISTINCT), Q4, Q6, Q7, Q8, Q9 and Q11
(stream pre: 3,143,073 rows after its filters vs num 3,091,826), Q12, Q13, Q15, Q18, Q25. Still refused: Q2, Q3, Q24 (subqueries),
Q5, Q10, Q14, Q16, Q17, Q19-Q23 (SELECT DISTINCT and subqueries), configs q24 (LEFT JOIN).
