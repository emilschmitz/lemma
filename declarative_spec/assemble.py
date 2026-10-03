"""Stitch declarative spec + agent body + host loaders."""

from __future__ import annotations

import re


def assemble_declarative_program(spec_rs: str, agent_body: str) -> str:
    start = spec_rs.find("// AGENT_EDIT_START")
    end = spec_rs.find("// AGENT_EDIT_END")
    if start == -1 or end == -1 or end < start:
        raise ValueError("AGENT_EDIT markers missing from spec")

    before = spec_rs[: start + len("// AGENT_EDIT_START")]
    after = spec_rs[end:]
    body_block = f"\n{agent_body.rstrip()}\n"
    stitched = before + body_block + after

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
        fields = re.findall(r"pub\s+([a-z0-9_]+):\s+Vec<([^>]+)>", body)
        param_parts = [f"n_{table_suffix}: usize"]
        for fname, fty in fields:
            param_parts.append(f"{table_suffix}_{fname}: Vec<{fty}>")
        params = ", ".join(param_parts)
        struct_fields = [f"n: n_{table_suffix}"] + [f"{fname}: {table_suffix}_{fname}" for fname, _ in fields]
        fn_name = f"load_cols_{table_suffix}"
        zero_args = ", ".join("0" if i == 0 else "vec![]" for i in range(len(param_parts)))
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
        mains_load.append(f"    let {col_var} = {fn_name}({zero_args});")
        mains_args.append(f"&{col_var}")

    if len(mains_args) == 1:
        run_call = f"run_query({mains_args[0]})"
    elif len(mains_args) == 2:
        run_call = f"run_query({mains_args[0]}, {mains_args[1]})"
    else:
        run_call = "run_query()"

    main_fn = "fn main() {\n"
    main_fn += "\n".join(mains_load) + "\n"
    main_fn += f"""    let start = std::time::Instant::now();
    let _res = {run_call};
    let elapsed = start.elapsed();
    println!("QUERY_LATENCY_US: {{}}", elapsed.as_micros());
}}
"""

    # Loaders carry `ensures valid_cols`, so they stay inside verus!.
    # main is outside the timer and outside the verus block.
    closed = verus_part.rstrip()
    if not closed.endswith("}"):
        raise ValueError("verus block did not end at '}'")
    verus_with_loaders = closed[:-1] + "\n" + "\n\n".join(loaders) + "\n}\n"
    return verus_with_loaders + "\n" + main_fn
