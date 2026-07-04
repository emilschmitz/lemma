# Lemma pipeline: verification, translation, and performance

This document describes the full path from SQL to fast native Rust: what is formally
proved, what is trusted engineering, and how to write Dafny the agent should emit.

**Audience:** the optimization agent (read-only context). The agent edits only the
`RunQuery` **body** in `agent_workspace/runquery_agent.dfy`; the host injects signature
and `ensures` via `assemble_runquery.py`.

See also: `research_loop/PIPELINE_IMPROVEMENTS.md` (threat model), `native.dfy` (extern
contracts), `postprocessor.py` (Rust peepholes), `admit_runquery.py` (NativeAggMap lint).

---

## End-to-end pipeline

```
SQL  →  transpiler (MethodSpec)  →  agent RunQuery body
         ↓
assemble_runquery (trusted ensures)  →  admit_runquery (lint)
         ↓
dafny verify (Z3)  →  dafny translate rs  →  postprocessor.py (regex)  →  cargo build
```

| Step | Formal guarantee? |
|:---|:---|
| SQL → `MethodSpec` | **Trusted** transpiler + Python reference tests (`transpiler/tests/`) |
| `MethodSpec` body | **`{:verify false}`** — not independently verified by Dafny |
| `RunQuery` vs `MethodSpec` | **Proved** by `dafny verify` (for admitted agent code) |
| `{:extern}` Rust (`native_ops.rs`, `native_agg.rs`, `cols_native.rs`) | **Assumed** — Dafny trusts `ensures` on externs, does not check Rust |
| `postprocessor.py` rewrites | **Not proved** — pattern-matched peepholes + unit tests |
| Final binary vs DuckDB SQL | **Empirical** — not in CI today; benchmarked manually |

**What “verification passed” means:** `dafny verify` exit code 0 — i.e. the agent’s
`RunQuery` satisfies `ensures res == MethodSpec(cols)` in **Dafny semantics**, using
`MethodSpec` as an **unverified definition**. It does **not** mean SQL ≡ result, or
that post-processed Rust is refinement-correct.

---

## What Dafny actually verifies

On a typical columnar query, Dafny reports proof obligations including:

- `RunQuery` (well-formedness)
- `RunQuery` (correctness) — the meaningful one
- Well-formedness of `NativeU64`, extern ops, `ValidCols`, etc.

It does **not** verify `MethodSpec` / `MethodSpecHelper` (marked `{:verify false}`).
Z3 still **unfolds** those definitions when proving `ensures res == MethodSpec(cols)`.

If you sabotage `MethodSpec` to return a constant, a correct `RunQuery` **fails** to
verify. The gap is **SQL ≡ MethodSpec**, not agent vs spec.

---

## Stage 1 — Write Dafny for fast verification and fast codegen

### Use native extern types (primary speed path)

Defined in `research_loop/native.dfy`. Prefer these in `RunQuery` — **do not** rely on
postprocessor to rewrite `DafnyInt` → `u64` (legacy path removed).

| Dafny | Rust (via `{:extern}`) | Role |
|:---|:---|:---|
| `NativeU32` | `u32` | Column values, small keys |
| `NativeU64` | `u64` | Sums, extended price |
| `NativeI64` | `i64` | Signed aggregates (e.g. revenue − supplycost) |
| `AddU64`, `MulU64U32`, `AddI64`, `SubU64ToI64` | `native_ops.rs` | Arithmetic with math `ensures` |
| `Cols` / `ColsNative` | `cols_native.rs` (schema-specific) | Columnar scan |
| `NativeAggMap` | `native_agg.rs` | Group-by hash map |

```dafny
// Good: native ops — verifies fast, codegen emits u64 calls
res := AddU64(res, MulU64U32(ep as NativeU64, disc));
```

```dafny
// Bad: plain int accumulator — slow BigInt runtime (no postprocess fix)
var res: int := 0;
res := res + (ep as int) * (disc as int);
```

```dafny
// Bad: bv64 in hot loop — Z3 bit-blasting, verification timeouts
var res: bv64 := 0;
```

**Trust gap on externs:** Dafny proves your program **if** `AddU64` etc. satisfy their
`ensures`. Rust uses `wrapping_*`; sound when Z3 proves results stay in range. The link
“Rust implements `ensures`” is **not** machine-checked (same class of trust as Dafny’s
own Rust backend for `DafnyInt`).

### Columnar loop shape (matches postprocessor patterns)

```dafny
method RunQuery(cols: Cols) returns (res: NativeU64)
  ensures res == MethodSpec(cols)
{
  res := 0 as NativeU64;
  var i := cols.n();
  while i > 0
    invariant 0 <= i <= cols.n()
    invariant res as int == MethodSpecHelper(cols, i) as int
  {
    i := i - 1;
    var od := cols.GetLO_ORDERDATE(i);
    // filters via EqAt* for string columns, AddU64/MulU64U32 for terms
  }
}
```

- **Backward** loop from `cols.n()` down to `0`.
- String filters: `cols.EqAtP_CATEGORY(i, "MFGR#12")` not `Get… == "…"` when possible.
- Group-by: `var agg := new NativeAggMap();` with ghost map invariant tying
  `agg.Snapshot()` to `MethodSpecHelper` (see `benchmark_runqueries.py`).

### NativeAggMap rules (admission lint)

Before verify, `admit_runquery.py` enforces **linear** use of `NativeAggMap`:

- Exactly one `new NativeAggMap()`
- No aliases (`var alias := agg`), no passing `agg` to helpers, no storing in tuples/arrays

Violations → harness rejects **before** verify. This is required because postprocessor
may rewrite `Object<NativeAggMap>` to a stack `NativeAggMap` (see `poc_alias/q.dfy`).

### Agent must not

- Add `method`, `function`, `lemma`, `{:verify false}`, `assume`, `axiom` in body
- Change `requires` / `ensures` (host injects those)

---

## Stage 2 — `dafny translate rs`

Emits Rust under `working_query-rust/` using `dafny_runtime` plus:

- `cols_native.rs` — generated per schema (`generate_cols_native_rs`)
- `native_ops.rs`, `native_agg.rs` — copied from `research_loop/native_bridge/src/`

Default codegen uses `Object<ColsNative>`, `rd!(cols)`, `DafnyInt` loop indices,
`Sequence<DafnyChar>` for strings — correct but slow. Native types already map to
`u64` / direct calls at this stage; postprocessor removes remaining runtime overhead.

**Dafny does not formally verify** that translation preserves semantics (faithful
runtime + tests, not a certified compiler).

---

## Stage 3 — Postprocessor (`research_loop/postprocessor.py`)

Invoked from `harness.py` → `optimize_rust_file()` → `postprocess()`.

**Mechanism:** regex on generated `RunQuery` in `working_query.rs` (not tree-sitter).
Rewrites apply only when output **matches a pattern**; non-matching code stays slow but
unchanged.

| Rewrite | What | Why faster | Safety / trust |
|:---|:---|:---|:---|
| `cols_ref = rd!(cols)` | Hoist one read borrow | Avoid repeated `Object` derefs | Safe if `cols` is read-only in loop (normal for `RunQuery`) |
| `DafnyInt` → `usize` loop | `i -= 1` not `clone() - int!(1)` | Native loop counter | Only matched backward-loop shape; math `int` ≡ `usize` on `0..n` |
| `GetCOL(&i)` → `GetCOL_usize(i)` | Direct `Vec` index | No `DafnyInt` per read | Relies on Dafny proof that `i` in range |
| `EqAt…(…, string_of("lit"))` → `EqAt…_usize(i, "lit")` | `&str` compare | Skip `Sequence` alloc | UTF-8 string data assumption |
| Stack `NativeAggMap` | Drop `Object` wrapper | Direct `HashMap` updates | **Requires** `admit_runquery` (no aliasing) |
| `Add` → `AddStrKey` | `&str` group keys | Skip Dafny string wrappers | Matched codegen shapes only |
| Strip `MaybePlacebo` | Direct `return` | Less clone/wrapper | Narrow return pattern |

**Not done anymore (do not document / expect):** blanket `DafnyInt` → `u64` for all
locals, row-oriented `seq<Row>` unwrap, `HashMap` replacement for Dafny `Map` in general.

`inject_hot_loop_main()` adds benchmark `main` that loads `.tbl` → `ColsNative`.

Slow path: `postprocess(..., allow_fast_native_agg=False)` skips agg rewrites.

---

## Trust model (short)

Lemma optimizes the **spec → code translation layer** without closing the refinement
proofs Dafny would need to ship the same opts as defaults:

1. **Verified:** `RunQuery` implements transpiled `MethodSpec` (Dafny/Z3).
2. **Trusted:** SQL transpiler, `{:verify false}` spec, `{:extern}` Rust implementations.
3. **Trusted:** post-verify regex peepholes + admission lint + tests.

This is the same *kind* of gap Dafny’s Rust backend already has (verify Dafny, trust
codegen); we add **more** unproved translation optimizations for speed.

---

## Performance (Q1, 50k rows — indicative)

From `writeup_plan.md` on SSB flat data:

| Stage | Latency |
|:---|---:|
| DuckDB | ~1.5 ms |
| Dafny row-oriented / default runtime | ~2.2 ms (slower) |
| Columnar `ColsNative` + native extern types | ~0.27 ms |
| + postprocessor peepholes | **~0.09 ms** |

Native extern types are the large step; postprocessor is ~3× on top of columnar.
Pure `int` / `DafnyInt` loops are ~500× slower on loop ops than machine words.

---

## File map

| File | Role |
|:---|:---|
| `transpiler/` | SQL → `MethodSpec` + skeleton (`{:verify false}`) |
| `assemble_runquery.py` | Trusted `ensures`, body validation |
| `admit_runquery.py` | NativeAggMap linearity lint |
| `harness.py` | Orchestration, `dafny verify`, calls postprocessor |
| `postprocessor.py` | Rust peepholes (regex) |
| `native.dfy` | Extern type contracts |
| `native_bridge/src/` | Rust implementations |
| `benchmark_runqueries.py` | Hand-written fast `RunQuery` examples |
| `test_postprocessor.py` | Semantic equivalence tests (legacy + agg hazards) |
| `test_admit_runquery.py` | Admission / adversarial patterns |

---

## Writing checklist for the agent

1. Read `MethodSpec` / `MethodSpecHelper` in `spec.dfy` — ground truth for filters and terms.
2. Use `NativeU64` / `NativeI64` + `AddU64` / `MulU64U32` / `SubU64ToI64` for arithmetic.
3. Backward loop `i := cols.n(); while i > 0 { i := i - 1; ... }`.
4. Invariant: `res as int == MethodSpecHelper(cols, i) as int` (scalar) or agg ghost map (group-by).
5. One `new NativeAggMap()`, no aliases, no passing agg anywhere.
6. String filters via `EqAtCOLUMN(i, "literal")`.
7. Do not use `bv64` accumulators or plain `int` hot loops.
