//! Link lemma_storage against prebuilt libduckdb.so + duckdb.hpp (ABI-matched).

use std::env;
use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let repo = manifest_dir.join("../../..");
    let duck_dir = env::var("LEMMA_DUCKDB_LIB_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| repo.join("build/libduckdb"));

    let storage_cpp = manifest_dir.join("../src/lemma_storage.cpp");
    let storage_inc = manifest_dir.join("../src");

    println!("cargo:rerun-if-changed={}", storage_cpp.display());
    println!("cargo:rerun-if-changed={}", storage_inc.join("lemma_storage.h").display());
    println!("cargo:rerun-if-changed={}", storage_inc.join("lemma_storage_internal.hpp").display());
    println!("cargo:rerun-if-env-changed=LEMMA_DUCKDB_LIB_DIR");

    let duck_hpp = duck_dir.join("duckdb.hpp");
    let duck_so = duck_dir.join("libduckdb.so");
    if !duck_hpp.is_file() || !duck_so.is_file() {
        println!(
            "cargo:warning=prebuilt libduckdb missing at {}",
            duck_dir.display()
        );
        return;
    }

    cc::Build::new()
        .cpp(true)
        .std("c++17")
        .flag("-D_GLIBCXX_USE_CXX11_ABI=0")
        .file(&storage_cpp)
        .include(&storage_inc)
        .include(&duck_dir)
        .compile("lemma_storage_ffi");

    println!("cargo:rustc-link-search=native={}", duck_dir.display());
    println!("cargo:rustc-link-lib=static=lemma_storage_ffi");
    println!("cargo:rustc-link-lib=dylib=duckdb");
    println!("cargo:rustc-link-arg=-Wl,-rpath,{}", duck_dir.display());
    println!("cargo:rustc-link-lib=dylib=stdc++");
    println!("cargo:rustc-link-lib=dylib=pthread");
    println!("cargo:rustc-link-lib=dylib=dl");
}
