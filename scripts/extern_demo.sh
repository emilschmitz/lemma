#!/usr/bin/env bash
# Early native-extern Dafny→Rust micro-benchmark (SSB Q1-shaped, synthetic rows).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKDIR="$ROOT/scratch/extern_demo"
DFY="$WORKDIR/query1_extern.dfy"

mkdir -p "$WORKDIR"
cp "$ROOT/research_loop/examples/dafny/query1_extern.dfy" "$DFY"

echo "=== 1. Bounded native spec (from research_loop/examples/dafny/) ==="
echo "=== 2. Translating Dafny to Rust ==="
rm -rf "$WORKDIR/query1_extern-rust"
(
  cd "$WORKDIR"
  dafny translate rs --enforce-determinism query1_extern.dfy

  echo "=== 3. Injecting benchmark harness ==="
  mkdir -p query1_extern-rust/src

  if [ -f "query1_extern.rs" ]; then
    mv query1_extern.rs query1_extern-rust/src/
  elif [ -f "query1_extern-rust/query1_extern.rs" ]; then
    mv query1_extern-rust/query1_extern.rs query1_extern-rust/src/
  fi

  cat << 'CARGO' > query1_extern-rust/Cargo.toml
[package]
name = "query1_benchmark"
version = "0.1.0"
edition = "2021"

[dependencies]
dafny_runtime = "*"
CARGO

  cat << 'HARNESS' > query1_extern-rust/src/main.rs
mod query1_extern;

fn main() {
    println!("Allocating 10,000,000 rows into sequence...");
    let mut mock_data = Vec::with_capacity(10_000_000);
    for _ in 0..10_000_000 {
        mock_data.push(query1_extern::_module::Row::Row {
            lo_orderdate: 19930615,
            lo_discount: 2,
            lo_quantity: 20,
            lo_extendedprice: 1000,
        });
    }

    let dafny_seq = dafny_runtime::Sequence::from_array_owned(mock_data);

    let start = std::time::Instant::now();
    let res = query1_extern::_module::RunQuery(&dafny_seq);
    let elapsed = start.elapsed().as_micros();

    println!("----------------------------------------");
    println!("QUERY_LATENCY_US: {} μs", elapsed);
    println!("Calculated Revenue: {}", res);
    println!("----------------------------------------");
}
HARNESS

  echo "=== 4. Compiling and benchmarking ==="
  cd query1_extern-rust
  cargo run --release
)
