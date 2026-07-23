#include "lemma_runtime.h"
#include "duckdb_extension.h"

#include <cstring>
#include <string>

extern "C" {
#include "../../db_extension/src/lemma_stream.h"
}

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

static void LemmaRuntime(duckdb_function_info info, duckdb_data_chunk input, duckdb_vector output) {
    idx_t input_size = duckdb_data_chunk_get_size(input);
    duckdb_vector spec_vec = duckdb_data_chunk_get_vector(input, 0);
    duckdb_string_t *spec_data = (duckdb_string_t *)duckdb_vector_get_data(spec_vec);
    duckdb_connection conn = static_cast<duckdb_connection>(duckdb_scalar_function_get_extra_info(info));

    for (idx_t row = 0; row < input_size; row++) {
        uint32_t length = duckdb_string_t_length(spec_data[row]);
        const char *data_ptr = duckdb_string_t_data(&spec_data[row]);
        std::string table(data_ptr, length);

        char err[256] = {};
        const char *cols[] = {"event_date", "amount"};
        LemmaStreamId stream = lemma_stream_start(conn, table.c_str(), cols, 2, err, sizeof(err));
        std::string out;
        if (stream == LEMMA_STREAM_INVALID) {
            out = std::string("lemma_runtime error: ") + err;
        } else {
            uint64_t matched = 0;
            uint64_t sum = 0;
            const int32_t lo = 19960101;
            const int32_t hi = 19961231;
            while (lemma_stream_fetch_next(stream) > 0) {
                uint64_t n = lemma_stream_chunk_len(stream);
                if (n == 0) {
                    continue;
                }
                void *date_ptr = lemma_stream_vector_data(stream, 0);
                void *amount_ptr = lemma_stream_vector_data(stream, 1);
                if (date_ptr == nullptr || amount_ptr == nullptr) {
                    continue;
                }
                auto *dates = static_cast<const int32_t *>(date_ptr);
                auto *amounts = static_cast<const int64_t *>(amount_ptr);
                for (uint64_t i = 0; i < n; i++) {
                    if (dates[i] >= lo && dates[i] <= hi) {
                        sum += static_cast<uint64_t>(amounts[i]);
                        matched++;
                    }
                }
            }
            lemma_stream_close(stream);
            out = "lemma_runtime OK table=" + table + " matched=" + std::to_string(matched) +
                  " sum=" + std::to_string(sum);
        }
        duckdb_vector_assign_string_element(output, row, out.c_str());
    }
}

extern "C" int lemma_runtime_h1_smoke(void *conn, char *error_out, size_t error_len) {
    if (conn == nullptr) {
        if (error_out != nullptr && error_len > 0) {
            std::strncpy(error_out, "null connection", error_len - 1);
            error_out[error_len - 1] = '\0';
        }
        return -1;
    }
    const char *cols[] = {"event_date", "amount"};
    LemmaStreamId stream = lemma_stream_start(conn, "scan_skew", cols, 2, error_out, error_len);
    if (stream == LEMMA_STREAM_INVALID) {
        return -1;
    }
    lemma_stream_close(stream);
    return 0;
}

DUCKDB_EXTENSION_EXTERN

DUCKDB_EXTENSION_ENTRYPOINT(
    duckdb_connection connection,
    duckdb_extension_info info,
    struct duckdb_extension_access *access
) {
    register_varchar_scalar(connection, "lemma_runtime", LemmaRuntime);
    return true;
}
