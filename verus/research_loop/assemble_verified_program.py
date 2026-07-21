"""Assemble a single verified Verus program: transpiled spec + proved run_query + load + main."""

from __future__ import annotations

import re

from verus.research_loop.exec_cols import _rust_vec_type

RUNQUERY_SKELETON_MARKER = "// === RunQuery skeleton"

# Per return-type metadata for group-by boundary helpers and RESULT formatting.
RET_TYPE_CONFIG: dict[str, dict[str, str]] = {
    "u64": {
        "rust_ret": "u64",
        "format_result": 'format!("RESULT: {}", res)',
    },
    "map_u32_str_u64": {
        "rust_ret": "HashMap<(u32, String), u64>",
        "hm_map": "Map<(u32, String), u64>",
        "spec_map": "Map<(u32, Seq<char>), u64>",
        "view_spec": "hashmap_u32_str_u64_view",
        "agg_suffix": "u32_str_u64",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.values().copied().fold(0u64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: map_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "map_str_str_u64": {
        "rust_ret": "HashMap<(String, String), u64>",
        "hm_map": "Map<(String, String), u64>",
        "spec_map": "Map<(Seq<char>, Seq<char>), u64>",
        "view_spec": "hashmap_str_str_u64_view",
        "agg_suffix": "str_str_u64",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.values().copied().fold(0u64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: map_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "map_str_str_u32_u64": {
        "rust_ret": "HashMap<(String, String, u32), u64>",
        "hm_map": "Map<(String, String, u32), u64>",
        "spec_map": "Map<(Seq<char>, Seq<char>, u32), u64>",
        "view_spec": "hashmap_str_str_u32_u64_view",
        "agg_suffix": "str_str_u32_u64",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.values().copied().fold(0u64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: map_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "map_u32_str_i64": {
        "rust_ret": "HashMap<(u32, String), i64>",
        "hm_map": "Map<(u32, String), i64>",
        "spec_map": "Map<(u32, Seq<char>), i64>",
        "view_spec": "hashmap_u32_str_i64_view",
        "agg_suffix": "u32_str_i64",
        "format_result": (
            "{\n"
            "        let checksum: i64 = res.values().copied().fold(0i64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: map_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "map_u32_str_str_i64": {
        "rust_ret": "HashMap<(u32, String, String), i64>",
        "hm_map": "Map<(u32, String, String), i64>",
        "spec_map": "Map<(u32, Seq<char>, Seq<char>), i64>",
        "view_spec": "hashmap_u32_str_str_i64_view",
        "agg_suffix": "u32_str_str_i64",
        "format_result": (
            "{\n"
            "        let checksum: i64 = res.values().copied().fold(0i64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: map_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "map_u32_u64": {
        "rust_ret": "HashMap<u32, u64>",
        "hm_map": "Map<u32, u64>",
        "spec_map": "Map<u32, u64>",
        "view_spec": "hashmap_u32_u64_view",
        "agg_suffix": "u32_u64",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.values().copied().fold(0u64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: map_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "map_str_u64": {
        "rust_ret": "HashMap<String, u64>",
        "hm_map": "Map<String, u64>",
        "spec_map": "Map<Seq<char>, u64>",
        "view_spec": "hashmap_str_u64_view",
        "agg_suffix": "str_u64",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.values().copied().fold(0u64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: map_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "seq_u64": {
        "rust_ret": "Vec<u64>",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.iter().copied().fold(0u64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "set_u32": {
        "rust_ret": "Vec<u32>",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.iter().map(|v| *v as u64).fold(0u64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: set_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "seq_u32": {
        "rust_ret": "Vec<u32>",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.iter().map(|v| *v as u64).fold(0u64, |a, v| a.wrapping_add(v));\n"
            '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "seq_u32_u32": {
        "rust_ret": "Vec<(u32, u32)>",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.iter().fold(0u64, |a, (k, v)| {\n"
            "            a.wrapping_add(*k as u64).wrapping_add(*v as u64)\n"
            "        });\n"
            '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
    "seq_u32_u64": {
        "rust_ret": "Vec<(u32, u64)>",
        "format_result": (
            "{\n"
            "        let checksum: u64 = res.iter().fold(0u64, |a, (k, v)| {\n"
            "            a.wrapping_add(*k as u64).wrapping_add(*v)\n"
            "        });\n"
            '        format!("RESULT: seq_len={} checksum={}", res.len(), checksum)\n'
            "    }"
        ),
    },
}

# NativeAgg-style trusted helpers per map return type.
_AGG_HELPER_SPECS: dict[str, dict[str, str]] = {
    "map_u32_str_u64": {
        "add_params": "k0: u32, k1: &str, delta: u64",
        "spec_key": "(k0, k1@)",
        "value_ty": "u64",
        "exec_body": """
    let key = (k0, k1.to_string());
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_str_str_u64": {
        "add_params": "k0: &str, k1: &str, delta: u64",
        "spec_key": "(k0@, k1@)",
        "value_ty": "u64",
        "exec_body": """
    let key = (k0.to_string(), k1.to_string());
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_str_str_u32_u64": {
        "add_params": "k0: &str, k1: &str, k2: u32, delta: u64",
        "spec_key": "(k0@, k1@, k2)",
        "value_ty": "u64",
        "exec_body": """
    let key = (k0.to_string(), k1.to_string(), k2);
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_u32_str_i64": {
        "add_params": "k0: u32, k1: &str, delta: i64",
        "spec_key": "(k0, k1@)",
        "value_ty": "i64",
        "exec_body": """
    let key = (k0, k1.to_string());
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_u32_str_str_i64": {
        "add_params": "k0: u32, k1: &str, k2: &str, delta: i64",
        "spec_key": "(k0, k1@, k2@)",
        "value_ty": "i64",
        "exec_body": """
    let key = (k0, k1.to_string(), k2.to_string());
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
    "map_u32_u64": {
        "add_params": "k0: u32, delta: u64",
        "spec_key": "k0",
        "value_ty": "u64",
        "exec_body": """
    let prev = hm.get(&k0).copied().unwrap_or(0);
    hm.insert(k0, prev.wrapping_add(delta));
""",
    },
    "map_str_u64": {
        "add_params": "k0: &str, delta: u64",
        "spec_key": "k0@",
        "value_ty": "u64",
        "exec_body": """
    let key = k0.to_string();
    let prev = hm.get(&key).copied().unwrap_or(0);
    hm.insert(key, prev.wrapping_add(delta));
""",
    },
}


def _agg_add_ensures(view: str, spec_map: str, spec_key: str, value_ty: str) -> str:
    old_view = f"{view}(old(hm)@)"
    final_view = f"{view}(final(hm)@)"
    return f"""{final_view} == {old_view}.insert(
        {spec_key},
        if {old_view}.contains_key({spec_key}) {{
            ({old_view}[{spec_key}] as int + delta as int) as {value_ty}
        }} else {{
            delta
        }},
    )"""


def _emit_agg_helpers(ret_type: str) -> str:
    cfg = RET_TYPE_CONFIG.get(ret_type, {})
    view = cfg.get("view_spec")
    suffix = cfg.get("agg_suffix")
    if not view or not suffix:
        return ""
    spec_map = cfg["spec_map"]
    hm_map = cfg["hm_map"]
    rust_ret = cfg["rust_ret"]
    agg = _AGG_HELPER_SPECS[ret_type]
    spec_key = agg["spec_key"]
    value_ty = agg["value_ty"]
    add_ensures = _agg_add_ensures(view, spec_map, spec_key, value_ty)
    return f"""
// === TRUSTED NativeAgg-style map helpers (view + agg_new + agg_add; same loop as ghost map) ===
#[verifier::external_body]
pub open spec fn {view}(hm: {hm_map}) -> {spec_map} {{
    arbitrary()
}}

#[verifier::external_body]
pub exec fn agg_new_{suffix}() -> (hm: {rust_ret})
    ensures {view}(hm@) == Map::empty(),
{{
    HashMap::new()
}}

#[verifier::external_body]
pub exec fn agg_add_{suffix}(hm: &mut {rust_ret}, {agg["add_params"]})
    ensures
        {add_ensures},
{{
{agg["exec_body"].rstrip()}
}}
"""


def _strip_skeleton(spec_rs: str) -> str:
    """Remove commented run_query skeleton; keep closing verus! brace."""
    if RUNQUERY_SKELETON_MARKER not in spec_rs:
        return spec_rs
    head, _ = spec_rs.split(RUNQUERY_SKELETON_MARKER, 1)
    tail_match = re.search(r"\n\} // verus!\s*$", spec_rs, re.MULTILINE)
    if not tail_match:
        raise ValueError("transpiled spec missing closing verus! brace")
    return head.rstrip() + "\n"


def generate_load_cols_verus(
    schema_dict: dict[str, str],
    *,
    struct_name: str = "Cols",
    valid_fn: str = "valid_cols",
    load_fn: str = "load_cols",
) -> str:
    """Trusted tbl loader with ensures valid_cols (I/O boundary)."""
    fields = ["    pub n: usize,"]
    col_indices: list[str] = []
    load_pushes: list[str] = []
    vec_decls: list[str] = []

    for col, col_type in schema_dict.items():
        field = col.lower()
        rust_ty = _rust_vec_type(col_type)
        fields.append(f"    pub {field}: Vec<{rust_ty}>,")
        col_indices.append(
            f'    let {field}_i = *name_to_idx.get("{col.upper()}").expect("missing col {col}");'
        )
        vec_decls.append(f"        let mut {field}: Vec<{rust_ty}> = Vec::new();")
        if rust_ty == "String":
            load_pushes.append(
                f"        {field}.push(strip_quotes(f[{field}_i]).to_string());"
            )
        else:
            load_pushes.append(
                f"        {field}.push(f[{field}_i].parse::<{rust_ty}>().unwrap());"
            )

    first_field = list(schema_dict.keys())[0].lower()
    field_inits = "\n".join(f"            {col.lower()}," for col in schema_dict)

    return f"""
#[verifier::external_body]
pub exec fn {load_fn}(path: &str, limit: usize) -> (cols: {struct_name})
    ensures {valid_fn}(&cols),
{{
    use std::collections::HashMap;
    use std::fs::File;
    use std::io::{{BufRead, BufReader}};

    fn strip_quotes(s: &str) -> &str {{
        s.trim_matches('"')
    }}

    let f = File::open(path).expect("open .tbl");
    let mut rdr = BufReader::new(f);
    let mut hdr = String::new();
    rdr.read_line(&mut hdr).unwrap();
    let mut name_to_idx: HashMap<String, usize> = HashMap::new();
    for (i, c) in hdr.split('|').enumerate() {{
        name_to_idx.insert(c.trim().to_uppercase(), i);
    }}
{chr(10).join('    ' + line for line in col_indices)}

{chr(10).join(vec_decls)}

    for line in rdr.lines().take(limit) {{
        let line = line.unwrap();
        let f: Vec<&str> = line.split('|').collect();
        if f.is_empty() {{
            continue;
        }}
{chr(10).join(load_pushes)}
    }}

    let n = {first_field}.len();
    {struct_name} {{
        n,
{field_inits}
    }}
}}
"""


_BENCH_ITERS = 5


def _bench_black_box(ret_type: str) -> str:
    if ret_type == "u64":
        return "std::hint::black_box(res);"
    return "std::hint::black_box(res.len());"


def _median_bench_loop(
    *,
    fmt: str,
    ret_type: str = "u64",
    bench_call: str = "",
    bench_timing_body: str = "",
    bench_post_timing: str = "",
) -> str:
    """Five timed iterations; print median QUERY_LATENCY_US; keep RESULT from last run."""
    black_box = _bench_black_box(ret_type)
    if bench_timing_body:
        exec_block = f"""let t0 = Instant::now();
        {bench_timing_body}
        *t = t0.elapsed().as_micros();
        {bench_post_timing}"""
    else:
        exec_block = f"""let t0 = Instant::now();
        let res = {bench_call};
        {black_box}
        *t = t0.elapsed().as_micros();"""
    return f"""let mut times = [0u128; {_BENCH_ITERS}];
    let mut last = String::new();
    for t in &mut times {{
        {exec_block}
        last = {fmt};
    }}
    times.sort();
    println!("QUERY_LATENCY_US: {{}}", times[times.len() / 2]);"""


def generate_main_rs(
    *,
    default_tbl: str,
    ret_type: str,
    bench_exec: str = "",
    bench_timing_body: str = "",
    bench_post_timing: str = "",
    bench_main_prefix: str = "",
) -> str:
    cfg = RET_TYPE_CONFIG[ret_type]
    fmt = cfg["format_result"]
    bench_call = bench_exec or "run_query(&cols)"
    timing = _median_bench_loop(
        fmt=fmt,
        ret_type=ret_type,
        bench_call=bench_call,
        bench_timing_body=bench_timing_body,
        bench_post_timing=bench_post_timing,
    )
    return f"""
fn main() {{
    use std::env;
    use std::time::Instant;

    let args: Vec<String> = env::args().collect();
    let tbl_path = args
        .get(1)
        .map(|s| s.as_str())
        .unwrap_or("{default_tbl}");
    let limit: usize = args
        .get(2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50_000);

    let cols = load_cols(tbl_path, limit);
{bench_main_prefix}

    {timing}
    println!("{{}}", last);
}}
"""


def generate_main_join_rs(
    *,
    left_table: str,
    right_table: str,
    default_left_tbl: str,
    default_right_tbl: str,
    ret_type: str,
    bench_exec: str = "run_query(&left, &right)",
) -> str:
    cfg = RET_TYPE_CONFIG[ret_type]
    fmt = cfg["format_result"]
    left_struct = f"Cols_{left_table}"
    right_struct = f"Cols_{right_table}"
    load_left = f"load_cols_{left_table}"
    load_right = f"load_cols_{right_table}"
    return f"""
fn main() {{
    use std::env;
    use std::time::Instant;

    let args: Vec<String> = env::args().collect();
    let left_path = args
        .get(1)
        .map(|s| s.as_str())
        .unwrap_or("{default_left_tbl}");
    let right_path = args
        .get(2)
        .map(|s| s.as_str())
        .unwrap_or("{default_right_tbl}");
    let limit: usize = args
        .get(3)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50_000);

    let left = {load_left}(left_path, limit);
    let right = {load_right}(right_path, limit);

    {_median_bench_loop(fmt=fmt, ret_type=ret_type, bench_call=bench_exec)}
    println!("{{}}", last);
}}
"""


def assemble_verified_join_program(
    *,
    spec_rs: str,
    run_query_body: str,
    multi_schema: dict[str, dict[str, str]],
    table_order: tuple[str, str],
    ret_type: str,
    default_tbls: dict[str, str],
    hot_path_rs: str = "",
    bench_exec: str = "",
) -> str:
    """Build one `.rs` file for a two-table join query."""
    if ret_type not in RET_TYPE_CONFIG:
        raise ValueError(f"unknown ret_type: {ret_type}")

    left_table, right_table = table_order
    if left_table not in multi_schema or right_table not in multi_schema:
        raise ValueError(f"table_order {table_order} not in multi_schema keys")

    core = _strip_skeleton(spec_rs)
    boundary = _emit_agg_helpers(ret_type)
    loaders = "\n".join(
        generate_load_cols_verus(
            cols,
            struct_name=f"Cols_{table}",
            valid_fn=f"valid_cols_{table}",
            load_fn=f"load_cols_{table}",
        ).strip()
        for table, cols in multi_schema.items()
    )
    main_rs = generate_main_join_rs(
        left_table=left_table,
        right_table=right_table,
        default_left_tbl=default_tbls[left_table],
        default_right_tbl=default_tbls[right_table],
        ret_type=ret_type,
        bench_exec=bench_exec or "run_query(&left, &right)",
    )

    hot = f"{hot_path_rs.rstrip()}\n\n" if hot_path_rs else ""
    return (
        f"{core}\n"
        f"{boundary}\n"
        f"{run_query_body.rstrip()}\n\n"
        f"{loaders}\n"
        f"}} // verus!\n"
        f"{hot}"
        f"{main_rs}"
    )


def generate_main_nway_rs(
    *,
    table_order: tuple[str, ...],
    default_tbls: dict[str, str],
    ret_type: str,
    bench_exec: str = "",
) -> str:
    cfg = RET_TYPE_CONFIG[ret_type]
    fmt = cfg["format_result"]
    load_lines = []
    arg_names = []
    for i, table in enumerate(table_order):
        idx = i + 2
        default = default_tbls[table]
        load_lines.append(
            f"    let {table}_path = args.get({idx}).map(|s| s.as_str()).unwrap_or(\"{default}\");"
        )
        load_lines.append(
            f"    let {table} = load_cols_{table}({table}_path, limit);"
        )
        arg_names.append(f"&{table}")
    bench_call = bench_exec or f"run_query({', '.join(arg_names)})"
    return f"""
fn main() {{
    use std::env;
    use std::time::Instant;

    let args: Vec<String> = env::args().collect();
    let limit: usize = args
        .get(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(50_000);

{chr(10).join(load_lines)}

    {_median_bench_loop(fmt=fmt, ret_type=ret_type, bench_call=bench_call)}
    println!("{{}}", last);
}}
"""


def assemble_verified_nway_program(
    *,
    spec_rs: str,
    run_query_body: str,
    multi_schema: dict[str, dict[str, str]],
    table_order: tuple[str, ...],
    ret_type: str,
    default_tbls: dict[str, str],
    hot_path_rs: str = "",
    bench_exec: str = "",
) -> str:
    """Build one `.rs` file for an N-table (3+) join query."""
    if ret_type not in RET_TYPE_CONFIG:
        raise ValueError(f"unknown ret_type: {ret_type}")

    for table in table_order:
        if table not in multi_schema:
            raise ValueError(f"table {table!r} not in multi_schema")

    core = _strip_skeleton(spec_rs)
    boundary = _emit_agg_helpers(ret_type)
    loaders = "\n".join(
        generate_load_cols_verus(
            cols,
            struct_name=f"Cols_{table}",
            valid_fn=f"valid_cols_{table}",
            load_fn=f"load_cols_{table}",
        ).strip()
        for table, cols in multi_schema.items()
    )
    main_rs = generate_main_nway_rs(
        table_order=table_order,
        default_tbls=default_tbls,
        ret_type=ret_type,
        bench_exec=bench_exec,
    )
    hot = f"{hot_path_rs.rstrip()}\n\n" if hot_path_rs else ""
    return (
        f"{core}\n"
        f"{boundary}\n"
        f"{run_query_body.rstrip()}\n\n"
        f"{loaders}\n"
        f"}} // verus!\n"
        f"{hot}"
        f"{main_rs}"
    )


def assemble_verified_program(
    *,
    spec_rs: str,
    run_query_body: str,
    schema_dict: dict[str, str],
    ret_type: str,
    default_tbl: str,
    hot_path_rs: str = "",
    bench_exec: str = "",
    bench_timing_body: str = "",
    bench_post_timing: str = "",
    bench_main_prefix: str = "",
) -> str:
    """Build one `.rs` file: spec + proved run_query + load_cols + main."""
    if ret_type not in RET_TYPE_CONFIG:
        raise ValueError(f"unknown ret_type: {ret_type}")

    core = _strip_skeleton(spec_rs)
    boundary = _emit_agg_helpers(ret_type)
    load_cols = generate_load_cols_verus(schema_dict)
    main_rs = generate_main_rs(
        default_tbl=default_tbl,
        ret_type=ret_type,
        bench_exec=bench_exec,
        bench_timing_body=bench_timing_body,
        bench_post_timing=bench_post_timing,
        bench_main_prefix=bench_main_prefix,
    )
    hot = f"{hot_path_rs.rstrip()}\n\n" if hot_path_rs else ""

    return (
        f"{core}\n"
        f"{boundary}\n"
        f"{run_query_body.rstrip()}\n\n"
        f"{load_cols}\n"
        f"}} // verus!\n"
        f"{hot}"
        f"{main_rs}"
    )
