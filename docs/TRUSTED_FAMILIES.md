# Trusted return-type families

Lemma admits agent `run_query` implementations only against a **fixed menu** of
Trusted return-type families. Each family maps a normalized Verus MethodSpec
return type `T` to exec-shaped Rust (`u64`/`i64`, `HashMap<…>`, `Vec<…>`) plus
optional TRUSTED view/agg helpers.

**Reviewability:** Trusteds should stay **conceptually few** and **grouped** (views,
agg accumulate, distinct-set, one-row `agg_step`, HAVING filter) so a human can
audit them. Suffixes encode key/value shape; they are not separate Trusted
ideas. Prefer fixing MethodSpec/docs over inventing another opaque helper.

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
   **Fold slot/count/sum bounds** stay honest ``assume_*`` empty ``external_body``
   under catalog; ``LEMMA_FOLD_SLOT_INDUCTIVE=1`` emits experimental inductive
   ``lemma_*`` bodies (WIP — not default).

### External assumptions vs Trusteds

::

    [External] CatalogAssumptions (user | engine defaults | sec_prove_loop profile)
        → resolve_bounds → LEMMA_MAX_* + valid_cols
    [Trusteds] IF valid_cols/caps THEN checked_add / lemma_* fold bounds
    [Agent]    uses assumes + lemmas under those caps

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

**HAVING map peel:** vstd `HashMapWithView` / `StringHashMap` unwrap/wrap Trusteds
(`having_map_peel.rs.inc`) — one idea: single-field newtype over `std::collections::HashMap`;
`transmute` only inside those named helpers; HAVING exec uses unwrap → filter → wrap.

**Agent primitives (opt-in):** `emit_agent_externs()` is **not** on the default product
assemble path. Set `LEMMA_EMIT_AGENT_PRIMITIVES=1` (or reference symbols in `run_query`)
to splice hash-join / zone-map / dict helpers from `agent_primitives/`.

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
3. Maps / seq-with-strings: `view_spec` set; `trusted_rs` contains the view name,
   `external_body`, and `agg_new_` + (`agg_add_` or `agg_put_`) or `seq_new_` /
   `seq_push_` as appropriate.
4. `assert_menu_complete()` validates the full menu in CI.

Parametrized structural tests: `tests/test_trusted_families.py`.
Semantic differential (exec math vs oracle / DuckDB): `tests/test_trusted_semantic_differential.py`.

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
