#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

//! Opaque pin handle. Valid until `lemma_unpin`.
typedef int64_t LemmaPinId;

//! Invalid pin id returned on error.
#define LEMMA_PIN_INVALID ((LemmaPinId)-1)

//! Pin a table (or subset of columns) by running `SELECT ... FROM table` and
//! retaining the `duckdb_result` plus materialized chunks so vector buffers
//! stay alive.  While pinned, callers must not mutate the underlying table.
//!
//! @param conn      DuckDB connection pointer (`duckdb_connection`).
//! @param table     Table name (unquoted).
//! @param columns   Optional column names; NULL pins all columns.
//! @param n_columns Number of entries in @p columns (0 = all columns).
//! @param error_out Optional buffer for error message (may be NULL).
//! @param error_len Size of @p error_out.
//! @return Pin id, or LEMMA_PIN_INVALID on failure.
LemmaPinId lemma_pin_table(
    void *conn,
    const char *table,
    const char *const *columns,
    size_t n_columns,
    char *error_out,
    size_t error_len);

//! Release a pin. Blocks while chunk iterators hold the pin mutex.
void lemma_unpin(LemmaPinId pin);

//! Total row count across all chunks.
uint64_t lemma_pin_row_count(LemmaPinId pin);

//! Number of pinned columns.
uint64_t lemma_pin_column_count(LemmaPinId pin);

//! Column name (as returned by DuckDB).
const char *lemma_pin_column_name(LemmaPinId pin, uint64_t col);

//! Logical type id (`duckdb_type` enum value).
uint32_t lemma_pin_column_type(LemmaPinId pin, uint64_t col);

//! Number of vector chunks.
uint64_t lemma_pin_chunk_count(LemmaPinId pin);

//! Row count in chunk @p chunk_index.
uint64_t lemma_pin_chunk_len(LemmaPinId pin, uint64_t chunk_index);

//! Raw data pointer for column @p col in chunk @p chunk_index.
void *lemma_pin_vector_data(LemmaPinId pin, uint64_t chunk_index, uint64_t col);

//! Validity bitmask (uint64_t words) or NULL if all-valid.
uint64_t *lemma_pin_vector_validity(LemmaPinId pin, uint64_t chunk_index, uint64_t col);

//! Vector logical type id (`duckdb_type`).
uint32_t lemma_pin_vector_type(LemmaPinId pin, uint64_t chunk_index, uint64_t col);

//! True while any pin is active (used to refuse unsafe unbind).
bool lemma_pin_any_active(void);

#ifdef __cplusplus
}
#endif
