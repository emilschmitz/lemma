"""RunQuery template emission (toggle via enable_templates)."""

from __future__ import annotations

import re

from .agg_push import agg_push_method_name
from .agg_push_str import agg_push_str_method_name
from .parse_sql import SQLQuery


def emit_run_query_skeleton(
    query: SQLQuery,
    ret_type: str,
    *,
    agg_push: tuple[str, str] | None = None,
    agg_push_str: tuple[str, str] | None = None,
    is_join: bool = False,
) -> str:
    """Emit a commented/TODO exec fn run_query skeleton."""
    if is_join:
        sig = "pub exec fn run_query(left: &Cols_left, right: &Cols_right) -> (res: u64)"
        req = "    requires valid_cols_left(left),\n    requires valid_cols_right(right),"
        ens = "    ensures res == method_spec(left, right),"
    else:
        sig = f"pub exec fn run_query(cols: &Cols) -> (res: {ret_type})"
        req = "    requires valid_cols(cols),"
        ens = "    ensures res == method_spec(cols),"

    if query.groupby_columns:
        inv = (
            "        invariant 0 <= i && i <= cols.n,\n"
            "        invariant g@ == method_spec_helper(cols, i as int),\n"
        )
        if agg_push is not None:
            u32_col, str_col = agg_push
            push = agg_push_method_name(u32_col, str_col)
            body_hint = (
                f"        // TODO: if <filter> {{\n"
                f"        //   cols.{push}(&mut agg, i, term);\n"
                f"        // }}\n"
            )
            init = (
                "    // let mut agg: HashMap<(u32, String), i64> = HashMap::new();\n"
                "    // ghost let mut g: Map<_, i64> = Map::empty();\n"
            )
            end = "    // res = agg;\n"
        elif agg_push_str is not None:
            s0, s1 = agg_push_str
            push = agg_push_str_method_name(s0, s1)
            body_hint = (
                f"        // TODO: if <filter> {{\n"
                f"        //   cols.{push}(&mut agg, i, term);\n"
                f"        // }}\n"
            )
            init = (
                "    // let mut agg: HashMap<(String, String), u64> = HashMap::new();\n"
                "    // ghost let mut g: Map<_, u64> = Map::empty();\n"
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
