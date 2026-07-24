"""Plain Rust Cols + tbl loader for exec bench (no Verus syntax in cargo path)."""

from __future__ import annotations

from verus_transpiler.value_bounds import col_verus_type


def _rust_vec_type(col_type: str) -> str:
    vt = col_verus_type(col_type)
    if vt == "bool":
        return "bool"
    if vt in ("u32", "u64"):
        return vt
    return "String"


def generate_cols_exec_rs(schema_dict: dict[str, str]) -> str:
    """Emit `cols.rs`: columnar `Cols` + projected loader from pipe-delimited tbl."""
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

    return f"""// Generated exec Cols (plain Rust — not compiled with Verus).
use std::collections::HashMap;
use std::fs::File;
use std::io::{{BufRead, BufReader}};

fn strip_quotes(s: &str) -> &str {{
    s.trim_matches('"')
}}

#[derive(Clone, Debug)]
pub struct Cols {{
{chr(10).join(fields)}
}}

impl Cols {{
    pub fn load_from_tbl(path: &str, limit: usize) -> Self {{
        let f = File::open(path).expect("open .tbl");
        let mut rdr = BufReader::new(f);
        let mut hdr = String::new();
        rdr.read_line(&mut hdr).unwrap();
        let mut name_to_idx: HashMap<String, usize> = HashMap::new();
        for (i, c) in hdr.split('|').enumerate() {{
            name_to_idx.insert(c.trim().to_uppercase(), i);
        }}
{chr(10).join(col_indices)}

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
        Self {{
            n,
{field_inits}
        }}
    }}
}}
"""
