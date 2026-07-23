#include "lemma_storage.h"
#include "lemma_storage_internal.hpp"

#include <cstring>
#include <string>

namespace {

constexpr const char *kScanMode = "real_datatable_scan";

void set_error(char *error_out, size_t error_len, const std::string &msg) {
    if (error_out == nullptr || error_len == 0) {
        return;
    }
    std::strncpy(error_out, msg.c_str(), error_len - 1);
    error_out[error_len - 1] = '\0';
}

void set_scan_mode(char *out, size_t out_len) {
    if (out == nullptr || out_len == 0) {
        return;
    }
    std::strncpy(out, kScanMode, out_len - 1);
    out[out_len - 1] = '\0';
}

bool chunk_may_satisfy(
    duckdb::DataChunk &chunk,
    idx_t date_col,
    int64_t date_lo,
    int64_t date_hi
) {
    idx_t n = chunk.size();
    if (n == 0) {
        return false;
    }

    duckdb::UnifiedVectorFormat date_fmt;
    chunk.data[date_col].ToUnifiedFormat(n, date_fmt);
    const int64_t *dates = duckdb::UnifiedVectorFormat::GetData<int64_t>(date_fmt);
    const auto &sel = *date_fmt.sel;

    int64_t min_v = dates[sel.get_index(0)];
    int64_t max_v = min_v;
    for (idx_t row = 1; row < n; row++) {
        const int64_t d = dates[sel.get_index(row)];
        if (d < min_v) {
            min_v = d;
        }
        if (d > max_v) {
            max_v = d;
        }
    }
    return max_v >= date_lo && min_v <= date_hi;
}

void filter_sum_chunk(
    duckdb::DataChunk &chunk,
    idx_t date_col,
    idx_t amount_col,
    int64_t date_lo,
    int64_t date_hi,
    uint64_t &matched,
    uint64_t &sum
) {
    idx_t n = chunk.size();
    if (n == 0) {
        return;
    }

    duckdb::UnifiedVectorFormat date_fmt;
    duckdb::UnifiedVectorFormat amount_fmt;
    chunk.data[date_col].ToUnifiedFormat(n, date_fmt);
    chunk.data[amount_col].ToUnifiedFormat(n, amount_fmt);

    const int64_t *dates = duckdb::UnifiedVectorFormat::GetData<int64_t>(date_fmt);
    const int64_t *amounts = duckdb::UnifiedVectorFormat::GetData<int64_t>(amount_fmt);
    const auto &date_sel = *date_fmt.sel;
    const auto &amount_sel = *amount_fmt.sel;

    for (idx_t row = 0; row < n; row++) {
        const idx_t di = date_sel.get_index(row);
        const int64_t d = dates[di];
        if (d < date_lo || d > date_hi) {
            continue;
        }
        const idx_t ai = amount_sel.get_index(row);
        sum += static_cast<uint64_t>(amounts[ai]);
        matched += 1;
    }
}

}  // namespace

extern "C" {

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
    size_t error_len
) {
    if (db_path == nullptr || table == nullptr || matched_out == nullptr || sum_out == nullptr) {
        set_error(error_out, error_len, "lemma_storage_h1_run: null argument");
        return -1;
    }

    try {
        duckdb::DuckDB database(db_path);
        duckdb::Connection con(database);
        duckdb::ClientContext &context = *con.context;
        con.BeginTransaction();

        const std::string &catalog_name = duckdb::DatabaseManager::GetDefaultDatabase(context);
        duckdb::Catalog &catalog = duckdb::Catalog::GetCatalog(context, catalog_name);
        duckdb::DuckTableEntry &table_entry =
            catalog.GetEntry<duckdb::DuckTableEntry>(context, DEFAULT_SCHEMA, table);
        duckdb::DataTable &storage = table_entry.GetStorage();
        duckdb::AttachedDatabase &attached = catalog.GetAttached();
        duckdb::DuckTransaction &txn = duckdb::DuckTransaction::Get(context, attached);

        // scan_skew layout: event_date (0), region (1), amount (2)
        const idx_t date_col = 0;
        const idx_t amount_col = 2;

        const idx_t total_rows = storage.GetTotalRows();
        const int64_t lo = static_cast<int64_t>(date_lo);
        const int64_t hi = static_cast<int64_t>(date_hi);

        uint64_t matched = 0;
        uint64_t sum = 0;
        storage.ScanTableSegment(txn, 0, total_rows, [&](duckdb::DataChunk &chunk) {
            if (!chunk_may_satisfy(chunk, date_col, lo, hi)) {
                return;
            }
            filter_sum_chunk(chunk, date_col, amount_col, lo, hi, matched, sum);
        });

        con.Commit();

        *matched_out = matched;
        *sum_out = sum;
        set_scan_mode(scan_mode_out, scan_mode_len);
        return 0;
    } catch (const duckdb::Exception &ex) {
        set_error(error_out, error_len, ex.what());
        return -1;
    } catch (const std::exception &ex) {
        set_error(error_out, error_len, ex.what());
        return -1;
    } catch (...) {
        set_error(error_out, error_len, "lemma_storage_h1_run: unknown error");
        return -1;
    }
}

}  // extern "C"
