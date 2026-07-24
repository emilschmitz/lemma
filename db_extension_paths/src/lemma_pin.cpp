#include "lemma_pin.h"
#include <duckdb.h>

#include <algorithm>
#include <cstring>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

std::mutex g_registry_mutex;
std::unordered_map<LemmaPinId, std::unique_ptr<struct PinState>> g_pins;
LemmaPinId g_next_pin_id = 1;

struct PinState {
    std::mutex lease_mutex;
    duckdb_result result{};
    bool has_result = false;
    idx_t row_count = 0;
    idx_t col_count = 0;
    std::vector<std::string> col_names;
    std::vector<duckdb_type> col_types;
    std::vector<duckdb_data_chunk> chunks;
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

PinState *lookup_pin(LemmaPinId pin) {
    auto it = g_pins.find(pin);
    if (it == g_pins.end()) {
        return nullptr;
    }
    return it->second.get();
}

void materialize_chunks(PinState &state) {
    state.chunks.clear();
    idx_t n_chunks = duckdb_result_chunk_count(state.result);
    state.row_count = duckdb_row_count(&state.result);
    state.col_count = duckdb_column_count(&state.result);
    state.col_names.clear();
    state.col_types.clear();
    for (idx_t c = 0; c < state.col_count; c++) {
        const char *name = duckdb_column_name(&state.result, c);
        state.col_names.emplace_back(name != nullptr ? name : "");
        state.col_types.push_back(duckdb_column_type(&state.result, c));
    }
    state.chunks.reserve(n_chunks);
    for (idx_t i = 0; i < n_chunks; i++) {
        duckdb_data_chunk chunk = duckdb_result_get_chunk(state.result, i);
        state.chunks.push_back(chunk);
    }
}

}  // namespace

extern "C" {

LemmaPinId lemma_pin_table(
    void *conn,
    const char *table,
    const char *const *columns,
    size_t n_columns,
    char *error_out,
    size_t error_len
) {
    auto *connection = static_cast<duckdb_connection>(conn);
    if (connection == nullptr || table == nullptr) {
        set_error(error_out, error_len, "lemma_pin_table: null connection or table");
        return LEMMA_PIN_INVALID;
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

    auto state = std::make_unique<PinState>();
    state->table_name = table;

    duckdb_state status = duckdb_query(connection, sql.str().c_str(), &state->result);
    state->has_result = true;
    if (status != DuckDBSuccess) {
        const char *err = duckdb_result_error(&state->result);
        set_error(error_out, error_len, err != nullptr ? err : "duckdb_query failed");
        duckdb_destroy_result(&state->result);
        return LEMMA_PIN_INVALID;
    }

    materialize_chunks(*state);

    std::lock_guard<std::mutex> lock(g_registry_mutex);
    LemmaPinId pin = g_next_pin_id++;
    g_pins.emplace(pin, std::move(state));
    return pin;
}

void lemma_unpin(LemmaPinId pin) {
    std::unique_ptr<PinState> owned;
    {
        std::lock_guard<std::mutex> lock(g_registry_mutex);
        auto it = g_pins.find(pin);
        if (it == g_pins.end()) {
            return;
        }
        owned = std::move(it->second);
        g_pins.erase(it);
    }
    if (owned != nullptr) {
        std::lock_guard<std::mutex> lease(owned->lease_mutex);
        for (auto &chunk : owned->chunks) {
            if (chunk != nullptr) {
                duckdb_destroy_data_chunk(&chunk);
            }
        }
        owned->chunks.clear();
        if (owned->has_result) {
            duckdb_destroy_result(&owned->result);
            owned->has_result = false;
        }
    }
}

uint64_t lemma_pin_row_count(LemmaPinId pin) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    PinState *state = lookup_pin(pin);
    return state != nullptr ? static_cast<uint64_t>(state->row_count) : 0;
}

uint64_t lemma_pin_column_count(LemmaPinId pin) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    PinState *state = lookup_pin(pin);
    return state != nullptr ? static_cast<uint64_t>(state->col_count) : 0;
}

const char *lemma_pin_column_name(LemmaPinId pin, uint64_t col) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    PinState *state = lookup_pin(pin);
    if (state == nullptr || col >= state->col_names.size()) {
        return nullptr;
    }
    return state->col_names[col].c_str();
}

uint32_t lemma_pin_column_type(LemmaPinId pin, uint64_t col) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    PinState *state = lookup_pin(pin);
    if (state == nullptr || col >= state->col_types.size()) {
        return DUCKDB_TYPE_INVALID;
    }
    return static_cast<uint32_t>(state->col_types[col]);
}

uint64_t lemma_pin_chunk_count(LemmaPinId pin) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    PinState *state = lookup_pin(pin);
    return state != nullptr ? static_cast<uint64_t>(state->chunks.size()) : 0;
}

uint64_t lemma_pin_chunk_len(LemmaPinId pin, uint64_t chunk_index) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    PinState *state = lookup_pin(pin);
    if (state == nullptr || chunk_index >= state->chunks.size()) {
        return 0;
    }
    return static_cast<uint64_t>(duckdb_data_chunk_get_size(state->chunks[chunk_index]));
}

void *lemma_pin_vector_data(LemmaPinId pin, uint64_t chunk_index, uint64_t col) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    PinState *state = lookup_pin(pin);
    if (state == nullptr || chunk_index >= state->chunks.size()) {
        return nullptr;
    }
    duckdb_data_chunk chunk = state->chunks[chunk_index];
    if (col >= duckdb_data_chunk_get_column_count(chunk)) {
        return nullptr;
    }
    duckdb_vector vec = duckdb_data_chunk_get_vector(chunk, static_cast<idx_t>(col));
    return duckdb_vector_get_data(vec);
}

uint64_t *lemma_pin_vector_validity(LemmaPinId pin, uint64_t chunk_index, uint64_t col) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    PinState *state = lookup_pin(pin);
    if (state == nullptr || chunk_index >= state->chunks.size()) {
        return nullptr;
    }
    duckdb_data_chunk chunk = state->chunks[chunk_index];
    if (col >= duckdb_data_chunk_get_column_count(chunk)) {
        return nullptr;
    }
    duckdb_vector vec = duckdb_data_chunk_get_vector(chunk, static_cast<idx_t>(col));
    return duckdb_vector_get_validity(vec);
}

uint32_t lemma_pin_vector_type(LemmaPinId pin, uint64_t chunk_index, uint64_t col) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    PinState *state = lookup_pin(pin);
    if (state == nullptr || chunk_index >= state->chunks.size()) {
        return DUCKDB_TYPE_INVALID;
    }
    duckdb_data_chunk chunk = state->chunks[chunk_index];
    if (col >= duckdb_data_chunk_get_column_count(chunk)) {
        return DUCKDB_TYPE_INVALID;
    }
    duckdb_vector vec = duckdb_data_chunk_get_vector(chunk, static_cast<idx_t>(col));
    duckdb_logical_type ltype = duckdb_vector_get_column_type(vec);
    duckdb_type ty = duckdb_get_type_id(ltype);
    duckdb_destroy_logical_type(&ltype);
    return static_cast<uint32_t>(ty);
}

bool lemma_pin_any_active(void) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    return !g_pins.empty();
}

}  // extern "C"
