# MethodSpec → shell → Trusted: what the gap actually is

## Short answer

For many SEC EDGAR holdout queries, the **transpiler already emits a real MethodSpec** with a concrete return type `T`. The pipeline then fails because the **host has no Trusted/shell wiring for that `T`** — not because MethodSpec invented a nickname wrong.

```
SQL  →  MethodSpec (... -> T)     ← often OK for SEC holdout
     →  agent shell run_query -> exec(T) + ensures ≡ method_spec
     →  needs Trusted HashMap/Vec ↔ Map/Seq bridges for that T
```

Fail loud looks like:

```text
unsupported MethodSpec return type: Seq<(Seq<char>, Seq<char>, u64)>
```

or

```text
unsupported MethodSpec return type: Map<(Seq<char>, Seq<char>), (u64, u64, u64)>
```

## What the old “nicknames” were (and why they felt useless)

Historically the host ignored MethodSpec’s `T` and did:

1. Guess a string key from SQL shape (`map_u32_str_str_u64`, …).
2. Look that key up in `RET_TYPE_CONFIG` / `RET_TYPE_SPECS`.

That catalog was a **host codegen convenience**, not the query meaning. It could fail with `unknown ret_type: map_…` even when MethodSpec was fine, or (worse) disagree with MethodSpec. That path is **not** the source of truth anymore: we parse MethodSpec `-> T` and map `T` to the same config keys. Missing support is reported as **unsupported MethodSpec return type: {T}**.

The config keys still exist as **internal names for Trusted recipes**. They are not a second semantics of SQL.

## Two different incompletenesses

| Layer | Symptom | Meaning |
|-------|---------|---------|
| **Transpile** | `UnsupportedContractError` / failed_transpile | SQL feature or schema not yet MethodSpec’d |
| **Shell / Trusted** | `unsupported MethodSpec return type: T` | MethodSpec exists; no exec shell + Trusted view/`agg_*` for `T` |

SEC holdout (representative 6): transpile OK; **agent shell resolves** via structural bridge (2026-08-09). End-to-end Verus proof still depends on agent `run_query` + Trusted helpers.

**Structural bridge:** `research_loop/trusted_ret_bridge.py` — parses MethodSpec `T`, emits dynamic `RET_TYPE_CONFIG` keys, Trusted `hashmap_*_view` / `vec_*_view` + `agg_*` / `seq_*` helpers. Wired through `method_spec_ret_type.resolve_ret_type_from_method_spec`, `assemble_verified_program._cfg`, and `assemble_runquery` (ensures/stub via `get_bridge`).

## SEC EDGAR holdout vs supported concrete set (2026-08-09)

From `holdout/gendb_sec_edgar/queries.sql` + `schema.sql` (MethodSpec `T` after transpile):

| Q | MethodSpec `T` (approx) | Shell key | Shell today | Gap family |
|---|-------------------------|-----------|-------------|------------|
| Q1 | `Map<(Seq<char>, Seq<char>), (u64, u64, u64)>` | `map_str_str__u64_u64_u64` | **yes** (structural) | Multi-agg (COUNT/COUNT_DISTINCT/AVG) |
| Q2 | `Seq<(Seq<char>, Seq<char>, u64)>` | `seq_str_str_u64` | **yes** (structural) | Projection / row-list |
| Q3 | `Map<(Seq<char>, u32), u64>` | `map_str_u32_u64` | **yes** (static) | Single-agg map |
| Q4 | `Map<(u32, Seq<char>, Seq<char>), (u64, u64, u64)>` | `map_u32_str_str__u64_u64_u64` | **yes** (structural) | Multi-agg + 3-key |
| Q6 | `Map<(Seq<char>×4), (u64, u64)>` | `map_str_str_str_str__u64_u64` | **yes** (structural) | Multi-agg + 4-string keys |
| Q24 | `Map<(Seq<char>, Seq<char>), (u64, u64)>` | `map_str_str__u64_u64` | **yes** (structural) | Multi-agg (COUNT+SUM) |

Shell “yes” means `resolve_ret_type_from_method_spec` + `build_runquery_agent_source(ret_type=key)` succeed after the bridge registers the dynamic key. The agent edit region wraps the **full** `pub exec fn run_query`; admission still requires `ensures ≡ method_spec` (see `docs/VERIFICATION_CHAIN.md`). Remaining work for verified SEC:

1. **Agent bodies** — prove `run_query` against multi-agg / projection MethodSpec folds (distinct/avg state in helper; ORDER BY/LIMIT for Q2).
2. **Trusted surface** — structural helpers are `#[verifier::external_body]` view bridges (same pattern as existing `hashmap_*_view`); not a vacuous whole-query bridge.
3. Keep extending **single-value map key shapes** when MethodSpec emits new static-catalog shapes (cheap; mirrors existing `agg_new_*` / `agg_add_*`).

Joins, HAVING, subqueries, anti-joins are MethodSpec’d for these queries; **shell/Trusted wiring is in place** (2026-08-09). Remaining blocker is agent `run_query` proof bodies.

## Full generality vs “enough for SEC”

**Full generality** would mean: any MethodSpec `T` the transpiler can emit gets a proved or Trusted exec bridge automatically (polymorphic maps/seqs). We deliberately **do not** invent a vacuous generic Trusted that “supports everything.” Prefer fail loud.

**Enough for this SEC holdout** (shell layer): structural bridge covers multi-agg maps + stringy projection seqs, plus static single-agg key permutations. **Verified end-to-end** still needs agent bodies and non-vacuous use of the Trusted helpers.

**What we already have** (build on this): scalar `u64`; static single-value `HashMap` key shapes; **`trusted_ret_bridge.py`** for dynamic multi-agg maps and stringy `Seq` projections (`hashmap_*_view` / `vec_*_view` + `agg_*` / `seq_*`).

## Decision (current)

- MethodSpec `T` is authority for shell `->` type.
- **Static** `RET_TYPE_CONFIG` entries first; else **structural bridge** (`trusted_ret_bridge.py`) for multi-agg maps and stringy projection seqs.
- Add missing **single-agg** map shapes to the static catalog when the pattern already exists (e.g. `map_str_u32_u64`).
- **Do not** claim SEC is “verified end-to-end” until agent `run_query` bodies prove against MethodSpec; shell/Trusted wiring is necessary but not sufficient.
- Experimental `codegen_exec` / `hashmap_multi_agg_view` is **not** the research-loop agent contract (`AGENTS.md`).

## Pointers

- Parse / map: `research_loop/method_spec_ret_type.py`
- Structural bridge: `research_loop/trusted_ret_bridge.py`
- Trusted recipes: `research_loop/assemble_verified_program.py` (`RET_TYPE_CONFIG`, `_AGG_HELPER_SPECS`, `_cfg`)
- Agent shell: `research_loop/assemble_runquery.py`
- Pipeline contract: repo `AGENTS.md`
