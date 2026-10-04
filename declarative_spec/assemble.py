"""Stitch declarative spec + agent body + host loaders."""

from __future__ import annotations

import re

_WIDTH = {
    "u64": 8,
    "i64": 8,
    "u32": 4,
    "i32": 4,
    "usize": 8,
    "i128": 16,
    "f64": 8,
}


def _insert_agent_uses(stitched: str, extra_uses: list[str]) -> str:
    """Place new vstd imports next to the host imports. Broadcast uses go inside verus!."""
    plain: list[str] = []
    broadcast: list[str] = []
    for line in extra_uses:
        if line in stitched:
            continue
        if line.startswith(("broadcast ", "pub broadcast ")):
            broadcast.append(line)
        else:
            plain.append(line)
    if broadcast:
        stitched = stitched.replace("verus! {", "verus! {\n" + "\n".join(broadcast), 1)
    if plain:
        stitched = stitched.replace("verus! {", "\n".join(plain) + "\nverus! {", 1)
    return stitched


def assemble_declarative_program(
    spec_rs: str,
    agent_body: str,
    *,
    column_bins: dict[str, str] | None = None,
    extra_uses: list[str] | None = None,
) -> str:
    start = spec_rs.find("// AGENT_EDIT_START")
    end = spec_rs.find("// AGENT_EDIT_END")
    if start == -1 or end == -1 or end < start:
        raise ValueError("AGENT_EDIT markers missing from spec")

    before = spec_rs[: start + len("// AGENT_EDIT_START")]
    after = spec_rs[end:]
    body_block = f"\n{agent_body.rstrip()}\n"
    stitched = before + body_block + after
    stitched = _insert_agent_uses(stitched, extra_uses or [])

    host_start = stitched.find("// HOST_LEMMAS_START")
    host_end = stitched.find("// HOST_LEMMAS_END")
    if host_start == -1 or host_end == -1 or host_end < host_start:
        raise ValueError("HOST_LEMMAS markers missing from spec")

    from declarative_spec.lemmas import float_error_lemmas_rs, integer_fit_lemmas_rs

    lemmas = integer_fit_lemmas_rs().rstrip() + "\n\n" + float_error_lemmas_rs().rstrip()
    inner_start = host_start + len("// HOST_LEMMAS_START")
    stitched = stitched[:inner_start] + "\n" + lemmas + "\n" + stitched[host_end:]

    m = re.search(r"verus!\s*\{", stitched)
    if not m:
        raise ValueError("verus! block not found")
    depth = 0
    verus_end = None
    for i in range(m.end() - 1, len(stitched)):
        if stitched[i] == "{":
            depth += 1
        elif stitched[i] == "}":
            depth -= 1
            if depth == 0:
                verus_end = i + 1
                break
    if verus_end is None:
        raise ValueError("unclosed verus! block")

    verus_part = stitched[:verus_end]

    structs = re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", verus_part, re.DOTALL)
    loaders: list[str] = []
    mains_load: list[str] = []
    mains_args: list[str] = []

    for struct_name, body in structs:
        table_suffix = struct_name.removeprefix("Cols_")
        fields = re.findall(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>", body)
        param_parts = [f"n_{table_suffix}: usize"]
        for fname, fty in fields:
            param_parts.append(f"{table_suffix}_{_local_ident(fname)}: Vec<{fty}>")
        params = ", ".join(param_parts)
        struct_fields = [f"n: n_{table_suffix}"] + [
            f"{fname}: {table_suffix}_{_local_ident(fname)}" for fname, _ in fields
        ]
        fn_name = f"load_cols_{table_suffix}"
        if column_bins is None:
            prelude = ""
            call_args = ", ".join("0" if i == 0 else "vec![]" for i in range(len(param_parts)))
        else:
            bin_path = column_bins.get(table_suffix)
            if not bin_path:
                raise ValueError(f"no column file for {table_suffix}")
            prelude, call_args = _read_column_prelude(bin_path, table_suffix, fields)
        loaders.append(
            f"""#[verifier::external_body]
fn {fn_name}({params}) -> (cols: {struct_name})
    ensures
        valid_cols_{table_suffix}(&cols),
{{
    {struct_name} {{ {", ".join(struct_fields)} }}
}}"""
        )
        col_var = f"cols_{table_suffix}"
        mains_load.append(f"{prelude}    let {col_var} = {fn_name}({call_args});")
        mains_args.append(f"&{col_var}")

    if mains_args:
        run_call = f"run_query({', '.join(mains_args)})"
    else:
        run_call = "run_query()"

    hex_fn = ""
    if column_bins is None:
        timed = f"""    let start = std::time::Instant::now();
    let _res = {run_call};
    let elapsed = start.elapsed();
    println!("QUERY_LATENCY_US: {{}}", elapsed.as_micros());
"""
    else:
        timed, hex_fn = _timed_runs(run_call, verus_part)
    main_fn = "fn main() {\n"
    main_fn += "\n".join(mains_load) + "\n"
    main_fn += timed
    main_fn += "}\n"

    # Loaders carry `ensures valid_cols`, so they stay inside verus!.
    # main is outside the timer and outside the verus block.
    closed = verus_part.rstrip()
    if not closed.endswith("}"):
        raise ValueError("verus block did not end at '}'")
    verus_with_loaders = closed[:-1] + "\n" + "\n\n".join(loaders) + "\n}\n"
    return verus_with_loaders + "\n" + hex_fn + main_fn


def _local_ident(fname: str) -> str:
    return fname.removeprefix("r#")


def _from_le(fty: str, bytes_var: str, off: str) -> str:
    width = _WIDTH[fty]
    return f"{fty}::from_le_bytes({bytes_var}[{off}..{off} + {width}].try_into().unwrap())"


def _read_column_prelude(path: str, suffix: str, fields: list[tuple[str, str]]) -> tuple[str, str]:
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    lines = [
        f'    let bytes_{suffix} = std::fs::read("{escaped}").expect("cols");',
        f"    let n_{suffix} = u64::from_le_bytes(bytes_{suffix}[0..8].try_into().unwrap()) as usize;",
        f"    let mut off_{suffix}: usize = 8;",
    ]
    args = [f"n_{suffix}"]
    for fname, fty in fields:
        var = f"{suffix}_{_local_ident(fname)}"
        lines.append(f"    let mut {var}: Vec<{fty}> = Vec::with_capacity(n_{suffix});")
        lines.append(f"    let mut j_{var}: usize = 0;")
        lines.append(f"    while j_{var} < n_{suffix} {{")
        if fty == "String":
            lines.append(
                f"        let len_{var} = u32::from_le_bytes(bytes_{suffix}[off_{suffix}..off_{suffix} + 4].try_into().unwrap()) as usize;"
            )
            lines.append(f"        off_{suffix} += 4;")
            lines.append(
                f"        let v_{var} = String::from_utf8(bytes_{suffix}[off_{suffix}..off_{suffix} + len_{var}].to_vec()).expect(\"utf8\");"
            )
            lines.append(f"        off_{suffix} += len_{var};")
        elif fty == "bool":
            lines.append(f"        let v_{var} = bytes_{suffix}[off_{suffix}] != 0;")
            lines.append(f"        off_{suffix} += 1;")
        elif fty in _WIDTH:
            width = _WIDTH[fty]
            lines.append(f"        let v_{var} = {_from_le(fty, f'bytes_{suffix}', f'off_{suffix}')};")
            lines.append(f"        off_{suffix} += {width};")
        else:
            raise ValueError(f"cannot load column type {fty}")
        lines.append(f"        {var}.push(v_{var});")
        lines.append(f"        j_{var} += 1;")
        lines.append("    }")
        args.append(var)
    return "\n".join(lines) + "\n", ", ".join(args)


def _out_row_fields(verus_part: str) -> list[tuple[str, str]]:
    match = re.search(r"pub struct OutRow\s*\{([^}]+)\}", verus_part)
    if not match:
        return []
    return re.findall(
        r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+([^,\n]+),",
        match.group(1),
    )


def _row_printer(run_call: str, fields: list[tuple[str, str]]) -> tuple[str, str]:
    placeholders: list[str] = []
    args: list[str] = []
    needs_hex = False
    for fname, fty in fields:
        access = f"res[i].{fname}"
        if fty == "String":
            needs_hex = True
            placeholders.append("{}")
            args.append(f"row_hex(&{access})")
        elif fty.startswith("Option<"):
            inner = fty[len("Option<") : -1]
            fmt_one = "{:.17}" if inner == "f64" else "{}"
            placeholders.append("{}")
            args.append(
                f'match {access} {{ Some(v) => format!("{fmt_one}", v), None => "NULL".to_string() }}'
            )
        elif fty == "f64":
            placeholders.append("{:.17}")
            args.append(access)
        elif fty == "bool":
            placeholders.append("{}")
            args.append(f"if {access} {{ 1u8 }} else {{ 0u8 }}")
        else:
            placeholders.append("{}")
            args.append(access)
    fmt = "ROW\\u{1f}" + "\\u{1f}".join(placeholders)
    hex_fn = ""
    if needs_hex:
        hex_fn = """fn row_hex(s: &str) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let bytes = s.as_bytes();
    let mut out = String::with_capacity(bytes.len() * 2);
    let mut i: usize = 0;
    while i < bytes.len() {
        let b = bytes[i];
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
        i += 1;
    }
    out
}

"""
    body = f"""    let res = {run_call};
    let mut i: usize = 0;
    while i < res.len() {{
        println!("{fmt}", {", ".join(args)});
        i += 1;
    }}
"""
    return hex_fn, body


def _timed_runs(run_call: str, verus_part: str) -> tuple[str, str]:
    fields = _out_row_fields(verus_part)
    dump = ""
    after = ""
    hex_fn = ""
    if fields:
        hex_fn, after = _row_printer(run_call, fields)
    else:
        caps = re.findall(r"pub const (KEY_CAP_[A-Za-z0-9_]+): usize", verus_part)
        if len(caps) == 1 and "HashMapWithView<u64, u64>" in verus_part:
            cap = caps[0]
            dump = f"""        if s == 4 {{
            let mut key: u64 = 0;
            while key < {cap} as u64 {{
                match res.get(&key) {{
                    Some(v) => println!("ROW {{}} {{}}", key, *v),
                    None => {{}}
                }}
                key += 1;
            }}
        }}
"""
    timed = f"""    let mut samples: [u128; 5] = [0, 0, 0, 0, 0];
    let mut s: usize = 0;
    while s < 5 {{
        let start = std::time::Instant::now();
        let res = {run_call};
        samples[s] = start.elapsed().as_micros();
{dump}        s = s + 1;
    }}
    let mut a: usize = 0;
    while a < 5 {{
        let mut b: usize = a + 1;
        while b < 5 {{
            if samples[b] < samples[a] {{
                let tmp = samples[a];
                samples[a] = samples[b];
                samples[b] = tmp;
            }}
            b = b + 1;
        }}
        a = a + 1;
    }}
    println!("QUERY_LATENCY_US: {{}}", samples[2]);
{after}"""
    return timed, hex_fn
