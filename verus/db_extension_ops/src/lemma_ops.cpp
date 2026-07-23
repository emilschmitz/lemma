#include "lemma_ops.h"
#ifndef LEMMA_OPS_FFI_BUILD
#include "duckdb_extension.h"
#endif
#include <algorithm>
#include <cstring>
#include <duckdb.h>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

struct OpsBatchState {
    duckdb_prepared_statement prepared = nullptr;
    duckdb_pending_result pending = nullptr;
    duckdb_result result{};
    bool has_result = false;
    bool has_pending = false;
    bool has_prepared = false;
    bool exhausted = false;
    duckdb_data_chunk current_chunk = nullptr;
    bool has_current_chunk = false;
};

void set_error(char *error_out, size_t error_len, const std::string &msg) {
    if (error_out == nullptr || error_len == 0) {
        return;
    }
    std::strncpy(error_out, msg.c_str(), error_len - 1);
    error_out[error_len - 1] = '\0';
}

std::string quote_ident(const std::string &name) {
    std::string out = "\"";
    for (char c : name) {
        if (c == '"') {
            out += "\"\"";
        } else {
            out += c;
        }
    }
    out += "\"";
    return out;
}

void release_chunk(OpsBatchState &state) {
    if (state.has_current_chunk && state.current_chunk != nullptr) {
        duckdb_destroy_data_chunk(&state.current_chunk);
        state.current_chunk = nullptr;
        state.has_current_chunk = false;
    }
}

void destroy_ops_state(OpsBatchState &state) {
    release_chunk(state);
    if (state.has_result) {
        duckdb_destroy_result(&state.result);
        state.has_result = false;
    }
    if (state.has_pending && state.pending != nullptr) {
        duckdb_destroy_pending(&state.pending);
        state.pending = nullptr;
        state.has_pending = false;
    }
    if (state.has_prepared && state.prepared != nullptr) {
        duckdb_destroy_prepare(&state.prepared);
        state.prepared = nullptr;
        state.has_prepared = false;
    }
}

bool start_pending_stream(OpsBatchState &state, duckdb_connection conn, const std::string &sql, char *error_out, size_t error_len) {
    duckdb_state status = duckdb_prepare(conn, sql.c_str(), &state.prepared);
    state.has_prepared = true;
    if (status != DuckDBSuccess) {
        const char *err = duckdb_prepare_error(state.prepared);
        set_error(error_out, error_len, err != nullptr ? err : "duckdb_prepare failed");
        return false;
    }

    status = duckdb_pending_prepared_streaming(state.prepared, &state.pending);
    state.has_pending = true;
    if (status != DuckDBSuccess) {
        const char *err = duckdb_prepare_error(state.prepared);
        set_error(error_out, error_len, err != nullptr ? err : "duckdb_pending_prepared_streaming failed");
        return false;
    }

    duckdb_pending_state pstate;
    do {
        pstate = duckdb_pending_execute_task(state.pending);
    } while (pstate == DUCKDB_PENDING_RESULT_NOT_READY);

    if (pstate == DUCKDB_PENDING_ERROR) {
        const char *err = duckdb_pending_error(state.pending);
        set_error(error_out, error_len, err != nullptr ? err : "duckdb_pending_execute_task failed");
        return false;
    }

    status = duckdb_execute_pending(state.pending, &state.result);
    state.has_result = true;
    if (status != DuckDBSuccess) {
        const char *err = duckdb_pending_error(state.pending);
        set_error(error_out, error_len, err != nullptr ? err : "duckdb_execute_pending failed");
        return false;
    }
    return true;
}

/// Stage kernel: sum pre-filtered amount column in one operator batch.
void ops_sum_amounts_batch(duckdb_data_chunk chunk, uint64_t &matched, uint64_t &sum) {
    if (chunk == nullptr) {
        return;
    }
    idx_t n = duckdb_data_chunk_get_size(chunk);
    if (n == 0 || duckdb_data_chunk_get_column_count(chunk) < 1) {
        return;
    }
    matched += static_cast<uint64_t>(n);

    duckdb_vector amount_vec = duckdb_data_chunk_get_vector(chunk, 0);
    void *amount_ptr = duckdb_vector_get_data(amount_vec);
    if (amount_ptr == nullptr) {
        return;
    }

    duckdb_logical_type amount_ltype = duckdb_vector_get_column_type(amount_vec);
    duckdb_type amount_ty = duckdb_get_type_id(amount_ltype);
    duckdb_destroy_logical_type(&amount_ltype);

    if (amount_ty == DUCKDB_TYPE_BIGINT || amount_ty == DUCKDB_TYPE_UBIGINT) {
        const int64_t *p = static_cast<const int64_t *>(amount_ptr);
        const int64_t *end = p + n;
        uint64_t local = 0;
        for (; p < end; ++p) {
            local += static_cast<uint64_t>(*p);
        }
        sum += local;
    } else {
        const int32_t *p = static_cast<const int32_t *>(amount_ptr);
        const int32_t *end = p + n;
        uint64_t local = 0;
        for (; p < end; ++p) {
            local += static_cast<uint64_t>(*p);
        }
        sum += local;
    }
}

bool fetch_next_batch(OpsBatchState &state) {
    if (state.exhausted) {
        return false;
    }
    release_chunk(state);
    duckdb_data_chunk chunk = duckdb_fetch_chunk(state.result);
    if (chunk == nullptr) {
        state.exhausted = true;
        return false;
    }
    state.current_chunk = chunk;
    state.has_current_chunk = true;
    return true;
}

}  // namespace

extern "C" {

int lemma_ops_h1_run(
    void *conn,
    const char *table,
    int32_t lo,
    int32_t hi,
    uint64_t *matched_out,
    uint64_t *sum_out,
    char *error_out,
    size_t error_len
) {
    auto *connection = static_cast<duckdb_connection>(conn);
    if (connection == nullptr || table == nullptr || matched_out == nullptr || sum_out == nullptr) {
        set_error(error_out, error_len, "lemma_ops_h1_run: null argument");
        return -1;
    }

    std::ostringstream sql;
    sql << "SELECT \"amount\" FROM " << quote_ident(table)
        << " WHERE \"event_date\" >= " << lo
        << " AND \"event_date\" <= " << hi;

    OpsBatchState state;
    if (!start_pending_stream(state, connection, sql.str(), error_out, error_len)) {
        destroy_ops_state(state);
        return -1;
    }

    uint64_t matched = 0;
    uint64_t sum = 0;
    while (fetch_next_batch(state)) {
        ops_sum_amounts_batch(state.current_chunk, matched, sum);
    }

    destroy_ops_state(state);
    *matched_out = matched;
    *sum_out = sum;
    return 0;
}

}  // extern "C"

#ifndef LEMMA_OPS_FFI_BUILD

static void register_varchar_scalar(
    duckdb_connection connection,
    const char *name,
    duckdb_scalar_function_t fn
) {
    duckdb_scalar_function function = duckdb_create_scalar_function();
    duckdb_scalar_function_set_name(function, name);
    duckdb_logical_type param_type = duckdb_create_logical_type(DUCKDB_TYPE_VARCHAR);
    duckdb_scalar_function_add_parameter(function, param_type);
    duckdb_logical_type ret_type = duckdb_create_logical_type(DUCKDB_TYPE_VARCHAR);
    duckdb_scalar_function_set_return_type(function, ret_type);
    duckdb_destroy_logical_type(&param_type);
    duckdb_destroy_logical_type(&ret_type);
    duckdb_scalar_function_set_extra_info(function, connection, nullptr);
    duckdb_scalar_function_set_function(function, fn);
    duckdb_register_scalar_function(connection, function);
    duckdb_destroy_scalar_function(&function);
}

static void LemmaOps(duckdb_function_info info, duckdb_data_chunk input, duckdb_vector output) {
    idx_t input_size = duckdb_data_chunk_get_size(input);
    duckdb_vector spec_vec = duckdb_data_chunk_get_vector(input, 0);
    duckdb_string_t *spec_data = (duckdb_string_t *)duckdb_vector_get_data(spec_vec);
    duckdb_connection conn = static_cast<duckdb_connection>(duckdb_scalar_function_get_extra_info(info));

    for (idx_t row = 0; row < input_size; row++) {
        uint32_t length = duckdb_string_t_length(spec_data[row]);
        const char *data_ptr = duckdb_string_t_data(&spec_data[row]);
        std::string table(data_ptr, length);

        uint64_t matched = 0;
        uint64_t sum = 0;
        char err[256] = {};
        int rc = lemma_ops_h1_run(conn, table.c_str(), 19960101, 19961231, &matched, &sum, err, sizeof(err));
        std::string out;
        if (rc != 0) {
            out = std::string("lemma_ops error: ") + err;
        } else {
            out = "lemma_ops OK table=" + table + " matched=" + std::to_string(matched) +
                  " sum=" + std::to_string(sum);
        }
        duckdb_vector_assign_string_element(output, row, out.c_str());
    }
}

DUCKDB_EXTENSION_EXTERN

DUCKDB_EXTENSION_ENTRYPOINT(
    duckdb_connection connection,
    duckdb_extension_info info,
    struct duckdb_extension_access *access
) {
    register_varchar_scalar(connection, "lemma_ops", LemmaOps);
    return true;
}

#endif  // LEMMA_OPS_FFI_BUILD
