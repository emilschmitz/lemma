//! Smoke-test binary for DuckDB → `.lemma_cols` export manifests.

use std::env;
use std::path::PathBuf;

use lemma_agent_primitives::{checksum_u64, load_cols_from_duckdb_export, load_manifest};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 4 {
        eprintln!("usage: {} <manifest.json> <table> <column>", args[0]);
        std::process::exit(2);
    }
    let manifest_path = PathBuf::from(&args[1]);
    let table = &args[2];
    let column = &args[3];

    let manifest = load_manifest(&manifest_path).expect("load manifest");
    let table_meta = manifest
        .tables
        .get(table)
        .or_else(|| {
            manifest
                .tables
                .iter()
                .find(|(k, _)| k.eq_ignore_ascii_case(table))
                .map(|(_, v)| v)
        })
        .expect("table in manifest");

    let col = load_cols_from_duckdb_export(&manifest_path, table, column).expect("load column");
    let cksum = checksum_u64(&col);
    let sample = col.first().copied().unwrap_or(0);

    println!("DUCKDB_EXPORT_OK");
    println!("TABLE: {table}");
    println!("COLUMN: {column}");
    println!("ROW_COUNT: {}", table_meta.row_count);
    println!("COL_LENGTH: {}", col.len());
    println!("CHECKSUM_U64: {cksum}");
    println!("FIRST_VALUE: {sample}");
}
