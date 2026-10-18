// The C ABI of a Lemma executor library (ABI version 2: version 1 plus query-template parameters). Emitted by declarative_spec/assemble_library.py, the same template
// for every query; the proved run_query sits behind lemma_run. Little-endian cells throughout.
#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// One input buffer. A table's "rows" entry has data = NULL, len = 0, n = row count. A field entry holds the field's cells in
// the column-file encoding (fixed-width cells; a string is a u32 byte length then its UTF-8 bytes); n = number of cells
// (the dictionary size for a __dict field). The library reads but never writes or keeps it.
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

// Bytes owned by the library; give them back with lemma_free_out. On return 0 they are the result
// ("LMR1", u64 load_us, u64 run_us, u64 rows, u32 columns, one kind byte per column (1 int as i128, 2 f64, 3 bool,
// 4 string), then per column: one validity byte per row, then the cells). On a nonzero return they are a UTF-8 message.
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

#ifdef __cplusplus
}
#endif
