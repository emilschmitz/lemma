//! Link `lemma_pin_ffi` against **prebuilt** `build/libduckdb/libduckdb.so`.
//! Never compile DuckDB from source here (that OOMs small WSL boxes).

use std::env;
use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let repo = manifest_dir.join("../../..");
    let duck_dir = env::var("LEMMA_DUCKDB_LIB_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| repo.join("build/libduckdb"));

    let pin_cpp = manifest_dir.join("../../db_extension/src/lemma_pin.cpp");
    let stream_cpp = manifest_dir.join("../../db_extension/src/lemma_stream.cpp");
    let pin_inc = manifest_dir.join("../../db_extension/src");

    println!("cargo:rerun-if-changed={}", pin_cpp.display());
    println!("cargo:rerun-if-changed={}", stream_cpp.display());
    println!("cargo:rerun-if-changed={}", pin_inc.join("lemma_pin.h").display());
    println!("cargo:rerun-if-changed={}", pin_inc.join("lemma_stream.h").display());
    println!("cargo:rerun-if-env-changed=LEMMA_DUCKDB_LIB_DIR");

    if !cfg!(feature = "duckdb_pin") {
        return;
    }

    let duck_h = duck_dir.join("duckdb.h");
    let duck_so = duck_dir.join("libduckdb.so");
    if !duck_h.is_file() || !duck_so.is_file() {
        println!(
            "cargo:warning=duckdb_pin enabled but prebuilt lib missing at {}; \
             download libduckdb-linux-amd64.zip into build/libduckdb/",
            duck_dir.display()
        );
        return;
    }

    cc::Build::new()
        .cpp(true)
        .std("c++17")
        .file(&pin_cpp)
        .file(&stream_cpp)
        .include(&pin_inc)
        .include(&duck_dir)
        .define("LEMMA_PIN_FFI_BUILD", None)
        .compile("lemma_pin_ffi");

    println!("cargo:rustc-link-search=native={}", duck_dir.display());
    println!("cargo:rustc-link-lib=dylib=duckdb");
    // Runtime path so the smoke binary finds libduckdb.so without LD_LIBRARY_PATH.
    println!("cargo:rustc-link-arg=-Wl,-rpath,{}", duck_dir.display());
}
