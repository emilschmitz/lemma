#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/// Smoke hook: returns 0 on success.
int lemma_runtime_h1_smoke(void *conn, char *error_out, size_t error_len);

#ifdef __cplusplus
}
#endif
