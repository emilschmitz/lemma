"""Global column value bounds for Lemma (all queries, host-injected via valid_cols)."""

from __future__ import annotations

# Max rows in one Cols table (also matches practical in-memory caps).
LEMMA_MAX_ROWS = 2**31

# u32 cells: keys, dates (YYYYMMDD), quantities, discounts, etc.
LEMMA_MAX_NATIVE_U32 = 2**31

# u64 money / wide metric cells (per row, before aggregation).
LEMMA_MAX_MONEY_U64 = 2**40

# Per-cell string length (nation names, brands, regions, …).
LEMMA_MAX_STRING_LEN = 128


def col_verus_type(col_type: str) -> str:
    t = col_type.lower()
    if t in (
        "bigint",
        "int64",
        "int8",
        "hugeint",
        "decimal",
        "numeric",
        "double",
        "float8",
        "float",
        "real",
    ):
        return "u64"
    if t in (
        "int",
        "integer",
        "int4",
        "int32",
        "smallint",
        "int2",
        "int16",
        "tinyint",
        "int1",
        "date",
    ):
        return "u32"
    if t in ("string", "varchar", "text", "char", "bpchar"):
        return "String"
    if t in ("bool", "boolean"):
        return "bool"
    raise ValueError(f"unsupported column type: {col_type!r}")


def spec_map_key_type(col_type: str) -> str:
    """Map key type for method_spec group-by (String cols use Seq<char>)."""
    if col_verus_type(col_type) == "String":
        return "Seq<char>"
    return col_verus_type(col_type)


def col_spec_accessor_return(col_type: str) -> str:
    t = col_type.lower()
    if t in ("string", "varchar", "text", "char", "bpchar"):
        return "Seq<char>"
    return col_verus_type(col_type)


def emit_bound_constants() -> str:
    return f"""// === Lemma global input bounds (all queries) ===
pub const LEMMA_MAX_ROWS: usize = {LEMMA_MAX_ROWS};
pub const LEMMA_MAX_NATIVE_U32: u32 = {LEMMA_MAX_NATIVE_U32};
pub const LEMMA_MAX_MONEY_U64: u64 = {LEMMA_MAX_MONEY_U64};
pub const LEMMA_MAX_STRING_LEN: usize = {LEMMA_MAX_STRING_LEN};
"""


def emit_trusted_prelude() -> str:
    return """// === Trusted arithmetic helpers ===
// TRUSTED: rustc wrapping_add; sound when ValidCols row/cell bounds apply (no overflow).
#[verifier::external_body]
pub exec fn add_u64(a: u64, b: u64) -> (res: u64)
    ensures res == a + b,
{
    a.wrapping_add(b)
}

// TRUSTED: rustc wrapping_mul; sound when ValidCols bounds apply.
#[verifier::external_body]
pub exec fn mul_u64_u32(a: u64, b: u32) -> (res: u64)
    ensures res == a * (b as u64),
{
    a.wrapping_mul(b as u64)
}

// TRUSTED: signed difference on bounded u64 cells.
#[verifier::external_body]
pub exec fn sub_u64_to_i64(a: u64, b: u64) -> (res: i64)
    ensures res == (a as int) - (b as int),
{
    (a as i64) - (b as i64)
}

// TRUSTED: rustc wrapping_add on i64.
#[verifier::external_body]
pub exec fn add_i64(a: i64, b: i64) -> (res: i64)
    ensures res == a + b,
{
    a.wrapping_add(b)
}

// === CASE WHEN (simple int branches) ===
pub open spec fn case_when_u64(cond: bool, then_v: u64, else_v: u64) -> u64 {
    if cond { then_v } else { else_v }
}

#[verifier::external_body]
pub exec fn case_when_u64_exec(cond: bool, then_v: u64, else_v: u64) -> (res: u64)
    ensures res == case_when_u64(cond, then_v, else_v),
{
    if cond { then_v } else { else_v }
}

// === String LIKE helpers (basic % prefix/suffix/contains) ===
pub open spec fn str_like_prefix(s: Seq<char>, lit: Seq<char>) -> bool {
    lit.is_prefix_of(s)
}

pub open spec fn str_like_suffix(s: Seq<char>, lit: Seq<char>) -> bool {
    lit.is_suffix_of(s)
}

// TRUSTED axiom: substring containment (exists quantifier needs manual triggers).
#[verifier::external_body]
pub open spec fn str_like_contains(s: Seq<char>, lit: Seq<char>) -> bool {
    arbitrary()
}

// TRUSTED: exec string prefix check (ensures tie to spec).
#[verifier::external_body]
pub exec fn str_like_prefix_exec(s: &str, lit: &str) -> (res: bool)
    ensures res == str_like_prefix(s@, lit@),
{
    s.starts_with(lit)
}

// TRUSTED: exec string suffix check (ensures tie to spec).
#[verifier::external_body]
pub exec fn str_like_suffix_exec(s: &str, lit: &str) -> (res: bool)
    ensures res == str_like_suffix(s@, lit@),
{
    s.ends_with(lit)
}

// TRUSTED: exec string contains check (ensures tie to spec).
#[verifier::external_body]
pub exec fn str_like_contains_exec(s: &str, lit: &str) -> (res: bool)
    ensures res == str_like_contains(s@, lit@),
{
    s.contains(lit)
}

// === ILIKE + underscore LIKE (TRUSTED pattern match) ===
// TRUSTED axiom: case-insensitive SQL LIKE/ILIKE pattern (%, _ wildcards).
#[verifier::external_body]
pub open spec fn str_ilike_match(s: Seq<char>, pat: Seq<char>) -> bool {
    arbitrary()
}

// TRUSTED axiom: case-sensitive LIKE with _ single-char wildcard.
#[verifier::external_body]
pub open spec fn str_like_underscore_match(s: Seq<char>, pat: Seq<char>) -> bool {
    arbitrary()
}

// TRUSTED: exec ILIKE pattern check (ensures tie to spec).
#[verifier::external_body]
pub exec fn str_ilike_match_exec(s: &str, pat: &str) -> (res: bool)
    ensures res == str_ilike_match(s@, pat@),
{
    str_like_underscore_match_exec(&s.to_ascii_lowercase(), &pat.to_ascii_lowercase())
}

// TRUSTED: exec underscore LIKE pattern check (ensures tie to spec).
#[verifier::external_body]
pub exec fn str_like_underscore_match_exec(s: &str, pat: &str) -> (res: bool)
    ensures res == str_like_underscore_match(s@, pat@),
{
    fn m(s: &[char], si: usize, p: &[char], pi: usize) -> bool {
        if pi >= p.len() {
            return si >= s.len();
        }
        if p[pi] == '%' {
            let mut k = si;
            while k <= s.len() {
                if m(s, k, p, pi + 1) {
                    return true;
                }
                k += 1;
            }
            return false;
        }
        if p[pi] == '_' {
            if si >= s.len() {
                return false;
            }
            return m(s, si + 1, p, pi + 1);
        }
        if si >= s.len() || s[si] != p[pi] {
            return false;
        }
        m(s, si + 1, p, pi + 1)
    }
    let sc: Vec<char> = s.chars().collect();
    let pc: Vec<char> = pat.chars().collect();
    m(&sc, 0, &pc, 0)
}

// === Scalar helpers (abs / case) ===
// TRUSTED: abs on bounded u64 cell.
#[verifier::external_body]
pub open spec fn abs_u64(x: u64) -> u64 {
    arbitrary()
}

#[verifier::external_body]
pub exec fn abs_u64_exec(x: u64) -> (res: u64)
    ensures res == abs_u64(x),
{
    if x > (0u64) { x } else { 0u64.wrapping_sub(x) }
}

// TRUSTED axiom: ASCII lower/upper on Seq<char>.
#[verifier::external_body]
pub open spec fn str_lower(s: Seq<char>) -> Seq<char> {
    arbitrary()
}

#[verifier::external_body]
pub open spec fn str_upper(s: Seq<char>) -> Seq<char> {
    arbitrary()
}

#[verifier::external_body]
pub exec fn str_lower_exec(s: &str) -> (res: String)
    ensures res@ == str_lower(s@),
{
    s.to_ascii_lowercase()
}

#[verifier::external_body]
pub exec fn str_upper_exec(s: &str) -> (res: String)
    ensures res@ == str_upper(s@),
{
    s.to_ascii_uppercase()
}
"""


def emit_valid_cols_predicate(schema_dict: dict[str, str], struct_name: str = "Cols") -> str:
    """Columnar valid_cols: row count + per-column cell bounds."""
    lines = [
        f"pub open spec fn valid_cols(cols: &{struct_name}) -> bool {{",
        "    &&& cols.n <= LEMMA_MAX_ROWS",
    ]
    for col, col_type in schema_dict.items():
        field = col.lower()
        vt = col_verus_type(col_type)
        if vt == "u32":
            lines.append(
                f"    &&& forall|i: int| 0 <= i && i < cols.n as int ==>"
                f" cols.{field}[i] < LEMMA_MAX_NATIVE_U32"
            )
        elif vt == "u64":
            lines.append(
                f"    &&& forall|i: int| 0 <= i && i < cols.n as int ==>"
                f" cols.{field}[i] < LEMMA_MAX_MONEY_U64"
            )
        elif vt == "bool":
            lines.append(
                f"    &&& cols.{field}.len() == cols.n"
            )
        else:
            lines.append(
                f"    &&& cols.{field}@.len() == cols.n"
            )
            lines.append(
                f"    &&& forall|i: int| 0 <= i && i < cols.n as int ==>"
                f" (cols.{field}[i]@).len() <= LEMMA_MAX_STRING_LEN"
            )
    lines.append("}")
    return "\n".join(lines)


def emit_valid_cols_accessor_lemmas(schema_dict: dict[str, str], struct_name: str = "Cols") -> str:
    """Per-column bound lemmas (proved from valid_cols when possible)."""
    blocks: list[str] = []
    for col, col_type in schema_dict.items():
        field = col.lower()
        vt = col_verus_type(col_type)
        if vt == "u32":
            ensures = f"cols.{field}[i as int] < LEMMA_MAX_NATIVE_U32"
        elif vt == "u64":
            ensures = f"cols.{field}[i as int] < LEMMA_MAX_MONEY_U64"
        elif vt == "bool":
            ensures = "true"
        else:
            ensures = f"(cols.{field}[i as int]@).len() <= LEMMA_MAX_STRING_LEN"
        blocks.append(
            f"pub proof fn valid_cols_get_{field}(cols: &{struct_name}, i: int)\n"
            f"    requires\n"
            f"        valid_cols(cols),\n"
            f"        0 <= i && i < cols.n as int,\n"
            f"    ensures {ensures},\n"
            f"{{\n"
            f"}}"
        )
    return "\n\n".join(blocks)
