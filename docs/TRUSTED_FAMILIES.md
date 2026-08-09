# Trusted return-type families

Lemma admits agent `run_query` implementations only against a **fixed menu** of
Trusted return-type families. Each family maps a normalized Verus MethodSpec
return type `T` to exec-shaped Rust (`u64`/`i64`, `HashMap<…>`, `Vec<…>`) plus
optional TRUSTED view/agg helpers.

Registry: `research_loop/trusted_families.py` (`TRUSTED_FAMILY_MENU`).

**Nested `Map` return types are intentionally unsupported.** COUNT DISTINCT and
similar queries use flat projected `u64` or `Seq<…>` families instead of nested
maps. MethodSpec helper state may still use `Map<K, bool>` for distinct keys;
agents prove exec `HashSet` updates via TRUSTED `hashset_*_view` + `set_insert_*`
(emitted alongside multi-agg map families in agent-visible spec).

## Testing policy

For every family in `TRUSTED_FAMILY_MENU`:

1. `bridge_for_family` succeeds.
2. Scalars: `ensures res == method_spec(cols),` and empty `trusted_rs`.
3. Maps / seq-with-strings: `view_spec` set; `trusted_rs` contains the view name,
   `external_body`, and `agg_new_` + (`agg_add_` or `agg_put_`) or `seq_new_` /
   `seq_push_` as appropriate.
4. `assert_menu_complete()` validates the full menu in CI.

Parametrized tests: `tests/test_trusted_families.py`.

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

| helper | exec | spec view |
|--------|------|-----------|
| `hashset_str_view` | `HashSet<String>` | `Map<Seq<char>, bool>` |
| `set_new_str` / `set_insert_str` | string keys | membership + dom size on insert |
| `hashset_u32_view` | `HashSet<u32>` | `Map<u32, bool>` |
| `set_new_u32` / `set_insert_u32` | u32 keys | same contract |

`set_insert_*` returns `is_new`; when true, `dom().len()` increases by 1. Use
with ghost `method_spec_helper` folds that track `Map<K, bool>` distinct state
then project via `dom().len() as u64`.

## Admission wiring

`admit_agent_runquery.trusted_view_menu` merges views from `TRUSTED_FAMILY_MENU`
when a family's `spec_ret` normalizes equal to the query MethodSpec return type
T (via `bridge_for_family`). Views are deduplicated by name.
