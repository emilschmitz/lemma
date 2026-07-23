#pragma once

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/// Operator-shaped H1 runner: pending stream + per-batch filter+sum callbacks.
/// Returns 0 on success; writes matched/sum on success.
int lemma_ops_h1_run(
    void *conn,
    const char *table,
    int32_t lo,
    int32_t hi,
    uint64_t *matched_out,
    uint64_t *sum_out,
    char *error_out,
    size_t error_len
);

#ifdef __cplusplus
}
#endif
