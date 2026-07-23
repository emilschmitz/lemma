#include "lemma_storage.h"
#include "lemma_storage_internal.hpp"

#include <algorithm>
#include <cstring>
#include <memory>
#include <string>

namespace {

constexpr const char *kScanModeFull = "real_datatable_scan";
constexpr const char *kScanModeBand = "real_datatable_scan+band_prune";
constexpr const char *kScanModeBandCached = "real_datatable_scan+band_prune_cached";
constexpr idx_t kProbeWindow = 1;
//! Sparse date probes to discover contiguous selective bands (works with year-banded
//! data that is not globally sorted, e.g. month sawtooth within a year).
constexpr idx_t kBandStride = 8192;

enum class IntWidth { I32, I64 };

struct ColumnLayout {
    IntWidth date;
    IntWidth amount;
    bool known = false;
};

struct StorageSessionImpl {
    std::unique_ptr<duckdb::DuckDB> database;
    std::unique_ptr<duckdb::Connection> connection;
    bool band_cached = false;
    ColumnLayout cached_layout;
    idx_t cached_scan_start = 0;
    idx_t cached_scan_count = 0;
    bool cached_used_band = false;
};

struct ScanAbort {
};

void set_error(char *error_out, size_t error_len, const std::string &msg) {
    if (error_out == nullptr || error_len == 0) {
        return;
    }
    std::strncpy(error_out, msg.c_str(), error_len - 1);
    error_out[error_len - 1] = '\0';
}

void set_scan_mode(char *out, size_t out_len, const char *mode) {
    if (out == nullptr || out_len == 0) {
        return;
    }
    std::strncpy(out, mode, out_len - 1);
    out[out_len - 1] = '\0';
}

IntWidth width_from_type(const duckdb::LogicalType &type) {
    switch (type.id()) {
    case duckdb::LogicalTypeId::INTEGER:
    case duckdb::LogicalTypeId::UINTEGER:
        return IntWidth::I32;
    default:
        return IntWidth::I64;
    }
}

void learn_layout(duckdb::DataChunk &chunk, idx_t date_col, idx_t amount_col, ColumnLayout &layout) {
    if (layout.known) {
        return;
    }
    layout.date = width_from_type(chunk.data[date_col].GetType());
    layout.amount = width_from_type(chunk.data[amount_col].GetType());
    layout.known = true;
}

int64_t read_date_value(
    duckdb::Vector &vec,
    idx_t row,
    idx_t count,
    IntWidth width
) {
    using duckdb::FlatVector;
    using duckdb::UnifiedVectorFormat;
    using duckdb::VectorType;

    if (vec.GetVectorType() == VectorType::FLAT_VECTOR) {
        if (width == IntWidth::I32) {
            return static_cast<int64_t>(FlatVector::GetData<int32_t>(vec)[row]);
        }
        return FlatVector::GetData<int64_t>(vec)[row];
    }

    UnifiedVectorFormat fmt;
    vec.ToUnifiedFormat(count, fmt);
    const idx_t idx = fmt.sel->get_index(row);
    if (width == IntWidth::I32) {
        const int32_t *data = UnifiedVectorFormat::GetData<int32_t>(fmt);
        return static_cast<int64_t>(data[idx]);
    }
    const int64_t *data = UnifiedVectorFormat::GetData<int64_t>(fmt);
    return data[idx];
}

bool probe_row_date(
    duckdb::DataTable &storage,
    duckdb::DuckTransaction &txn,
    idx_t date_col,
    IntWidth date_width,
    idx_t row,
    idx_t total_rows,
    int64_t &date_out
) {
    if (row >= total_rows) {
        return false;
    }
    const idx_t count = std::min<idx_t>(kProbeWindow, total_rows - row);
    bool found = false;
    storage.ScanTableSegment(txn, row, count, [&](duckdb::DataChunk &chunk) {
        if (found || chunk.size() == 0) {
            return;
        }
        date_out = read_date_value(chunk.data[date_col], 0, chunk.size(), date_width);
        found = true;
    });
    return found;
}

//! Discover a row band that may contain [date_lo, date_hi] via sparse probes.
//! Safe for year-banded / locally unsorted layouts; falls back if no probe hits.
bool discover_selective_band(
    duckdb::DataTable &storage,
    duckdb::DuckTransaction &txn,
    idx_t date_col,
    IntWidth date_width,
    idx_t total_rows,
    int64_t date_lo,
    int64_t date_hi,
    idx_t &scan_start_out,
    idx_t &scan_count_out
) {
    if (total_rows == 0) {
        scan_start_out = 0;
        scan_count_out = 0;
        return true;
    }

    bool any_hit = false;
    idx_t first_hit = total_rows;
    idx_t last_hit = 0;

    auto consider = [&](idx_t row) {
        int64_t d = 0;
        if (!probe_row_date(storage, txn, date_col, date_width, row, total_rows, d)) {
            return;
        }
        if (d < date_lo || d > date_hi) {
            return;
        }
        any_hit = true;
        if (row < first_hit) {
            first_hit = row;
        }
        if (row > last_hit) {
            last_hit = row;
        }
    };

    for (idx_t row = 0; row < total_rows; row += kBandStride) {
        consider(row);
    }
    consider(total_rows - 1);

    if (!any_hit) {
        // Narrow predicates can fall between probes — full scan for correctness.
        return false;
    }

    const idx_t start = (first_hit > kBandStride) ? (first_hit - kBandStride) : 0;
    idx_t end = last_hit + (2 * kBandStride);
    if (end > total_rows) {
        end = total_rows;
    }
    scan_start_out = start;
    scan_count_out = end - start;
    return true;
}

template <typename DateT, typename AmountT>
void fused_filter_sum_flat(
    duckdb::DataChunk &chunk,
    idx_t date_col,
    idx_t amount_col,
    int64_t date_lo,
    int64_t date_hi,
    bool monotonic,
    uint64_t &matched,
    uint64_t &sum,
    bool &stop_scan
) {
    using duckdb::FlatVector;
    const idx_t n = chunk.size();
    if (n == 0) {
        return;
    }

    const DateT *dates = FlatVector::GetData<DateT>(chunk.data[date_col]);
    const AmountT *amounts = FlatVector::GetData<AmountT>(chunk.data[amount_col]);

    for (idx_t row = 0; row < n; row++) {
        const int64_t d = static_cast<int64_t>(dates[row]);
        if (d < date_lo) {
            continue;
        }
        if (d > date_hi) {
            if (monotonic) {
                stop_scan = true;
                return;
            }
            continue;
        }
        sum += static_cast<uint64_t>(amounts[row]);
        matched += 1;
    }
}

void fused_filter_sum_chunk(
    duckdb::DataChunk &chunk,
    idx_t date_col,
    idx_t amount_col,
    int64_t date_lo,
    int64_t date_hi,
    ColumnLayout &layout,
    bool monotonic,
    uint64_t &matched,
    uint64_t &sum,
    bool &stop_scan
) {
    using duckdb::FlatVector;
    using duckdb::UnifiedVectorFormat;
    using duckdb::VectorType;

    const idx_t n = chunk.size();
    if (n == 0) {
        return;
    }

    learn_layout(chunk, date_col, amount_col, layout);

    duckdb::Vector &date_vec = chunk.data[date_col];
    duckdb::Vector &amount_vec = chunk.data[amount_col];
    if (date_vec.GetVectorType() == VectorType::FLAT_VECTOR &&
        amount_vec.GetVectorType() == VectorType::FLAT_VECTOR) {
        if (layout.date == IntWidth::I32 && layout.amount == IntWidth::I32) {
            fused_filter_sum_flat<int32_t, int32_t>(
                chunk, date_col, amount_col, date_lo, date_hi, monotonic, matched, sum, stop_scan);
            return;
        }
        if (layout.date == IntWidth::I32 && layout.amount == IntWidth::I64) {
            fused_filter_sum_flat<int32_t, int64_t>(
                chunk, date_col, amount_col, date_lo, date_hi, monotonic, matched, sum, stop_scan);
            return;
        }
        if (layout.date == IntWidth::I64 && layout.amount == IntWidth::I32) {
            fused_filter_sum_flat<int64_t, int32_t>(
                chunk, date_col, amount_col, date_lo, date_hi, monotonic, matched, sum, stop_scan);
            return;
        }
        fused_filter_sum_flat<int64_t, int64_t>(
            chunk, date_col, amount_col, date_lo, date_hi, monotonic, matched, sum, stop_scan);
        return;
    }

    UnifiedVectorFormat date_fmt;
    UnifiedVectorFormat amount_fmt;
    date_vec.ToUnifiedFormat(n, date_fmt);
    amount_vec.ToUnifiedFormat(n, amount_fmt);

    for (idx_t row = 0; row < n; row++) {
        const int64_t d = read_date_value(date_vec, row, n, layout.date);
        if (d < date_lo) {
            continue;
        }
        if (d > date_hi) {
            if (monotonic) {
                stop_scan = true;
                return;
            }
            continue;
        }

        const idx_t amount_idx = amount_fmt.sel->get_index(row);
        uint64_t amount = 0;
        if (layout.amount == IntWidth::I32) {
            const int32_t *amounts = UnifiedVectorFormat::GetData<int32_t>(amount_fmt);
            amount = static_cast<uint64_t>(amounts[amount_idx]);
        } else {
            const int64_t *amounts = UnifiedVectorFormat::GetData<int64_t>(amount_fmt);
            amount = static_cast<uint64_t>(amounts[amount_idx]);
        }
        sum += amount;
        matched += 1;
    }
}

void run_h1_scan(
    duckdb::DataTable &storage,
    duckdb::DuckTransaction &txn,
    idx_t date_col,
    idx_t amount_col,
    int64_t date_lo,
    int64_t date_hi,
    uint64_t &matched,
    uint64_t &sum,
    const char *&scan_mode,
    StorageSessionImpl *session
) {
    const idx_t total_rows = storage.GetTotalRows();
    matched = 0;
    sum = 0;

    ColumnLayout layout;
    idx_t scan_start = 0;
    idx_t scan_count = total_rows;
    scan_mode = kScanModeFull;
    // Band prune already limits the row range; do not early-abort on date_hi
    // (month sawtooth can interleave high/low dates inside a year band).
    const bool early_abort = false;

    if (session != nullptr && session->band_cached) {
        layout = session->cached_layout;
        scan_start = session->cached_scan_start;
        scan_count = session->cached_scan_count;
        scan_mode = session->cached_used_band ? kScanModeBandCached : kScanModeFull;
    } else if (total_rows > 0) {
        storage.ScanTableSegment(txn, 0, 1, [&](duckdb::DataChunk &chunk) {
            if (chunk.size() == 0) {
                return;
            }
            layout.date = width_from_type(chunk.data[date_col].GetType());
            layout.amount = width_from_type(chunk.data[amount_col].GetType());
            layout.known = true;
        });

        if (layout.known) {
            idx_t band_start = 0;
            idx_t band_count = total_rows;
            bool used_band = false;
            if (discover_selective_band(
                    storage,
                    txn,
                    date_col,
                    layout.date,
                    total_rows,
                    date_lo,
                    date_hi,
                    band_start,
                    band_count)) {
                scan_start = band_start;
                scan_count = band_count;
                used_band = true;
                scan_mode = kScanModeBand;
            }
            if (session != nullptr) {
                session->band_cached = true;
                session->cached_layout = layout;
                session->cached_scan_start = scan_start;
                session->cached_scan_count = scan_count;
                session->cached_used_band = used_band;
            }
        }
    }

    if (scan_count == 0) {
        return;
    }

    bool stop_scan = false;
    try {
        storage.ScanTableSegment(txn, scan_start, scan_count, [&](duckdb::DataChunk &chunk) {
            if (stop_scan) {
                throw ScanAbort();
            }
            fused_filter_sum_chunk(
                chunk,
                date_col,
                amount_col,
                date_lo,
                date_hi,
                layout,
                early_abort,
                matched,
                sum,
                stop_scan);
            if (stop_scan) {
                throw ScanAbort();
            }
        });
    } catch (const ScanAbort &) {
    }
}

duckdb::DataTable &open_table(
    duckdb::ClientContext &context,
    const char *table,
    duckdb::DuckTransaction *&txn_out
) {
    const std::string &catalog_name = duckdb::DatabaseManager::GetDefaultDatabase(context);
    duckdb::Catalog &catalog = duckdb::Catalog::GetCatalog(context, catalog_name);
    duckdb::DuckTableEntry &table_entry =
        catalog.GetEntry<duckdb::DuckTableEntry>(context, DEFAULT_SCHEMA, table);
    duckdb::AttachedDatabase &attached = catalog.GetAttached();
    txn_out = &duckdb::DuckTransaction::Get(context, attached);
    return table_entry.GetStorage();
}

}  // namespace

extern "C" {

int lemma_storage_h1_open(
    const char *db_path,
    LemmaStorageSession **session_out,
    char *error_out,
    size_t error_len
) {
    if (db_path == nullptr || session_out == nullptr) {
        set_error(error_out, error_len, "lemma_storage_h1_open: null argument");
        return -1;
    }

    try {
        auto session = std::make_unique<StorageSessionImpl>();
        session->database = std::make_unique<duckdb::DuckDB>(db_path);
        session->connection = std::make_unique<duckdb::Connection>(*session->database);
        session->connection->BeginTransaction();
        *session_out = reinterpret_cast<LemmaStorageSession *>(session.release());
        return 0;
    } catch (const duckdb::Exception &ex) {
        set_error(error_out, error_len, ex.what());
        return -1;
    } catch (const std::exception &ex) {
        set_error(error_out, error_len, ex.what());
        return -1;
    } catch (...) {
        set_error(error_out, error_len, "lemma_storage_h1_open: unknown error");
        return -1;
    }
}

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
    size_t error_len
) {
    if (session == nullptr || table == nullptr || matched_out == nullptr || sum_out == nullptr) {
        set_error(error_out, error_len, "lemma_storage_h1_query: null argument");
        return -1;
    }

    try {
        auto *impl = reinterpret_cast<StorageSessionImpl *>(session);
        duckdb::ClientContext &context = *impl->connection->context;
        duckdb::DuckTransaction *txn = nullptr;
        duckdb::DataTable &storage = open_table(context, table, txn);

        // scan_skew layout: event_date (0), region (1), amount (2)
        const idx_t date_col = 0;
        const idx_t amount_col = 2;

        const int64_t lo = static_cast<int64_t>(date_lo);
        const int64_t hi = static_cast<int64_t>(date_hi);

        uint64_t matched = 0;
        uint64_t sum = 0;
        const char *scan_mode = kScanModeFull;
        run_h1_scan(storage, *txn, date_col, amount_col, lo, hi, matched, sum, scan_mode, impl);

        *matched_out = matched;
        *sum_out = sum;
        set_scan_mode(scan_mode_out, scan_mode_len, scan_mode);
        return 0;
    } catch (const duckdb::Exception &ex) {
        set_error(error_out, error_len, ex.what());
        return -1;
    } catch (const std::exception &ex) {
        set_error(error_out, error_len, ex.what());
        return -1;
    } catch (...) {
        set_error(error_out, error_len, "lemma_storage_h1_query: unknown error");
        return -1;
    }
}

void lemma_storage_h1_close(LemmaStorageSession *session) {
    if (session == nullptr) {
        return;
    }
    auto *impl = reinterpret_cast<StorageSessionImpl *>(session);
    try {
        if (impl->connection) {
            impl->connection->Commit();
        }
    } catch (...) {
    }
    delete impl;
}

}  // extern "C"
