// The C ABI of a Lemma executor library (ABI version 4: version 3 plus owned input columns; version 3 added the DECLINED
// status of lemma_run, version 2 query-template parameters). Emitted by declarative_spec/assemble_library.py, the same
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
// An owned buffer of `cap` zeroed cells for input `index` (NULL when that input is not owned).
typedef uint8_t *(*lemma_alloc_input_fn)(uint64_t index, uint64_t cap);
// Return an owned buffer of input `index` (len = its allocated bytes) that was never passed to lemma_run.
typedef void (*lemma_free_input_fn)(uint64_t index, uint8_t *data, uint64_t len);

#ifdef __cplusplus
}
#endif
