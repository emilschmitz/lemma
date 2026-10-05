# Trusted return-type families

Lemma admits agent `run_query` implementations only against a **fixed menu** of
Trusted return-type families. Each family maps a normalized Verus MethodSpec
return type `T` to exec-shaped Rust (`u64`/`i64`, `HashMap<…>`, `Vec<…>`) plus
optional TRUSTED view/agg helpers.

**Reviewability:** Trusteds should stay **conceptually few** and **grouped** (views,
agg accumulate, distinct-set, one-row `agg_step`, HAVING filter) so a human can
audit them. Suffixes encode key/value shape; they are not separate Trusted
ideas. Prefer fixing MethodSpec/docs over inventing another opaque helper.

### Expert card (what you are asked to accept)

Three menus. None uses empty `assume_*`. None is a whole-query Trusted.

**A — product path (always on; `r23rocket`):** an expert can treat these like
Rust/`vstd` facts.

| Family | One sentence |
|--------|----------------|
| Loader `load_cols_*` | I/O established `valid_cols` (Layer A data boundary, not arithmetic). |
| `checked_add` / `add_u64` + fit lemmas | Under named caps, this add does not overflow / matches wrap as specified. |
| vstd `HashMap` / `HashSet` / `StringHashMap` `@` | Exec container view is the spec map/set. |
| `agg_new_*` / `agg_add_*` / `agg_step_*` | One-row accumulate; inner view stays `≡` the MethodSpec helper. |
| HAVING peel | `res@ == apply_having_filter(...)` (peel private; no `ensures true`). |
| Proved `lemma_*` rem / fold-slot bounds | Induction from catalog caps. **Not** empty `assume_*`. |

**B — speed menu (`LEMMA_FAST_TRUSTEDS=1`; `r23fast`):** still local IF–THEN.
`run_query ≡ method_spec` is still proved. Extra Trusteds:

| Helper | One sentence | Honest skip |
|--------|----------------|-------------|
| `build_hashset_u32` | `s@` is the set of keys in the vec. | None. |
| `probe_sum_u64` | Sum is the wrapping fold over hash hits (`probe_sum_u64_spec`). | `external_body` (body is that fold). |
| `par_probe_sum_u64` | Same wrapping spec as `probe_sum_u64` (`probe_sum_u64_spec`). | **We are not proving the parallel implementation** (std threads). |
| `par_sum_u64` / `par_filter_sum_u64` | Result equals the **serial** wrapping spec. | **We are not proving the parallel implementation** (std threads). |
| `vector_filter_sum_u64` | Wrapping sum of amounts where date in `[lo, hi]`. | **We are not proving the parallel implementation** (std threads). |
| `may_satisfy_range_u32` | `b == (seg.max >= lo && seg.min <= hi)`. | None. |
| `decode_dict_str` | `s == dict[code]` when code in range. | None. |
| `build_zone_map_u32` | Zones non-empty only if `zone_rows > 0`. | **Weak** — not per-segment min/max. Do not sell as rocketship. |

**C — mid menu (`LEMMA_ENABLE_VECTOR_SCAN=1` + `LEMMA_ENABLE_SPILL_HASH=1` on top of B;
`r26mid`):** same proof bar — `run_query ≡ method_spec`. Extra build features unlock
Trusteds agents may call; SIMD/spill **schedule** is not proved, result ≡ serial
wrapping spec:

| Helper | One sentence | Honest skip |
|--------|----------------|-------------|
| `vector_filter_sum_u64` | Wrapping sum of amounts where date in `[lo, hi]`. | **We are not proving the SIMD/vector scan schedule** (feature `vector_scan`). |
| `build_hashset_u32_spill` | `s@` is the set of keys (spills when estimate > threshold). | **We are not proving spill I/O schedule** (feature `spill_hash`). |

**Not on any menu:** `ensures true`, whole-query EXISTS Trusted, empty
`assume_*_slot*`, `LEMMA_FOLD_SLOT_ASSUME_ALIAS`.

**Live `r23sloppy` (`EMIT=1` on `b5c838e`):** same as A **plus** hashset (good)
and **probe/zone with the older loose ensures** (`sum <= n·MAX`). That probe
bound is **not** the expert card. `r23fast` is the named speed menu.

### Rocketship bar (NASA / Rust-evident)

A product-path Trusted may stay only if a careful Rust/systems reviewer would
**commit it to high-assurance code** after reading `requires`/`ensures` and a
short body — **same kind of acceptance as “two ints summing under `u64::MAX`
do not overflow,”** or “I know how this Rust container behaves.”

Must hold **all** of:

1. **One idea** — one sentence names the operation.
2. **Ensures ≡ body under a named precondition** — no silent gap (math `+` vs
   wrap; no “owned map will stay in bounds” as a substitute for fit-in-width
   `requires` on accumulate).
3. **Local** — not a whole-query / whole-join / “subquery answer” Trusted.
4. **Rust-evident** — no Lemma folklore; no Lemma-authored `arbitrary()` view
   bodies. Prefer Verus vstd container Trusteds (`HashMapWithView` /
   `HashSetWithView` / `StringHashMap`) whose insert/new match Rust maps/sets.
   **Bound caps:** rocketship base = SQL type width + checked ops + vstd `@`.
   Tighter `u64` cell caps (`LEMMA_MAX_CELL_U64`) and row-depth caps appear only
   when the transpiler caller supplies external ``CatalogAssumptions`` /
   ``TableAssumptions`` (prove_loop uses ``research_loop/sec_table_assumptions.py``
   explicitly). Product arithmetic lemmas (`lemma_*_cell_u64_*`, `lemma_rem_cap_*`)
   are checkable from those named caps; **rem geometry**
   (`lemma_join_nested_rem_*`, `lemma_fold_suffix_rem_*`) is **proved** (Phase 1).
   **Fold slot/count/sum bounds** default to inductive proved ``lemma_*`` bodies
   under catalog; honest empty ``assume_*`` only with
   ``LEMMA_FOLD_SLOT_AXIOMATIC=1``. Migration alias ``assume_*`` → ``lemma_*``
   is ``LEMMA_FOLD_SLOT_ASSUME_ALIAS=1`` (off by default).

**Proved equijoin** (`research_loop/verus_lib/eq_join.rs`, spliced into join queries only): the bucket for a key is the increasing row ids where that column equals the key, and `equijoin_pairs_*` / `star_eq_triples_str` equal that nested match list. `loop_acc` is the same nested loop as an arbitrary step, and `lemma_acc` proves it equals a backward fold of that pair list. A two-table, one-equality helper also gets `lemma_<helper>_is_loop`, which proves the helper equals `loop_acc`. A two-table, two-equality helper gets `lemma_<helper>_is_loop2`: the helper equals `loop_acc2`, and `lemma_acc2` proves that equals a backward fold of `nested_eq_pairs2`. A three-table star gets `lemma_<helper>_is_star`: the helper equals `loop_acc3`, and `lemma_star_acc` proves that equals a backward fold of `nested_star`. The bodies are verified. The hash trust is menu A (`StringHashMap` and `std::collections::HashMap` `@`). This is not menu B (`build_hashset_u32` / `probe_sum_u64`) and not a whole-query Trusted: the agent still proves `run_query ≡ method_spec`.

### External assumptions vs Trusteds

::

    [External] CatalogAssumptions (user | engine defaults | sec_prove_loop profile)
        → resolve_bounds → LEMMA_MAX_* + valid_cols
    [Trusteds] IF valid_cols/caps THEN checked_add / lemma_* fold bounds
    [Agent]    calls proved lemma_* fold / rem / fit helpers under those caps

Engine defaults are applied at transpile/assemble boundaries via
``with_catalog_assumptions(..., defaults=engine_default_catalog_assumptions())`` —
not baked into Trusted bodies.

**Default / SEC profiles (plain language).** Engine defaults: ≤65 536 rows/table,
INT32-ish &lt; 2³¹, strings ≤128 chars; BIGINT uncapped. SEC/prove_loop keeps the
**same row/string/native caps** and adds BIGINT/money cells &lt; 2³¹ (~2.1 billion),
plus smaller row caps for 3-/4-table joins (≤2047 / ≤256) so rem·cell fits in
``u64``. A “sum under a trillion” cell story is too loose at 64k-row join scale;
“under ~two billion per cell” is the simple sound bound. See
``research_loop/sec_table_assumptions.py``
(``sec_prove_loop_assumption_summary()``).
5. **Tested** — semantic differential (or equivalent), including precondition
   boundaries.

**Out (must go):** opaque Lemma `hashmap_*_view` / `hashset_*_view` /
`agg_step_inner_*_view` with `arbitrary()`; owned-map overflow handwaves;
empty-body fold axioms that smuggle MethodSpec shape; whole-query Trusteds.

### Say “not proving” when we are not proving

Do **not** paper over a missing proof with “weak contract”, “opt-in primitive”,
“fast path”, “stand-in”, or “alias”. Name the skip.

| What we did | What to say | Still a `run_query ≡ method_spec` proof? |
|-------------|-------------|----------------------------------------|
| Empty `assume_*_slot*` (`LEMMA_FOLD_SLOT_AXIOMATIC=1`) | **Axiom, not a proof** of that COUNT/SUM ≤ rem·cap bound. Verus is told the inequality. | The body may still be proved *using* that axiom. We did **not** prove the bound. |
| `ensures true` on a helper, whole-query Trusted, Trusted `run_query`, or `external_body` that claims the query result | **We are not proving this implementation.** | No. That is skipping the implementation proof. |
| `par_*` Verus extern (`external_body` + std-thread exec; rayon in the holdout crate) | **We are not proving the parallel implementation.** We trust `result == serial_wrapping_spec(...)`. Product path uses `std::thread`; holdout crate uses rayon. | Proving a call to `par_sum_u64` does not prove threads or rayon. |
| `LEMMA_FAST_TRUSTEDS=1` speed menu (hashset / probe / zone / `par_*`) | **Trust result ≡ a named serial spec** (wrapping fold / set membership). Local, one idea, IF–THEN. Does **not** enable empty `assume_*` or `LEMMA_FOLD_SLOT_AXIOMATIC`. | Yes — `run_query ≡ method_spec` using these helpers under the named specs. |

**Why `LEMMA_ENABLE_PARALLEL` alone is off on rocketship:** not because rayon lost a
bake-off. Because turning it on without the speed Trusted menu still requires opting
into core primitives separately. Prefer **`LEMMA_FAST_TRUSTEDS=1`** as the one flag for
“speed Trusteds, still proving `run_query ≡ method_spec` using these helpers.” Turning
on parallel without FAST_TRUSTEDS would either (a) still execute the serial stub in the
assembled binary (no speed), or (b) swap in an unproved rayon body behind `external_body`.
That is skip-impl-proof unless the Verus contract names the serial wrapping spec.

Query-level `LEMMA_PARALLEL` (many `run_optimizer` workers) is process parallelism and
does not change the proof bar.

**Empty assume ≠ skip the whole query.** It skips **one bound lemma**. Do not
call that “rocketship.” Do not rename `assume_*` to `lemma_*` without a proof
(`LEMMA_FOLD_SLOT_ASSUME_ALIAS` is a workaround — leave it off).

**HAVING map peel:** vstd `HashMapWithView` / `StringHashMap` peel is **private** inside
`apply_having_filter_exec_*` only (`having_map_peel.rs.inc` layout structs + inline
transmute). One Trusted per query with real `res@ == apply_having_filter(hm@, …)`;
no standalone unwrap/wrap helpers with `ensures true`.

**Loader (Layer A):** `load_cols_*` exec that establishes `valid_cols` is an
**external data boundary** (I/O → columnar invariants), not an arithmetic Trusted.
Keep it; do not invent a proof — document and audit as named assumption surface.

**Agent primitives (opt-in):** `emit_agent_externs()` is **not** on the default product
assemble path. Set `LEMMA_EMIT_AGENT_PRIMITIVES=1` for core helpers only, or
`LEMMA_FAST_TRUSTEDS=1` for core + parallel with result ≡ serial wrapping specs (or
reference symbols in `run_query`) from `agent_primitives/`.

**String dialect:** LIKE / ILIKE / `str_lower` / `str_upper` = **ASCII /
DuckDB-like** only (`to_ascii_lowercase`, open `%`/`_` specs). Non-ASCII
codepoints pass through unchanged in lower/upper.

Inventory: `docs/RESEARCH_NOTES.md`. Gate: keep looping agent-prove on fresh
draws until **≥98%** `VERIFY True` under this surface (`AGENT_TIMEOUT_SEC`
target 600s / 10 min; stretch 15–20 min only when needed).

Registry: `research_loop/trusted_families.py` (`TRUSTED_FAMILY_MENU`).

**Nested `Map` return types are intentionally unsupported.** COUNT DISTINCT and
similar queries use flat projected `u64` or `Seq<…>` families instead of nested
maps. MethodSpec helper state may still use `Map<K, bool>` for distinct keys;
agents prove exec set updates via vstd `HashSetWithView` (or equivalent) whose
`@` is the membership model — not Lemma `hashset_*_view` + `arbitrary()`.

## Testing policy

For every family in `TRUSTED_FAMILY_MENU`:

1. `bridge_for_family` succeeds.
2. Scalars: `ensures res == method_spec(cols),` and empty `trusted_rs`.
3. Maps: `view_spec` is `None`; `ensures res@ == method_spec(cols),`; vstd
   `HashMapWithView` / `StringHashMap` helpers with `external_body` and
   `agg_new_` + (`agg_add_` or `agg_put_`). Seq-with-strings: `view_spec` set
   to named `vec_*_view` (open spec, not `arbitrary()`); `ensures` uses that
   view on `res@`; `trusted_rs` contains `seq_new_` / `seq_push_`.
4. `assert_menu_complete()` validates the full menu in CI.

Parametrized structural tests: `tests/test_trusted_families.py`.
Semantic differential (exec math vs oracle / DuckDB): `tests/test_trusted_semantic_differential.py`.

## f64 idealization (the ONLY trusted float code)

> **Floating-point rounding error is ACCEPTED** (Emil, 2026-10-04). Floats are modeled as exact real arithmetic. An
> adversary report that only shows rounding error (a last-bit difference, a near-tie flip in HAVING / ORDER BY,
> cancellation, absorption, underflow, the double 0.1 not being the real 1/10) is an **accepted float limitation**, not a
> hole. A soundness hole (a wrong body that verifies for a reason other than rounding) still counts. The proved
> error-bound and exact lemmas are archived, unused, in `declarative_spec/future_float_error_bounds/` (README there);
> the prover agent never sees them (`tests/test_future_float_archive_is_invisible.py`).

**Claim.** For finite `f64` values within the catalog magnitude caps (the loader rejects NaN and infinity and enforces
`MAG_CAP_<table>_<col>`; `valid_cols` carries both as conjuncts), the executable `+ - * /`, the integer-to-`f64` casts and
the comparisons `< <= > >= ==` behave as the real operations on `x as real`. A float aggregate is therefore an exact
fold over reals and its spec says `result == the real value`: there is no epsilon in any spec, ensures or proof.
**What is false about it:** `+ - * /` and casts above 2^53 round (relative error up to 2^-53 per operation), and `mul`/`div`
have no lower magnitude bound (underflow). Comparisons are exact in IEEE 754; only the link from vstd's uninterpreted
`lt_ensures`-style predicates to `as real` is trusted.

**Accuracy against DuckDB is empirical.** The measure step compares the binary's rows with DuckDB's within
`declarative_spec/bench.py::float_tolerance` (relative 1e-9 with a 1e-9 floor); that is the only epsilon left and it never
enters a spec. Last-bit differences and near-tie flips can occur (DuckDB's own `SUM(double)` is plain f64 and
nondeterministic under parallel execution).

**Companion hypothesis (an assumption in the spec, not a lemma).** Verus gives a float literal no value as a real, so every
float query's `run_query` carries `requires f64_literals_ok()`: each f64 literal of the query and `0.0` denote their decimal
value. Soundness items kept (the adversary's blocker): two literals that round to the same double make this hypothesis
contradictory (every body would verify), so the emitter refuses them naming both; a literal that rounds to 0 or infinity, or
has so many digits that it overflows, is refused cleanly (`DeclarativeUnsupported`, no crash).

**Operand and result caps.** Operands are `f64_within(x, cap)` (finite and `|x| < cap`, the catalog cap); every operation also
requires its result bound at most `f64_safe_bound()` = 2^200, far below the f64 overflow bound, so no operation overflows.

**The trusted items: 11, each labeled `TRUSTED (f64 idealization)` in the source.** Each of add/sub/mul/div is called
BEFORE the operation and ensures both that the operation is defined (`add_req` etc.) and that whatever it returns is the
real operation of its operands; `add_within`/`sub_within`/`mul_within` are proved (not trusted) wrappers that add the result's
`f64_within` bound. Exact text (from `declarative_spec/lemmas.py`, `float_error_lemmas_rs`):

```rust
pub open spec fn f64_within(x: f64, cap: real) -> bool {
    x.is_finite_spec() && -cap < (x as real) && (x as real) < cap
}

// TRUSTED (f64 idealization): addition. Called BEFORE `x + y`: finite x, y within caps and a sum below
// the overflow bound make the exec `+` defined (`add_req`), and whatever the add returns is the real sum
// (rounding error ignored).
#[verifier::external_body]
pub proof fn lemma_f64_add_real(x: f64, y: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
    ensures
        x.add_req(y),
        forall|o: f64| #[trigger] add_ensures::<f64>(x, y, o) ==>
            o.is_finite_spec() && (o as real) == (x as real) + (y as real),
{ }

// TRUSTED (f64 idealization): subtraction, same shape.
#[verifier::external_body]
pub proof fn lemma_f64_sub_real(x: f64, y: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
    ensures
        x.sub_req(y),
        forall|o: f64| #[trigger] sub_ensures::<f64>(x, y, o) ==>
            o.is_finite_spec() && (o as real) == (x as real) - (y as real),
{ }

// TRUSTED (f64 idealization): multiplication, same shape (product below the overflow bound).
#[verifier::external_body]
pub proof fn lemma_f64_mul_real(x: f64, y: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx * cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
    ensures
        x.mul_req(y),
        forall|o: f64| #[trigger] mul_ensures::<f64>(x, y, o) ==>
            o.is_finite_spec() && (o as real) == (x as real) * (y as real),
{ }

// TRUSTED (f64 idealization): division of finite x by finite nonzero y whose real quotient is within the
// cap: the exec `/` is defined and returns the real quotient (rounding ignored).
#[verifier::external_body]
pub proof fn lemma_f64_div_real(x: f64, y: f64, cx: real, cq: real)
    requires
        0real <= cx, 0real <= cq, cq <= f64_safe_bound(),
        f64_within(x, cx),
        y.is_finite_spec(), (y as real) != 0real,
        -cq * abs_real(y as real) < (x as real),
        (x as real) < cq * abs_real(y as real),
    ensures
        x.div_req(y),
        forall|o: f64| #[trigger] div_ensures::<f64>(x, y, o) ==>
            o.is_finite_spec() && (o as real) == (x as real) / (y as real),
{ }

// TRUSTED (f64 idealization): an integer cast to f64 keeps its value (exact below 2^53, rounding
// ignored above, up to the safe bound). vstd gives the exec `as f64` no specification, so the host
// provides the cast as a trusted exec function; the body is the plain Rust cast.
#[verifier::external_body]
pub fn host_u64_to_f64(n: u64) -> (o: f64)
    requires (n as int as real) <= f64_safe_bound(),
    ensures o.is_finite_spec(), (o as real) == (n as int as real),
{
    n as f64
}

// TRUSTED (f64 idealization): the same cast claim for i128.
#[verifier::external_body]
pub fn host_i128_to_f64(n: i128) -> (o: f64)
    requires -f64_safe_bound() <= (n as int as real) && (n as int as real) <= f64_safe_bound(),
    ensures o.is_finite_spec(), (o as real) == (n as int as real),
{
    n as f64
}

// TRUSTED (f64 idealization): comparisons of finite f64 values hold exactly when the real
// comparison does (exact in IEEE 754; the link from the uninterpreted predicate is trusted).
#[verifier::external_body]
pub proof fn lemma_f64_lt_real(x: f64, y: f64, o: bool)
    requires x.is_finite_spec(), y.is_finite_spec(), lt_ensures::<f64>(x, y, o),
    ensures o <==> (x as real) < (y as real),
{ }

// TRUSTED (f64 idealization): `<=` on finite f64 is `<=` on the reals.
#[verifier::external_body]
pub proof fn lemma_f64_le_real(x: f64, y: f64, o: bool)
    requires x.is_finite_spec(), y.is_finite_spec(), le_ensures::<f64>(x, y, o),
    ensures o <==> (x as real) <= (y as real),
{ }

// TRUSTED (f64 idealization): `>` on finite f64 is `>` on the reals.
#[verifier::external_body]
pub proof fn lemma_f64_gt_real(x: f64, y: f64, o: bool)
    requires x.is_finite_spec(), y.is_finite_spec(), gt_ensures::<f64>(x, y, o),
    ensures o <==> (x as real) > (y as real),
{ }

// TRUSTED (f64 idealization): `>=` on finite f64 is `>=` on the reals.
#[verifier::external_body]
pub proof fn lemma_f64_ge_real(x: f64, y: f64, o: bool)
    requires x.is_finite_spec(), y.is_finite_spec(), ge_ensures::<f64>(x, y, o),
    ensures o <==> (x as real) >= (y as real),
{ }

// TRUSTED (f64 idealization): `==` on finite f64 is equality of the reals.
#[verifier::external_body]
pub proof fn lemma_f64_eq_real(x: f64, y: f64, o: bool)
    requires x.is_finite_spec(), y.is_finite_spec(), eq_ensures::<f64>(x, y, o),
    ensures o <==> (x as real) == (y as real),
{ }
```

Tests: `tests/test_declarative_float_idealization.py` (the trusted set is exactly these 11 items; every float shape verifies, runs
against DuckDB within tolerance, and a wrong body is rejected), `tests/test_declarative_float_q2.py` (the SEC AVG shape),
`tests/test_declarative_float_typecheck.py`, `tests/test_f64_idealization_adversary.py` (the adversary's literal-collision,
cast and loader tests that still apply; its rounding findings are pinned as accepted limitations).

**Accepted limitations (rounding; not holes).** The idealization keeps exactly 11 trusted items.
- Rounding in every `*_real` lemma: add, subtract, multiply and divide are taken as the real operations; the f64 result differs
  by up to 2^-53 relative per operation (`0.06 + 0.01` is `0.06999999999999999`; `2^53 + 1` is `2^53`); integer casts above 2^53 round.
- Underflow: `mul`/`div` have no lower magnitude bound (`1e-200 * 1e-200` is 0 in IEEE and positive in the spec).
- Denormal and non-dyadic literals: a literal denotes its decimal value, but the double is only the nearest one (denormal literals
  are the least precise); two literals that round to the same double are refused.
- Comparisons of computed floats (`p * d = 0.3`, `HAVING SUM(v) > x`, `v + 1 > w`): the spec compares exact reals, the execution
  compares rounded doubles, so a value that is a tie over the reals can differ.
- Summation-order flips: DuckDB's `SUM(double)` is plain f64 in an order we do not control and is nondeterministic under parallel
  execution; `0.1 + 0.2 + 0.3 > 0.6` is true in DuckDB and false over the reals; cancellation (`1e16, 1, 1, 1, -1e16`) and absorption
  lose small terms in f64 but not in the spec; ORDER BY / HAVING near ties can flip.
- `0.06 + 0.01` constants are folded exactly (as DuckDB folds them in DECIMAL), not in f64.
Still refused (not a rounding matter): an integer or DECIMAL column compared with, or mixed in arithmetic with, a float column or
float expression (no typed bridge), colliding float literals, literals that are not a finite nonzero double.

## Division by zero of a ratio (one more trusted item; adversary-gated)

A SELECT item `[K *] SUM|COUNT(..) / SUM|COUNT(..)` (TPC-H Q14) is a DOUBLE in DuckDB (`DECIMAL / DECIMAL` and integer
division are computed in DOUBLE). The spec says: with exact integer sums N (numerator, times the constant K) and D, the
result is finite and equals `(K*N / 10^sN) / (D / 10^sD)` as a real when `D != 0` (the f64 idealization), and when `D == 0`
the IEEE 754 result of dividing by +0.0: `+inf` for `K*N > 0`, `-inf` for `K*N < 0`, `NaN` for `K*N == 0`. DuckDB returns
exactly these (`ieee_floating_point_ops` is on). A zero denominator is data, so it must be part of the specification
(leaving it unconstrained makes every body verify; excluding it makes no body provable). The one trusted statement is
the exec division of a finite `f64` by `0.0`. It is exact IEEE 754, not an idealization, lives in its own block
(`declarative_spec/lemmas.py::float_div_zero_lemma_rs`, NOT in the pinned eleven-item family above), and is placed in
the host lemma region only for a spec that states an infinite or NaN result. Exact text:

```rust
// TRUSTED (IEEE 754 division by zero; exact, not an idealization): a finite f64 divided by +0.0 is +infinity for a
// positive numerator, -infinity for a negative one, and NaN for a zero numerator (either zero sign). DuckDB's DOUBLE
// division returns exactly these values (`ieee_floating_point_ops` is on), so a ratio whose denominator is the exact
// value 0 is specified by them. The body is the plain Rust division by the literal 0.0.
#[verifier::external_body]
pub fn host_f64_div_by_zero(x: f64) -> (o: f64)
    requires x.is_finite_spec(),
    ensures
        (x as real) > 0real ==> o.is_infinite_spec() && !o.is_sign_negative_spec(),
        (x as real) < 0real ==> o.is_infinite_spec() && o.is_sign_negative_spec(),
        (x as real) == 0real ==> o.is_nan_spec(),
{
    x / 0.0
}
```

Verdict and proposal: `research_loop/menus/ratio_division_ADVERSARY_VERDICT.md`, `research_loop/menus/ratio_division_PROPOSAL.md`.
What is false about it: nothing about the IEEE operation; the surrounding idealization (casts of sums above 2^53, the real
quotient) carries the accepted float limitations.

## Menu (25 families)

| id | kind | spec_ret | purpose |
|----|------|----------|---------|
| `scalar_u64` | scalar | `u64` | Scalar aggregate (SUM/COUNT/MIN/MAX) |
| `scalar_i64` | scalar | `i64` | Signed scalar aggregate |
| `map_u32_u64` | map | `Map<u32, u64>` | Single-key group-by (u32) |
| `map_str_u64` | map | `Map<Seq<char>, u64>` | Single string-key group-by |
| `map_u32_str_u64` | map | `Map<(u32, Seq<char>), u64>` | Composite group-by (u32 + string) |
| `map_str_u32_u64` | map | `Map<(Seq<char>, u32), u64>` | Composite group-by (string + u32) |
| `map_str_str_u64` | map | `Map<(Seq<char>, Seq<char>), u64>` | Two-string group-by |
| `map_u32_str_str_u64` | map | `Map<(u32, Seq<char>, Seq<char>), u64>` | Three-part group-by |
| `map_str_str_u32_u64` | map | `Map<(Seq<char>, Seq<char>, u32), u64>` | Three-part group-by (strings + u32) |
| `map_str_str_str_u64` | map | `Map<(Seq<char>, Seq<char>, Seq<char>), u64>` | Three-string group-by |
| `map_str_str_str_str_u64` | map | `Map<(Seq<char>, Seq<char>, Seq<char>, Seq<char>), u64>` | Four-string group-by |
| `map_u32_str_i64` | map | `Map<(u32, Seq<char>), i64>` | Signed aggregate group-by |
| `map_u32_str_str_i64` | map | `Map<(u32, Seq<char>, Seq<char>), i64>` | Signed aggregate, three-part keys |
| `map_str_str_i64` | map | `Map<(Seq<char>, Seq<char>), i64>` | Signed aggregate, two-string keys |
| `map_str_str__u64_u64` | map | `Map<(Seq<char>, Seq<char>), (u64, u64)>` | Multi-agg tuple value (two u64) |
| `map_str_str__u64_u64_u64` | map | `Map<(Seq<char>, Seq<char>), (u64, u64, u64)>` | Multi-agg tuple value (three u64) |
| `map_u32_str_str__u64_u64_u64` | map | `Map<(u32, Seq<char>, Seq<char>), (u64, u64, u64)>` | Multi-agg on three-part keys |
| `map_str_str_str_str__u64_u64` | map | `Map<(Seq<char>, Seq<char>, Seq<char>, Seq<char>), (u64, u64)>` | Multi-agg on four-string keys |
| `map_u32__u64_u64` | map | `Map<u32, (u64, u64)>` | Multi-agg on u32 key |
| `seq_u64` | seq | `Seq<u64>` | Projection / ordered u64 sequence |
| `seq_u32` | seq | `Seq<u32>` | Projection / DISTINCT u32 sequence |
| `seq_str_u64` | seq | `Seq<(Seq<char>, u64)>` | String + u64 projection row |
| `seq_str_str_u64` | seq | `Seq<(Seq<char>, Seq<char>, u64)>` | Two-string + u64 projection row |
| `seq_u32_str_u64` | seq | `Seq<(u32, Seq<char>, u64)>` | u32 + string + u64 projection row |
| `seq_str_str_u32_u64` | seq | `Seq<(Seq<char>, Seq<char>, u32, u64)>` | Two-string + u32 + u64 projection row |

## Distinct-set helpers (multi-agg companion)

When the shell ret_type is a projected multi-agg map (`map_*__u64_…` keys),
`prepare_agent_visible_spec` also emits:

| helper | exec | spec bridge |
|--------|------|-----------|
| `hashset_str_as_map` | `HashSetWithView<String>` | `Map<Seq<char>, bool>` via `Map::new(s, \|k\| true)` |
| `set_new_str` / `set_insert_str` | string keys | membership + dom on `hashset_str_as_map(s@)` |
| `hashset_u32_as_map` | `HashSetWithView<u32>` | `Map<u32, bool>` |
| `set_new_u32` / `set_insert_u32` | u32 keys | same contract |

`set_insert_*` returns `is_new`; when true, `dom().len()` increases by 1. Use
with ghost `method_spec_helper` folds that track `Map<K, bool>` distinct state
then project via `dom().len() as u64`.

## Correlated EXISTS keys map (transpiler companion)

For each `exists_corr_{alias}_spec` semi-join fold, the transpiler also emits
`exists_corr_{alias}_keys_map` (inner keys matching the non-correlation WHERE
slice) and proved `lemma_exists_corr_{alias}_spec_contains`, which shows
`exists_corr_{alias}_spec(inner, outer_key)` equals `keys_map(inner, 0).contains_key(outer_key)`;
for u32 / `Seq<char>` keys this is the spec-side counterpart of
`hashset_{u32|str}_as_map` membership after an exec HashSet build.

## Multi-agg group step (`agg_step_*`)

When `prepare_agent_visible_spec` / assembly sees a projected multi-agg map
(`map_*__u64_…` ret_type) **and** can parse the transpiled fold, it also emits
per-query step helpers (names keyed by `agg_suffix`, e.g. `str_str__u64_u64_u64`):

| helper | role |
|--------|------|
| `AggStepState_{suffix}` | `projected` HashMap + `inner` HashMap (exec tuple incl. `HashSet` for COUNT_DISTINCT slots) |
| `agg_step_inner_{suffix}_spec` | open spec: exec inner map → spec helper state map (structural `@` on map slots) |
| `agg_step_project_{suffix}` | open spec: inner state tuple → projected agg tuple (from `method_spec` `map_values`) |
| `agg_step_apply_row_{suffix}` | open spec: one-row inner update (from fold body; row params for distinct / SUM/AVG inputs) |
| `agg_step_state_new_{suffix}` | empty state |
| `agg_step_{suffix}` | TRUSTED: apply one qualifying row to a group (inner + projected maps stay in sync) |

Agent loop pattern: backward scan, `agg_step_{suffix}(…)` per row, invariant
`agg_step_inner_{suffix}_view(st.inner@) == method_spec_helper(cols, i)`.
Capability reference: `research_loop/bench_standins/sec_q1_runquery.py` (Verus-verified).

## Admission wiring

`admit_agent_runquery.trusted_view_menu` merges views from `TRUSTED_FAMILY_MENU`
when a family's `spec_ret` normalizes equal to the query MethodSpec return type
T (via `bridge_for_family`). Views are deduplicated by name.

Admission and research harvests also record **which menu helpers the agent body used**
(`research_loop/trusted_usage.py` → `logs/trusted_usage.json`).

**NULL support is not a trusted lemma.** The NULL calculus (`declarative_spec/nulls.py`: three-valued logic reduced to
two-valued SQL over validity bits) is a HOST REWRITE of the query, checked differentially against DuckDB
(`tests/null_differential.py`, used by `tests/test_nulls_adversary.py`). Every new predicate kind must be run through it.
