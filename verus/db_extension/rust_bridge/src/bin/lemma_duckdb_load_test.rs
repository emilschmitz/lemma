//! Smoke-test binary for Lemma on DuckDB mem (default) and legacy sidecar export.

use std::env;
use std::path::PathBuf;

use lemma_agent_primitives::{
    checksum_u64, load_cols_from_duckdb_export, load_manifest, pin_and_checksum, DuckDb,
};

fn sidecar_mode(args: &[String]) {
    if args.len() < 4 {
        eprintln!("usage: {} sidecar <manifest.json> <table> <column>", args[0]);
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

    println!("DUCKDB_SIDECAR_OK");
    println!("TABLE: {table}");
    println!("COLUMN: {column}");
    println!("ROW_COUNT: {}", table_meta.row_count);
    println!("COL_LENGTH: {}", col.len());
    println!("CHECKSUM_U64: {cksum}");
    println!("FIRST_VALUE: {sample}");
}

fn pin_mode(args: &[String]) {
    if args.len() < 4 {
        eprintln!("usage: {} pin <db_path> <table> <column>", args[0]);
        std::process::exit(2);
    }
    let db_path = &args[1];
    let table = &args[2];
    let column = &args[3];

    let db = DuckDb::open(db_path).expect("open duckdb");
    let (rows, cksum) = pin_and_checksum(&db, table, column).expect("pin column");

    println!("DUCKDB_PIN_OK");
    println!("DB: {db_path}");
    println!("TABLE: {table}");
    println!("COLUMN: {column}");
    println!("ROW_COUNT: {rows}");
    println!("CHECKSUM_U64: {cksum}");
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: {} <pin|sidecar> ...", args[0]);
        std::process::exit(2);
    }
    match args[1].as_str() {
        "pin" => pin_mode(&args[1..]),
        "sidecar" => sidecar_mode(&args[1..]),
        // Back-compat: manifest path as first arg → sidecar
        _ => {
            let mut legacy = vec![args[0].clone(), "sidecar".to_string()];
            legacy.extend(args[1..].iter().cloned());
            sidecar_mode(&legacy[1..]);
        }
    }
}
