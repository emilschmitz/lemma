#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

//! H1 on table storage scan (DataTable::ScanTableSegment — not analytical SQL).
//! Opens db_path internally; single-threaded.
int lemma_storage_h1_run(
    const char *db_path,
    const char *table,
    int32_t date_lo,
    int32_t date_hi,
    uint64_t *matched_out,
    uint64_t *sum_out,
    char *scan_mode_out,
    size_t scan_mode_len,
    char *error_out,
    size_t error_len);

#ifdef __cplusplus
}
#endif
