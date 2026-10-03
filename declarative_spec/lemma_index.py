"""Markdown index of host lemmas and vstd items for declarative agents."""


def lemma_index_markdown() -> str:
    lines = [
        "# Declarative spec lemma index",
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
        ("- `lemma_f64_sum_within_eps(acc: f64, n_terms: int, mag_cap: int, eps: f64, terms: Seq<f64>)`. "
        "A plain left-to-right f64 fold is within eps of the real sum of the loaded floats when "
        "eps is at least host_f64_sum_error(n_terms, mag_cap). Pass the ghost sequence you tracked; "
        "do not unfold an f64 add step by step."),
        "",
        ("- `lemma_f64_add_defined(x: f64, y: f64)`. "
        "IEEE f64 addition is defined for every pair of values. Call it before `acc + x`."),
        "",
        ("- `lemma_f64_left_fold_empty()` and `lemma_f64_left_fold_push(prefix, x, acc, next)`. "
        "The host opaque f64 accumulator: empty is 0.0. "
        "`next` is one f64 add, and it is the fold of `prefix.push(x)`."),
        "",
        ("- `host_f64_sum_error(n_terms: int, mag_cap: int) -> real`. "
        "Host error bound depending only on term count and magnitude cap."),
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
        ("- `vstd::std_specs::hash::axiom_u64_obeys_hash_table_key_model` and the i64 and i128 variants. "
        "Primitive keys obey the hash-map model; broadcast-use the one you need. Do not `assume()` it."),
        "",
        "- `Seq::len`, `Seq::index`, `Seq::skip`, `Seq::push`.",
        "",
        ("You may call these and other vstd lemmas; look them up here when unsure. "
        "You may **not** declare `spec fn` or `proof fn`."),
    ]
    return "\n".join(lines) + "\n"
