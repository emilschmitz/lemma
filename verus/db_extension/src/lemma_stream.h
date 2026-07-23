#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

//! Opaque streaming scan handle. Valid until `lemma_stream_close`.
typedef int64_t LemmaStreamId;

#define LEMMA_STREAM_INVALID ((LemmaStreamId)-1)

//! Start a streaming `SELECT ... FROM table` (no chunk retention).
//!
//! Prepares via DuckDB pending streaming API; first chunk is fetched by
//! `lemma_stream_fetch_next`.
LemmaStreamId lemma_stream_start(
    void *conn,
    const char *table,
    const char *const *columns,
    size_t n_columns,
    char *error_out,
    size_t error_len);

//! Fetch the next chunk. Destroys any prior current chunk.
//! @return 1 if a chunk is available, 0 if stream exhausted, -1 on error.
int lemma_stream_fetch_next(LemmaStreamId stream);

//! Row count in the current chunk (0 if none).
uint64_t lemma_stream_chunk_len(LemmaStreamId stream);

//! Number of projected columns.
uint64_t lemma_stream_column_count(LemmaStreamId stream);

const char *lemma_stream_column_name(LemmaStreamId stream, uint64_t col);

uint32_t lemma_stream_column_type(LemmaStreamId stream, uint64_t col);

void *lemma_stream_vector_data(LemmaStreamId stream, uint64_t col);

uint32_t lemma_stream_vector_type(LemmaStreamId stream, uint64_t col);

void lemma_stream_close(LemmaStreamId stream);

//! Pushdown scan: `SELECT amount_col FROM table WHERE date_col >= lo AND date_col <= hi`.
//! Projects one column; DuckDB applies the predicate during storage scan.
LemmaStreamId lemma_stream_start_pushdown(
    void *conn,
    const char *table,
    const char *amount_column,
    const char *date_column,
    int64_t date_lo,
    int64_t date_hi,
    char *error_out,
    size_t error_len);

//! H1 e2e default: pushdown `scan_skew` date range + fused amount sum in C++ (no per-chunk Rust FFI).
int lemma_stream_h1_sum_optimized(
    void *conn,
    uint64_t *matched_out,
    uint64_t *sum_out,
    char *error_out,
    size_t error_len);

#ifdef __cplusplus
}
#endif
