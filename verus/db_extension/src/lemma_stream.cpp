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

}  // extern "C"
