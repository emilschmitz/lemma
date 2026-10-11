# What the Lemma container agent receives, per LEMMA_EXAMPLES mode

Query: SSB Q2.1 (sum(lo_revenue), d_year, p_brand1 ... p_category='MFGR#12', s_region='AMERICA'), package `ssb_sf1.json`,
`LEMMA_STRING_ENCODING=dict LEMMA_JOIN_CHAIN=1`, menu `adversary_declarative0` (parallel params auto, target-cpu x86-64-v3), model claude-sonnet-5-5.
Code at branch commit cd47a53.

## How it was produced (and the gap)

The workspace is built by `declarative_spec/drive.py::run_declarative_optimization_loop`:
`emit_declarative_spec` -> `_ensure_context_files` (spec.rs, query.sql, schema.json, lemma_index.md, `mount_verus_docs`, `mount_examples`)
-> `runquery_agent.rs` = copy of the spec -> `build_declarative_prompt` -> written to `context/ro/DECLARATIVE.md` and (`agent_sandbox.run_agent_docker`) to
`PROMPT.txt`, piped to `claude -p` in the container. The script that reproduced it (no container, no agent, no prover) calls exactly those functions
with the same schema projection and catalog (`LEMMA_ASSUMPTION_PACKAGE`) as `db_extension/optimizer.py`.
Validation: the `spec.rs` is byte-identical to the real frozen run `research_loop/runs/20261010T223124Z_q4_e7190cc3` (same query, SHA 75f4303). The prompt differs from that
run's `PROMPT.txt` only by code changes after 75f4303 (19 diff lines: admission-rule sentence, parallel recipe wording, examples set).
Gap: the prompt's `dict_sizes` (dense-slot budget section) normally comes from the DuckDB measure at prepare time; I took them from that real run's
`decl_data/expect.json` (`part.p_brand1` 1000, `part.p_category` 25, `supplier.s_region` 5) instead of running the measure. Nothing else in the prompt depends on a run.
The hardware block in the prompt is this laptop (`lscpu`, 8 CPUs, 15 GB), as it was for the frozen run.

Layout per mode: `<mode>/PROMPT_as_sent.txt` (exact prompt text), `<mode>/mounted_files/` (all text files; `context/ro/...`, `runquery_agent.rs`, `PROMPT.txt`),
`<mode>/tree.tsv` (bytes, path of EVERY mounted file incl. vendor docs), `<mode>/vendor_docs_listing.tsv` (names+sizes of the vendor docs left out:
`context/ro/verus/{vstd,guide,examples,tests}`, 583 files, 6.8 MB, identical in all modes), `<mode>/vendor_dirs_summary.tsv`.

## Information sources (same for all modes unless noted)

| Source | Where | Size | Differs by mode? |
|---|---|---|---|
| Task prompt (`DECLARATIVE.md` == `PROMPT.txt`) | prompt via stdin | full 351 lines / 36.1 KB; principles 341 / 33.0 KB; none 332 / 31.6 KB | yes (see below) |
| SQL + schema | prompt block, `context/ro/query.sql`, `schema.json` | 5 lines / 0.27 KB; 21 lines / 0.35 KB (projected to the 4 tables, 13 columns) | no |
| Spec file (MethodSpec, typed `Cols_*`, `valid_cols_*` with the catalog caps, `row_hit`, folds, `OutRow`, postcondition) | `context/ro/spec.rs` | 539 lines / 30.3 KB | no |
| `run_query` skeleton | `/workspace/runquery_agent.rs` (= spec + empty `AGENT_HELPERS` and `AGENT_EDIT` regions) | 539 lines / 30.3 KB | no |
| Host lemma library inside the file (chain-hit uniqueness, per-row fold lemmas `lemma_sum_sum_row`, group-close lemmas, `seq_le`) | spec.rs lines ~116-517 | ~400 lines, part of the 539 | no |
| Task docs: rules, regions, recipes for this spec shape, dense-slot budget, star-join "what the host proved", parallel section, "Do not" list, speed/bar, proof hygiene | inside the prompt | most of the 330-350 lines | small edits (below) |
| Lemma index (callable host lemma names for this spec) | `context/ro/lemma_index.md` | 43 lines / 3.3 KB (none: 42 / 3.1 KB) | example citations removed in none |
| Verus guide/lemma docs | `context/ro/verus/INDEX.md` 98 lines/6.3 KB, `LEMMAS.md` 11,591 lines/564 KB, `EXAMPLES_INDEX.md` 299/28 KB, `GUIDE_INDEX.md` 161/14.8 KB; plus raw vstd source (129 files, 1.8 MB), guide (157, 0.5 MB), Verus examples (160, 1.3 MB), Verus tests (137, 3.1 MB) | 6.8 MB raw + 0.6 MB indexes | no |
| Worked examples (verified `run_query` bodies) | `context/ro/examples/` + `INDEX.md` | full: 75 files, 1.54 MB, 32.9k lines (incl. 15 `hard/` files, SSB Q3.1/Q4.1/Q4.2 star joins, TPC-H Q1/Q3/Q12/Q14/Q19, 96-line INDEX); principles: 7 files + INDEX, 66.7 KB, 1.2k lines, invented schema (events/items/users); none: nothing | yes |
| Data profile / statistics | prompt: row caps of the official tables (lineorder 33,554,432 ...), the dictionary sizes for the dense-slot budget, iterate cap 50,000 rows; no raw rows (AGENT_DATA_MODE stats) | ~15 lines | no |
| Hardware info | prompt: `lscpu` excerpt, MemTotal, target-cpu, "DuckDB threads=8, memory_limit=3GB", worker-count guidance | ~15 lines | no |
| Speed bar | prompt: timed on the full table vs all-core DuckDB; submit refuses verified bodies below the bar | ~12 lines | no |

## Tools

- Claude Code (`claude -p --permission-mode acceptEdits --allowedTools Bash,Read,Edit,Write,Glob,Grep,mcp__lemma-host --disallowedTools WebSearch,WebFetch --strict-mcp-config`), run in
  a container with network none and an allowlisted API egress. The init message of the real run lists these tools: Bash, Read, Edit, Write, Glob, Grep, plus (not removed)
  Task, Cron*, EnterWorktree/ExitWorktree, ListAgents, NotebookEdit, RemoteTrigger, ReportFindings, ScheduleWakeup, SendMessage, Skill, TaskStop, ToolSearch, Workflow, MCP resource readers.
  No web. Shell and file tools see `/workspace` (and the container image).
- MCP server `lemma-host` (`db_extension/agent/mcp_tool_specs.py`), 7 tools:
  - `validate_runquery`: checks the edit markers and that no `assume` was added; does not verify.
  - `run_runquery(path, dataset_size?)`: admission, Verus verify, compile, run. Returns `run_id`, `ok`, `metrics`: `proof_verified`, `verify_summary` ("N verified, M errors"),
    `compiler_error` (reduced Verus/rustc errors, locations mapped to `runquery_agent.rs`, host-owned lines marked; full log in the run dir), `latency_us` (kernel time),
    `duck_us`/`duck1_us`/`duck_threads` (DuckDB time, all cores and one core), `speedup`, `speedup_1t`, `speedup_best`, `speed_bar_mult`, `official_tables` (row counts),
    and the row check ("proved but result rows differ from the loaded table ..." as an error). Default size is the 50,000-row iterate cap; the timed official run is host-side after submit.
  - `submit_runquery(run_id)`: marks a verified run (refused if unverified or below the speed bar).
  - `session_status` (wall-clock budget), `get_submit_result`, `list_runs`, `mcp_health`.

## What differs between the modes

| | full | principles | none |
|---|---|---|---|
| `context/ro/examples/` | 75 verified bodies + INDEX, benchmark-shaped (SSB Q3.1/Q4.1/Q4.2 star joins, TPC-H Q1/Q3/Q12/Q14/Q19) | 7 small bodies on an invented schema + INDEX | absent |
| Prompt "recipe for THIS spec" | points at a close-shape example (same shape in full) | points at the technique examples | generic text |
| Example citations in prompt/lemma_index/hints | benchmark example paths | principles paths | removed (`principles.scrub`) |
| MCP hint text (run_runquery) | cites the full set | cites principles | cites none |

## 'none': what is still there beyond task + docs + tools

Greps (`PROMPT.txt`, `spec.rs`, `lemma_index.md`, `verus/*.md`) find no TPC-H/SSB name, no query id (Q1...), no example path, and no `.rs` body of another query.
Remaining items:
1. **Dangling example text.** Sentences that mention examples without naming a path survive the line-based scrub: "read the ones whose technique your spec needs (a scan ..., a unique-key join as a lookup, a star join with a group-by, a sorted top-N, a parallel scan, NULL-skipping aggregates)" (PROMPT line ~89), the section "Which techniques have worked examples" (lines ~182-190) and "the examples keep ... per slot" (line ~108). They refer to files that do not exist in none mode. Not a solution, but a hint at the technique list and a prompt inconsistency.
2. **A pasted example header.** The "Parallel scan" section still embeds the header comment of `principles/parallel_scan_sum.rs` ("Principle 6: a PARALLEL scan with vstd threads ... SELECT SUM(ev_qty) FROM events ...", ~22 lines, telescoping proof, chunk bounds, merge rule) and says "The example is the template", although the file is not mounted. This is a technique description of an invented query, not a benchmark query, but it is example-derived material.
3. **Star-join recipe in prose.** Section "Star / chain join: what the host has already proved" (lines 97-109) names the host lemmas (`lemma_chain_hit_unique`, `lemma_sum_sum_row`) and gives the plan: one pass over the fact table, an array per dimension indexed by `key + offset`, never loop over a dimension inside the fact loop, overflow bound. Similarly a "Dense slot table" section (per-group-code arrays) and a "Grouped result" closing-lemma section. This is an algorithm outline for a star join/group-by, generated for this spec shape; it is part of the product's task docs, not an implementation.
4. **Host lemmas in the file** (`lemma_sum_sum_row`, `lemma_group_close_*`, ~400 lines) prove the per-row fold and grouped output facts; they carry the star-join proof structure but no executable code. Code that implements a star join (index build, probe loop) exists in none mode only in `LEMMAS.md`/vstd (generic, none star-join) and in the paper-header of item 2 (a scan, not a join).
5. Verus `examples/` and `tests/` (vendor, 160 + 137 files): no file name or EXAMPLES_INDEX line mentions SSB, TPC-H, lineorder or a join (grep over names and the index); file contents not read.
