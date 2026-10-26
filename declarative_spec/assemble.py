"""Stitch declarative spec + agent body + host loaders."""

from __future__ import annotations

import re
from pathlib import Path

from declarative_spec import decline, parallel

# The timed measure is the MEDIAN of this many runs (odd). The shared box shows ~30 percent run-to-run noise.
TIMED_RUNS = 9

_WIDTH = {
    "u8": 1,
    "u16": 2,
    "u64": 8,
    "i64": 8,
    "u32": 4,
    "i32": 4,
    "i16": 2,
    "i8": 1,
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


def _fill_region(spec_rs: str, start_mark: str, end_mark: str, text: str) -> str:
    start = spec_rs.find(start_mark)
    end = spec_rs.find(end_mark)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"{start_mark.removeprefix('// ')} markers missing from spec")
    inner = start + len(start_mark)
    return spec_rs[:inner] + f"\n{text.strip()}\n" + spec_rs[end:]


def _stitch_verus(spec_rs: str, agent_body: str, helpers: str, *, state: str = "", build: str = "") -> str:
    """The spec with the agent body and helpers in their regions and the host lemmas pasted: the ``verus!`` part of the program.

    A stateful spec (``stateful.is_stateful``) also gets the agent's ``state`` types and ``build`` body in their regions
    (``agent_body`` is then the ``execute`` body)."""
    from declarative_spec import stateful
    from declarative_spec.regions import EDIT_END, EDIT_START

    if stateful.is_stateful(spec_rs):
        spec_rs = _fill_region(spec_rs, stateful.STATE_START, stateful.STATE_END, state)
        spec_rs = _fill_region(spec_rs, stateful.BUILD_START, stateful.BUILD_END, build)

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

    return stitched[:verus_end]


def assemble_declarative_program(
    spec_rs: str,
    agent_body: str,
    *,
    helpers: str = "",
    column_bins: dict[str, str] | None = None,
    expected_rows: dict[str, int] | None = None,
    state: str = "",
    build: str = "",
    serve: bool = False,
) -> str:
    """The program Verus checks and rustc compiles. A stateful spec (``stateful.is_stateful``) also takes the agent's
    ``state`` types and ``build`` body (``agent_body`` is then the ``execute`` body), and gets the fixed host runtime; with
    ``serve`` its ``main`` answers one call per stdin line (``<version> <column file per table>``) instead of the timed runs."""
    from declarative_spec import stateful

    from declarative_spec import stream

    if stream.is_stream(spec_rs):
        raise ValueError("a stream spec (lemma.toml [run] stream) has no run_query: use assemble_stream_program")
    is_stateful = stateful.is_stateful(spec_rs)
    if not is_stateful and (state.strip() or build.strip() or serve):
        raise ValueError("state / build / serve are for a stateful spec (lemma.toml `stateful`)")
    verus_part = _stitch_verus(spec_rs, agent_body, helpers, state=state, build=build)
    structs = re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", verus_part, re.DOTALL)
    loaders: list[str] = []
    mains_load: list[str] = []
    mains_args: list[str] = []

    for struct_name, body in structs:
        table_suffix = struct_name.removeprefix("Cols_")
        fields = re.findall(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>", body)
        param_parts = [f"n_{table_suffix}: usize"] + [f"{table_suffix}_{_local_ident(f)}: Vec<{t}>" for f, t in fields]
        fn_name = f"load_cols_{table_suffix}"
        if serve:
            prelude, call_args = _read_column_prelude(
                "",
                table_suffix,
                fields,
                checks=_runtime_checks(verus_part, table_suffix, fields),
                path_expr=f"path_{table_suffix}",
            )
        elif column_bins is None:
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
        loaders.append(_loader_fn(verus_part, struct_name, fields))
        col_var = f"cols_{table_suffix}"
        mains_load.append(f"{prelude}    let {col_var} = {fn_name}({call_args});")
        mains_args.append(f"&{col_var}")

    join_cap_checks = _join_cap_checks(verus_part)
    if is_stateful:
        return _assemble_stateful(
            verus_part, loaders, mains_load, join_cap_checks, column_bins is not None, serve, column_bins,
            scans_called="scan_where_" in "\n".join((agent_body, helpers, state, build)),
        )
    run_call, arc_lets = _run_call(verus_part, mains_args, column_bins)
    param_prelude, param_args = _param_prelude(verus_part)
    if param_args:
        run_call = run_call[:-1] + (", " if run_call != "run_query()" else "") + ", ".join(param_args) + ")"
    decline_const = ""
    if decline.is_decline_spec(verus_part):
        # assumptions = false: run_query returns Option and None declines (decline.py). The program says so on one line and exits with
        # the decline code before any result row or latency line, so no harness can mistake a decline for a result or a crash.
        decline_const = (
            f"// The exit code of a declined run (run_query returned None); the C ABI status of the same outcome is {decline.ABI_STATUS_DECLINED}.\n"
            f"const LEMMA_DECLINE_EXIT_CODE: i32 = {decline.DECLINE_EXIT_CODE};\n\n"
        )
        run_call = (
            f'match {run_call} {{ Some(v) => v, None => {{ println!("{decline.DECLINE_LINE}"); std::process::exit(LEMMA_DECLINE_EXIT_CODE); }} }}'
        )

    hex_fn = ""
    if column_bins is None:
        timed = f"""    let start = std::time::Instant::now();
    let _res = {run_call};
    let elapsed = start.elapsed();
    println!("QUERY_LATENCY_US: {{}}", elapsed.as_micros());
"""
    else:
        timed, hex_fn = _timed_runs(run_call, verus_part)
    main_fn = "fn main() {\n" + param_prelude
    if column_bins is not None:
        main_fn += "    let load_start = std::time::Instant::now();\n"
    main_fn += "\n".join(mains_load) + "\n"
    main_fn += join_cap_checks
    if column_bins is not None:
        # Reading the column files into the loaded vectors and checking the requirements: the host-side cost the timer excludes.
        main_fn += '    println!("LOAD_US: {}", load_start.elapsed().as_micros());\n'
    main_fn += arc_lets
    main_fn += timed
    main_fn += "}\n"

    # Loaders are verified (`requires` lengths and catalog caps, `ensures valid_cols`).
    # The column-file reader in `main` is the only trusted part; it checks the `requires` at runtime.
    # main is outside the timer and outside the verus block.
    closed = verus_part.rstrip()
    if not closed.endswith("}"):
        raise ValueError("verus block did not end at '}'")
    verus_with_loaders = closed[:-1] + "\n" + "\n\n".join(loaders) + "\n}\n"
    return verus_with_loaders + "\n" + decline_const + hex_fn + main_fn


def _param_prelude(verus_part: str) -> tuple[str, list[str]]:
    """Query-template parameters (``// PARAM`` lines of the spec, see ``declarative_spec/templates.py``): read each value from the
    command line, in run_query's order, and check the range run_query ``requires`` with a loud ``assert!``, like the data checks.
    Returns the code and the arguments to append to the run_query call."""
    from declarative_spec.templates import spec_params

    params = spec_params(verus_part)
    if not params:
        return "", []
    names = ", ".join(name for name, _ty, _lo, _hi in params)
    lines = [
        "    let lemma_param_argv: Vec<String> = std::env::args().collect();",
        f'    assert!(lemma_param_argv.len() == {len(params) + 1}, "expected {len(params)} query parameter values ({names}) on the command line, got {{}}", lemma_param_argv.len() - 1);',
    ]
    args: list[str] = []
    for index, (name, ty, lo, hi) in enumerate(params, start=1):
        var = f"param_{name}"
        if ty == "String":
            lines.append(f"    let {var}: String = lemma_param_argv[{index}].clone();")
            args.append(f"&{var}")
            continue
        lines.append(f'    let {var}: {ty} = lemma_param_argv[{index}].parse::<{ty}>().expect("parameter {name}: not a {ty}");')
        lines.append(
            f'    assert!(({var} as i128) >= {lo}i128 && ({var} as i128) <= {hi}i128, "parameter {name} = {{}} is outside its declared range [{lo}, {hi}]", {var});'
        )
        args.append(var)
    return "\n".join(lines) + "\n", args


def _loader_fn(verus_part: str, struct_name: str, fields: list[tuple[str, str]]) -> str:
    """The verified loader of one column struct: ``requires`` every ``valid_cols`` conjunct over its parameters, ``ensures valid_cols``."""
    table_suffix = struct_name.removeprefix("Cols_")
    param_parts = [f"n_{table_suffix}: usize"] + [f"{table_suffix}_{_local_ident(fname)}: Vec<{fty}>" for fname, fty in fields]
    requires = _loader_requires(verus_part, table_suffix, fields)
    struct_init = ", ".join(
        [f"n: n_{table_suffix}"] + [f"{fname}: {table_suffix}_{_local_ident(fname)}" for fname, _ in fields]
    )
    return f"""fn load_cols_{table_suffix}({", ".join(param_parts)}) -> (cols: {struct_name})
    requires
{requires}
    ensures
        valid_cols_{table_suffix}(&cols),
{{
    {struct_name} {{ {struct_init} }}
}}"""


def _run_call(verus_part: str, mains_args: list[str], column_bins: dict[str, str] | None = None) -> tuple[str, str]:
    """``(the run_query call, the Arc and scan-handle lets it needs)`` over the loaded ``cols_<suffix>`` structs."""
    if not mains_args:
        return "run_query()", ""
    # One argument per parameter: two aliases of one table (a self join) share one loaded struct.
    sig = re.search(r"pub fn run_query\(([^)]*)\)", verus_part)
    structs_in_sig = re.findall(r":\s*&Cols_([A-Za-z0-9_]+)", sig.group(1)) if sig else []
    args = [f"&cols_{suffix}" for suffix in structs_in_sig] or mains_args
    arc_lets = ""
    if parallel.is_parallel(verus_part):
        # The same object twice: `&*arc` and `&arc`, so `**arc == *cols` holds by construction.
        arc_lets = "".join(
            f"    let arc_{suffix} = std::sync::Arc::new(cols_{suffix});\n" for suffix in dict.fromkeys(structs_in_sig)
        )
        args = [f"&*arc_{suffix}" for suffix in structs_in_sig] + [f"&arc_{suffix}" for suffix in structs_in_sig]
    # Agent scans (declarative_spec/agent_scan.py): one handle per table, over the directory of that table's column file.
    for suffix in re.findall(r":\s*&Scan_([A-Za-z0-9_]+)", sig.group(1)) if sig else []:
        scan_dir = "" if column_bins is None else str(Path(column_bins[suffix]).parent)
        escaped = scan_dir.replace("\\", "\\\\").replace('"', '\\"')
        arc_lets += f'    let scan_{suffix} = scan_open_{suffix}("{escaped}");\n'
        args.append(f"&scan_{suffix}")
    return f"run_query({', '.join(args)})", arc_lets


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
        if c == f"{param}.n as int <= 0x7fff_ffff_ffff_ffffint":
            # assumptions = false: the structural row bound (a Vec holds at most isize::MAX elements), checked like the lengths.
            out.append(f'    assert!(n_{suffix} <= isize::MAX as usize, "{suffix}: {{}} rows exceed isize::MAX", n_{suffix});')
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
        m = re.fullmatch(rf"{p}\.((?:r#)?\w+)__dict@\.len\(\) <= (\d+)", c)
        if m:
            dct = f"{suffix}_{_local_ident(m.group(1))}__dict"
            out.append(
                f'    assert!({dct}.len() <= {m.group(2)}, "{suffix}.{_local_ident(m.group(1))}: the dictionary has more entries than the catalog distinct cap {m.group(2)}");'
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
    path_expr: str | None = None,
) -> tuple[str, str]:
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    source = f"&{path_expr}" if path_expr is not None else f'"{escaped}"'
    lines = [
        f'    let bytes_{suffix} = std::fs::read({source}).expect("cols");',
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


def _read_stream_prelude(path: str, suffix: str, fields: list[tuple[str, str]], *, checks: list[str]) -> str:
    """The binary-mode stream main's reader of the same column file as ``_read_column_prelude`` (n, then each column in Cols order),
    read front to back through a buffer instead of whole: a fixed-width column becomes ``Vec<ty>``, a VARCHAR column ``<var>: Vec<u32>``
    (one code per row) plus ``<var>_dict: Vec<String>`` (its distinct strings). Same loud checks (exact length, the ``valid_cols``
    conjuncts in ``checks``)."""
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    lines = [
        "    use std::io::Read as _;",
        f'    let mut rd_{suffix} = std::io::BufReader::with_capacity(1 << 22, std::fs::File::open("{escaped}").expect("cols"));',
        f"    let n_{suffix} = u64::from_le_bytes(lemma_read_bytes(&mut rd_{suffix}, 8)[..].try_into().unwrap()) as usize;",
    ]
    for fname, fty in fields:
        var = f"{suffix}_{_local_ident(fname)}"
        if fname.endswith("__dict"):
            raise ValueError("a stream table has plain strings (no dictionary column)")
        if fty == "String":
            lines.append(f'    let ({var}, {var}_dict) = lemma_read_strings(&mut rd_{suffix}, n_{suffix}, "{suffix}.{_local_ident(fname)}");')
        elif fty == "bool":
            lines.append(f"    let {var}: Vec<bool> = lemma_read_bytes(&mut rd_{suffix}, n_{suffix}).iter().map(|&x| x != 0).collect();")
        elif fty in _WIDTH:
            width = _WIDTH[fty]
            lines.append(
                f"    let {var}: Vec<{fty}> = lemma_read_bytes(&mut rd_{suffix}, n_{suffix} * {width}).chunks_exact({width})"
                f".map(|x| {fty}::from_le_bytes(x.try_into().unwrap())).collect();"
            )
        else:
            raise ValueError(f"cannot load column type {fty}")
    lines.append(
        f'    assert!(rd_{suffix}.read(&mut [0u8; 1]).expect("cols") == 0, "{suffix}: column file has trailing or missing bytes");'
    )
    for fname, _fty in fields:
        var = f"{suffix}_{_local_ident(fname)}"
        lines.append(f'    assert!({var}.len() == n_{suffix}, "{suffix}.{_local_ident(fname)}: {{}} values for {{}} rows", {var}.len(), n_{suffix});')
    lines.extend(checks)
    return "\n".join(lines) + "\n"


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
            placeholders.append("{}")
            if inner == "String":
                needs_hex = True
                shown = "row_hex(v)"
            elif inner == "bool":
                shown = 'format!("{}", if *v { 1u8 } else { 0u8 })'
            elif inner == "Rat":
                shown = 'format!("{:.17}", (v.num as f64) / (v.den as f64))'
            else:
                fmt_one = "{:.17}" if inner == "f64" else "{}"
                shown = f'format!("{fmt_one}", v)'
            args.append(f'match &{access} {{ Some(v) => {shown}, None => "NULL".to_string() }}')
        elif fty == "f64":
            placeholders.append("{:.17}")
            args.append(access)
        elif fty == "Rat":
            # An exact rational (lemma.toml [sql] exact_division) printed as DuckDB's DOUBLE: num / den in IEEE double,
            # outside the proof. den == 0 gives +inf, -inf or NaN by the sign of num, as DuckDB's division by zero does.
            placeholders.append("{:.17}")
            args.append(f"({access}.num as f64) / ({access}.den as f64)")
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
    suffix = re.search(r"pub fn run_query\(cols: &Cols_(\w+)(?:, cols_scan: &Scan_\1)?\)", verus_part)
    field = re.search(r"cols\.((?:r#)?\w+)@\[j\]@ == k", verus_part)
    if suffix is None or field is None:
        raise ValueError("a StringHashMap result needs a one-table run_query keyed by `cols.<field>@[j]@ == k`")
    keys = f"cols_{suffix.group(1)}.{field.group(1)}"
    dump = f"""        if s == {TIMED_RUNS - 1} {{
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
    elif re.search(r"-> \(res: (?:Option<)?StringHashMap<(u64|i64|i128)>>?\)", verus_part) is not None:
        dump, hex_fn = _string_map_dump(verus_part)
    else:
        caps = re.findall(r"pub const (KEY_CAP_[A-Za-z0-9_]+): usize", verus_part)
        shape = re.search(r"-> \(res: (?:Option<)?HashMapWithView<(u64|i64|i128), (u64|i64|i128)>>?\)", verus_part)
        if len(caps) == 1 and shape:
            cap = caps[0]
            key_ty = shape.group(1)
            dump = f"""        if s == {TIMED_RUNS - 1} {{
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
    timed = f"""    let mut samples: [u128; {TIMED_RUNS}] = [0; {TIMED_RUNS}];
    let mut s: usize = 0;
    while s < {TIMED_RUNS} {{
        let start = std::time::Instant::now();
        let res = {run_call};
        samples[s] = start.elapsed().as_micros();
{dump}        s = s + 1;
    }}
    let mut a: usize = 0;
    while a < {TIMED_RUNS} {{
        let mut b: usize = a + 1;
        while b < {TIMED_RUNS} {{
            if samples[b] < samples[a] {{
                let tmp = samples[a];
                samples[a] = samples[b];
                samples[b] = tmp;
            }}
            b = b + 1;
        }}
        a = a + 1;
    }}
    println!("QUERY_LATENCY_US: {{}}", samples[{TIMED_RUNS // 2}]);
    println!("QUERY_LATENCY_BEST_US: {{}}", samples[0]);
    println!("TIMED_RUNS: {TIMED_RUNS}");
{after}"""
    return timed, hex_fn


def _indent(text: str, extra: int) -> str:
    pad = " " * extra
    return "\n".join(pad + line if line.strip() else line for line in text.rstrip("\n").splitlines())


def _assemble_stateful(
    verus_part: str,
    loaders: list[str],
    mains_load: list[str],
    join_cap_checks: str,
    loaded: bool,
    serve: bool,
    column_bins: dict[str, str] | None = None,
    scans_called: bool = False,
) -> str:
    """Verus part + loaders + the fixed host runtime (``stateful.runtime_rs``), and a ``main`` that drives the runtime.

    Measure ``main``: load, ``refresh`` once at version 0 (``STATE_BUILD_US``, outside the timer), then the timed runs of
    ``execute_at(0)``. Serve ``main``: per stdin line ``<version> <file per table in SERVE_TABLES order>``, read the files and
    ``refresh`` only when the version is not the one the state was built at (``BUILT 1``; else ``BUILT 0``), then answer.
    """
    from declarative_spec import stateful

    c = stateful.contract(verus_part)
    suffix_of = {name: struct.removeprefix("Cols_") for name, struct in c.tables}
    if c.params:
        raise ValueError("stateful main: runtime parameters need a caller that supplies them (the template driver); none here")
    refresh_args = ", ".join(f"cols_{suffix_of[n]}" for n, _s in c.tables)
    scan_lets = ""
    if c.scans:
        # Agent scans in build (agent_scan.py): one handle per table over the directory of its column file, as for run_query.
        if serve and scans_called:
            raise ValueError(
                "stateful serve mode with a build that calls scan_where is not supported: a scan handle reads the prepared export "
                "directory of one data version, and serve mode refreshes on other versions' files (set agent_scan = false)"
            )
        for _n, scan_struct in c.scans:
            suffix = scan_struct.removeprefix("Scan_")
            # serve mode: the agent code never calls scan_where (checked above), so the handle is never read; an empty directory
            scan_dir = "" if column_bins is None or serve else str(Path(column_bins[suffix]).parent)
            escaped = scan_dir.replace("\\", "\\\\").replace('"', '\\"')
            scan_lets += f'    let scan_{suffix} = scan_open_{suffix}("{escaped}");\n'
        refresh_args += "".join(f", &scan_{s.removeprefix('Scan_')}" for _n, s in c.scans)
    closed = verus_part.rstrip()
    if not closed.endswith("}"):
        raise ValueError("verus block did not end at '}'")
    verus_all = closed[:-1] + "\n" + stateful.runtime_rs(verus_part) + "\n" + "\n\n".join(loaders) + "\n}\n"
    fields = _out_row_fields(verus_part)
    answer = 'rt.execute_at({v}).expect("the state was built at this version")'
    decline_const = ""
    if c.declines:
        # assumptions = false: execute returns Option and None declines (decline.py); same line and exit code as a run_query decline.
        decline_const = (
            f"// The exit code of a declined run (execute returned None); the C ABI status of the same outcome is {decline.ABI_STATUS_DECLINED}.\n"
            f"const LEMMA_DECLINE_EXIT_CODE: i32 = {decline.DECLINE_EXIT_CODE};\n\n"
        )
    if serve:
        if not fields:
            raise ValueError("stateful serve mode prints OutRow results only")
        hex_fn, rows = _row_printer("answer", fields)
        if c.declines:  # one call declined: say so on its own line; the server keeps serving
            served = f"""        let answered = {answer.format(v="version")};
        println!("EXEC_US: {{}}", start.elapsed().as_micros());
        match answered {{
            Some(answer) => {{
{_indent(rows, 12)}
            }}
            None => {{
                println!("{decline.DECLINE_LINE}");
            }}
        }}"""
        else:
            served = f"""        let answer = {answer.format(v="version")};
        println!("EXEC_US: {{}}", start.elapsed().as_micros());
{_indent(rows, 4)}"""
        order = [suffix_of[n] for n, _s in c.tables]
        paths = "".join(f"            let path_{sfx} = words[{i + 1}].to_string();\n" for i, sfx in enumerate(order))
        loads = "\n".join(_indent(block, 8) for block in mains_load)
        main_fn = f"""fn main() {{
    use std::io::BufRead;
    use std::io::Write;
    let stdin = std::io::stdin();
{scan_lets}    let mut rt = QRuntime::new();
    println!("SERVE_TABLES: {' '.join(order)}");
    std::io::stdout().flush().unwrap();
    for line in stdin.lock().lines() {{
        let line = line.expect("stdin");
        let words: Vec<&str> = line.split_whitespace().collect();
        if words.is_empty() {{
            continue;
        }}
        assert!(words.len() == {1 + len(order)}, "a call is: <version> then one column file per table ({' '.join(order)})");
        let version: u64 = words[0].parse().expect("version is a u64");
        if rt.is_current(version) {{
            println!("BUILT 0");
        }} else {{
{paths}{loads}
{_indent(join_cap_checks, 8)}
            let build_start = std::time::Instant::now();
            rt.refresh(version, {refresh_args});
            println!("BUILT 1");
            println!("STATE_BUILD_US: {{}}", build_start.elapsed().as_micros());
        }}
        let start = std::time::Instant::now();
{served}
        println!("END");
        std::io::stdout().flush().unwrap();
    }}
}}
"""
        return verus_all + "\n" + decline_const + hex_fn + main_fn
    if not fields and re.search(r"-> \(res: (?:Option<)?StringHashMap<", verus_part):
        raise ValueError("a stateful spec with a StringHashMap result has no printer (the key column moved into the state)")
    run_call = answer.format(v="0")
    if c.declines:
        run_call = (
            f'match {run_call} {{ Some(v) => v, None => {{ println!("{decline.DECLINE_LINE}"); std::process::exit(LEMMA_DECLINE_EXIT_CODE); }} }}'
        )
    if loaded:
        timed, hex_fn = _timed_runs(run_call, verus_part)
    else:
        hex_fn = ""
        timed = f"""    let start = std::time::Instant::now();
    let _res = {run_call};
    let elapsed = start.elapsed();
    println!("QUERY_LATENCY_US: {{}}", elapsed.as_micros());
"""
    main_fn = "fn main() {\n"
    if loaded:
        main_fn += "    let load_start = std::time::Instant::now();\n"
    main_fn += "\n".join(mains_load) + "\n" + join_cap_checks
    if loaded:
        main_fn += '    println!("LOAD_US: {}", load_start.elapsed().as_micros());\n'
    main_fn += scan_lets + (
        "    let mut rt = QRuntime::new();\n"
        "    let build_start = std::time::Instant::now();\n"
        f"    rt.refresh(0, {refresh_args});\n"
        '    println!("STATE_BUILD_US: {}", build_start.elapsed().as_micros());\n'
    )
    main_fn += timed + "}\n"
    return verus_all + "\n" + decline_const + hex_fn + main_fn


# ---- streaming executors (lemma.toml [run] stream, declarative_spec/stream.py) ---------------------------------------------------

STREAM_DEFAULT_CHUNK_MAX = 2048
STREAM_DEFAULT_THREADS = 4
STREAM_DEFAULT_SEED = 1


def _stitch_stream(spec_rs: str, regions: dict[str, str]) -> str:
    """The stream spec with the agent's six regions filled and the host lemmas pasted: the ``verus!`` part of the program."""
    from declarative_spec import stream
    from declarative_spec.regions import HELPERS_END, HELPERS_START, STATE_END, STATE_START
    from declarative_spec.trusted_sets import current

    text = _fill_region(spec_rs, STATE_START, STATE_END, regions["state"])
    text = _fill_region(text, HELPERS_START, HELPERS_END, regions["helpers"])
    for name, (start, end) in stream.BODY_REGIONS.items():
        text = _fill_region(text, start, end, regions[name])
    host_start = text.find("// HOST_LEMMAS_START")
    host_end = text.find("// HOST_LEMMAS_END")
    if host_start == -1 or host_end == -1 or host_end < host_start:
        raise ValueError("HOST_LEMMAS markers missing from spec")
    inner = host_start + len("// HOST_LEMMAS_START")
    text = text[:inner] + "\n" + current().lemmas_rs(text) + "\n" + text[host_end:]
    m = re.search(r"verus!\s*\{", text)
    if not m:
        raise ValueError("verus! block not found")
    depth = 0
    for i in range(m.end() - 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[: i + 1]
    raise ValueError("unclosed verus! block")


def assemble_stream_program(spec_rs: str, regions: dict[str, str], *, column_bins: dict[str, str] | None = None) -> str:
    """A stream spec (``stream.is_stream``) + the agent's regions (state, helpers, init, step, merge, finish) + the binary-mode ``main``.

    The ``main`` (plain Rust, outside ``verus!``; with the column-file reader it is the only host code here that is not proved)
    reads the column file (the existing format) and checks ``valid_cols`` on it (what S2 claims), cuts the rows into chunks of
    random sizes in ``[1, chunk_max]`` (alternately FLAT and dictionary-style VARCHAR entries, so both string forms are run), and in
    each timed run lets ``threads`` workers take chunk indices from one atomic counter and drive the ``Exec`` API (``exec_new`` /
    ``exec_step``), then merges the workers' executors (``exec_merge``) and calls ``exec_finish``. Command line: the template
    parameters (as for ``run_query``), then optionally ``<chunk_max> <threads> <seed>``. A decline prints ``LEMMA_DECLINED`` and exits
    with the decline code; an error of the glue or the scheduling (``StreamOut::Error``) panics."""
    from declarative_spec import stream
    from declarative_spec.templates import spec_params

    if not stream.is_stream(spec_rs):
        raise ValueError("not a stream spec (lemma.toml [run] stream)")
    verus_part = _stitch_stream(spec_rs, regions)
    structs = re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", verus_part, re.DOTALL)
    if len(structs) != 1:
        raise ValueError("a stream program reads one table")
    struct_name, body = structs[0]
    ts = struct_name.removeprefix("Cols_")
    fields = re.findall(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>", body)
    if column_bins is None:
        load = f"    let n_{ts}: usize = 0;\n" + "".join(
            f"    let {ts}_{_local_ident(f)}: Vec<{'u32' if t == 'String' else t}> = Vec::new();\n"
            + (f"    let {ts}_{_local_ident(f)}_dict: Vec<String> = Vec::new();\n" if t == "String" else "")
            for f, t in fields
        )
    else:
        bin_path = column_bins.get(ts)
        if not bin_path:
            raise ValueError(f"no column file for {ts}")
        load = _read_stream_prelude(bin_path, ts, fields, checks=_runtime_checks(verus_part, ts, fields))
    # every distinct string of a VARCHAR column once, as DuckDB's string_t (inline up to 12 bytes, else pointing into the String's buffer)
    load += "".join(
        f"    let {ts}_{_local_ident(f)}_raws: Vec<StrRaw> = {ts}_{_local_ident(f)}_dict.iter().map(|s| lemma_str_raw(s)).collect();\n"
        for f, t in fields
        if t == "String"
    )
    params = spec_params(verus_part)
    np = len(params)
    names = ", ".join(n for n, _t, _lo, _hi in params)
    prelude = [
        "    let lemma_argv: Vec<String> = std::env::args().collect();",
        f'    assert!(lemma_argv.len() == {np + 1} || lemma_argv.len() == {np + 4}, "expected {np} query parameter values ({names}), then optionally <chunk_max> <threads> <seed>");',
    ]
    inits = []
    for index, (name, ty, lo, hi) in enumerate(params, start=1):
        if ty == "String":
            raise ValueError("a stream spec has no VARCHAR template parameter")
        prelude.append(f'    let param_{name}: {ty} = lemma_argv[{index}].parse::<{ty}>().expect("parameter {name}: not a {ty}");')
        if lo is not None and hi is not None:
            prelude.append(
                f'    assert!((param_{name} as i128) >= {lo}i128 && (param_{name} as i128) <= {hi}i128, "parameter {name} = {{}} is outside its declared range [{lo}, {hi}]", param_{name});'
            )
        inits.append(f"{name}: param_{name}")
    prelude.append(
        f"    let (lemma_chunk_max, lemma_threads, lemma_seed): (usize, usize, u64) = if lemma_argv.len() == {np + 4} {{\n"
        f'        (lemma_argv[{np + 1}].parse().expect("chunk_max"), lemma_argv[{np + 2}].parse().expect("threads"), lemma_argv[{np + 3}].parse().expect("seed"))\n'
        f"    }} else {{\n        ({STREAM_DEFAULT_CHUNK_MAX}, {STREAM_DEFAULT_THREADS}, {STREAM_DEFAULT_SEED})\n    }};\n"
        '    assert!(lemma_chunk_max >= 1 && lemma_threads >= 1, "chunk_max and threads must be at least 1");'
    )
    params_init = f"Params {{ {', '.join(inits)} }}"
    # per chunk: one RawChunk with one address per column; VARCHAR columns get their sel / entries buffers built here
    str_cols = [f for f, t in fields if t == "String"]
    str_bufs = "".join(
        f"        let (sel_{_local_ident(f)}, ents_{_local_ident(f)}) = lemma_str_chunk(&{ts}_{_local_ident(f)}[off..off + len], &{ts}_{_local_ident(f)}_raws, c % 2 == 1);\n"
        for f in str_cols
    )
    raw_fields = []
    for f, t in fields:
        v = f"{ts}_{_local_ident(f)}"
        if t == "String":
            raw_fields += [
                f"{_local_ident(f)}_sel: sel_{_local_ident(f)}.as_ptr() as usize",
                f"{_local_ident(f)}_ents: ents_{_local_ident(f)}.as_ptr() as usize",
                f"{_local_ident(f)}_nents: ents_{_local_ident(f)}.len() as u64",
                f"{_local_ident(f)}_dict: if c % 2 == 1 {{ c as u64 + 1 }} else {{ 0 }}",
            ]
        else:
            raw_fields.append(f"{_local_ident(f)}: {v}[off..].as_ptr() as usize")
    keep = "".join(f"        lemma_keep.push((sel_{_local_ident(f)}, ents_{_local_ident(f)}));\n" for f in str_cols)
    fields_out = _out_row_fields(verus_part)
    hex_fn, rows = _row_printer("lemma_rows", fields_out)
    main_fn = f"""// ---- binary-mode stream main (lemma.toml [run] stream): plain Rust, not proved ----

// xorshift64*: the chunk sizes (reproducible from the seed)
fn lemma_next(s: &mut u64) -> u64 {{
    *s ^= *s >> 12;
    *s ^= *s << 25;
    *s ^= *s >> 27;
    s.wrapping_mul(0x2545_f491_4f6c_dd1d)
}}

// DuckDB's string_t for one string (the bytes stay where they are: the column vector owns them).
fn lemma_str_raw(s: &str) -> StrRaw {{
    let b = s.as_bytes();
    let mut w = [0u8; 16];
    w[0..4].copy_from_slice(&(b.len() as u32).to_le_bytes());
    if b.len() <= 12 {{
        w[4..4 + b.len()].copy_from_slice(b);
    }} else {{
        w[4..8].copy_from_slice(&b[0..4]);
        w[8..16].copy_from_slice(&(b.as_ptr() as u64).to_le_bytes());
    }}
    StrRaw {{ w0: u64::from_le_bytes(w[0..8].try_into().unwrap()), w1: u64::from_le_bytes(w[8..16].try_into().unwrap()) }}
}}

// One chunk of a VARCHAR column (its rows as codes into the column's distinct strings `raws`): FLAT (one entry per row, sel the
// identity) or dictionary-style (the chunk's distinct entries, sel into them).
fn lemma_str_chunk(codes: &[u32], raws: &[StrRaw], dict: bool) -> (Vec<u32>, Vec<StrRaw>) {{
    let mut sel = Vec::with_capacity(codes.len());
    let mut ents = Vec::new();
    if dict {{
        let mut seen: std::collections::HashMap<u32, u32> = std::collections::HashMap::new();
        for &code in codes {{
            let next = ents.len() as u32;
            let j = *seen.entry(code).or_insert(next);
            if j == next {{
                let e = &raws[code as usize];
                ents.push(StrRaw {{ w0: e.w0, w1: e.w1 }});
            }}
            sel.push(j);
        }}
    }} else {{
        for (r, &code) in codes.iter().enumerate() {{
            let e = &raws[code as usize];
            ents.push(StrRaw {{ w0: e.w0, w1: e.w1 }});
            sel.push(r as u32);
        }}
    }}
    (sel, ents)
}}

// The column file, read front to back (it is column-major in Cols order): fixed-width columns as Vecs; a VARCHAR column as one u32
// code per row into its distinct strings, so the main does not hold one String per row (SF10 lineitem: 120M of them).
fn lemma_read_bytes(rd: &mut impl std::io::Read, n: usize) -> Vec<u8> {{
    let mut b = vec![0u8; n];
    rd.read_exact(&mut b).expect("cols: column file is shorter than its header says");
    b
}}

fn lemma_read_strings(rd: &mut impl std::io::Read, n: usize, what: &str) -> (Vec<u32>, Vec<String>) {{
    let mut codes: Vec<u32> = Vec::with_capacity(n);
    let mut dict: Vec<String> = Vec::new();
    let mut idx: std::collections::HashMap<Vec<u8>, u32> = std::collections::HashMap::new();
    let mut buf: Vec<u8> = Vec::new();
    let mut lb = [0u8; 4];
    for _ in 0..n {{
        rd.read_exact(&mut lb).expect("cols: column file is shorter than its header says");
        let len = u32::from_le_bytes(lb) as usize;
        buf.resize(len, 0);
        rd.read_exact(&mut buf).expect("cols: column file is shorter than its header says");
        let code = match idx.get(&buf[..]) {{
            Some(&c) => c,
            None => {{
                assert!(dict.len() < u32::MAX as usize, "{{}}: more than u32::MAX distinct strings", what);
                let c = dict.len() as u32;
                dict.push(String::from_utf8(buf.clone()).expect("utf8"));
                idx.insert(buf.clone(), c);
                c
            }}
        }};
        codes.push(code);
    }}
    (codes, dict)
}}

fn main() {{
{chr(10).join(prelude)}
    let lemma_p = {params_init};
    let load_start = std::time::Instant::now();
{load}    println!("LOAD_US: {{}}", load_start.elapsed().as_micros());
    // the chunks: random sizes in [1, chunk_max], in row order; chunk c is [off, off + len)
    let mut lemma_rng: u64 = lemma_seed.wrapping_mul(0x9e37_79b9_7f4a_7c15) | 1;
    let mut lemma_raws: Vec<RawChunk_{ts}> = Vec::new();
    let mut lemma_keep: Vec<(Vec<u32>, Vec<StrRaw>)> = Vec::new();
    let mut off: usize = 0;
    let mut c: usize = 0;
    while off < n_{ts} {{
        let len = std::cmp::min(1 + (lemma_next(&mut lemma_rng) as usize) % lemma_chunk_max, n_{ts} - off);
{str_bufs}        lemma_raws.push(RawChunk_{ts} {{ j: c as u64, off: off as u64, len: len as u64, {", ".join(raw_fields)} }});
{keep}        off += len;
        c += 1;
    }}
    let _ = &lemma_keep;
    let lemma_end = StreamEnd_{ts} {{ m: lemma_raws.len() as u64, n: n_{ts} as u64 }};
    let lemma_sh_raw = &lemma_end as *const StreamEnd_{ts} as usize;
    println!("STREAM_CHUNKS: {{}}", lemma_raws.len());
    println!("STREAM_THREADS: {{}}", lemma_threads);
    let mut samples: [u128; {TIMED_RUNS}] = [0; {TIMED_RUNS}];
    let mut lemma_out: Option<StreamOut> = None;
    let mut s: usize = 0;
    while s < {TIMED_RUNS} {{
        let start = std::time::Instant::now();
        let next = std::sync::atomic::AtomicUsize::new(0);
        let raws = &lemma_raws;
        let mut execs: Vec<Exec> = std::thread::scope(|sc| {{
            let handles: Vec<_> = (0..lemma_threads)
                .map(|_| {{
                    let next = &next;
                    sc.spawn(move || {{
                        let mut e = exec_new(Stream_{ts} {{ id: 0, raw: lemma_sh_raw }}, lemma_p);
                        loop {{
                            let j = next.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                            if j >= raws.len() {{
                                break;
                            }}
                            e = exec_step(e, &raws[j]);
                        }}
                        e
                    }})
                }})
                .collect();
            handles.into_iter().map(|h| h.join().expect("a stream worker panicked")).collect()
        }});
        let mut e = execs.pop().expect("at least one worker");
        while let Some(other) = execs.pop() {{
            e = exec_merge(e, other);
        }}
        let out = exec_finish(e);
        samples[s] = start.elapsed().as_micros();
        lemma_out = Some(out);
        s += 1;
    }}
    samples.sort();
    let lemma_rows = match lemma_out.expect("timed runs") {{
        StreamOut::Rows(r) => r,
        StreamOut::Declined => {{
            println!("{decline.DECLINE_LINE}");
            std::process::exit({decline.DECLINE_EXIT_CODE});
        }}
        StreamOut::Error => panic!("LEMMA_STREAM_ERROR: a chunk was lost, doubled or malformed (the stream runtime refused to answer)"),
    }};
    println!("QUERY_LATENCY_US: {{}}", samples[{TIMED_RUNS // 2}]);
    println!("QUERY_LATENCY_BEST_US: {{}}", samples[0]);
    println!("TIMED_RUNS: {TIMED_RUNS}");
{rows}}}
"""
    return verus_part + "\n\n" + hex_fn + main_fn
