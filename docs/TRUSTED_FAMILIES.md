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

## f64 idealization (the float trust, and its limits)

Authorized by Emil (2026-10-04: "accept floating point errors for now"), reviewed by the adversary gate
(`research_loop/menus/f64_idealization_ADVERSARY_VERDICT.md`, regression tests
`tests/test_f64_idealization_adversary.py`). All float trust is in `float_error_lemmas_rs` and
`float_exact_lemmas_rs` of `declarative_spec/lemmas.py` and consists of exactly the items below; everything else about
floats (the min/max/ORDER BY/HAVING proofs, the AVG bookkeeping, the sum-error bound's use) is proved.

**Three kinds of trusted item.**

1. **True statements** (no idealization): `lemma_f64_add_defined`/`sub_defined`/`mul_defined` (IEEE operations are
   defined), the comparison lemmas `lemma_f64_lt_real` .. `eq_real` (IEEE comparisons are exact for finite values; only
   the link from vstd's uninterpreted predicates to `as real` is trusted), the `_exact` lemmas
   (`lemma_f64_add_exact`, `sub_exact`, `mul_exact`: when the real result is an integer `s` with `|s| <= 2^53` the f64
   result is exactly `s`), the casts `host_u64_to_f64_exact` / `host_i128_to_f64_exact` (`|n| <= 2^53`), and the sum
   error lemma `lemma_f64_sum_within_eps` with its fold lemmas (a plain left-to-right f64 fold is within
   `n^2 * cap * 2^-52` of the real sum; holds in every summation order on all adversarial data tested). A plain
   `SUM(float)` / `AVG(float)` is proved with the sum-error lemma, so its epsilon really bounds the error.
2. **The idealization**: `lemma_f64_add_real`, `sub_real`, `mul_real`, `div_real` (with `div_defined`): for finite
   values within the caps (`f64_within`), the f64 result *is* the real result. **False whenever rounding occurs**
   (relative error up to 2^-53 per operation; `0.06 + 0.01` is `0.06999999999999999`; `2^53 + 1` is `2^53`). Used only
   where a shape needs it: products and differences inside an aggregate, a comparison of a computed value, AVG's
   division. Operands are bounded by the catalog caps and results by `f64_safe_bound()` = 2^200 (no overflow).
3. **A companion hypothesis**, not a lemma: `f64_literals_ok()` in `run_query`'s `requires` states that each f64
   literal of the query, `0.0` and `FLOAT_ABS_EPS` denote their decimal value. False for every non-dyadic literal
   (the double 0.1 is not the real 1/10). The emitter refuses two literals that round to the same double (the
   hypothesis would be contradictory) and a nonzero literal that rounds to 0 or infinity.

**Accepted, quantified limitations (measured by the adversary; Emil: float results need not match DuckDB exactly).**

| Class | Effect |
|---|---|
| HAVING / ORDER BY on a float aggregate | summation order flips near-ties: `0.1+0.2+0.3 > 0.6` is true in DuckDB (`0.6000000000000001`) and the proved real sum says false; one whole row differs. Tie order between equal real sums differs. |
| cancellation / absorption | `SUM(a*(1-b))` with `1e16, 1, 1, 1, -1e16`: real 3, DuckDB 0; idealization claims error 0 (true error 3). `2^53` plus 1000 ones: error 1000. |
| DuckDB's own sum | plain (uncompensated) f64, nondeterministic under parallel `SUM(double)`: 8 runs gave 8 distinct values. No single exact reference exists, so the row check uses a tolerance, never equality. |
| AVG over an integer / DECIMAL | refused when `rows * cell cap` may exceed 2^53 (the cast rounds above it); decided by the catalog caps, never guessed. |
| computed float equality (`p * d = 0.3`) | refused (spec says real equality, execution is IEEE). Stored value vs literal equality is in scope. |
| underflow | `1e-200 * 1e-200` is 0 in IEEE; the idealized statement claims a positive real. Answer equals DuckDB (0). |
| signed zero | `-0.0` vs `+0.0` equal under epsilon, differ in bits. |
| constants | `0.06 + 0.01` is folded exactly (DuckDB folds it in DECIMAL) by the emitter, not computed in f64. |

**Tolerance.** `LEMMA_FLOAT_ABS_EPS` defaults to relative 1e-9 of the largest float sum the catalog allows (floor
1e-9, `declarative_spec/float_eps.py`); the timed row check accepts `min(eps, 1e-9 * |value| + 1e-9)` per DuckDB float,
so a huge epsilon cannot make it vacuous.

**Exact statements (copied from `declarative_spec/lemmas.py`).**

```rust
pub open spec fn host_f64_sum_error(n_terms: int, mag_cap: int) -> real {
    (n_terms as real) * (n_terms as real) * (mag_cap as real) * (1real / 4503599627370496real)
}

pub open spec fn real_sum_seq(terms: Seq<f64>) -> real
    decreases terms.len()
{
    if terms.len() == 0 { 0real }
    else { (terms[0] as real) + real_sum_seq(terms.skip(1)) }
}

pub uninterp spec fn f64_left_fold(terms: Seq<f64>) -> f64;

pub open spec fn f64_within(x: f64, cap: real) -> bool {
    x.is_finite_spec() && -cap < (x as real) && (x as real) < cap
}

pub open spec fn f64_exact_int_max() -> int {
    0x20000000000000int
}

// TRUSTED (f64 sum error, true statement): the opaque f64 accumulator of an empty sum is 0.0.
#[verifier::external_body]
pub proof fn lemma_f64_left_fold_empty()
    ensures f64_left_fold(Seq::<f64>::empty()) == 0.0f64,
{ }

// TRUSTED (f64 idealization): IEEE addition is defined for every pair of f64 values (the exec `+`
// precondition holds). No value is claimed. The agent calls this before `acc + x`.
#[verifier::external_body]
pub proof fn lemma_f64_add_defined(x: f64, y: f64)
    ensures x.add_req(y),
{ }

// TRUSTED (f64 sum error, true statement): one f64 add extends the opaque left fold by that term.
#[verifier::external_body]
pub proof fn lemma_f64_left_fold_push(prefix: Seq<f64>, x: f64, acc: f64, next: f64)
    requires
        acc == f64_left_fold(prefix),
        vstd::std_specs::ops::add_ensures::<f64>(acc, x, next),
    ensures f64_left_fold(prefix.push(x)) == next,
{ }

// TRUSTED (f64 sum error, true statement; Higham-style bound with slack, held on all adversarial data):
// a plain left-to-right f64 fold of finite terms below the cap is within n^2 * cap * 2^-52 of the real sum.
// This is the lemma for a plain SUM(float): it is not an idealization and `eps` really bounds the error.
#[verifier::external_body]
pub proof fn lemma_f64_sum_within_eps(
    acc: f64,
    n_terms: int,
    mag_cap: int,
    eps: f64,
    terms: Seq<f64>,
)
    requires
        n_terms == terms.len() as int,
        0 <= n_terms < 0x10_0000_0000_0000int,
        0 <= mag_cap,
        acc == f64_left_fold(terms),
        forall|i: int| 0 <= i < terms.len() ==> {
            let r = #[trigger] (terms[i] as real);
            let cap = mag_cap as real;
            -cap < r && r < cap
        },
        host_f64_sum_error(n_terms, mag_cap) <= (eps as real),
    ensures
        abs_real((acc as real) - real_sum_seq(terms)) <= (eps as real),
{ }

// TRUSTED (f64 idealization): like `lemma_f64_add_defined`, IEEE subtraction is defined for every
// pair of f64 values (the exec `-` precondition holds). No value is claimed.
#[verifier::external_body]
pub proof fn lemma_f64_sub_defined(x: f64, y: f64)
    ensures x.sub_req(y),
{ }

// TRUSTED (f64 idealization): IEEE multiplication is defined for every pair (the exec `*`
// precondition holds). No value is claimed.
#[verifier::external_body]
pub proof fn lemma_f64_mul_defined(x: f64, y: f64)
    ensures x.mul_req(y),
{ }

// TRUSTED (f64 idealization): finite x, y within caps, a sum below the overflow bound:
// the f64 sum is the real sum (rounding error ignored).
#[verifier::external_body]
pub proof fn lemma_f64_add_real(x: f64, y: f64, o: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
        add_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (x as real) + (y as real),
{ }

// TRUSTED (f64 idealization): same claim for subtraction.
#[verifier::external_body]
pub proof fn lemma_f64_sub_real(x: f64, y: f64, o: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx + cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
        sub_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (x as real) - (y as real),
{ }

// TRUSTED (f64 idealization): same claim for multiplication (product below the overflow bound).
#[verifier::external_body]
pub proof fn lemma_f64_mul_real(x: f64, y: f64, o: f64, cx: real, cy: real)
    requires
        0real <= cx, 0real <= cy, cx * cy <= f64_safe_bound(),
        f64_within(x, cx), f64_within(y, cy),
        mul_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (x as real) * (y as real),
{ }

// TRUSTED (f64 idealization): division of finite x by finite nonzero y whose real quotient is
// within the cap: the f64 quotient is the real quotient (rounding ignored). The division
// precondition (`div_req`) holds, so the exec `/` is accepted.
#[verifier::external_body]
pub proof fn lemma_f64_div_defined(x: f64, y: f64, cx: real, cq: real)
    requires
        0real <= cx, 0real <= cq, cq <= f64_safe_bound(),
        f64_within(x, cx),
        y.is_finite_spec(), (y as real) != 0real,
        -cq * abs_real(y as real) < (x as real),
        (x as real) < cq * abs_real(y as real),
    ensures
        x.div_req(y),
{ }

// TRUSTED (f64 idealization): the quotient claim (see lemma_f64_div_defined for the requires).
#[verifier::external_body]
pub proof fn lemma_f64_div_real(x: f64, y: f64, o: f64, cx: real, cq: real)
    requires
        0real <= cx, 0real <= cq, cq <= f64_safe_bound(),
        f64_within(x, cx),
        y.is_finite_spec(), (y as real) != 0real,
        -cq * abs_real(y as real) < (x as real),
        (x as real) < cq * abs_real(y as real),
        div_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (x as real) / (y as real),
{ }

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

// TRUSTED (f64 exact, adversary-proposed): the f64 sum of finite x, y is the real sum whenever
// that real sum is an integer of magnitude at most 2^53 (representable, so IEEE returns it).
#[verifier::external_body]
pub proof fn lemma_f64_add_exact(x: f64, y: f64, o: f64, s: int)
    requires
        x.is_finite_spec(), y.is_finite_spec(),
        -f64_exact_int_max() <= s <= f64_exact_int_max(),
        (x as real) + (y as real) == (s as real),
        add_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (s as real),
{ }

// TRUSTED (f64 exact, adversary-proposed): same for subtraction.
#[verifier::external_body]
pub proof fn lemma_f64_sub_exact(x: f64, y: f64, o: f64, s: int)
    requires
        x.is_finite_spec(), y.is_finite_spec(),
        -f64_exact_int_max() <= s <= f64_exact_int_max(),
        (x as real) - (y as real) == (s as real),
        sub_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (s as real),
{ }

// TRUSTED (f64 exact, adversary-proposed): same for multiplication (an integer product of
// magnitude at most 2^53; a subnormal or inexact product is excluded because it is no such integer).
#[verifier::external_body]
pub proof fn lemma_f64_mul_exact(x: f64, y: f64, o: f64, s: int)
    requires
        x.is_finite_spec(), y.is_finite_spec(),
        -f64_exact_int_max() <= s <= f64_exact_int_max(),
        (x as real) * (y as real) == (s as real),
        mul_ensures::<f64>(x, y, o),
    ensures
        o.is_finite_spec(),
        (o as real) == (s as real),
{ }

// TRUSTED (f64 exact, adversary-proposed): an integer cast to f64 keeps its value up to 2^53.
// Above 2^53 the cast rounds (the idealized `host_u64_to_f64` is false there).
#[verifier::external_body]
pub fn host_u64_to_f64_exact(n: u64) -> (o: f64)
    requires n as int <= f64_exact_int_max(),
    ensures o.is_finite_spec(), (o as real) == (n as int as real),
{
    n as f64
}

// TRUSTED (f64 exact, adversary-proposed): the same for i128, |n| <= 2^53.
#[verifier::external_body]
pub fn host_i128_to_f64_exact(n: i128) -> (o: f64)
    requires -f64_exact_int_max() <= n as int <= f64_exact_int_max(),
    ensures o.is_finite_spec(), (o as real) == (n as int as real),
{
    n as f64
}
```

Proved (not trusted) next to them: `lemma_f64_add_within`, `lemma_f64_sub_within`, `lemma_f64_mul_within` (the result's
`f64_within` bound). Tests: `tests/test_declarative_float_idealization.py` (the trusted set is exactly this list; the
shapes verify, run against DuckDB within epsilon, and wrong bodies are rejected), `tests/test_declarative_float_q2.py`,
`tests/test_declarative_float_typecheck.py`, `tests/test_declarative_float_refusals.py`.

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
