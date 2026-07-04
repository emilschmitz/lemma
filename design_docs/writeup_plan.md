# Lemma — Plans & Design Journey

## Completed Design Journey: High-Speed Verified Compilation

We encountered two major bottlenecks trying to match DuckDB's baseline performance inside Dafny's compiled Rust output:

1. **The Bit-Blasting Timeout (Pure Bitvectors)**:
   * Doing arithmetic directly on bitvectors (`bv64`) forces Z3 to bit-blast multiplication into Boolean circuits, resulting in solver timeouts.
2. **The BigInt Overhead (Pure Integers)**:
   * Using mathematical integers (`int`) makes verification instant, but Dafny compiles them to heap-allocated, reference-counted `DafnyInt` (`BigInt` under `Rc`). This makes loop counter increments, indexing, and additions 500x slower.

### The Solution: The Two-Stage Verification/Compilation Pass & Vector Unwrapping

To solve this, we implemented a custom two-stage pipeline:

1. **Dafny Verification (Mathematical `int`)**:
   * We verify loop logic and safety invariants in Dafny using mathematical `int` (which verifies instantly in under 1.5 seconds).
   * We add a 64-bit precondition (`requires MethodSpec(data) < 2^64`) to guarantee no overflow can ever occur during intermediate calculation.
2. **Native Rust Post-Processing Compiler Pass (`harness.py`)**:
   * Right after Dafny translates the code to Rust but before Cargo compiles it, the harness runs a Python-based post-processor (`optimize_rust_file`) to replace the `DafnyInt` variables and functions inside `RunQuery` with primitive Rust types:
     * `DafnyInt` -> `u64` (accumulator, values)
     * Loop counter `i`, `len` -> `usize`
     * `data.get(&i)` -> `data.get_usize(i)` (direct vector lookup)
     * `int!(...)` -> native Rust typecasts
   * **Columnar Vector Unwrapping (New)**: For columnar queries, the post-processor parses the parameter list and automatically extracts direct references to the inner Rust `Vec` storage from Dafny's `Sequence` wrappers using `.to_array()` at the start of the query function:
     * `let col_vec = COL.to_array();`
     * `COL.get_usize(i)` -> `col_vec[i]`
     This completely eliminates boundary check and lookup indirection inside the query scan loop.

### Performance Results (50,000 rows, Query 1, Real SSB Dataset)
* **DuckDB (Baseline)**: **`1.50 ms`**
* **Dafny (Row-Oriented Loop)**: **`2.18 ms`**
* **Dafny (Columnar Sequence Scan)**: **`0.27 ms`**
* **Dafny (Columnar + Vector Unwrapping)**: **`0.09 ms`** (95 microseconds — **15.8x FASTER than DuckDB!**)

---

## Outstanding Tasks

> [!NOTE]
> DO NOT IMPLEMENT BY YOUR OWN INITIATIVE. THE HUMAN WILL ASK YOU TO IMPLEMENT THESE THINGS WHEN THE TIME HAS COME.

* **Plot execution curves across optimization runs**:
  * Plot latency vs. the number of optimizer tries/runs.
  * Add the aggregate number of input/output tokens or dollar cost to the same plot.
  * Decide how to aggregate across runs and datasets (e.g. show plots from example runs or average them).
* **Verify GenDB backup support**:
  * Integrate the verification strategies from GenDB as a backup if it does not introduce too much overhead.
* **SSB Flat queries consistency**:
  * Double-check if the SSB Flat dataset uses the same query across different datasets, and see if that affects our orchestrator's design.
