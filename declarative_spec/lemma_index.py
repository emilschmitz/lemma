"""Markdown index of host lemmas and vstd items for declarative agents."""


def lemma_index_markdown(floats: bool = True, div_zero: bool = False) -> str:
    """The index; ``floats=False`` leaves out every entry about f64 / reals (a spec with no float value).

    ``div_zero`` adds the entry of ``host_f64_div_by_zero`` (only a ratio spec has that lemma)."""
    text = _lemma_index_all()
    if floats:
        return text + (_DIV_ZERO_ENTRY if div_zero else "")
    paragraphs = text.split("\n\n")
    kept = [p for p in paragraphs if "f64" not in p and "`abs_real" not in p and "FLOATS" not in p]
    return "\n\n".join(kept)


_DIV_ZERO_ENTRY = (
    "\n- `host_f64_div_by_zero(x: f64) -> f64` (exec; this spec divides two aggregates): for finite `x`, the result is "
    "`+inf` when `x as real > 0`, `-inf` when `< 0`, NaN when `== 0` (IEEE 754 division by +0.0). Use it for the "
    "zero-denominator branch of the ratio; for a nonzero denominator use `lemma_f64_div_real`.\n"
)


def _lemma_index_all() -> str:
    lines = [
        "# Declarative spec lemma index",
        "",
        "Write the `run_query` edit before you read the rest of this index.",
        "Every vstd module is already imported by glob. Write no `use` lines.",
        "The one allowed line is `broadcast use vstd::<module>::group_<name>;` (exact name, see",
        "`context/ro/verus/INDEX.md` for the list).",
        "Still forbidden: `assume(`, `admit(`, `#[verifier::external_body]`, and a name containing",
        "`axiom`, `arbitrary`, or `proof_from_false`.",
        "A new `spec fn` or `proof fn` goes between `// AGENT_HELPERS_START` and `// AGENT_HELPERS_END`.",
        "`proof { lemma_...(); }` is allowed.",
        "",
        "Host lemmas (call these; the integer adds need none, Verus checks overflow itself):",
        "",
        ("- `lemma_dense_count_map(keys, counts, map, key_cap)`, when this spec defines it. "
        "Once every slot of `counts` equals `group_count(keys, 0, k)` and `map` holds exactly "
        "the nonzero slots, the map meets the `ensures`. Call it after the copy loop. "
        "Pass `KEY_CAP_... as int`."),
        "",
        ("- FLOATS (the f64 idealization; floating-point rounding error is ACCEPTED: a float is modeled as exact "
        "real arithmetic, so a float SUM is just an exact fold and the spec states `result == the real value`, no "
        "epsilon). For finite `f64` values within the catalog caps, `+ - * /`, the integer casts and the comparisons "
        "below behave as the real operations on `x as real`. `f64_within(x: f64, cap: real)` is `x` finite with "
        "`-cap < x as real < cap`: assert `t.<col>@[i].is_finite_spec()` (a `valid_cols` conjunct) and use the "
        "`MAG_CAP_<table>_<col> as real` cap. Keep `f64_literals_ok()` in every loop invariant: it states each f64 "
        "literal of the query (and `0.0`) denotes its decimal value."),
        "",
        ("- `lemma_f64_add_defined(x, y)`, `lemma_f64_sub_defined(x, y)`, `lemma_f64_mul_defined(x, y)`: call before "
        "`x + y`, `x - y`, `x * y` (the exec operation is defined)."),
        "",
        ("- `lemma_f64_add_within(x, y, o, cx, cy)`, `lemma_f64_sub_within(...)`, `lemma_f64_mul_within(...)`: "
        "requires `f64_within(x, cx)`, `f64_within(y, cy)`, the op's `*_ensures(x, y, o)` (it holds after `let o = x + y;`) "
        "and `cx + cy` (`cx * cy` for mul) at most `f64_safe_bound()` (2^200). Ensures `o as real` is the real "
        "sum/difference/product and `f64_within(o, cx + cy)` (`cx * cy`). Keep `acc as real == <spec sum>` and "
        "`f64_within(acc, count * cap + 1)` as the loop invariant of a float SUM. `lemma_f64_add_real` etc. are "
        "the same without the bound on the result."),
        "",
        ("- `lemma_f64_div_defined(x, y, cx, cq)` then `lemma_f64_div_real(x, y, o, cx, cq)`: x finite within cx, y finite "
        "nonzero, `-cq * |y| < x < cq * |y|`: `o as real == x as real / y as real`. Use for AVG."),
        "",
        ("- `host_u64_to_f64(n: u64) -> f64`, `host_i128_to_f64(n: i128) -> f64` (exec): the cast, with "
        "`(o as real) == (n as int as real)` and `o` finite. vstd gives the plain `as f64` no meaning, so use these."),
        "",
        ("- `lemma_f64_lt_real(x, y, o)`, `le`, `gt`, `ge`, `eq`: after `let o = x < y;` (resp. `<=`, `>`, `>=`, `==`) with "
        "both finite, `o <==> (x as real) < (y as real)` (resp. the other relations). Use for a float filter, MIN/MAX, "
        "ORDER BY on a float, HAVING on a float aggregate."),
        "",
        "- `abs_real(x: real) -> real`. Absolute value on reals.",
        "",
        "vstd items the declarative spec uses:",
        "",
        ("- `HashMapWithView::<K, V>::new`, `insert`, `contains_key`, `get` (vstd::hash_map). "
        "`insert` ensures the view is `old(self)@.insert(k@, v)`."),
        "",
        ("- `StringHashMap::<V>::new`, `insert`, `contains_key`, `get` for string keys; "
        "view key is `Seq<char>`."),
        "",
        "- `Map::contains_key`, `Map::insert`, `Map::empty` (vstd::map) as the spec view.",
        "",
        ("- The host already broadcasts "
        "`vstd::std_specs::hash::axiom_u64_obeys_hash_table_key_model` "
        "(and the i64 and i128 variants) for the group key. "
        "Do not use it by name. A name containing `axiom` is rejected except inside `broadcast use vstd::<module>::group_<name>;`, "
        "which is allowed for every vstd group."),
        "",
        "- `Seq::len`, `Seq::index`, `Seq::skip`, `Seq::push`.",
        "",
        ("You may call these and other vstd lemmas by bare name; look them up in `context/ro/verus/` "
        "when unsure. Do not use a name containing `axiom`, `arbitrary`, or `proof_from_false`. "
        "Do not `assume(` or `admit(` a fact. "
        "Write helper `spec fn` / `proof fn` items only in the helper region."),
    ]
    return "\n".join(lines) + "\n"
