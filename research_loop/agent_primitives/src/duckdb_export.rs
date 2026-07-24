//! Read `.lemma_cols` sidecars produced by `db_extension_paths/duckdb_memory.py`.
//!
//! This is a **copy export** path: Python copies DuckDB column data into binary
//! files; Rust reads them into `Vec<T>`. Not zero-copy from DuckDB memory.

use std::collections::HashMap;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

const MAGIC: [u8; 8] = *b"LEMMA1\0\0";
const HEADER_SIZE: u64 = 32;

#[derive(Debug, Clone)]
pub struct ColumnMeta {
    pub dtype: String,
    pub path: PathBuf,
    pub length: usize,
}

#[derive(Debug, Clone)]
pub struct TableMeta {
    pub row_count: usize,
    pub columns: HashMap<String, ColumnMeta>,
}

#[derive(Debug, Clone)]
pub struct DuckdbManifest {
    pub version: u32,
    pub db_path: String,
    pub export_dir: PathBuf,
    pub tables: HashMap<String, TableMeta>,
}

#[derive(Debug)]
pub enum LoadError {
    Io(std::io::Error),
    Json(serde_json::Error),
    Format(String),
}

impl std::fmt::Display for LoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LoadError::Io(e) => write!(f, "io: {e}"),
            LoadError::Json(e) => write!(f, "json: {e}"),
            LoadError::Format(s) => write!(f, "format: {s}"),
        }
    }
}

impl std::error::Error for LoadError {}

impl From<std::io::Error> for LoadError {
    fn from(e: std::io::Error) -> Self {
        LoadError::Io(e)
    }
}

impl From<serde_json::Error> for LoadError {
    fn from(e: serde_json::Error) -> Self {
        LoadError::Json(e)
    }
}

fn read_header(path: &Path) -> Result<(u8, u64), LoadError> {
    let mut f = File::open(path)?;
    let mut magic = [0u8; 8];
    f.read_exact(&mut magic)?;
    if magic != MAGIC {
        return Err(LoadError::Format(format!("bad magic in {}", path.display())));
    }
    let mut dtype_buf = [0u8; 1];
    f.read_exact(&mut dtype_buf)?;
    f.seek(SeekFrom::Start(16))?;
    let mut len_buf = [0u8; 8];
    f.read_exact(&mut len_buf)?;
    let row_count = u64::from_le_bytes(len_buf);
    Ok((dtype_buf[0], row_count))
}

fn read_fixed_column<T>(path: &Path, expected_dtype: u8, parse: fn(&[u8]) -> T) -> Result<Vec<T>, LoadError>
where
    T: Copy,
{
    let (dtype, row_count) = read_header(path)?;
    if dtype != expected_dtype {
        return Err(LoadError::Format(format!(
            "dtype mismatch in {}: expected {expected_dtype}, got {dtype}",
            path.display()
        )));
    }
    let mut f = File::open(path)?;
    f.seek(SeekFrom::Start(HEADER_SIZE))?;
    let elem_size = std::mem::size_of::<T>();
    let nbytes = row_count as usize * elem_size;
    let mut buf = vec![0u8; nbytes];
    f.read_exact(&mut buf)?;
    Ok(buf
        .chunks_exact(elem_size)
        .map(|chunk| parse(chunk))
        .collect())
}

fn le_u32(chunk: &[u8]) -> u32 {
    u32::from_le_bytes(chunk.try_into().unwrap())
}

fn le_u64(chunk: &[u8]) -> u64 {
    u64::from_le_bytes(chunk.try_into().unwrap())
}

fn le_i64(chunk: &[u8]) -> i64 {
    i64::from_le_bytes(chunk.try_into().unwrap())
}

fn le_f64(chunk: &[u8]) -> f64 {
    f64::from_le_bytes(chunk.try_into().unwrap())
}

fn le_bool(chunk: &[u8]) -> bool {
    chunk[0] != 0
}

pub fn load_manifest(path: &Path) -> Result<DuckdbManifest, LoadError> {
    let text = std::fs::read_to_string(path)?;
    let root: serde_json::Value = serde_json::from_str(&text)?;
    let export_dir = PathBuf::from(
        root.get("export_dir")
            .and_then(|v| v.as_str())
            .unwrap_or(""),
    );
    let mut tables = HashMap::new();
    if let Some(obj) = root.get("tables").and_then(|v| v.as_object()) {
        for (tname, tval) in obj {
            let row_count = tval
                .get("row_count")
                .and_then(|v| v.as_u64())
                .unwrap_or(0) as usize;
            let mut columns = HashMap::new();
            if let Some(cols) = tval.get("columns").and_then(|v| v.as_object()) {
                for (cname, cval) in cols {
                    let dtype = cval
                        .get("dtype")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string();
                    let path = PathBuf::from(
                        cval.get("path")
                            .and_then(|v| v.as_str())
                            .unwrap_or(""),
                    );
                    let length = cval
                        .get("length")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0) as usize;
                    columns.insert(
                        cname.to_uppercase(),
                        ColumnMeta {
                            dtype,
                            path,
                            length,
                        },
                    );
                }
            }
            tables.insert(
                tname.clone(),
                TableMeta {
                    row_count,
                    columns,
                },
            );
        }
    }
    Ok(DuckdbManifest {
        version: root.get("version").and_then(|v| v.as_u64()).unwrap_or(1) as u32,
        db_path: root
            .get("db_path")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        export_dir,
        tables,
    })
}

pub fn load_cols_from_duckdb_export(
    manifest_path: &Path,
    table: &str,
    column: &str,
) -> Result<Vec<u64>, LoadError> {
    let manifest = load_manifest(manifest_path)?;
    let table_key = manifest
        .tables
        .keys()
        .find(|k| k.eq_ignore_ascii_case(table))
        .cloned()
        .ok_or_else(|| LoadError::Format(format!("table not in manifest: {table}")))?;
    let tmeta = &manifest.tables[&table_key];
    let col_key = tmeta
        .columns
        .keys()
        .find(|k| k.eq_ignore_ascii_case(column))
        .cloned()
        .ok_or_else(|| LoadError::Format(format!("column not in manifest: {column}")))?;
    let cmeta = &tmeta.columns[&col_key];
    match cmeta.dtype.as_str() {
        "u32" => {
            let v = read_fixed_column(&cmeta.path, 0, le_u32)?;
            Ok(v.into_iter().map(|x| x as u64).collect())
        }
        "u64" => read_fixed_column(&cmeta.path, 1, le_u64),
        "i64" => {
            let v = read_fixed_column(&cmeta.path, 2, le_i64)?;
            Ok(v.into_iter().map(|x| x as u64).collect())
        }
        "f64" => {
            let v = read_fixed_column(&cmeta.path, 3, le_f64)?;
            Ok(v.into_iter().map(|x| x.to_bits()).collect())
        }
        "bool" => {
            let v = read_fixed_column(&cmeta.path, 4, le_bool)?;
            Ok(v.into_iter().map(|x| if x { 1 } else { 0 }).collect())
        }
        other => Err(LoadError::Format(format!(
            "load_cols_from_duckdb_export supports numeric cols; got {other}"
        ))),
    }
}

pub fn load_u32_column(manifest: &DuckdbManifest, table: &str, column: &str) -> Result<Vec<u32>, LoadError> {
    let tmeta = manifest
        .tables
        .get(table)
        .ok_or_else(|| LoadError::Format(format!("table not found: {table}")))?;
    let cmeta = tmeta
        .columns
        .get(&column.to_uppercase())
        .ok_or_else(|| LoadError::Format(format!("column not found: {column}")))?;
    read_fixed_column(&cmeta.path, 0, le_u32)
}

pub fn load_u64_column(manifest: &DuckdbManifest, table: &str, column: &str) -> Result<Vec<u64>, LoadError> {
    let tmeta = manifest
        .tables
        .get(table)
        .ok_or_else(|| LoadError::Format(format!("table not found: {table}")))?;
    let cmeta = tmeta
        .columns
        .get(&column.to_uppercase())
        .ok_or_else(|| LoadError::Format(format!("column not found: {column}")))?;
    read_fixed_column(&cmeta.path, 1, le_u64)
}

/// Wrapping checksum for quick load-path smoke tests.
pub fn checksum_u64(data: &[u64]) -> u64 {
    data.iter().fold(0u64, |acc, &x| acc.wrapping_add(x))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn checksum_empty() {
        assert_eq!(checksum_u64(&[]), 0);
    }
}
