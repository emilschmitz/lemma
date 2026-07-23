#include "lemma_stream.h"
#include <duckdb.h>

#include <cstring>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

std::mutex g_registry_mutex;
std::unordered_map<LemmaStreamId, std::unique_ptr<struct StreamState>> g_streams;
LemmaStreamId g_next_stream_id = 1;

struct StreamState {
    duckdb_prepared_statement prepared = nullptr;
    duckdb_pending_result pending = nullptr;
    duckdb_result result{};
    bool has_result = false;
    bool has_pending = false;
    bool has_prepared = false;
    bool exhausted = false;
    duckdb_data_chunk current_chunk = nullptr;
    bool has_current_chunk = false;
    idx_t col_count = 0;
    std::vector<std::string> col_names;
    std::vector<duckdb_type> col_types;
    std::string table_name;
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

StreamState *lookup_stream(LemmaStreamId stream) {
    auto it = g_streams.find(stream);
    if (it == g_streams.end()) {
        return nullptr;
    }
    return it->second.get();
}

void release_current_chunk(StreamState &state) {
    if (state.has_current_chunk && state.current_chunk != nullptr) {
        duckdb_destroy_data_chunk(&state.current_chunk);
        state.current_chunk = nullptr;
        state.has_current_chunk = false;
    }
}

void load_column_metadata(StreamState &state) {
    state.col_count = duckdb_column_count(&state.result);
    state.col_names.clear();
    state.col_types.clear();
    for (idx_t c = 0; c < state.col_count; c++) {
        const char *name = duckdb_column_name(&state.result, c);
        state.col_names.emplace_back(name != nullptr ? name : "");
        state.col_types.push_back(duckdb_column_type(&state.result, c));
    }
}

bool prepare_pushdown_sql(
    StreamState &state,
    duckdb_connection connection,
    const char *table,
    const char *amount_column,
    const char *date_column,
    int64_t date_lo,
    int64_t date_hi,
    char *error_out,
    size_t error_len
) {
    std::ostringstream sql;
    sql << "SELECT " << quote_ident(amount_column != nullptr ? amount_column : "amount")
        << " FROM " << quote_ident(table)
        << " WHERE " << quote_ident(date_column != nullptr ? date_column : "event_date")
        << " >= " << date_lo
        << " AND " << quote_ident(date_column != nullptr ? date_column : "event_date")
        << " <= " << date_hi;

    duckdb_state status = duckdb_prepare(connection, sql.str().c_str(), &state.prepared);
    state.has_prepared = true;
    if (status != DuckDBSuccess) {
        const char *err = duckdb_prepare_error(state.prepared);
        set_error(error_out, error_len, err != nullptr ? err : "duckdb_prepare failed");
        return false;
    }
    return true;
}

void sum_amounts_chunk(duckdb_data_chunk chunk, uint64_t &matched, uint64_t &sum) {
    if (chunk == nullptr) {
        return;
    }
    idx_t n = duckdb_data_chunk_get_size(chunk);
    if (n == 0) {
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

bool execute_streaming_result(StreamState &state, char *error_out, size_t error_len) {
    duckdb_state status = duckdb_pending_prepared_streaming(state.prepared, &state.pending);
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

    load_column_metadata(state);
    return true;
}

void destroy_stream_state(StreamState &state) {
    release_current_chunk(state);
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

}  // namespace

extern "C" {

LemmaStreamId lemma_stream_start(
    void *conn,
    const char *table,
    const char *const *columns,
    size_t n_columns,
    char *error_out,
    size_t error_len
) {
    auto *connection = static_cast<duckdb_connection>(conn);
    if (connection == nullptr || table == nullptr) {
        set_error(error_out, error_len, "lemma_stream_start: null connection or table");
        return LEMMA_STREAM_INVALID;
    }

    std::ostringstream sql;
    sql << "SELECT ";
    if (columns != nullptr && n_columns > 0) {
        for (size_t i = 0; i < n_columns; i++) {
            if (i > 0) {
                sql << ", ";
            }
            sql << quote_ident(columns[i] != nullptr ? columns[i] : "");
        }
    } else {
        sql << "*";
    }
    sql << " FROM " << quote_ident(table);

    auto state = std::make_unique<StreamState>();
    state->table_name = table;

    duckdb_state status = duckdb_prepare(connection, sql.str().c_str(), &state->prepared);
    state->has_prepared = true;
    if (status != DuckDBSuccess) {
        const char *err = duckdb_prepare_error(state->prepared);
        set_error(error_out, error_len, err != nullptr ? err : "duckdb_prepare failed");
        destroy_stream_state(*state);
        return LEMMA_STREAM_INVALID;
    }

    if (!execute_streaming_result(*state, error_out, error_len)) {
        destroy_stream_state(*state);
        return LEMMA_STREAM_INVALID;
    }

    std::lock_guard<std::mutex> lock(g_registry_mutex);
    LemmaStreamId id = g_next_stream_id++;
    g_streams.emplace(id, std::move(state));
    return id;
}

int lemma_stream_fetch_next(LemmaStreamId stream) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    StreamState *state = lookup_stream(stream);
    if (state == nullptr) {
        return -1;
    }
    if (state->exhausted) {
        return 0;
    }

    release_current_chunk(*state);

    duckdb_data_chunk chunk = duckdb_fetch_chunk(state->result);
    if (chunk == nullptr) {
        state->exhausted = true;
        return 0;
    }

    state->current_chunk = chunk;
    state->has_current_chunk = true;
    return 1;
}

uint64_t lemma_stream_chunk_len(LemmaStreamId stream) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    StreamState *state = lookup_stream(stream);
    if (state == nullptr || !state->has_current_chunk || state->current_chunk == nullptr) {
        return 0;
    }
    return static_cast<uint64_t>(duckdb_data_chunk_get_size(state->current_chunk));
}

uint64_t lemma_stream_column_count(LemmaStreamId stream) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    StreamState *state = lookup_stream(stream);
    return state != nullptr ? static_cast<uint64_t>(state->col_count) : 0;
}

const char *lemma_stream_column_name(LemmaStreamId stream, uint64_t col) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    StreamState *state = lookup_stream(stream);
    if (state == nullptr || col >= state->col_names.size()) {
        return nullptr;
    }
    return state->col_names[col].c_str();
}

uint32_t lemma_stream_column_type(LemmaStreamId stream, uint64_t col) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    StreamState *state = lookup_stream(stream);
    if (state == nullptr || col >= state->col_types.size()) {
        return DUCKDB_TYPE_INVALID;
    }
    return static_cast<uint32_t>(state->col_types[col]);
}

void *lemma_stream_vector_data(LemmaStreamId stream, uint64_t col) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    StreamState *state = lookup_stream(stream);
    if (state == nullptr || !state->has_current_chunk || state->current_chunk == nullptr) {
        return nullptr;
    }
    if (col >= duckdb_data_chunk_get_column_count(state->current_chunk)) {
        return nullptr;
    }
    duckdb_vector vec = duckdb_data_chunk_get_vector(state->current_chunk, static_cast<idx_t>(col));
    return duckdb_vector_get_data(vec);
}

uint32_t lemma_stream_vector_type(LemmaStreamId stream, uint64_t col) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    StreamState *state = lookup_stream(stream);
    if (state == nullptr || !state->has_current_chunk || state->current_chunk == nullptr) {
        return DUCKDB_TYPE_INVALID;
    }
    if (col >= duckdb_data_chunk_get_column_count(state->current_chunk)) {
        return DUCKDB_TYPE_INVALID;
    }
    duckdb_vector vec = duckdb_data_chunk_get_vector(state->current_chunk, static_cast<idx_t>(col));
    duckdb_logical_type ltype = duckdb_vector_get_column_type(vec);
    duckdb_type ty = duckdb_get_type_id(ltype);
    duckdb_destroy_logical_type(&ltype);
    return static_cast<uint32_t>(ty);
}

void lemma_stream_close(LemmaStreamId stream) {
    std::unique_ptr<StreamState> owned;
    {
        std::lock_guard<std::mutex> lock(g_registry_mutex);
        auto it = g_streams.find(stream);
        if (it == g_streams.end()) {
            return;
        }
        owned = std::move(it->second);
        g_streams.erase(it);
    }
    if (owned != nullptr) {
        destroy_stream_state(*owned);
    }
}

LemmaStreamId lemma_stream_start_pushdown(
    void *conn,
    const char *table,
    const char *amount_column,
    const char *date_column,
    int64_t date_lo,
    int64_t date_hi,
    char *error_out,
    size_t error_len
) {
    auto *connection = static_cast<duckdb_connection>(conn);
    if (connection == nullptr || table == nullptr) {
        set_error(error_out, error_len, "lemma_stream_start_pushdown: null connection or table");
        return LEMMA_STREAM_INVALID;
    }

    auto state = std::make_unique<StreamState>();
    state->table_name = table;

    if (!prepare_pushdown_sql(
            *state, connection, table, amount_column, date_column, date_lo, date_hi, error_out, error_len)) {
        destroy_stream_state(*state);
        return LEMMA_STREAM_INVALID;
    }

    if (!execute_streaming_result(*state, error_out, error_len)) {
        destroy_stream_state(*state);
        return LEMMA_STREAM_INVALID;
    }

    std::lock_guard<std::mutex> lock(g_registry_mutex);
    LemmaStreamId id = g_next_stream_id++;
    g_streams.emplace(id, std::move(state));
    return id;
}

bool chunk_may_satisfy_range(
    duckdb_data_chunk chunk,
    idx_t date_col,
    int64_t date_lo,
    int64_t date_hi
) {
    if (chunk == nullptr) {
        return false;
    }
    idx_t n = duckdb_data_chunk_get_size(chunk);
    if (n == 0) {
        return false;
    }
    duckdb_vector date_vec = duckdb_data_chunk_get_vector(chunk, date_col);
    void *date_ptr = duckdb_vector_get_data(date_vec);
    if (date_ptr == nullptr) {
        return false;
    }
    duckdb_logical_type date_ltype = duckdb_vector_get_column_type(date_vec);
    duckdb_type date_ty = duckdb_get_type_id(date_ltype);
    duckdb_destroy_logical_type(&date_ltype);

    int64_t min_v = 0;
    int64_t max_v = 0;
    if (date_ty == DUCKDB_TYPE_BIGINT || date_ty == DUCKDB_TYPE_UBIGINT) {
        const int64_t *p = static_cast<const int64_t *>(date_ptr);
        min_v = max_v = p[0];
        for (idx_t i = 1; i < n; ++i) {
            if (p[i] < min_v) {
                min_v = p[i];
            }
            if (p[i] > max_v) {
                max_v = p[i];
            }
        }
    } else {
        const int32_t *p = static_cast<const int32_t *>(date_ptr);
        min_v = max_v = p[0];
        for (idx_t i = 1; i < n; ++i) {
            if (p[i] < min_v) {
                min_v = p[i];
            }
            if (p[i] > max_v) {
                max_v = p[i];
            }
        }
    }
    return max_v >= date_lo && min_v <= date_hi;
}

void sum_filtered_chunk(
    duckdb_data_chunk chunk,
    idx_t date_col,
    idx_t amount_col,
    int64_t date_lo,
    int64_t date_hi,
    uint64_t &matched,
    uint64_t &sum
) {
    if (chunk == nullptr) {
        return;
    }
    idx_t n = duckdb_data_chunk_get_size(chunk);
    if (n == 0) {
        return;
    }

    duckdb_vector date_vec = duckdb_data_chunk_get_vector(chunk, date_col);
    duckdb_vector amount_vec = duckdb_data_chunk_get_vector(chunk, amount_col);
    void *date_ptr = duckdb_vector_get_data(date_vec);
    void *amount_ptr = duckdb_vector_get_data(amount_vec);
    if (date_ptr == nullptr || amount_ptr == nullptr) {
        return;
    }

    duckdb_logical_type date_ltype = duckdb_vector_get_column_type(date_vec);
    duckdb_logical_type amount_ltype = duckdb_vector_get_column_type(amount_vec);
    duckdb_type date_ty = duckdb_get_type_id(date_ltype);
    duckdb_type amount_ty = duckdb_get_type_id(amount_ltype);
    duckdb_destroy_logical_type(&date_ltype);
    duckdb_destroy_logical_type(&amount_ltype);

    if ((date_ty == DUCKDB_TYPE_BIGINT || date_ty == DUCKDB_TYPE_UBIGINT) &&
        (amount_ty == DUCKDB_TYPE_BIGINT || amount_ty == DUCKDB_TYPE_UBIGINT)) {
        const int64_t *dates = static_cast<const int64_t *>(date_ptr);
        const int64_t *amounts = static_cast<const int64_t *>(amount_ptr);
        for (idx_t i = 0; i < n; ++i) {
            const int64_t d = dates[i];
            if (d >= date_lo && d <= date_hi) {
                sum += static_cast<uint64_t>(amounts[i]);
                matched += 1;
            }
        }
        return;
    }
    if ((date_ty == DUCKDB_TYPE_BIGINT || date_ty == DUCKDB_TYPE_UBIGINT) &&
        (amount_ty == DUCKDB_TYPE_INTEGER || amount_ty == DUCKDB_TYPE_UINTEGER)) {
        const int64_t *dates = static_cast<const int64_t *>(date_ptr);
        const int32_t *amounts = static_cast<const int32_t *>(amount_ptr);
        for (idx_t i = 0; i < n; ++i) {
            const int64_t d = dates[i];
            if (d >= date_lo && d <= date_hi) {
                sum += static_cast<uint64_t>(amounts[i]);
                matched += 1;
            }
        }
        return;
    }
    if ((date_ty == DUCKDB_TYPE_INTEGER || date_ty == DUCKDB_TYPE_UINTEGER) &&
        (amount_ty == DUCKDB_TYPE_BIGINT || amount_ty == DUCKDB_TYPE_UBIGINT)) {
        const int32_t *dates = static_cast<const int32_t *>(date_ptr);
        const int64_t *amounts = static_cast<const int64_t *>(amount_ptr);
        for (idx_t i = 0; i < n; ++i) {
            const int64_t d = dates[i];
            if (d >= date_lo && d <= date_hi) {
                sum += static_cast<uint64_t>(amounts[i]);
                matched += 1;
            }
        }
        return;
    }
    if ((date_ty == DUCKDB_TYPE_INTEGER || date_ty == DUCKDB_TYPE_UINTEGER) &&
        (amount_ty == DUCKDB_TYPE_INTEGER || amount_ty == DUCKDB_TYPE_UINTEGER)) {
        const int32_t *dates = static_cast<const int32_t *>(date_ptr);
        const int32_t *amounts = static_cast<const int32_t *>(amount_ptr);
        for (idx_t i = 0; i < n; ++i) {
            const int64_t d = dates[i];
            if (d >= date_lo && d <= date_hi) {
                sum += static_cast<uint64_t>(amounts[i]);
                matched += 1;
            }
        }
    }
}

int lemma_stream_h1_sum_lemma_filter(
    void *conn,
    uint64_t *matched_out,
    uint64_t *sum_out,
    char *error_out,
    size_t error_len
) {
    auto *connection = static_cast<duckdb_connection>(conn);
    if (connection == nullptr || matched_out == nullptr || sum_out == nullptr) {
        set_error(error_out, error_len, "lemma_stream_h1_sum_lemma_filter: null argument");
        return -1;
    }

    const char *columns[] = {"event_date", "amount"};
    StreamState state;
    std::ostringstream sql;
    sql << "SELECT " << quote_ident(columns[0]) << ", " << quote_ident(columns[1])
        << " FROM " << quote_ident("scan_skew");

    duckdb_state status = duckdb_prepare(connection, sql.str().c_str(), &state.prepared);
    state.has_prepared = true;
    if (status != DuckDBSuccess) {
        const char *err = duckdb_prepare_error(state.prepared);
        set_error(error_out, error_len, err != nullptr ? err : "duckdb_prepare failed");
        destroy_stream_state(state);
        return -1;
    }
    if (!execute_streaming_result(state, error_out, error_len)) {
        destroy_stream_state(state);
        return -1;
    }

    const int64_t date_lo = 19960101;
    const int64_t date_hi = 19961231;
    const idx_t date_col = 0;
    const idx_t amount_col = 1;

    uint64_t matched = 0;
    uint64_t sum = 0;
    state.exhausted = false;
    while (true) {
        release_current_chunk(state);
        duckdb_data_chunk chunk = duckdb_fetch_chunk(state.result);
        if (chunk == nullptr) {
            break;
        }
        if (chunk_may_satisfy_range(chunk, date_col, date_lo, date_hi)) {
            sum_filtered_chunk(chunk, date_col, amount_col, date_lo, date_hi, matched, sum);
        }
        duckdb_destroy_data_chunk(&chunk);
    }

    destroy_stream_state(state);
    *matched_out = matched;
    *sum_out = sum;
    return 0;
}

int lemma_stream_h1_sum_optimized(
    void *conn,
    uint64_t *matched_out,
    uint64_t *sum_out,
    char *error_out,
    size_t error_len
) {
    auto *connection = static_cast<duckdb_connection>(conn);
    if (connection == nullptr || matched_out == nullptr || sum_out == nullptr) {
        set_error(error_out, error_len, "lemma_stream_h1_sum_optimized: null argument");
        return -1;
    }

    StreamState state;
    if (!prepare_pushdown_sql(
            state, connection, "scan_skew", "amount", "event_date", 19960101, 19961231, error_out, error_len)) {
        destroy_stream_state(state);
        return -1;
    }
    if (!execute_streaming_result(state, error_out, error_len)) {
        destroy_stream_state(state);
        return -1;
    }

    uint64_t matched = 0;
    uint64_t sum = 0;
    state.exhausted = false;
    while (true) {
        release_current_chunk(state);
        duckdb_data_chunk chunk = duckdb_fetch_chunk(state.result);
        if (chunk == nullptr) {
            break;
        }
        sum_amounts_chunk(chunk, matched, sum);
        duckdb_destroy_data_chunk(&chunk);
    }

    destroy_stream_state(state);
    *matched_out = matched;
    *sum_out = sum;
    return 0;
}

}  // extern "C"
