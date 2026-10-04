"""Stitch declarative spec + agent body + host loaders."""

from __future__ import annotations

import re

_WIDTH = {
    "u8": 1,
    "u16": 2,
    "u64": 8,
    "i64": 8,
    "u32": 4,
    "i32": 4,
    "usize": 8,
    "i128": 16,
    "f64": 8,
}


def _insert_helpers(stitched: str, helpers: str) -> str:
    """Put the agent's helper items between the host's helper markers, if the spec has them."""
    from declarative_spec.regions import HELPERS_END, HELPERS_START

    start = stitched.find(HELPERS_START)
    end = stitched.find(HELPERS_END)
    if not helpers.strip():
        return stitched
    if start == -1 or end == -1 or end < start:
        raise ValueError("AGENT_HELPERS markers missing from spec")
    inner = start + len(HELPERS_START)
    return stitched[:inner] + f"\n{helpers.strip()}\n" + stitched[end:]


def assemble_declarative_program(
    spec_rs: str,
    agent_body: str,
    *,
    helpers: str = "",
    column_bins: dict[str, str] | None = None,
    expected_rows: dict[str, int] | None = None,
) -> str:
    from declarative_spec.regions import EDIT_END, EDIT_START

    start = spec_rs.find(EDIT_START)
    end = spec_rs.find(EDIT_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError("AGENT_EDIT markers missing from spec")

    before = spec_rs[: start + len(EDIT_START)]
    after = spec_rs[end:]
    body_block = f"\n{agent_body.rstrip()}\n"
    stitched = before + body_block + after
    stitched = _insert_helpers(stitched, helpers)

    host_start = stitched.find("// HOST_LEMMAS_START")
    host_end = stitched.find("// HOST_LEMMAS_END")
    if host_start == -1 or host_end == -1 or host_end < host_start:
        raise ValueError("HOST_LEMMAS markers missing from spec")

    from declarative_spec.trusted_sets import current

    lemmas = current().lemmas_rs(stitched)
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
            prelude, call_args = _read_column_prelude(
                bin_path,
                table_suffix,
                fields,
                checks=_runtime_checks(verus_part, table_suffix, fields),
                expect_rows=(expected_rows or {}).get(table_suffix),
            )
        requires = _loader_requires(verus_part, table_suffix, fields)
        struct_init = ", ".join(
            [f"n: n_{table_suffix}"] + [f"{fname}: {table_suffix}_{_local_ident(fname)}" for fname, _ in fields]
        )
        loaders.append(
            f"""fn {fn_name}({params}) -> (cols: {struct_name})
    requires
{requires}
    ensures
        valid_cols_{table_suffix}(&cols),
{{
    {struct_name} {{ {struct_init} }}
}}"""
        )
        col_var = f"cols_{table_suffix}"
        mains_load.append(f"{prelude}    let {col_var} = {fn_name}({call_args});")
        mains_args.append(f"&{col_var}")

    join_cap_checks = _join_cap_checks(verus_part)
    if mains_args:
        # One argument per parameter: two aliases of one table (a self join) share one loaded struct.
        sig = re.search(r"pub fn run_query\(([^)]*)\)", verus_part)
        structs_in_sig = re.findall(r":\s*&Cols_([A-Za-z0-9_]+)", sig.group(1)) if sig else []
        args = [f"&cols_{suffix}" for suffix in structs_in_sig] or mains_args
        run_call = f"run_query({', '.join(args)})"
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
    main_fn += join_cap_checks
    main_fn += timed
    main_fn += "}\n"

    # Loaders are verified (`requires` lengths and catalog caps, `ensures valid_cols`).
    # The column-file reader in `main` is the only trusted part; it checks the `requires` at runtime.
    # main is outside the timer and outside the verus block.
    closed = verus_part.rstrip()
    if not closed.endswith("}"):
        raise ValueError("verus block did not end at '}'")
    verus_with_loaders = closed[:-1] + "\n" + "\n\n".join(loaders) + "\n}\n"
    return verus_with_loaders + "\n" + hex_fn + main_fn


_LEN_CONJ = re.compile(r"^[A-Za-z_]\w*\.(?:r#)?\w+@\.len\(\) == [A-Za-z_]\w*\.n as int$")


def _join_cap_checks(verus_part: str) -> str:
    """Rust ``assert!``s for every ``// JOIN_CAP`` line of the spec: the joined-tuple count is within the cap.

    Counted with a hash of the right table's key tuples, so it is linear. The same count is the spec fn the
    ``requires`` of ``run_query`` bounds, and what ``check.py`` measures on the database."""
    out = []
    for left, right, cols_l, cols_r, cap in re.findall(
        r"^// JOIN_CAP Cols_(\w+) Cols_(\w+) (\S+) (\S+) (\d+)$", verus_part, re.M
    ):
        kl = ", ".join(f"cols_{left}.{c}[i].clone()" for c in cols_l.split(","))
        kr = ", ".join(f"cols_{right}.{c}[j].clone()" for c in cols_r.split(","))
        out.append(
            "    {\n"
            "        let mut counts = std::collections::HashMap::new();\n"
            f"        for j in 0..cols_{right}.n {{ *counts.entry(({kr},)).or_insert(0u128) += 1; }}\n"
            "        let mut total: u128 = 0;\n"
            f"        for i in 0..cols_{left}.n {{ if let Some(c) = counts.get(&({kl},)) {{ total += *c; }} }}\n"
            f'        assert!(total <= {cap}u128, "join {left} x {right}: {{}} joined tuples exceed the catalog cap {cap}", total);\n'
            "    }\n"
        )
    return "".join(out)


def _valid_cols_conjuncts(verus_part: str, suffix: str) -> tuple[str, list[str]]:
    """Return the parameter name and the conjuncts of ``valid_cols_<suffix>``."""
    m = re.search(
        rf"pub open spec fn valid_cols_{re.escape(suffix)}\((\w+): &Cols_{re.escape(suffix)}\) -> bool \{{(.*?)\n\}}",
        verus_part,
        re.DOTALL,
    )
    if m is None:
        raise ValueError(f"valid_cols_{suffix} not found in spec")
    param, body = m.group(1), m.group(2)
    conj = [
        re.sub(r"^\s*&&&?\s*", "", chunk).strip()
        for chunk in re.split(r"\n\s*(?=&&)", body.strip())
        if chunk.strip()
    ]
    conj = [c for c in (re.sub(r"^&&&?\s*", "", c) for c in conj) if c]
    return param, conj


def _loader_requires(verus_part: str, suffix: str, fields: list[tuple[str, str]]) -> str:
    """Loader ``requires``: every ``valid_cols`` conjunct, restated over the loader parameters."""
    param, conj = _valid_cols_conjuncts(verus_part, suffix)
    lines: list[str] = []
    for fname, _fty in fields:
        if fname.endswith("__dict"):
            continue  # a dictionary has its own length: `valid_cols` relates it to the codes
        lines.append(f"        {suffix}_{_local_ident(fname)}@.len() == n_{suffix} as int,")
    for c in conj:
        if _LEN_CONJ.match(c):
            continue
        out = re.sub(rf"(?<![\w.]){re.escape(param)}\.n\b", f"n_{suffix}", c)
        for fname, _fty in fields:
            out = re.sub(
                rf"(?<![\w.]){re.escape(param)}\.{re.escape(fname)}@",
                f"{suffix}_{_local_ident(fname)}@",
                out,
            )
        if re.search(rf"(?<![\w.]){re.escape(param)}\.", out):
            raise ValueError(f"valid_cols_{suffix} conjunct mentions an unknown field: {c}")
        lines.append(f"        {out},")
    return "\n".join(lines)


def _runtime_checks(verus_part: str, suffix: str, fields: list[tuple[str, str]]) -> list[str]:
    """Rust ``assert!``s that make each non-length ``valid_cols`` conjunct true of the loaded data."""
    param, conj = _valid_cols_conjuncts(verus_part, suffix)
    types = {fname: fty for fname, fty in fields}
    out: list[str] = []
    p = re.escape(param)
    for c in conj:
        if _LEN_CONJ.match(c):
            continue
        m = re.fullmatch(rf"{p}\.n as int <= (ROW_CAP_\w+)(?: as int)?", c)
        if m:
            lit = _const_literal(verus_part, m.group(1))
            out.append(
                f'    assert!(n_{suffix} <= {lit}usize, "{suffix}: {{}} rows exceed the catalog cap {lit}", n_{suffix});'
            )
            continue
        m = re.fullmatch(
            rf"forall\|i: int\| 0 <= i < {p}\.n as int ==> (?:{p}\.((?:r#)?\w+)@\[i\] as int >= (-?\d+) && )?"
            rf"{p}\.((?:r#)?\w+)@\[i\] as int <= (\(?-?\d+\)?)",
            c,
        )
        if m:
            field = m.group(3)
            hi = int(m.group(4).strip("()"))
            var = f"{suffix}_{_local_ident(field)}"
            lo = f"{m.group(2)}i128" if m.group(1) else "i128::MIN"
            if hi > 2**127 - 1 or types[field] == "String":
                raise ValueError(f"cannot check integer bound on {suffix}.{field}: {c}")
            out.append(
                f"    assert!({var}.iter().all(|v| (*v as i128) >= {lo} && (*v as i128) <= {hi}i128), "
                f'"{suffix}.{_local_ident(field)}: value outside the catalog bound {hi}");'
            )
            continue
        m = re.fullmatch(
            rf"forall\|i: int\| #!\[trigger {p}\.((?:r#)?\w+)@\[i\]\] 0 <= i < {p}\.n as int ==> "
            rf"{p}\.(?:r#)?\w+@\[i\]\.is_finite_spec\(\)",
            c,
        )
        if m:
            var = f"{suffix}_{_local_ident(m.group(1))}"
            out.append(
                f"    assert!({var}.iter().all(|v| v.is_finite()), "
                f'"{suffix}.{_local_ident(m.group(1))}: a value is NaN or infinite");'
            )
            continue
        m = re.fullmatch(
            rf"forall\|i: int\| #!\[trigger {p}\.((?:r#)?\w+)@\[i\]\] 0 <= i < {p}\.n as int ==> "
            rf"-\((\w+) as real\) < \({p}\.(?:r#)?\w+@\[i\] as real\) < \(\2 as real\)",
            c,
        )
        if m:
            var = f"{suffix}_{_local_ident(m.group(1))}"
            const = m.group(2)
            out.append(
                f"    assert!({var}.iter().all(|v| v.abs() < ({const} as f64)), "
                f'"{suffix}.{_local_ident(m.group(1))}: value outside the catalog magnitude {const}");'
            )
            continue
        m = re.fullmatch(
            rf"forall\|i: int\| #!\[trigger {p}\.((?:r#)?\w+)@\[i\]\] 0 <= i < {p}\.n as int ==> "
            rf"\({p}\.\1@\[i\] as int\) < {p}\.\1__dict@\.len\(\)",
            c,
        )
        if m:
            codes, dct = f"{suffix}_{_local_ident(m.group(1))}", f"{suffix}_{_local_ident(m.group(1))}__dict"
            out.append(
                f'    assert!({codes}.iter().all(|c| (*c as usize) < {dct}.len()), "{suffix}.{_local_ident(m.group(1))}: a code is outside its dictionary");'
            )
            continue
        m = re.fullmatch(
            rf"forall\|a: int, b: int\| #!\[trigger {p}\.((?:r#)?\w+)__dict@\[a\]@, .*?\] "
            rf"0 <= a < b < {p}\.\1__dict@\.len\(\) ==> .*",
            c,
        )
        if m:
            dct = f"{suffix}_{_local_ident(m.group(1))}__dict"
            out.append(
                f'    assert!({dct}.iter().collect::<std::collections::HashSet<_>>().len() == {dct}.len(), "{suffix}.{_local_ident(m.group(1))}: a dictionary entry repeats");'
            )
            continue
        m = re.fullmatch(
            rf"forall\|i: int, j: int\| #!\[trigger .*?\] 0 <= i < j < {p}\.n as int ==> !\((.*)\)", c
        )
        if m:
            names = list(dict.fromkeys(re.findall(rf"{p}\.((?:r#)?\w+)@\[i\]", m.group(1))))
            vars_ = [f"{suffix}_{_local_ident(n)}" for n in names]
            key = ", ".join(f"{v}[i].clone()" for v in vars_)
            out.append(
                "    {\n"
                f"        let mut seen_{suffix} = std::collections::HashSet::new();\n"
                f"        for i in 0..n_{suffix} {{\n"
                f'            assert!(seen_{suffix}.insert(({key},)), "{suffix}: declared unique key ({", ".join(names)}) has a duplicate");\n'
                "        }\n    }"
            )
            continue
        raise ValueError(f"valid_cols_{suffix} has a conjunct the loader cannot check at runtime: {c}")
    return out


def _const_literal(verus_part: str, name: str) -> int:
    m = re.search(rf"pub (?:open spec )?const {re.escape(name)}: (?:int|usize|u64) = (\d+);", verus_part)
    if m is None:
        raise ValueError(f"constant {name} not found in spec")
    return int(m.group(1))


def _local_ident(fname: str) -> str:
    return fname.removeprefix("r#")


def _from_le(fty: str, bytes_var: str, off: str) -> str:
    width = _WIDTH[fty]
    return f"{fty}::from_le_bytes({bytes_var}[{off}..{off} + {width}].try_into().unwrap())"


def _read_column_prelude(
    path: str,
    suffix: str,
    fields: list[tuple[str, str]],
    *,
    checks: list[str] | None = None,
    expect_rows: int | None = None,
) -> tuple[str, str]:
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    lines = [
        f'    let bytes_{suffix} = std::fs::read("{escaped}").expect("cols");',
        f"    let n_{suffix} = u64::from_le_bytes(bytes_{suffix}[0..8].try_into().unwrap()) as usize;",
        f"    let mut off_{suffix}: usize = 8;",
    ]
    args = [f"n_{suffix}"]
    for fname, fty in fields:
        var = f"{suffix}_{_local_ident(fname)}"
        if fname.endswith("__dict"):
            # A dictionary: its own count (u64), then that many strings.
            lines.append(
                f"    let m_{var} = u64::from_le_bytes(bytes_{suffix}[off_{suffix}..off_{suffix} + 8].try_into().unwrap()) as usize;"
            )
            lines.append(f"    off_{suffix} += 8;")
            lines.append(f"    let mut {var}: Vec<{fty}> = Vec::with_capacity(m_{var});")
            lines.append(f"    let mut j_{var}: usize = 0;")
            lines.append(f"    while j_{var} < m_{var} {{")
        else:
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
    # Trusted reader: abort loudly unless the file is exactly what the loader `requires`.
    lines.append(
        f'    assert!(off_{suffix} == bytes_{suffix}.len(), "{suffix}: column file has trailing or missing bytes");'
    )
    if expect_rows is not None:
        lines.append(
            f'    assert!(n_{suffix} == {int(expect_rows)}usize, "{suffix}: loaded {{}} rows, DuckDB pin has {int(expect_rows)}", n_{suffix});'
        )
    for fname, _fty in fields:
        if fname.endswith("__dict"):
            continue
        var = f"{suffix}_{_local_ident(fname)}"
        lines.append(
            f'    assert!({var}.len() == n_{suffix}, "{suffix}.{_local_ident(fname)}: {{}} values for {{}} rows", {var}.len(), n_{suffix});'
        )
    lines.extend(checks or [])
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


def _string_map_dump(verus_part: str) -> tuple[str, str]:
    """Print a ``StringHashMap`` result: it cannot be iterated, so probe each key the column holds.

    One `ROW`, hex key, value line (unit-separated) per distinct key, as an OutRow prints; the key column is
    the one the run_query ``ensures`` ranges over (``cols.<field>@[j]@ == k``).
    """
    suffix = re.search(r"pub fn run_query\(cols: &Cols_(\w+)\)", verus_part)
    field = re.search(r"cols\.((?:r#)?\w+)@\[j\]@ == k", verus_part)
    if suffix is None or field is None:
        raise ValueError("a StringHashMap result needs a one-table run_query keyed by `cols.<field>@[j]@ == k`")
    keys = f"cols_{suffix.group(1)}.{field.group(1)}"
    dump = f"""        if s == 4 {{
            let mut seen: std::collections::HashSet<&str> = std::collections::HashSet::new();
            let mut printed: usize = 0;
            let mut r: usize = 0;
            while r < {keys}.len() {{
                let key = {keys}[r].as_str();
                if seen.insert(key) {{
                    let v = res.get(key).expect("a key of the column is missing from the result");
                    println!("ROW\\u{{1f}}{{}}\\u{{1f}}{{}}", row_hex(key), *v);
                    printed += 1;
                }}
                r += 1;
            }}
            assert!(printed == res.len(), "result has {{}} keys, the column has {{}} distinct", res.len(), printed);
        }}
"""
    hex_fn, _ = _row_printer("", [("k", "String")])
    return dump, hex_fn


def _timed_runs(run_call: str, verus_part: str) -> tuple[str, str]:
    fields = _out_row_fields(verus_part)
    dump = ""
    after = ""
    hex_fn = ""
    if fields:
        hex_fn, after = _row_printer(run_call, fields)
    elif re.search(r"-> \(res: StringHashMap<(u64|i64|i128)>\)", verus_part) is not None:
        dump, hex_fn = _string_map_dump(verus_part)
    else:
        caps = re.findall(r"pub const (KEY_CAP_[A-Za-z0-9_]+): usize", verus_part)
        shape = re.search(r"-> \(res: HashMapWithView<(u64|i64|i128), (u64|i64|i128)>\)", verus_part)
        if len(caps) == 1 and shape:
            cap = caps[0]
            key_ty = shape.group(1)
            dump = f"""        if s == 4 {{
            let mut key: {key_ty} = 0;
            let mut printed: usize = 0;
            while (key as i128) < {cap} as i128 {{
                match res.get(&key) {{
                    Some(v) => {{
                        println!("ROW {{}} {{}}", key, *v);
                        printed += 1;
                    }}
                    None => {{}}
                }}
                key += 1;
            }}
            assert!(printed == res.len(), "result has {{}} keys, only {{}} lie in 0..{cap}", res.len(), printed);
        }}
"""
        else:
            raise ValueError(
                "a timed run needs a printable result: an OutRow struct, or a HashMapWithView "
                "result with exactly one KEY_CAP; got neither, so the output could not be compared"
            )
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
