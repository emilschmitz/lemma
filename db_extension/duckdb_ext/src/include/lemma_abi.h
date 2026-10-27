// The C ABI of a Lemma executor library. ABI version 6 (below, "ABI 6") is the streaming executor: no lemma_run, chunks handed in
// place. ABI version 5: version 4 plus lemma_run_borrowed, which reads the owned-type input
// columns in place without taking them; version 4 added owned input columns, version 3 the DECLINED status of lemma_run,
// version 2 query-template parameters). Emitted by declarative_spec/assemble_library.py, the same
// template for every query; the proved run_query sits behind lemma_run. Little-endian cells throughout.
#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// One input buffer. A table's "rows" entry has data = NULL, len = 0, n = row count. A field entry holds the field's cells in
// the column-file encoding (fixed-width cells; a string is a u32 byte length then its UTF-8 bytes); n = number of cells
// (the dictionary size for a __dict field).
// OWNED fields (ABI 3): a field whose layout type is a fixed-width integer or f64 (not bool, not String) is passed in a
// buffer the library allocated with lemma_alloc_input(index, cap): data = that buffer, len = its allocated bytes
// (cap * cell width), n <= cap cells written by the caller. lemma_run (called with the layout's ncols) takes every owned
// buffer as the memory of its Vec, whatever it returns; a buffer never passed to lemma_run goes back with lemma_free_input.
// Every other field is BORROWED: the library reads but never writes or keeps it.
// LENT owned buffers (ABI 5, lemma_run_borrowed): the same buffers of lemma_alloc_input, but the library only reads them during
// the call and never frees, writes or keeps them; the caller keeps them (unwritten) at least until the call returns and returns
// them with lemma_free_input afterwards. One buffer may be lent to several calls, also at the same time.
typedef struct {
	const uint8_t *data;
	uint64_t len;
	uint64_t n;
} LemmaCol;

// One query-template parameter value (ABI version 2), in run_query's order (lemma_param_layout: "<name> <rust type> <lo> <hi>").
// kind 1: an integer, data = 8 bytes little-endian i64 (BIGINT as is, DATE the day number since 1970-01-01, DECIMAL(p,s) the
// value * 10^s); kind 4: a VARCHAR, data = its UTF-8 bytes. The library checks count, kinds, lengths and the range run_query
// requires before it decodes a column. A query without parameters takes nparams = 0.
typedef struct {
	uint32_t kind;
	const uint8_t *data;
	uint64_t len;
} LemmaParam;

// lemma_run's status (declarative_spec/decline.py ABI_STATUS_*). DECLINED: the proved run_query returned None (lemma.toml
// assumptions = false: the spec states no data assumptions and the body may decline, e.g. on a checked overflow); no row was
// computed, and the caller must not present any other engine's answer as Lemma's. ERROR: a contract or data check failed.
#define LEMMA_STATUS_OK 0
#define LEMMA_STATUS_DECLINED 1
#define LEMMA_STATUS_ERROR 2

// Bytes owned by the library; give them back with lemma_free_out. On LEMMA_STATUS_OK they are the result
// ("LMR1", u64 load_us, u64 run_us, u64 rows, u32 columns, one kind byte per column (1 int as i128, 2 f64, 3 bool,
// 4 string), then per column: one validity byte per row, then the cells). On DECLINED they are the UTF-8 reason, on ERROR
// the UTF-8 message.
typedef struct {
	uint8_t *ptr;
	uint64_t len;
	uint64_t cap;
} LemmaOut;

typedef uint32_t (*lemma_abi_version_fn)(void);
typedef const char *(*lemma_text_fn)(void); // lemma_query_sql, lemma_input_layout, lemma_output_layout, lemma_param_layout
typedef int32_t (*lemma_run_fn)(const LemmaCol *cols, uint64_t ncols, const LemmaParam *params, uint64_t nparams,
                                LemmaOut *out);
typedef void (*lemma_free_out_fn)(LemmaOut *out);
// ABI 5: lemma_run_borrowed has lemma_run's signature and statuses; its owned-type columns are LENT, not taken (see LemmaCol).
// An owned buffer of `cap` zeroed cells for input `index` (NULL when that input is not owned).
typedef uint8_t *(*lemma_alloc_input_fn)(uint64_t index, uint64_t cap);
// Return an owned buffer of input `index` (len = its allocated bytes) that was never passed to lemma_run (a buffer only ever
// LENT to lemma_run_borrowed, ABI 5, goes back here after its last call returned).
typedef void (*lemma_free_input_fn)(uint64_t index, uint8_t *data, uint64_t len);

// ---- ABI 6: streaming executors (lemma.toml [run] stream, docs/STREAM.md; declarative_spec/assemble_library.py "ABI 6") ----------
// A stream executor has no lemma_run: the extension's scan hands it DuckDB's chunks in place. Per query: lemma_stream_open (the
// parameters), one lemma_stream_worker per scan thread, lemma_stream_step per chunk, pairwise lemma_stream_merge, one
// lemma_stream_finish (LMR1 as lemma_run), lemma_stream_close. lemma_input_layout / lemma_output_layout / lemma_param_layout as above;
// lemma_stream_layout: one line per LemmaVec of a chunk, "<field> <rust type> <bytes per cell>" or "<field> String str".
//
// What the extension promises (the trusted items S1 / S2 of the proof rely on it): each chunk is rows of DuckDB's parallel scan of the
// table in the caller's transaction (MVCC applied, the transaction's own uncommitted rows included, no pushed predicate), every row
// exactly once; (j, off) of a chunk come from ONE fetch_add of the stream's counter (j += 1, off += len), each chunk is stepped once on
// one worker; finish gets m = chunks handed out and n = rows (the counter's final values) after every worker returned and was merged.
// Fixed-width cells are in the column-file encoding (DATE days i32, DECIMAL scaled to the spec's scale, bool one byte 0/1, a nullable
// column's NULL cells any value with its __valid column 0 there); VARCHAR: `sel` len u32 indices into `nents` DuckDB string_t
// entries (16 bytes), every entry a valid string_t (NULL rows point at an empty entry). The library checks the column count, null and
// misaligned buffers, bool cells, selection ranges and UTF-8; its proved runtime checks that the chunks tile [0, n) (ERROR otherwise).

// One column of a chunk.
typedef struct {
	const uint8_t *data;  // fixed width: len cells; VARCHAR: nents string_t entries
	const uint32_t *sel;  // VARCHAR: len indices into the entries; NULL for a fixed-width column
	uint64_t nents;       // VARCHAR: entries at data
	uint64_t dict;        // VARCHAR: DuckDB's dictionary id (hashed; 0 = FLAT or unknown). Plain data: nothing is claimed about it
} LemmaVec;

typedef struct {
	uint64_t j, off, len; // chunk index and first row (one fetch_add), rows
	uint64_t ncols;
	const LemmaVec *cols; // ncols columns in lemma_stream_layout order
} LemmaChunk;

typedef struct LemmaStream LemmaStream;
typedef struct LemmaWorker LemmaWorker;

// lemma_stream_step / lemma_stream_merge: go on; poisoned (the answer will be a decline or an error: hand no more chunks); the glue
// refused the chunk or a call panicked (finishing anything merged with this worker is an ERROR).
#define LEMMA_STEP_OK 0
#define LEMMA_STEP_POISONED 1
#define LEMMA_STEP_ERROR 2

// build/nbuild: phase 2 (joins); phase 1 takes nbuild = 0. NULL on a bad parameter, err = the message (free it with lemma_free_out).
typedef LemmaStream *(*lemma_stream_open_fn)(const LemmaCol *build, uint64_t nbuild, const LemmaParam *params, uint64_t nparams,
                                             LemmaOut *err);
typedef LemmaWorker *(*lemma_stream_worker_fn)(LemmaStream *s, LemmaOut *err);
typedef int32_t (*lemma_stream_step_fn)(LemmaWorker *w, const LemmaChunk *c);
typedef int32_t (*lemma_stream_merge_fn)(LemmaWorker *into, LemmaWorker *from); // `from` is consumed
// `w` is consumed; LEMMA_STATUS_* as lemma_run (OK: out = LMR1, load_us 0).
typedef int32_t (*lemma_stream_finish_fn)(LemmaWorker *w, uint64_t m, uint64_t n, LemmaOut *out);
typedef void (*lemma_stream_drop_fn)(LemmaWorker *w);
typedef void (*lemma_stream_close_fn)(LemmaStream *s); // after every worker of it is finished or dropped

// ---- ABI 6 for a join (phase 2a, docs/STREAM.md "Phase 2a, execution side"): one streamed table, materialized build tables ----------
// A join library's proved runtime is ONE Pool per stream (the build tables, the agent's QBuild, one locked slot per worker). Its
// lemma_stream_open refuses; the stream opens with lemma_stream_open_pool, which takes every build table's columns (in the order of
// lemma_stream_builds; per table the ABI 5 inputs of lemma_input_layout: its "rows" entry, then its fields in Cols order, cells in the
// column-file encoding as lemma_run takes them; nothing is taken or kept) and the slot count (one per scan thread), decodes and
// length-checks them, loads them with the verified loaders and calls pool_open. lemma_stream_ready says how pool_open ended. A worker
// is a slot (lemma_stream_worker hands out 0, 1, .. below nslots); lemma_stream_step(w, c) = pool_step on that slot; lemma_stream_merge
// only drops `from` (both of one stream; pool_finish merges the slots); lemma_stream_finish(w, m, n) = StreamEnd, then pool_finish, once
// per stream after every worker returned. A panic inside a step (it may leave the slot's lock held) makes every later step and the
// finish an ERROR (pool_finish is not called: it would wait for that lock forever). LMR1's load_us = decoding the builds + pool_open.
typedef const char *(*lemma_stream_builds_fn)(void); // the build tables' Cols suffixes, one per line, in q_build's order
// NULL on bad parameters / build columns or a panic (err = the message).
typedef LemmaStream *(*lemma_stream_open_pool_fn)(const LemmaCol *build, uint64_t nbuild, const LemmaParam *params, uint64_t nparams,
                                                  uint64_t nslots, LemmaOut *err);
// pool_open's outcome: LEMMA_STATUS_OK (workers may start), DECLINED (q_build declined; msg = the reason), ERROR (msg).
typedef int32_t (*lemma_stream_ready_fn)(const LemmaStream *s, LemmaOut *msg);

#ifdef __cplusplus
}
#endif
