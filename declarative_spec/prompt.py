"""Agent prompt for declarative run_query proofs."""


def build_declarative_prompt(
    *,
    sql: str,
    spec_path: str,
    edit_path: str,
    lemma_index: str,
) -> str:
    few_shots = _few_shots()
    return "\n".join(
        [
            "# Declarative run_query proof task",
            "",
            f"SQL:\n```sql\n{sql.strip()}\n```",
            "",
            (f"Read the spec at `{spec_path}`. Edit only `{edit_path}` between "
            "`// AGENT_EDIT_START` and `// AGENT_EDIT_END`."),
            "",
            "Rules:",
            ("- The `ensures` are conditions on the result (membership and count or sum). "
            "Do not redefine them. Do not add a `spec fn`. Do not write `proof fn`, `spec fn`, "
            "`assume(`, or `#[verifier::external_body]`."),
            ("- Prove the executable loop meets those conditions under `valid_cols` and the caps "
            "in the spec. Call the host fit lemmas. Do not assume the add fits."),
            ("- For a float sum, the spec is the real sum of the loaded floats. Use one f64 "
            "accumulator per group, added left to right. Show the loop is the host fold "
            "(`lemma_f64_add_defined`, `lemma_f64_left_fold_empty`, `lemma_f64_left_fold_push`), then call "
            "`lemma_f64_sum_within_eps`. Use the host const `FLOAT_ABS_EPS`, not a numeric "
            "literal in the agent body. Do not prove f64 rounding step by step. Do not truncate "
            "the float column to an integer."),
            ("- Any loop that meets the conditions is allowed. A group-by count may walk the column "
            "from the end: `i = i - 1`; `prev = map value or 0`; insert `prev + 1`; invariant is "
            "the two ensures for the suffix that starts at `i`; the fit lemma uses the row cap."),
            "",
            "## Lemma index",
            "",
            lemma_index.rstrip(),
            "",
            "## Few-shot patterns (tables `t` and `u` only)",
            "",
            few_shots,
        ]
    )


def _few_shots() -> str:
    return "\n".join(  # noqa: FLY002 — paragraphs, not an f-string interpolation
        [
            "### 1. Count group-by",
            "",
            "`SELECT k, COUNT(*) AS cnt FROM t GROUP BY k`",
            "",
            ("Ensures: map `contains_key` iff some index equals `k`, and the value as int equals "
            "the group count. Executable `u64` map built walking the column from the end. "
            "Fit lemma: `prev + 1` fits because the count is at most the row cap."),
            "",
            "### 2. Join integer sum",
            "",
            "`SELECT u.g, SUM(t.v) AS total FROM t JOIN u ON t.a = u.a GROUP BY u.g` with integer `v`.",
            "",
            ("Ensures: membership of pairs and `res[g]` as int equals the sum of loaded `t.v`. "
            "If `u.a` is unique, the fit lemma uses `t`'s row cap times the cap on `v`, not "
            "`u`'s row cap. Slot is u64 or i128 according to that product."),
            "",
            "### 3. Join float sum",
            "",
            ("Same query when `v` is float and `LEMMA_FLOAT_ABS_EPS` is set (host emits "
            "`FLOAT_ABS_EPS`). Ensures: `abs(res[g] as real - real sum) <= FLOAT_ABS_EPS as real`. "
            "Executable f64 accumulator. Proof calls "
            "`lemma_f64_sum_within_eps(acc, n_terms, mag_cap, FLOAT_ABS_EPS, terms)`. "
            "Do not put `0.000001` in the agent body."),
            "",
            "### 4. Not this mode",
            "",
            ("The recursive product path uses a spec function that recurses on two indexes and "
            "defines the result map in spec code, with `ensures res == that function`. "
            "That is the other spec style; this declarative spec does not ask you to write "
            "a spec fn or mirror that recursive map walk."),
        ]
    )
