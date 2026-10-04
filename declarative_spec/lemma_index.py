"""Markdown index of host lemmas and vstd items for declarative agents."""


def lemma_index_markdown() -> str:
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
        "Host lemmas (call these; do not re-prove arithmetic fit by hand):",
        "",
        ("- `lemma_u64_add_fits(a: u64, b: u64)` "
        "`requires a as int + b as int <= u64::MAX as int`, "
        "`ensures a + b == (a as int + b as int) as u64`. "
        "A u64 add equals the mathematical add when the sum fits in u64."),
        "",
        ("- `lemma_i128_add_fits(a: i128, b: i128)` with the corresponding i128 min/max requires. "
        "An i128 add equals the mathematical add when the sum fits in i128."),
        "",
        ("- `lemma_dense_count_map(keys, counts, map, key_cap)`, when this spec defines it. "
        "Once every slot of `counts` equals `group_count(keys, 0, k)` and `map` holds exactly "
        "the nonzero slots, the map meets the `ensures`. Call it after the copy loop. "
        "Pass `KEY_CAP_... as int`."),
        "",
        ("- `lemma_index_key_below_cap(cols, i: int)`, when this spec defines it. "
        "Requires `valid_cols_...(cols)` and `0 <= i < cols.n as int`. "
        "Ensures the loaded key at `i` is `>= 0` and `< KEY_CAP_...`. "
        "Call it after reading `cols.<field>[i]`. Keep `valid_cols_...` in the loop invariant."),
        "",
        ("- `lemma_count_step_fits_u64(prev: u64, row_cap: int)`. "
        "prev + 1 fits in u64 when the count is at most the row cap and the row cap fits in u64."),
        "",
        ("- `lemma_count_step_fits_i128(prev: i128, row_cap: int)`. "
        "Same count step when the aggregate slot is i128."),
        "",
        ("- `lemma_sum_step_fits_u64(prev: u64, cell: u64, total_cap: int)`. "
        "Adding one more cell fits in u64 when the running sum stays within total_cap."),
        "",
        ("- `lemma_sum_step_fits_i128(prev: i128, cell: i128, total_cap: int)`. "
        "Same sum step for an i128 slot, including negative cells inside the cap."),
        "",
        ("- f64 idealization (finite values within the catalog caps behave like the reals; rounding error is ignored; "
        "this is a labeled trusted family). `f64_within(x: f64, cap: real)` is `x` finite with `-cap < x as real < cap`: "
        "the loader proves `valid_cols` gives it for a float column with cap `MAG_CAP_<table>_<col> as real` once you read "
        "`t.<col>@[i].is_finite_spec()` (assert it) and the cap conjunct. Keep `f64_literals_ok()` in every loop "
        "invariant: it states each f64 literal in the query (and `0.0`) denotes its decimal value."),
        "",
        ("- `lemma_f64_add_defined(x, y)`, `lemma_f64_sub_defined(x, y)`, `lemma_f64_mul_defined(x, y)`. "
        "Call before `x + y`, `x - y`, `x * y`: the exec operation is defined."),
        "",
        ("- `lemma_f64_add_within(x, y, o, cx, cy)`, `lemma_f64_sub_within(...)`, `lemma_f64_mul_within(...)`: "
        "requires `f64_within(x, cx)`, `f64_within(y, cy)`, the op's `*_ensures(x, y, o)` (it holds after `let o = x + y;`), "
        "and `cx + cy` (`cx * cy` for mul) at most `f64_safe_bound()` (2^200). Ensures `o` is finite, `o as real` equals "
        "the real sum/difference/product, and `f64_within(o, cx + cy)` (`cx * cy`). A float SUM is exact in the "
        "idealization: keep `acc as real == <spec sum>` and `f64_within(acc, cnt * cap + 1)` as the loop invariant, so no "
        "epsilon is ever needed. (`lemma_f64_add_real`/`sub_real`/`mul_real` are the same without the bound.)"),
        "",
        ("- `lemma_f64_div_defined(x, y, cx, cq)` then `lemma_f64_div_real(x, y, o, cx, cq)`: x finite within cx, y finite and "
        "nonzero, `-cq * |y| < x < cq * |y|`: the quotient `o as real == x as real / y as real`. Use for AVG."),
        "",
        ("- `host_u64_to_f64(n: u64) -> f64` and `host_i128_to_f64(n: i128) -> f64` (exec): the cast, with "
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
        "Do not use it by name. A name containing `axiom` is an assume and is rejected."),
        "",
        "- `Seq::len`, `Seq::index`, `Seq::skip`, `Seq::push`.",
        "",
        ("You may call these and other vstd lemmas by bare name; look them up in `context/ro/verus/` "
        "when unsure. Do not use a name containing `axiom`, `arbitrary`, or `proof_from_false`. "
        "Do not `assume(` or `admit(` a fact. "
        "Write helper `spec fn` / `proof fn` items only in the helper region."),
    ]
    return "\n".join(lines) + "\n"
