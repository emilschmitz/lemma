"""RunQuery template emission (toggle via enable_templates)."""

from __future__ import annotations

import re

from .agg_push import agg_bridge_u32_str
from .agg_push_str import agg_bridge_str_str
from .parse_sql import SQLQuery, support_spec_params


def _emit_join_run_query_skeleton(ret_type: str) -> str:
    """Commented join walk: pairs/triples from the end, then the generated is_* lemma."""
    return f"""// Proved equijoin is already in this file. Call it; do not rebuild the hash invariant.
// Shapes (name the lemma this file emits for the helper):
//   one equality — equijoin_pairs_str / equijoin_pairs_u64 / equijoin_pairs_u32:
//     walk pairs from the end with invariant acc == pair_acc(pairs@, step, base, k as int);
//     then lemma_<helper>_is_pairs
//   two string equalities — equijoin_pairs_str2:
//     same pair_acc walk; then lemma_<helper>_is_pairs2
//   three string equalities — equijoin_pairs_str3:
//     same pair_acc walk; then lemma_<helper>_is_pairs3
//   OR equalities — orjoin_pairs_str:
//     same pair_acc walk; then lemma_<helper>_is_or
//   3-table star — star_eq_triples_str:
//     walk triples from the end with invariant acc == triple_acc(triples@, step, base, k as int);
//     then lemma_<helper>_is_star_pairs
//   3-table chain — chain_eq_triples_str:
//     same triple_acc walk; then lemma_<helper>_is_chain_pairs
//   3-table Q6 (1+3) — q6_eq_triples_str:
//     walk triples from the end with invariant acc == triple_acc(triples@, step, base, k as int);
//     then lemma_<helper>_is_q6_pairs
//   4-table star — star_eq_quads_str:
//     walk quads from the end with invariant acc == quad_acc(quads@, step, base, k as int);
//     then lemma_<helper>_is_quad_pairs
//   LEFT/ANTI miss — anti_miss_rows_str / anti_miss_rows_str3:
//     walk misses from the end with miss_acc; then lemma_<helper>_is_left or _is_anti
//   SEMI hits — semi_hit_rows_str:
//     walk hits from the end with hit_acc; then lemma_<helper>_is_semi
//   LEFT OUTER — left_outer_pairs_str / left_outer_pairs_u64:
//     walk slots from the end with loj_acc; then lemma_<helper>_is_loj
//   RIGHT OUTER — right_outer_pairs_str:
//     walk slots from the end with right_acc; then lemma_<helper>_is_right
//   FULL OUTER — full_outer_parts_str:
//     fold matched / left-miss / right-miss; then lemma_<helper>_is_full
//   self-join — same equijoin_pairs_*; params are SQL aliases (Cols_<alias>)
// After the walk: lemma_<helper>_method_is_fold (when this file emits it).
// Do not call build_hashset_u32 / probe_sum_u64. Do not build a second index of a derived Map.
// method_spec may still be map_values, spec_seq_take, or apply_having_filter of the helper.
// === RunQuery skeleton (agent provides the body) ===
// pub exec fn run_query(...) -> (res: {ret_type})
//     requires valid_cols_*(...),
//     ensures res == method_spec(...),  // or res@ == method_spec(...) for maps/vecs
// {{
//     // let pairs = equijoin_pairs_*(...);  // or: let triples = star_eq_triples_str(...);
//     // let mut k = pairs.len();           // or triples.len()
//     // let mut acc = <base>;
//     // while k > 0
//     //     invariant
//     //         acc == pair_acc(pairs@, step, base, k as int),  // or triple_acc(triples@, ...)
//     //     decreases k,
//     // {{
//     //     k = k - 1;
//     //     // apply step at pairs[k] (or triples[k]): filters / aggs from method_spec
//     // }}
//     // lemma_<helper>_is_pairs(...);  // or matching _is_* / _method_is_fold — name from this file
//     // res = ...;  // maybe map_values / spec_seq_take / apply_having_filter of the helper
// }}
"""


def emit_run_query_skeleton(
    query: SQLQuery,
    ret_type: str,
    *,
    agg_push: tuple[str, str] | None = None,
    agg_push_str: tuple[str, str] | None = None,
    is_join: bool = False,
    val_type: str = "u64",
) -> str:
    """Emit a commented/TODO exec fn run_query skeleton."""
    if is_join:
        return _emit_join_run_query_skeleton(ret_type)

    extras = support_spec_params(query)
    extra_sig = "".join(f", {n}: &{s}" for n, s, _ in extras)
    extra_req = "".join(f" && {v}({n})" for n, _, v in extras)
    extra_ens = "".join(f", {n}" for n, _, _ in extras)
    sig = f"pub exec fn run_query(cols: &Cols{extra_sig}) -> (res: {ret_type})"
    req = f"    requires valid_cols(cols){extra_req},"
    ens = f"    ensures res == method_spec(cols{extra_ens}),"

    if query.groupby_columns:
        inv = (
            "        invariant 0 <= i && i <= cols.n,\n"
            "        invariant g@ == method_spec_helper(cols, i as int),\n"
        )
        if agg_push is not None:
            u32_col, str_col = agg_push
            agg_new_fn, agg_add_fn, rust_map = agg_bridge_u32_str(val_type)
            u32_base = u32_col.lower()
            str_base = str_col.lower()
            body_hint = (
                f"        // TODO: if <filter> {{\n"
                f"        //   {agg_add_fn}(&mut agg, cols.get_{u32_base}_exec(i), "
                f"&cols.get_{str_base}_exec(i), term);\n"
                f"        // }}\n"
            )
            init = (
                f"    // let mut agg: {rust_map} = {agg_new_fn}();\n"
                "    // ghost let mut g: Map<_, _> = Map::empty();\n"
            )
            end = "    // res = agg;\n"
        elif agg_push_str is not None:
            s0, s1 = agg_push_str
            agg_new_fn, agg_add_fn, rust_map = agg_bridge_str_str(val_type)
            s0_base = s0.lower()
            s1_base = s1.lower()
            body_hint = (
                f"        // TODO: if <filter> {{\n"
                f"        //   {agg_add_fn}(&mut agg, &cols.get_{s0_base}_exec(i), "
                f"&cols.get_{s1_base}_exec(i), term);\n"
                f"        // }}\n"
            )
            init = (
                f"    // let mut agg: {rust_map} = {agg_new_fn}();\n"
                "    // ghost let mut g: Map<_, _> = Map::empty();\n"
            )
            end = "    // res = agg;\n"
        else:
            body_hint = "        // TODO: group-by body\n"
            init = "    // let mut agg: HashMap<_, _> = HashMap::new();\n"
            end = "    // res = agg;\n"
    else:
        inv = (
            "        invariant 0 <= i && i <= cols.n,\n"
            "        invariant res == method_spec_helper(cols, i as int),\n"
        )
        body_hint = "        // TODO: if <filter> { res = add_u64(res, term); }\n"
        init = "    // let mut res: u64 = 0;\n"
        end = ""

    inv_commented = "".join(f"// {line}\n" for line in inv.splitlines(keepends=False))
    body_hint_commented = "".join(
        f"// {line}\n" if not line.startswith("//") else f"{line}\n"
        for line in body_hint.splitlines(keepends=False)
    )

    return f"""// === RunQuery skeleton (agent provides the body) ===
// {sig}
// {req}
// {ens}
// {{
{init}//     let mut i = cols.n;
//     while i > 0
//         invariant
{inv_commented}//     {{
//         i = i - 1;
{body_hint_commented}//     }}
{end}// }}
"""


def _execify_expr(expr: str) -> str:
    """Rewrite spec getters/indexing into exec-friendly usize field access."""
    out = re.sub(r"cols\.get_(\w+)\((\w+) as int\)", r"cols.\1[\2]", expr)
    out = re.sub(r"\[(\w+) as int(?: as int)?\]", r"[\1]", out)
    return out


def _exec_accessorify(expr: str) -> str:
    """Use get_*_exec for proved loop bodies (satisfies vec index preconditions)."""
    placeholder = "__EXEC__"
    out = re.sub(
        r"cols\.get_(\w+)_exec\(i\)",
        lambda m: f"{placeholder}{m.group(1)}{placeholder}",
        expr,
    )
    out = re.sub(r"cols\.(\w+)\[i\]", r"cols.get_\1_exec(i)", out)
    out = re.sub(
        r"cols\.get_(\w+)\(i\)",
        lambda m: (
            f"cols.get_{m.group(1)}(i)"
            if m.group(1).endswith("_exec")
            else f"cols.get_{m.group(1)}_exec(i)"
        ),
        out,
    )
    out = re.sub(
        rf"{placeholder}(\w+){placeholder}",
        r"cols.get_\1_exec(i)",
        out,
    )
    return out


def _scalar_loop_invariant() -> str:
    return """            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),"""


def _filter_block(where_at_i: str | None, inner: str) -> str:
    if where_at_i:
        return f"if {where_at_i} {{\n            {inner}\n        }}"
    return inner


def emit_run_query_template(
    query: SQLQuery,
    ret_type: str,
    *,
    where_at_i: str | None,
    term_at_i: str,
    agg_push: tuple[str, str] | None = None,
    agg_push_str: tuple[str, str] | None = None,
    val_type: str = "u64",
) -> str:
    """Emit filled run_query for scalar SUM/COUNT/AVG only (no external_body).

    Group-by, joins, and subqueries emit a commented skeleton — exec≡spec is not
    claimed until the agent/fixture supplies a proved body.
    """
    if query.agg_type == "SELECT_SUBQUERY":
        return emit_run_query_skeleton(query, ret_type)

    if query.groupby_columns:
        return emit_run_query_skeleton(
            query,
            ret_type,
            agg_push=agg_push,
            agg_push_str=agg_push_str,
            val_type=val_type,
        )

    where_e = _exec_accessorify(_execify_expr(where_at_i)) if where_at_i else None
    term_e = _exec_accessorify(_execify_expr(term_at_i))
    inv = _scalar_loop_invariant()

    if query.agg_type == "AVG":
        sum_body = _filter_block(where_e, f"sum = add_u64(sum, {term_e});")
        count_body = _filter_block(where_e, "count = add_u64(count, 1);")
        return f"""// Scalar AVG template — loop structure for future exec≡spec proof.
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{{
    let mut sum: u64 = 0;
    let mut count: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            sum == sum_helper(cols, i as int),
            count == count_helper(cols, i as int),
        decreases i,
    {{
        i = i - 1;
        {sum_body}
        {count_body}
    }}
    if count == 0 {{ 0 }} else {{ sum / count }}
}}"""

    if query.agg_type == "COUNT":
        body = _filter_block(where_e, "res = add_u64(res, 1);")
    else:
        body = _filter_block(where_e, f"res = add_u64(res, {term_e});")

    return f"""// Scalar aggregate template — loop invariant ties res to method_spec_helper.
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{{
    let mut res: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
{inv}
        decreases i,
    {{
        i = i - 1;
        {body}
        assert(res == method_spec_helper(cols, i as int));
    }}
    res
}}"""


def emit_trusted_run_query(
    query: SQLQuery,
    ret_type: str,
    *,
    is_join: bool = False,
    join_tables: tuple[str, str] | None = None,
    view_spec: str | None = None,
    hot_path_call: str | None = None,
) -> str:
    """Emit TRUSTED executable run_query (external_body), not a commented skeleton."""
    if is_join and join_tables:
        left, right = join_tables
        left_struct = f"Cols_{left}"
        right_struct = f"Cols_{right}"
        sig = f"pub exec fn run_query(left: &{left_struct}, right: &{right_struct}) -> (res: {ret_type})"
        req = f"    requires valid_cols_{left}(left), valid_cols_{right}(right),"
        ens = (
            f"    ensures {view_spec}(res@) == method_spec(left, right),"
            if view_spec
            else "    ensures res@ == method_spec(left, right),"
        )
        body = hot_path_call or "unimplemented!(\"TRUSTED join run_query\")"
        return f"""// TRUSTED: join exec bridge (HashMap/nested-loop hot path when generated).
#[verifier::external_body]
{sig}
{req}
{ens}
{{
    {body}
}}"""

    sig = f"pub exec fn run_query(cols: &Cols) -> (res: {ret_type})"
    req = "    requires valid_cols(cols),"
    ens = (
        f"    ensures {view_spec}(res@) == method_spec(cols),"
        if view_spec
        else "    ensures res == method_spec(cols),"
    )
    body = hot_path_call or "unimplemented!(\"TRUSTED run_query\")"
    return f"""// TRUSTED: exec bridge tied to method_spec.
#[verifier::external_body]
{sig}
{req}
{ens}
{{
    {body}
}}"""
