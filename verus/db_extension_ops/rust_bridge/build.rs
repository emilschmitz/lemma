//! Link lemma_ops batch runner against prebuilt libduckdb.so.

use std::env;
use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let repo = manifest_dir.join("../../..");
    let duck_dir = env::var("LEMMA_DUCKDB_LIB_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| repo.join("build/libduckdb"));

    let ops_cpp = manifest_dir.join("../src/lemma_ops.cpp");
    let ops_inc = manifest_dir.join("../src");

    println!("cargo:rerun-if-changed={}", ops_cpp.display());
    println!("cargo:rerun-if-changed={}", ops_inc.join("lemma_ops.h").display());
    println!("cargo:rerun-if-env-changed=LEMMA_DUCKDB_LIB_DIR");

    let duck_h = duck_dir.join("duckdb.h");
    let duck_so = duck_dir.join("libduckdb.so");
    if !duck_h.is_file() || !duck_so.is_file() {
        println!(
            "cargo:warning=prebuilt libduckdb missing at {}",
            duck_dir.display()
        );
        return;
    }

    // Compile ops runner only (extension entrypoint symbols are weak/unused in the binary).
    cc::Build::new()
        .cpp(true)
        .std("c++17")
        .file(&ops_cpp)
        .include(&ops_inc)
        .include(&duck_dir)
        .define("LEMMA_OPS_FFI_BUILD", None)
        .compile("lemma_ops_ffi");

    println!("cargo:rustc-link-search=native={}", duck_dir.display());
    println!("cargo:rustc-link-lib=dylib=duckdb");
    println!("cargo:rustc-link-arg=-Wl,-rpath,{}", duck_dir.display());
}
