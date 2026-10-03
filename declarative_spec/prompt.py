"""Prompt for the declarative flag. The recursive agent prompt is a different file."""

from __future__ import annotations


def build_declarative_prompt(
    *,
    sql: str,
    spec_path: str,
    edit_path: str,
    lemma_index: str,
    last_error: str = "",
    in_docker: bool = False,
) -> str:
    """Instructions for this spec style only.

    When ``in_docker`` is set, paths are the container mount. The recursive
    prompt in ``research_loop.agent_sandbox.build_agent_prompt`` is not used.
    """
    if in_docker:
        spec_path = "/workspace/context/ro/spec.rs"
        edit_path = "/workspace/runquery_agent.rs"
        index_path = "/workspace/context/ro/lemma_index.md"
    else:
        index_path = "context/ro/lemma_index.md"

    sections = [
        "# Declarative run_query",
        "",
        "This session is `LEMMA_SPEC_STYLE=declarative`.",
        "It is not the recursive optimizer prompt. There is no `method_spec` to match.",
        "The spec states conditions on the result. A small helper such as `group_count`",
        "or `matched_sum` is fine. Do not define the query as a spec function that",
        "walks indexes and updates a map.",
        "",
        "## SQL",
        "",
        "```sql",
        sql.strip(),
        "```",
        "",
        "## Edit",
        "",
        f"Read `{spec_path}`. Edit only `{edit_path}` between `// AGENT_EDIT_START`",
        "and `// AGENT_EDIT_END`, with the file edit tool.",
        "The shell cannot run in this container. Do not use it.",
        "Do not search outside this workspace. Host lemmas are already in the file",
        f"between `// HOST_LEMMAS_START` and `// HOST_LEMMAS_END`, and in `{index_path}`.",
        "Call those names. Do not invent a vstd module path.",
        "",
        "## What you may write",
        "",
        "Any executable loop that meets the `ensures`. `proof { lemma_...( ... ); }` is allowed.",
        "Do not write `proof fn`, `spec fn`, `assume(`, or `#[verifier::external_body]`.",
        "Do not add a `spec fn`. The host already emitted the helpers.",
        "",
        "Integers. A `u64` or `i128` add equals the mathematical add when the result fits.",
        "Call the host fit lemma under the row cap and the cell cap in the spec.",
        "If the slot is `u64`, call `lemma_count_step_fits_u64` or `lemma_sum_step_fits_u64`.",
        "If the slot is `i128`, call the `i128` lemma. Do not assume the add fits.",
        "Bind a view before you use its length: `let keys = cols.k@;` then `keys.len()`.",
        "Do not write `cols.k@.len()`.",
        "Parenthesize a cast in a comparison: `(k as int) < (KEY_CAP_t_k as int)`.",
        "Do not write `k as int <`.",
        "Snapshot the index before you decrement it. After `i = i - 1` the old suffix",
        "is `i_old`, not `i`.",
        "",
        "A count walks the column from the end. The fit lemma's cap argument is the",
        "`ROW_CAP_...` const in the spec.",
        "If the spec has `pub const KEY_CAP_...: usize`, that is the exclusive key domain.",
        "Allocate `let mut counts: Vec<u64> = Vec::new();` and push a zero once per slot",
        "until `counts.len() == KEY_CAP_...`. Every loaded key is `< KEY_CAP_...`.",
        "On each row, read `prev` from `counts[k as usize]`, call",
        "`lemma_count_step_fits_u64(prev, ROW_CAP_...)`, then",
        "`counts[k as usize] = prev + 1`. Leave every other slot unchanged.",
        "After the column loop, `counts[k] as int == group_count(keys, 0, k)` for each",
        "slot. Insert a slot into the result map only when its count is nonzero.",
        "A HashMap update on every row loses the timed run on the large table.",
        "If the spec has no `KEY_CAP` const, keep the count in the result map:",
        "`prev` is the map value or 0, then insert `prev + 1`.",
        "",
        "Floats. The spec is the real sum of the loaded floats, within `FLOAT_ABS_EPS`.",
        "Use one `f64` accumulator per group, added left to right.",
        "Call `lemma_f64_add_defined` before the add, then `lemma_f64_left_fold_push`,",
        "then `lemma_f64_sum_within_eps`. Pass `FLOAT_ABS_EPS`. Do not write a numeric",
        "epsilon. Do not unfold an `f64` add. Do not truncate the float to an integer.",
        "",
        "A join sum contains a group when some row of each side shares the join key",
        "and the group column has that value. The value is the sum of the loaded",
        "measure over those pairs. If the spec's sum cap is one side's row cap times",
        "the cell cap, the other side's key is unique. Use that cap in the fit lemma.",
        "",
        "## Tools",
        "",
        "lemma-host MCP is already approved (`--approve-mcps`).",
        f"1. Edit `{edit_path}`.",
        "2. Call `run_runquery` with `path` `runquery_agent.rs`.",
        "   That call verifies, compiles, and runs this declarative program.",
        "   It does not look for `method_spec`.",
        "3. Call `submit_runquery` with the returned `run_id`.",
        "Do this before the session ends. If `run_runquery` returns an error, fix the",
        "edit and call it again. Do not search the image for another copy of the lemma.",
        "",
        "## Lemma index",
        "",
        lemma_index.rstrip(),
        "",
        "## Other spec style",
        "",
        "The recursive product path uses a spec function that recurses on two indexes",
        "and defines the result map in spec code, with `ensures res == that function`.",
        "That is the other spec style. Do not write that here.",
    ]
    if last_error.strip():
        sections.extend(
            [
                "",
                "## Previous host error",
                "",
                "The last compile or verify of your edit failed. Fix that edit and call",
                "`run_runquery` again.",
                "",
                "```",
                last_error.strip()[-4000:],
                "```",
            ]
        )
    return "\n".join(sections) + "\n"
