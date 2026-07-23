#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

//! Opaque session: DuckDB + Connection (storage scan path — not analytical SQL).
typedef struct LemmaStorageSession LemmaStorageSession;

//! Open db_path; timed separately from query. Single-threaded.
int lemma_storage_h1_open(
    const char *db_path,
    LemmaStorageSession **session_out,
    char *error_out,
    size_t error_len);

//! H1 filter+sum on table storage via DataTable::ScanTableSegment.
int lemma_storage_h1_query(
    LemmaStorageSession *session,
    const char *table,
    int32_t date_lo,
    int32_t date_hi,
    uint64_t *matched_out,
    uint64_t *sum_out,
    char *scan_mode_out,
    size_t scan_mode_len,
    char *error_out,
    size_t error_len);

void lemma_storage_h1_close(LemmaStorageSession *session);

#ifdef __cplusplus
}
#endif
