#pragma once

//! Minimal storage-layer declarations not exported in the public duckdb.hpp surface.
//! Linked against prebuilt libduckdb.so (ABI must match build/libduckdb).

#include "duckdb.hpp"

namespace duckdb {

class DuckTableEntry : public StandardEntry {
public:
    static constexpr const CatalogType Type = CatalogType::TABLE_ENTRY;
    static constexpr const char *Name = "table";

    DUCKDB_API DataTable &GetStorage();
};

class DataTable {
public:
    DUCKDB_API idx_t GetTotalRows() const;
    DUCKDB_API void ScanTableSegment(
        DuckTransaction &transaction,
        idx_t start_row,
        idx_t count,
        const std::function<void(DataChunk &chunk)> &function);
};

class DuckTransaction {
public:
    DUCKDB_API static DuckTransaction &Get(ClientContext &context, AttachedDatabase &db);
};

}  // namespace duckdb
