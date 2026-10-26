"""The agent prompt for a stream spec (lemma.toml ``[run] stream``, docs/STREAM.md, declarative_spec/stream.py).

``prompt.build_declarative_prompt`` hands a stream spec here and returns before any of its own text is built, so with the flag off
every prompt is byte-identical to before. A stream spec has no ``run_query``: the agent writes six regions (the state ``QAcc``, the
helpers with ``qacc_inv`` / ``st_val``, and the bodies of ``q_init`` / ``q_step`` / ``q_merge`` / ``q_finish``). The sections that
only make sense for a ``run_query`` body (its recipes and worked examples, agent scans, the Arc/parallel recipe, row-cap advice) are
not shown; the stream contract, the chunk view S1 gives, the host lemmas and the timing of the binary-mode stream main are.

Section kinds follow ``principles.kinds_emitted``: with ``examples = "none"`` the technique advice (RECIPE: the per-chunk string memo,
the speed guidance) and every pointer to an example file are left out, exactly as the ``run_query`` prompt leaves out its own.
No section names a benchmark query or a benchmark column.
"""

from __future__ import annotations

import re

import lemma_config
from declarative_spec import principles


def _contract_text(spec_text: str) -> str:
    """The four contracts as the spec states them (signature, requires, ensures; bodies are the agent's regions)."""
    from declarative_spec import stream

    out = []
    for name, (start, _end) in stream.BODY_REGIONS.items():
        m = re.search(rf"pub fn q_{name}\(.*?\n\{{\n{re.escape(start)}", spec_text, re.DOTALL)
        if m is None:
            raise ValueError(f"stream spec without the q_{name} contract")
        out.append(m.group(0).removesuffix(start).rstrip().removesuffix("{").rstrip())
    return "\n\n".join(out)


def _names(spec_text: str) -> dict[str, str]:
    m = re.search(r"pub uninterp spec fn stream_table_(\w+)\(id: u64\) -> (Cols_\w+);", spec_text)
    if m is None:
        raise ValueError("stream spec without stream_table_<t>")
    ts = m.group(1)
    key = re.search(r"pub type Key = ([^;]+);", spec_text)
    return {"ts": ts, "cols": m.group(2), "key": key.group(1) if key else "()"}


def _agg_fields(spec_text: str) -> list[str]:
    m = re.search(r"pub struct Agg \{\n(.*?)\n\}", spec_text, re.DOTALL)
    return [ln.strip().removeprefix("pub ").rstrip(",") for ln in m.group(1).splitlines()] if m else []


def _chunk_fields(spec_text: str, ts: str) -> list[str]:
    m = re.search(rf"pub struct Chunk_{ts}<'a> \{{\n(.*?)\n\}}", spec_text, re.DOTALL)
    return [ln.strip().removeprefix("pub ").rstrip(",") for ln in m.group(1).splitlines()] if m else []


def _params(spec_text: str) -> list[str]:
    m = re.search(r"pub struct Params \{\n(.*?)\n?\}", spec_text, re.DOTALL)
    return [ln.strip().removeprefix("pub ").rstrip(",") for ln in m.group(1).splitlines() if ln.strip()] if m else []


def _what_you_get(edit_path: str, spec_path: str, root: str, index_path: str) -> tuple[list[str], list[str], list[str]]:
    from declarative_spec.prompt import (
        _CLAUDE_TOOL_NAMES,
        MCP_SERVER,
        _verus_queue_lines,
    )

    bar = lemma_config.get("speed_bar_mult")
    head = [
        "## What you get",
        "",
        f"- `{edit_path}` already holds the host spec, the host lemmas, the stream contract, the chunk view and the host runtime, with",
        "  six empty agent regions. You edit those regions.",
        f"- Read-only: `{spec_path}` (same spec), `{root}/query.sql`, `{root}/schema.json`, `{index_path}`,",
    ]
    pointer = [f"  `{root}/examples/` (verified stream programs on a small invented table; start with `INDEX.md` there),"]
    tools = [
        f"  `{root}/verus/` (vstd source, Verus guide, small examples;",
        "  read `INDEX.md` first (one grep recipe per common lookup), then grep `LEMMAS.md`, `EXAMPLES_INDEX.md` and `GUIDE_INDEX.md`).",
        '- Look up vstd with one grep, e.g. `grep -n -A5 "^## StringHashMap::" LEMMAS.md` (in `verus/`).',
        "- Tools: the file edit tool; `run_runquery` (path `runquery_agent.rs`) admits your regions, verifies the whole program,",
        "  compiles it and times it on the official table (see \"How the program is timed\"); `submit_runquery` with the returned `run_id`.",
        f"  In Claude Code these are `{MCP_SERVER}run_runquery` and `{MCP_SERVER}submit_runquery`; if they are not in your tool list",
        f"  yet, load them first with ToolSearch (`select:{_CLAUDE_TOOL_NAMES}`). A Bash tool may exist, but it has no network and",
        "  Verus is not on its PATH: `run_runquery` is the only Verus you have, so do not try `verus`, `npx` or any package install.",
        "- `verify_functions` (`names`, path `runquery_agent.rs`) verifies only the functions you name (e.g. `q_step`, `q_merge`, a",
        "  helper); faster on a large file, and the result is a partial check that does not count as a submission.",
        *_verus_queue_lines(),
        "- Done means: Verus says `N verified, 0 errors` for the whole program (your regions and the host runtime), the result equals the",
        "  reference engine's rows, and the timed run beats the reference engine (`run_runquery` reports the speedup). `submit_runquery`",
        "  accepts only a run that is `ok`, i.e. one that also beats the reference engine: a verified program below the bar is reported as",
        "  `proved but below the speed bar`, is refused by `submit_runquery`, and still counts as your best proved run. Keep it aside as",
        "  your base (copy the file), then make it faster. Submit as soon as a program verifies and beats the bar, and again if a later",
        "  one is better.",
        *([f"  The bar of this run is a speedup of {bar:g}x: the median of your timed runs times {bar:g} must be below the reference engine's median."] if bar != 1.0 else []),
        "",
    ]
    return head, pointer, tools


def _regions_and_rules(root: str, n: dict[str, str]) -> list[str]:
    return [
        "## Regions and rules",
        "",
        "- Six regions are kept, everything else in the file is discarded:",
        "  - `// AGENT_STATE_START` .. `// AGENT_STATE_END`: `pub struct QAcc { .. }` and any further `struct` / `enum` it uses. No",
        "    references and no lifetimes (a state outlives the chunk it folded). Fields may be `Vec`, `StringHashMap`, `HashMapWithView`,",
        "    integers, `String`, `Ghost<..>`.",
        "  - `// AGENT_HELPERS_START` .. `// AGENT_HELPERS_END`: `spec fn` / `proof fn` / exec `fn` items. It must define",
        "    `spec fn qacc_inv(s: &QAcc) -> bool` (your state invariant) and `spec fn st_val(s: &QAcc, k: Key) -> Agg` (the value of group",
        "    `k` that the state stands for). A helper may not reuse a name the host spec defines.",
        "  - the bodies of `q_init`, `q_step`, `q_merge` and `q_finish` between `// AGENT_INIT_START` / `_END`, `// AGENT_STEP_START` /",
        "    `_END`, `// AGENT_MERGE_START` / `_END` and `// AGENT_FINISH_START` / `_END`. A nested `proof fn` or `spec fn` inside a body",
        "    does not work: helpers go in the helper region.",
        "- `p: &Params` is read as `p.<name>` (the template parameters; empty struct without any). In `q_step` the state after the call",
        "  is `final(s)` in the ensures, `old(s)` the one before; in your proof code `s` is the current state.",
        "- No region may name the host runtime or the glue: `Exec`, `exec_*`, `StreamOut`, `Stream_*`, `RawChunk_*`, `StreamEnd_*`,",
        f"  `StrRaw`, `stream_end_*`, `seg_fold`, `seg_agg`, `lemma_stream_total`; no call of `chunk_{n['ts']}(..)`, no `.raw` field, no",
        f"  `Chunk_{n['ts']} {{ .. }}` or `StrCol {{ .. }}` built by hand. You read a chunk only through its fields (`c.off`, `c.len`, the",
        "  column slices, `c.<col>.sel` and `str_ent` for a VARCHAR column).",
        "- Write no `use` lines: every vstd module is imported by glob; call lemmas by bare name",
        "  (`vstd::map_lib::lemma_map_new_domain` in full; that one name is ambiguous).",
        "  The only allowed line is `broadcast use vstd::<module>::group_<name>;` naming a group listed in",
        f"  `{root}/verus/INDEX.md`, inside a body or inside a `proof fn` body; at the top level of the helper region it is rejected.",
        "- Forbidden (rejected before Verus runs): `assume(`, `admit(`, `#[verifier::external_body]`, `assume_specification`,",
        "  `unimplemented!`, `unsafe`, any attribute other than `#[verifier::opaque|rlimit|loop_isolation|spinoff_prover|truncate|inline|memoize|trigger|auto]` /",
        "  `#[trigger]` (so no `external*`, `exec_allows_no_decreases_clause`, `cfg`, `derive`), `impl` / `trait` / `macro_rules!` / `static`,",
        "  and any name containing `axiom`, `arbitrary` or `proof_from_false` outside a `broadcast use` line. You add no trusted item: the",
        "  only two (S1, S2) are the host's. `requires`/`ensures` are the host's; changing them has no effect.",
        "- `StringHashMap` and `HashMapWithView` are in scope (`new`, `insert`, `contains_key`, `get`; the view key is `Seq<char>` for",
        "  strings). Do not call `HashMapWithView::new` on a `String` or a tuple key.",
        "",
    ]


def _contract_section(spec_text: str, n: dict[str, str]) -> list[str]:
    ts, cols, key = n["ts"], n["cols"], n["key"]
    fields = _agg_fields(spec_text)
    chunk = _chunk_fields(spec_text, ts)
    params = _params(spec_text)
    strings = [f.split(":")[0] for f in chunk if f.endswith("StrCol<'a>")]
    nullable = [f.split(":")[0] for f in chunk if f.split(":")[0].endswith("__valid")]
    return [
        "## Streaming contract (this spec has no `run_query`)",
        "",
        f"The rows are not in one `{cols}` you can index. A ghost table `T = stream_table_{ts}(id)` stands for the rows the scan of `{ts}`",
        "returns (each row once). The scan hands the rows out in CHUNKS of consecutive rows `[c.off, c.off + c.len)` (at most 2048 rows",
        "each), to several worker threads at once, in any order. Each worker owns one state: `q_init` makes it, `q_step` folds one chunk",
        "into it, `q_merge` combines two workers' states (any two, in any order), and `q_finish` answers from the state of all chunks. The",
        "host runtime around them (`Exec`, fixed and proved) checks at run time that the stepped chunks tile `[0, n)` exactly; you never",
        "see the scheduling.",
        "",
        "What you prove is that your state stands for a value of the query's aggregate MONOID, per group: `st_val(s, k)` is an `Agg`",
        f"(spec-only, mathematical `int` fields; `Key` is `{key}`):",
        "",
        "```rust",
        "pub struct Agg { " + ", ".join(fields) + " }",
        "```",
        "",
        "one field per fold the spec's result uses (a SUM, a COUNT, the sum and the count of an AVG, `Option<int>` for a MIN/MAX),",
        "`hits` = the rows of group `k` that pass the WHERE, and `n_hit_*` = per nullable aggregate, the rows whose cell is summed.",
        "The host defines and proves (call by bare name; nothing here is trusted):",
        "",
        "- `agg_zero()`, `agg_plus(a, b)` (fieldwise `+`; `omin` / `omax` on `Option<int>`), `agg_row(t, i0, k, p)` (row `i0`'s",
        "  contribution to group `k`: zero unless the row passes the WHERE and has key `k`), `agg_rng(t, lo, hi, k, p)` (the fold of",
        f"  `agg_row` over rows `[lo, hi)`; `t: &{cols}`).",
        "- `lemma_agg_empty(t, lo, k, p)`: `0 <= lo ==> agg_rng(t, lo, lo, k, p) == agg_zero()`.",
        "- `lemma_agg_step(t, lo, hi, k, p)`: `0 <= lo < hi ==> agg_rng(t, lo, hi, k, p) == agg_plus(agg_rng(t, lo, hi - 1, k, p), agg_row(t, hi - 1, k, p))`:",
        "  a range grows by one row at its end. This is the one fact a forward loop over a chunk needs per row.",
        "- `lemma_agg_laws()`: `monoid_laws(agg_zero(), agg_plus_f())` and `comm_laws(agg_plus_f())` (identity, associativity,",
        "  commutativity of `agg_plus`; for `q_merge`).",
        "- `lemma_agg_total(t, k, p)`: the range `[0, t.n)` equals the spec's own folds field by field (the spec fn of the same name at",
        "  row 0), `hits > 0 <==>` some row of group `k` passes the WHERE, and for a MIN/MAX field `None <==>` no such row and",
        "  `Some(b) ==>` the spec's min/max predicate holds of `b`. With it `q_finish` meets `run_query_ok` without any loop over rows.",
        "- From the generic library (`research_loop/verus_lib/stream_lib.rs`, pasted in the spec): `fold_by`, `sum_by` and their",
        "  push/concat/permutation lemmas, `omin` / `omax` with `lemma_omin_at` / `lemma_omax_at`, `monoid_laws`, `comm_laws`.",
        "",
        "The contracts you implement (verbatim from the spec):",
        "",
        "```rust",
        _contract_text(spec_text),
        "```",
        "",
        f"What the chunk view `c: &Chunk_{ts}` gives you (the host's trusted item S1, stated as `chunk_ok_{ts}(c)`; read it in the spec). With",
        f"`T = stream_table_{ts}(c.sid)`: `c.off + c.len <= T.n`, and for every row `0 <= r < c.len`:",
        "",
        "- a fixed-width column `x` (a slice `&[i64]` / `&[i32]` / ..., DATE as days, DECIMAL as the scaled integer, as in the spec):",
        "  `c.x@.len() == c.len` and `c.x@[r] == T.x@[c.off + r]`;",
        *(["- a nullable column `x` has `c.x__valid` beside it: `c.x__valid@[r] == T.x__valid@[c.off + r]` always, and the value",
           "  `c.x@[r] == T.x@[c.off + r]` only where the cell is valid; test the bit before you use the value."] if nullable else []),
        *(["- a VARCHAR column `g` is a `StrCol`: `c.g.sel@.len() == c.len`, every `c.g.sel@[r] < c.g.ents@.len()`, and",
           "  `c.g.ents@[c.g.sel@[r] as int] == T.g@[c.off + r]@` (row `r`'s string is entry `sel[r]`). `ents` is ghost; the one way to read an",
           "  entry is `str_ent(&c.g, j)` (requires `j < c.g.ents@.len()`, ensures `s@ == c.g.ents@[j as int]`, a `&str` borrowed from the",
           "  chunk). Several rows may share an entry (DuckDB's dictionary vectors) or each row has its own (flat vectors): never assume",
           "  either. The entry count is not an exec value: an entry index you can use is one that occurs in `sel` (so `1 + max sel[r]`",
           "  bounds the entries the chunk's rows use). `c.g.dict_id` is plain data: nothing is promised about it, so a memo that",
           "  survives the chunk cannot be proved; build it per chunk."] if strings else []),
        "",
        "Every value is exact (`int` in the spec); there are no data assumptions, so no cell, sum or row count has a cap. An exec",
        "addition or product that could overflow must be checked (`checked_add` / `checked_mul`, decline on `None`) or proved in range from",
        "the cell types and a run-time check you made (an `i64` cell times an `i64` cell always fits `i128`; a sum of `i128` does not).",
        "",
        "Declining: `q_step` returning `false`, `q_merge` or `q_finish` returning `None` declines the query: the runtime then answers",
        "nothing (it never answers wrongly). A run that declines on the measured data is reported as DECLINED: not a success, not a proof",
        "failure, never replaced by another engine's answer, and in experiments a declined query counts as a failed query.",
        "",
        "The proof shape that works: in `q_step` a forward loop over `r` in `[0, c.len)` with the invariant",
        "`forall|k: Key| #[trigger] st_val(s, k) == agg_plus(st_val(&s0, k), agg_rng(&T, c.off as int, c.off + r, k, p))` (`s0` a ghost copy",
        "of the state before the loop, `T` a ghost of `stream_table_..(c.sid)`, `chunk_ok_..(c)` and `qacc_inv(s)` in the invariant too),",
        "and per row `lemma_agg_step(&T, c.off as int, c.off + r + 1, k, p)` with the row's cells tied to `T` by S1 (`assert(c.x@[r] ==",
        "T.x@[c.off + r])`). `q_merge` adds the two states group by group (`lemma_agg_laws()` for the reordering). `q_finish` calls",
        "`lemma_agg_total(&t@, k, p)` per group and builds the rows; HAVING, ORDER BY and LIMIT are done here, over the groups, not",
        "per row. `qacc_inv` usually ties the state's parts together (a key -> slot map and its key list, parallel `Vec` lengths).",
        "",
        *(["This query is a template: its parameters are the fields of `p: &Params` (" + ", ".join(f"`{x}`" for x in params) + "); the proof",
           "holds for every value of their types, and each official timed round runs the binary and DuckDB with the same freshly drawn values.",
           ""] if params else []),
    ]


def _timing_section() -> list[str]:
    threads = int(lemma_config.get("duck_threads"))
    return [
        "## How the program is timed (this run: the binary-mode stream main, not yet inside DuckDB)",
        "",
        "`run_runquery` and the official measure compile your program with the host's binary-mode stream `main`: it reads the exported",
        "column file of the table and checks it (not timed), cuts the rows into chunks of random sizes in [1, 2048] (VARCHAR columns",
        f"alternate between one entry per row and dictionary-style shared entries), and in each timed run starts {threads} workers (one per",
        "DuckDB thread of the reference measure) that take chunks from one shared counter and call `q_step`, then merges the workers'",
        f"states with `q_merge` and calls `q_finish`. The time is the median of {_timed_runs()} such runs. `q_step` runs once per chunk on every",
        "worker: it is the hot loop. `q_init` runs once per worker, `q_merge` once per pair of workers, `q_finish` once: they are cold.",
        "The reported time does not include reading the file. The later in-DuckDB measure (DuckDB's own parallel scan handing its",
        "chunks to the same code) is not used yet; each result says so in `stream_measure`.",
        "",
    ]


def _timed_runs() -> int:
    from declarative_spec.assemble import TIMED_RUNS

    return TIMED_RUNS


def _speed_section() -> list[str]:
    return [
        "## Speed (the hot loop is `q_step`)",
        "",
        "- `q_step` is called once per chunk (up to 2048 rows) on every worker: keep its row loop branch-free and allocation-free. A filter",
        "  is a 0/1 value, not a branch: `acc = acc + (if hit { v } else { 0 })` or `count + (hit as u64)`; combine conditions as u8",
        "  factors multiplied (`(if a { 1u8 } else { 0 }) * (if b { 1u8 } else { 0 })`), since Verus rejects `&` / `|` on bool. No `Vec`,",
        "  `String` or map insert per row; no `String::clone` or hashing per row.",
        "- Exact arithmetic fast: per chunk, first check the ranges you need at run time (for example the largest absolute cell of each",
        "  column in this chunk, or that every product of this chunk fits in 64 bits), then run the row loop in `i64` / `u64` (products",
        "  of two values that fit 32 bits are exact in 64 bits) into chunk-local accumulators, and add the chunk's totals into the `i128`",
        "  state once. When the check fails, run the same chunk on an exact `i128` path (checked, declining only on a real `i128`",
        "  overflow). The proof covers both paths: the run-time check is what gives the fast path its bounds (no data assumption).",
        "- Group keys that are strings: map each ENTRY of the chunk to its group once, not each row. Per chunk, take `m = 1 + max sel[r]`",
        "  of the key column, fill a `Vec<usize>` memo of length `m` with the group slot of entry `j` (look `str_ent(&c.g, j)` up in your",
        "  key -> slot map, opening a slot when it is new; or only for the entries that occur, with an `in use` marker), then per row the",
        "  slot is `memo[sel[r]]`: an array read. With several string key columns, memo each column's entries to a small code and combine",
        "  the codes into one slot index (`code_a * width_b + code_b`) into dense per-slot accumulators. Prove the memo with an invariant",
        "  like `forall|j| j < memo.len() ==> slot_key(s, memo[j]) == c.g.ents@[j]` (only for the entries the memo has filled).",
        "- Accumulate a chunk into local scalars or a small per-slot array, then add it to the state once per chunk; keep the state's",
        "  accumulators in `Vec`s indexed by slot (no map update per row).",
        "- `q_merge` and `q_finish` are cold: a simple loop over groups is fine there. HAVING, ORDER BY and LIMIT belong in `q_finish`.",
        "- Get a verified program first (a plain checked `i128` loop per row is a correct `q_step`), submit it, then make `q_step` fast.",
        "",
    ]


def _do_not_section() -> list[str]:
    return [
        "## Do not",
        "",
        "- Verus rejects these in exec code: `sort`/`sort_by`; iterating a `HashMapWithView`/`StringHashMap` (`.iter()`, `.keys()`,",
        "  `.entry()`; keep the keys in a `Vec` next to the map and loop over the `Vec`); `for x in &mut v`, `.iter_mut()`, `.into_iter()`;",
        "  `.clone()` on an `OutRow` (write `OutRow { .. }` from fields; `String::clone` is fine); `as int`, `as nat` outside ghost code",
        "  (`proof {}`, invariants, `spec fn`). Use `while` loops over indices, each with a `decreases`.",
        "- Keep `chunk_ok_<t>(c)` (and the ghost `T == stream_table_<t>(c.sid)`) in every loop invariant of `q_step`, and `qacc_inv` of",
        "  the state a loop changes: a fact a loop does not restate is forgotten inside and after it.",
        "- Never replace a failing region with a placeholder (`false` / `None` / an empty result) to have something to submit: a",
        "  declining program is a failed query. Keep the version with the fewest errors and fix the error the host reports.",
        "- Use only names that exist: the host spec, the lemma index, vstd (grep `LEMMAS.md`), your own helper region.",
        "",
    ]


def _hygiene_section() -> list[str]:
    return [
        "## Proof hygiene that costs people time",
        "",
        "- Give every quantifier an explicit `#[trigger]`; the contracts trigger on `st_val(s, k)`, so state per-group facts with",
        "  `st_val(..)` as the trigger term. Call host lemmas inside `proof { .. }` or `assert forall .. by { .. }`.",
        "- A quantified invariant whose body mentions the NEXT index loops the solver; use a two-term trigger (`#![trigger res@[q], res@[q + 1]]`).",
        "- A long proof exhausts the rlimit (@@RLIMIT@@ here) and Verus then reports a misleading error such as `invariant not satisfied",
        "  before loop`. Put each invariant bundle in a `#[verifier::opaque] spec fn` revealed in a small `proof fn`, or move a step into an",
        "  exec helper `fn` with its own `requires` / `ensures` (the callers then use only those). `#[verifier::rlimit(N)]` on one helper",
        "  is accepted. `verify_functions` checks one function at a time.",
        "- A struct equality of two `Agg` values is decided field by field; when it fails, assert the fields that differ one by one to",
        "  see which one.",
        "- A spec function of a row (`key_at(t, i0)`) only fires on a ground term: bind one (`let w = key_at(&T, c.off + r);`) or take a",
        "  witness with `choose|..| ..` before you assert the instance.",
        "- Exec helper `fn`s are verified against their own `requires` / `ensures` (give each loop and recursion a `decreases`); a",
        "  postcondition on a `&mut` parameter uses `final(x)` / `old(x)`. No `struct`, `impl`, `trait`, `macro_rules!`, `static` or `use`",
        "  in the helper region (types go in the state region).",
        "- A string literal compared with a `&str` has no spec tying it to `@`: build the literal once (`String::from_str`, ensures",
        "  `x@ == \"..\"@`) and compare with it.",
        "- `Vec::insert` has the view `Seq::insert`; `Seq::insert_ensures` (vstd `seq_lib.rs`) gives its length and element facts. Grep",
        "  `LEMMAS.md` for a vstd lemma before you write your own.",
        "",
    ]


def _helper_example() -> list[str]:
    return [
        "## Region example (the shape of a file; names are placeholders)",
        "",
        "```rust",
        "// AGENT_STATE_START",
        "pub struct QAcc { pub cnt: u64 }",
        "// AGENT_STATE_END",
        "// AGENT_HELPERS_START",
        "pub open spec fn qacc_inv(s: &QAcc) -> bool { true }",
        "pub open spec fn st_val(s: &QAcc, k: Key) -> Agg { .. }",
        "// AGENT_HELPERS_END",
        "// AGENT_INIT_START",
        "    QAcc { cnt: 0 }",
        "// AGENT_INIT_END",
        "```",
        "",
    ]


def build_stream_prompt(
    *,
    sql: str,
    spec_path: str,
    edit_path: str,
    lemma_index: str,
    last_error: str,
    in_docker: bool,
    spec_text: str,
    restart_note: str,
) -> str:
    from declarative_spec.prompt import (
        _GROUP_CLOSE_OUTLINE,
        _GROUP_CLOSE_OUTLINE_PRINCIPLES,
        _data_profile_section,
        _division_text,
        _error_excerpt,
        _exact_rational_section,
        _group_close_section,
        _hardware_facts,
        _speed_target_section,
    )

    if in_docker:
        spec_path = "/workspace/context/ro/spec.rs"
        edit_path = "/workspace/runquery_agent.rs"
        index_path = "/workspace/context/ro/lemma_index.md"
        root = "/workspace/context/ro"
    else:
        index_path = "context/ro/lemma_index.md"
        root = "context/ro"
    n = _names(spec_text)
    head, pointer, tools = _what_you_get(edit_path, spec_path, root, index_path)
    # the closing lemmas apply to q_finish over t@; the outline of a run_query worked example (not mounted here) is left out
    outline = {*_GROUP_CLOSE_OUTLINE, *_GROUP_CLOSE_OUTLINE_PRINCIPLES}
    group_close = [
        ln.replace("at the end of `run_query` call", "at the end of `q_finish` call (over `&t@` and the parameters `p.<name>`)")
        .replace("inside `run_query`", "inside `q_finish`")
        .replace("the matching `run_query` postcondition", "the matching clause of `run_query_ok`")
        for ln in _group_close_section(spec_text)
        if ln not in outline
    ]
    P = principles
    parts: list[tuple[str, list[str]]] = [
        (P.TASK, ["# Declarative streaming executor (q_init / q_step / q_merge / q_finish)", ""]),
        (P.TOOLS, head),
        (P.EXAMPLE_POINTER, pointer),
        (P.TOOLS, tools),
        (P.TASK, _speed_target_section(lemma_config.get("speed_target"))),
        (P.RULES, _regions_and_rules(root, n)),
        (P.TASK, ["## SQL", "", "```sql", sql.strip(), "```", ""]),
        (P.RULES, _contract_section(spec_text, n)),
        (P.LIMITS, _timing_section()),
        (P.HARDWARE, _hardware_facts()),
        (P.EXAMPLE_POINTER, [
            "## Worked examples",
            "",
            f"`{root}/examples/INDEX.md` lists verified stream programs (all six regions) on a small invented table `t`: an ungrouped",
            "SUM with a filter and a nullable column, and a GROUP BY a string key with COUNT and SUM (a key -> slot `StringHashMap` with",
            "its key list, merge slot by slot, finish with `lemma_agg_total`). They are proof templates, not speed templates (their",
            "`q_step` looks the key up per row): see the speed section for the hot loop.",
            "",
        ]),
        (P.RECIPE, _speed_section()),
        (P.RULES, _exact_rational_section(spec_text)),
        (P.RECIPE, group_close),
        (P.LIMITS, _data_profile_section(root)),
        (P.RULES, _do_not_section()),
        (P.RULES, [_hygiene_section_text()]),
        (P.RULES, _helper_example()),
        (P.TOOLS, ["## Lemma index", "", lemma_index.replace("Write the `run_query` edit before", "Write your regions before").rstrip()]),
    ]
    sections: list[str] = []
    emitted = P.kinds_emitted()
    for kind, lines in parts:
        assert kind in P.KINDS, kind
        if kind in emitted:
            sections += lines
    if restart_note.strip():
        sections.extend(["", "## This is a restart: where your file stands", "", restart_note.strip()])
    if last_error.strip():
        sections.extend([
            "",
            "## Previous host error",
            "",
            (
                "These are the first errors of the previous session's LAST attempt (not necessarily the file now in place; see above)."
                if restart_note.strip()
                else "The last compile or verify of your file failed. Fix it and call `run_runquery` again."
            ),
            "",
            "```",
            _error_excerpt(last_error),
            "```",
        ])
    sections.extend([
        "",
        "## Do this now",
        "",
        "This is a non-interactive session: nobody answers questions. Do the task now. Never ask the user anything and never",
        "offer options. Do not stop until `run_runquery` shows `N verified, 0 errors` and you have called `submit_runquery` with the",
        "`run_id` of your best verified program. A verified program that stays below the bar cannot be submitted (the host refuses it):",
        "keep improving `q_step` until the wall, and leave your best verified file in place. If you conclude it cannot verify, say",
        "plainly why in your last message; an empty or placeholder region is a failure, not a result.",
    ])
    return _division_text(principles.scrub("\n".join(sections))) + "\n"


def _hygiene_section_text() -> str:
    return "\n".join(_hygiene_section()).replace("@@RLIMIT@@", f"{lemma_config.get('verus_rlimit'):g}")
