# Configuration: `lemma.toml`

Every setting that shapes a container run, and the safety/infrastructure settings around it, lives in **one file: `lemma.toml`** at the repo root. One line per key, each with a comment. `python -m lemma_config dump` prints every key with its effective value and where it came from. The loader is `lemma_config.py` (stdlib `tomllib`); code calls `lemma_config.get("key")`, shell scripts `python3 -m lemma_config get <key>`.

## The rule

```
lemma.toml  <  experiment file (configs/experiments/X.toml)  <  environment variable LEMMA_<KEY>  <  explicit CLI flag
```

* The variable of a key is `LEMMA_` + the key upper-cased, in any section: `[measure] official_rounds` is `LEMMA_OFFICIAL_ROUNDS`. An empty variable counts as unset. Booleans are `0/1/true/false`.
* CLI flags exist on the launcher (`run_container_agent.py`: `--style --menu --agent --trusted-set --assumption-package --speed-bar-mult --max-iterations`); `container_batch.py` takes `model:query` pairs and passes the model as `--agent`.
* The experiment file is the fourth source (`experiment`, origin = its path): `[settings]` use lemma.toml keys (unknown keys fail), and each `[[run]]` supplies `agent_model`, `duckdb_path`, plus `assumption_package` exactly when the experiment has `assumptions = true` (with the default `false` a package is refused). A replicable run (`container_batch.py --experiment`) refuses any `env`/`cli` source; see AGENTS.md "Replicable experiments".
* Query templates in a container run: a `[[run]]` whose query has a `-- params:` header also sets `bindings_rules` (repo-relative substitution JSON, tracked at HEAD; the entry named by the query file's stem is used) and `bindings_seed` (integer). `drive.py` draws `official_rounds + 1` bindings from (rules, seed) with `templates.generate_bindings`, uses `[0]` for prepare and in-session runs, and records rules path, seed and the full list in the run manifest (`template_bindings`). A template without them is refused before the agent starts.
* No other source. `research_loop/config.env` no longer owns any container-run setting (it keeps only the legacy imperative / overnight / OpenRouter ones, see its header).
* Startup check (`container_batch.py`, `run_container_agent.py`, `python -m lemma_config check`): an unknown `LEMMA_*` variable (typo or dead flag), a dead setting, a bad value or type, or a duck memory limit at or above the scope cap raises, listing the culprits. Nothing falls back to a default. Two keys have no default at all: `duckdb_path`, and `assumption_package` while `assumptions = true` (empty in the file; a run without a value, from the file, `LEMMA_<KEY>` or a flag, stops at startup with a message; `assumption_package = "auto"` remains valid as an explicit value). With `assumptions = false` (the default) `assumption_package` must stay empty; a value stops the run.
* Old spellings still work with a one-line deprecation message (table below). If both spellings are set to different values it raises.
* Every container run writes all keys with `value`, `section`, `source` (`file`/`experiment`/`env`/`cli`) and `origin` into the run manifest (`lemma_config`) and the `RESULT` line (`config`), with `git_sha`, `git_dirty` and `git_untracked_files` (a count; untracked files never make `git_dirty` true). A dirty tree (tracked files; untracked and gitignored data do not count) is refused unless `allow_dirty = true`.
* `container_batch.py` forwards nothing by name. The child reads `lemma.toml` itself; the batch passes only values that differ from the file (`lemma_config.forwarded_env`, plus `LEMMA_CONFIG_ORIGIN` so a flag is still reported as a flag).

## Sections (63 keys)

| Section | Keys |
| --- | --- |
| `[run]` | `spec_style menu agent_model trusted_set assumptions assumption_package speed_bar_mult max_iterations string_encoding join_chain examples narrow_cells pushdown agent_scan parallel_vstd stateful stream prover` |
| `[agent]` | `speed_target max_idle_sessions agent_timeout_sec max_budget_usd agent_submit_ends_session agent_data_mode agent_resource_exhausted_retries harness agent_auth claude_effort claude_thinking_tokens claude_tool_search mcp_iterate_rows` |
| `[prover]` | `verus_rlimit verus_timeout_sec run_timeout_sec target_cpu dense_slot_budget verus_home prover_image image_registry` |
| `[measure]` | `official_rounds official_duck_reps duck_memory_limit duck_threads` |
| `[data]` | `duckdb_path data_profile` |
| `[sql]` | `agg_times_constant derived_agg_expr cte_reuse left_join_count exact_division templates` (new SQL shapes of the transpiler, default false, verdicts in `research_loop/menus/sql_<feature>_ADVERSARY_VERDICT.md`; except `exact_division`, default **true**: AVG and `/` over exact operands are exact rationals with no float trusted item, a FLOAT/DOUBLE operand is refused, false = the f64 idealization, see `docs/TRUSTED_FAMILIES.md`) |
| `[engine]` | `in_duckdb` (Lemma inside DuckDB, default off; see the section below) |
| `[wip]` | `zero_copy cold_stream cold_stream_mode` (parked pin path, default off, see `research_loop/menus/pin_path_archive.md`; nothing here is used by a container run) |
| `[safety]` | `allow_dirty scope_memory_max egress_profile egress_allowlist heavy_lock heavy_min_avail_mb heavy_mem_max verus_mem_max verus_slots verus_min_avail_mb` |

Meaning, allowed values and defaults are in the file. `menu` selects a profile (`research_loop/menu_profile.py`); the next four axis keys override its values (the launcher takes them as authority and the selection printed first shows them as overrides).

## No data assumptions: `assumptions` (default `false` since 2026-10-17)

Owner decision, following JetStream (arXiv 2610.20527). The assumption-package path (`assumptions = true`) is **UNMAINTAINED**: it stays
byte-identical for the old runs (`tests/test_assumptions_flag.py` hashes the spec and the assembled program of five TPC-H queries) but is
not extended.

With `assumptions = false` (declarative chain; `declarative_spec/decline.py`):

* **Spec.** No row caps (`ROW_CAP_*`), no value or DECIMAL-precision bounds, no dictionary-size caps, no unique keys, no join caps in
  `valid_cols_*`. What remains is what the fixed loader builds and checks: each column vector has length `n`, dictionary codes index their
  dictionary, dictionary entries are distinct, and (for an integer SUM) `n <= isize::MAX`, a fact of the Rust types. A catalog with any cap
  passed to the emitter is refused. Cell types come from the SQL type alone: DECIMAL(p,s) i64 (p <= 18) or i128, BIGINT i64,
  INTEGER/SMALLINT/TINYINT i32/i16/i8, DATE i32 (days), VARCHAR a u32 dictionary code (dictionary mode). Arithmetic in the spec is over
  exact integers; nothing is refused for possible overflow (a SUM that may leave i128 is the body's problem: it declines).
* **Contract.** `run_query` returns `Option<T>` (T = the old result type); the old `ensures` clauses are the spec fn
  `run_query_ok(<params>, res: T)`, and `run_query` ensures `res matches Some(res) ==> run_query_ok(.., res)`. `None` = DECLINE, always
  allowed. When to decline (e.g. `checked_add` returned None) is the agent's choice: coverage and speed, not correctness. The prompt says
  this in one paragraph, with no recipe.
* **Nullability** is read from the database (`research_loop/structural_catalog.py`: a column holding a NULL gets a validity vector). It
  is a representation choice, not a proof assumption: the exporter refuses a NULL in any other column.
* **Generated main.** No cap `assert!`s (they followed the caps). The structural checks stay: lengths, codes in range, distinct entries,
  `n <= isize::MAX`. On `None` the program prints `LEMMA_DECLINED` and exits with code **3** before any row or latency line.
* **Harness.** `pipeline.compile_and_run` turns that exit into status **`DECLINED`** (`proof_verified` true, no latency). A decline in a
  later official round (another template binding) is also `DECLINED`. The MCP `run_runquery` result has `ok: false, declined: true`
  (submit refuses it); the loop's result and the launcher's `RESULT` line say `status: DECLINED`, `declined: true` and exit 1: in
  experiments a declined query is a FAILED query. The official measure never substitutes DuckDB's answer or time for ours.
* **C ABI (for the in-DuckDB extension, built elsewhere).** Status codes `0` OK, `1` DECLINED, `2` error (`decline.ABI_STATUS_*`). The
  extension may answer a declined query with DuckDB only under its user flag `lemma_route_unproved`, and must label that answer as not
  produced by the proved program.
* **CLI.** `lemma optimize` needs no approved package (`lemma assumptions` is only for `assumptions = true`); a DECLINED run installs nothing.
* **Experiments.** `configs/experiments/*.toml` omit `assumption_package`; the three older files set `assumptions = true` to replay as recorded.

## Resolved conflicts (one value each)

| Setting | Was | Now |
| --- | --- | --- |
| `agent_timeout_sec` | 600 (config.env, code, AGENTS.md), 750 (batch) | 900 (2 x 1800 s = 60 min per query) |
| `max_iterations` | 1/4 (`MAX_ITERATIONS` in overnight chains), 3 (loop default), 2 (launcher flag) | 2 |
| Verus wall | `VERUS_VERIFY_TIMEOUT_SEC` 120 (imperative) vs `LEMMA_VERUS_TIMEOUT_SEC` 300 | `verus_timeout_sec` 300; the MCP harness wait is derived from it (`VERUS_VERIFY_TIMEOUT_SEC` is its alias) |
| harness timeout precedence | file beat environment for `COMPILE_TIMEOUT_SEC`/`VERUS_VERIFY_TIMEOUT_SEC` | environment beats file, like everything else |
| `agent_data_mode` | `stats` (code), `none` (config.env), `stats` (compose) | `none` |
| `parallel_vstd` | off in the module, forced `auto` by the launcher, shell value overwritten | explicit `auto` in `[run]`, overridable; values `off/auto/on` (was `1`) |
| `duck_memory_limit` vs scope | default 3GB, frozen run 8GB, scope `MemoryMax=6G` | 8GB, scope `scope_memory_max = "9G"` (= `lemma.slice` cap), checked `duck < scope` |
| `heavy_min_avail_mb` | 3500 (heavy_phase.py), 4000 (heavy.sh) | 4000 |
| `agent_model` | `claude-haiku-4-5-20251001` (menu profile) | `claude-sonnet-5-5` (the frozen run) |
| dirty tree | not checked for container runs (`LEMMA_EXPERIMENT` not set by the launcher) | refused by default (`allow_dirty`) |

## Old spellings (aliases, deprecated)

`AGENT_TIMEOUT_SEC AGENT_SUBMIT_ENDS_SESSION AGENT_DATA_MODE AGENT_RESOURCE_EXHAUSTED_RETRIES` -> `LEMMA_AGENT_*`; `AGENT_EGRESS_PROFILE` -> `LEMMA_EGRESS_PROFILE`; `VERUS_VERIFY_TIMEOUT_SEC` -> `LEMMA_VERUS_TIMEOUT_SEC`; `LEMMA_EXPERIMENT_ALLOW_DIRTY` -> `LEMMA_ALLOW_DIRTY`; `HEAVY_LOCK HEAVY_MIN_AVAIL_MB HEAVY_MEM_MAX VERUS_MEM_MAX VERUS_SLOTS VERUS_MIN_AVAIL_MB` -> `LEMMA_<same>`. The table is `ALIASES` in `lemma_config.py`.

## Removed as dead (rejected when set; `DEAD` in `lemma_config.py`)

`DEFAULT_ROW_LIMIT`, `AGENT_WEB_SEARCH`, `AGENT_DOCS_MOUNT`, `AGENT_SUBMIT_ONLY_MEASURE`, `AGENT_MCP_URL` (parsed, no consumer; the AgentFlags fields are gone), `LEMMA_MCP_URL` (compose only), `LEMMA_FLOAT_ABS_EPS` (docstring), `LEMMA_SERIOUS` (overnight only; the launcher no longer sets it). `LEMMA_TPCH_DB` is no longer forwarded by the batch (a container run reads `duckdb_path`; it stays for `declarative_manual/oneshot/remeasure.py`).
Kept although partly inert: `mcp_iterate_rows` (prompt text and the probe-pin check at submit; the declarative measure itself always times the full tables).

## Not in `lemma.toml`

* Fixed by the container launcher, not chosen: `USE_AGENT_DOCKER=1`, `LEMMA_AGENT_BACKEND=cli`, `LEMMA_RESEARCH_LOG=1`, `AGENT_IMAGE`, `AGENT_CMD`, `AGENT_ENV` (from the model, `declarative_ladder.agent_env`); agent container `--memory 3g --network none --cap-drop ALL`; scope swap 0, `choom -n 800`; the Verus guard slot lock; `LEMMA_MEASURE_DB`, `LEMMA_TRUST_CONFIG` and the trust-config flags (set by `activate_menu`, no reader in the declarative path).
* Environment only (secrets and paths, never in the file): `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `LEMMA_CLAUDE_CONFIG_DIR`, `AGENT_CREDENTIALS_DIR`, `AGENT_AUTH_DIR`, `AGENT_CLI_DIR`, `HTTPS_PROXY`, `LEMMA_VERUS_BIN` (bypass the guard on purpose), `LEMMA_VERUS_REAL`, `LEMMA_MENU_ALLOW_OVERRIDE` (library-level `resolve_menu`).
* Legacy imperative / overnight / Spot / dev scripts keep their own variables (`LEMMA_FAMILY`, `LEMMA_SHUFFLE_*`, `LEMMA_HARVEST_*`, `LEMMA_LAPTOP_LEASE*`, `LEMMA_BUDGET_USD`, `LEMMA_BENCH_TIMEOUT_SEC`, `MAX_ITERATIONS`, `COMPILE_TIMEOUT_SEC`, `AGENT_NETWORK`, `OPENROUTER_*`, `LEMMA_DEMO*`, ...). They are listed in `NOT_CONFIG` in `lemma_config.py` so the startup check accepts them; they are not part of a container run and were not refactored.
* Deep readers that need "not a SEC run" to be expressible still read `LEMMA_DUCKDB_PATH` from the environment (`dataset_config`, `workload_config`, ...); the container launcher exports the resolved absolute `duckdb_path` there.

## Agent harness (`harness`)

`harness = "claude" | "codex" | "gemini"` (`LEMMA_HARNESS`, or `lemma setup --harness codex`), default `claude`: which agent CLI runs in the
sandbox container. Image `lemma-agent:<harness>`; `agent_model` must be a model of that harness (codex: an OpenAI model such as
`gpt-6.1-sol`; gemini: a `gemini-*` model; claude: `claude-*`, any other slug keeps running the legacy Cursor agent). A model of another vendor
is a loud error, and nothing switches harness or credential silently. Details and the per-harness command, MCP config, credentials and egress
hosts: `research_loop/AGENT_SANDBOX.md` "Agent harnesses".

## Agent authentication (`agent_auth`)

`agent_auth = "login" | "api_key"` (`LEMMA_AGENT_AUTH`, or `lemma setup --auth api-key`), default `login`. It decides how the agent CLI of the
selected `harness` authenticates inside the sandbox container; the two never switch silently. Below for Claude Code; codex uses `CODEX_API_KEY`
or `~/.codex/auth.json`, gemini `GEMINI_API_KEY` or `~/.gemini/oauth_creds.json` (same rules: by name only, or the login file read-only).

* `login`: the host Claude Code login file (`~/.claude/.credentials.json`, read-only mount; run `claude` once to log in). `ANTHROPIC_API_KEY` in the environment is ignored and never passed to the container. (`CLAUDE_CODE_OAUTH_TOKEN` and `LEMMA_CLAUDE_CONFIG_DIR` remain login-type credentials of this mode.)
* `api_key`: `ANTHROPIC_API_KEY` from the environment, handed to the container with `docker run -e ANTHROPIC_API_KEY` (name only: the value is never on a command line, written to disk, put in a manifest or logged; `lemma` redacts it from any output it prints). If the variable is empty the run stops; it does not fall back to the login.

## The agent prompt

Every run value the prompt states (DuckDB threads and memory limit, iterate cap, Verus rlimit, dense-slot budget, a non-default speed bar) is read from the effective config when the prompt is built; the worker count it mentions is read from the worked example's own header. Prompt sections carry a kind (task, rules, tools, limits, hardware, recipe, example-pointer, `declarative_spec/principles.py`); `examples = "none"` emits only the first five.

## Speed target and further sessions

* `speed_target` (float >= 1.0, default 10.0): the prompt (section "Target speedup", present in every examples mode) tells the agent to submit a first verified body that beats the reference engine, then keep trying faster verified bodies until this speedup, submitting each improvement and never replacing a submitted body with a slower or unverified one.
* `max_budget_usd` (float >= 0, default 20.0, 0 = no cap) is the model spend cap per query across all its agent sessions (Claude only; codex and gemini report tokens but no cost, so their sessions record `cost_usd: null` with `cost_note: "not reported by harness (...)"` and the cap is not enforced). Each session's command gets `--max-budget-usd <remaining>` (cap minus the earlier sessions' spend). Spend is the sum of `total_cost_usd` of the `result` events in `workspace/logs/claude_raw.jsonl` (appended by every session; a session killed before its result event counts 0). No further session starts once the cap is used (`budget used`); the manifest records `cost_usd` per entry of `sessions` and a top-level `total_cost_usd`.
* The per-query wall budget is `max_iterations x agent_timeout_sec`. Until a body has beaten the bar the old rule holds (a further session only after a session that did not verify, at most `max_iterations`). After one has, a session that ends early with the best speedup (official measure or the agent's submitted run, whichever is higher) below `speed_target` is followed by another session that starts from the best body, with a short host message (best speedup, target, minutes left); its wall limit is the time left. Stop: target reached, budget used, or `max_idle_sessions` sessions in a row without a better speedup. `speed_target = 1.0` is the old behaviour (the first body that beats the bar ends the query). `speed_bar_mult`, the acceptance bar of `submit_runquery`, is unchanged.
* The manifest has `sessions`: per session start, end, agent seconds, session speedup, best speedup so far, and the stop reason on the last one.

## Stateful accelerators (`stateful`)

`[run] stateful` (bool, default `false`; `LEMMA_STATEFUL`). Off: the spec has `run_query` and is byte-identical to the emitter without the flag
(`tests/fixtures/stateful_flag_off_golden.json`). On: `run_query` is replaced by a frozen build/execute contract over the SAME query spec
(`declarative_spec/stateful.py`): host `query_pre` (the old requires) and `query_post` (the old ensures), `QDb` (one field per table),
`QState { snap: Ghost<QDb>, acc: QAcc }` with `db()` and `inv() = query_pre(db) && qstate_inv(self)`; the agent writes `struct QAcc` (region
`AGENT_STATE`), `spec fn qstate_inv` (helpers), `build(<tables by value>)` ensuring `s.inv()` and `s.db() == QDb { inputs }` (region `AGENT_BUILD`)
and `execute(&QState, <params>)` ensuring `query_post(db, params, res)` (region `AGENT_EDIT`). Admission is the same as for `run_query` bodies
and helpers; the state region holds only `struct`/`enum` items. The assembler adds the fixed, verified host runtime `QRuntime` (one state tagged
with the data version it was built from; `execute_at(version)` answers only from a state built at that version, `refresh` builds on the given
tables). The measure `main` builds once (`STATE_BUILD_US`, outside the timer) and times `execute` only; `serve=True` gives a `main` that takes one
call per stdin line (`<version> <column file per table>`) and rebuilds only when the version changes. The parallel (Arc) variant is not emitted
with this flag; a self join and a requires on a runtime parameter are refused. Design note: `docs/STATEFUL.md`.

## Streaming executors (`stream`)

`[run] stream` (bool, default `false`; `LEMMA_STREAM`). Off: every spec and program is byte-identical to the emitter without the flag
(`tests/fixtures/stream_flag_off_golden.json`: the TPC-H 22 and the TPC-H templates, run defaults and test defaults). On (phase 1 of
`docs/STREAM.md`, `declarative_spec/stream.py`): `run_query` is replaced by the streaming contract over one ghost table
`stream_table_<t>(id)` (the table's rows, no pushed predicate: the spec's WHERE is in `agg_row`). Host, proved: `Params`, `Key`, the
spec-only `Agg`, `agg_zero` / `agg_plus` / `agg_row` / `agg_rng`, `lemma_agg_step` / `lemma_agg_empty` / `lemma_agg_laws` /
`lemma_agg_total`, the generic library `research_loop/verus_lib/stream_lib.rs`, the chunk view `Chunk_<t>`, and the runtime `Exec`
(type invariant; `exec_finish` checks at run time that the chunks tile `[0, n)`). Trusted, data loading only, authorized 2026-10-25:
S1 (`chunk_<t>`, `str_ent`) and S2 (`stream_end_<t>`), the only `external_body` items. Agent regions `AGENT_STATE` (`QAcc`), `AGENT_HELPERS`
(`qacc_inv`, `st_val`), `AGENT_INIT` / `STEP` / `MERGE` / `FINISH` (`admit.admit_stream`). Phase 1 takes single-table grouped or ungrouped
aggregates (SUM / COUNT / AVG incl. exact rationals / MIN / MAX, WHERE, template parameters, HAVING / ORDER BY / LIMIT in `q_finish`) and
refuses everything else loudly (joins, DISTINCT, rowid, order-dependent aggregates, a nullable GROUP BY key, floats, map results); it needs
`assumptions = false`, refuses `stateful` and `in_duckdb`, emits no Arc variant and no scan handles, and forces the plain string encoding
for the stream table. `assemble.assemble_stream_program` builds a binary-mode `main` (column file, random chunk sizes, several threads;
argv: the template parameters, then optionally `<chunk_max> <threads> <seed>`). Tests: `tests/test_stream.py`.

## Partial verification

The MCP tool `verify_functions(names, path)` runs Verus on the assembled program with `--verify-root --verify-function <name>` once per name (same admission, same Verus guards, `verus_timeout_sec` for all names together). No compile, no timing, no row check. The result is labelled "partial check: not a proof of run_query"; it is stored under `mcp_results/runs/` with `partial: true` and `ok: false`, and `submit_runquery` refuses its run_id.

## Predicate pushdown and agent scans (`[run] pushdown`, `[run] agent_scan`; both default `true`)

* `pushdown = true`: the data export (`research_loop/decl_query_measure.py`) reads each table with `SELECT <needed columns> FROM t WHERE
  <pushed conjuncts>` instead of the full scan. The transpiler's rule (`declarative_spec/pushdown.py`, allow-list in its docstring) picks the
  WHERE conjuncts that mention one table only, in a plain SELECT over inner joins with no subquery; it refuses outer / anti joins, NOT
  EXISTS, subqueries, CTEs, windows, HAVING, self-joined tables and anything off its expression allow-list. `scan_plan.json` beside the
  column files (and `expect.json` key `scan_plan`) lists per table the needed columns, the pushed SQL fragments with their parameter
  names, and rows full vs delivered. The spec text does not change; `table_rows` and the dictionaries are those of the delivered rows;
  DuckDB's reference answer is still computed on the full original SQL. `false`: full-table export, byte-identical to before, no
  `scan_plan.json`, no `scan_plan` key.
* `agent_scan = true`: `run_query` gets one handle `<p>_scan: &Scan_<t>` per table parameter `<p>: &Cols_<t>` and may call `scan_where_<t>(handle, &pred)`, the ONE
  authorized DuckDB-filter trusted item (`docs/TRUSTED_FAMILIES.md`, "Agent scans"); its rows come from a host export with
  `WHERE <pushed> AND <pred>` (`research_loop/scan_export.py`, run on demand by the binary through `<data dir>/scan_cmd`). The ensures is
  unchanged, so a too-narrow predicate fails the proof. `false`: spec and assembled `main` byte-identical to before.
* Both on: they compose. The table the scan handle stands for (`scan_full_<t>`) is the pushed-down export the loader checks; an agent
  scan is the conjunction of the transpiler's pushed predicate and the agent's. With no `scan_where` call (or `agent_scan = false`) the
  transpiler pushdown alone applies.
* Measurement: the pushed filter (and an agent scan's DuckDB filter) runs in the export, outside the timed `run_query`, while DuckDB's
  reference time includes its own filtering. So with either flag on the binary's time is labelled `hot, excludes scan/filter`
  (`hot_label` in the official record and the RESULT line, `research_loop/official_measure.py` `timing_labels`) and the REPORTED number
  is the in-DuckDB end-to-end measure `measure_in_duckdb` (`reported_measure`), which scans with the pushed predicate inside DuckDB.
  See `docs/COMPARABILITY.md`.
* With `assumptions = false` (the default): the scan items are emitted as above under the Option/decline contract (`run_query_ok` takes
  the handles as arguments and ignores them); scan columns are the SQL-type cells (DECIMAL(38,s) is `i128`, no caps).
  `tests/fixtures/declarative_proofs/decline/scan_usum_checked.rs` scans and declines on overflow.
* Query templates: a pushed conjunct may compare a column with a parameter (`x > $lo`). The export of the canonical column files binds
  `bindings[0]` (in-session runs, expected rows); every binding gets its own export under `<data>/bindings/b<k>/` (`binding_data` in
  `expect.json`), and official round i first puts binding `i % len`'s files at the paths the binary reads and points the agent-scan
  context at that binding's predicate (`decl_query_measure.activate_binding`, outside the timed region). The generated `main` does not
  pin the row count of such a table. In the extension the manifest keeps the `$name` placeholders and each `lemma_query` call binds
  its own values.
* `stateful`: `build` gets the scan handles (`build(<t>: Cols_<t>, <t>_scan: &Scan_<t>)` requires `scan_full_<t>(<t>_scan) == <t>`; so do
  the runtime's `refresh`); `execute` has none. The measure `main` opens the handles on the prepared data directory. Serve mode
  refuses a build that calls `scan_where` (a handle reads one data version's export; serve mode refreshes on other versions' files);
  with no call the handles are passed but never read.
* In-DuckDB (`in_duckdb`): the manifest's `rows` entries carry the table's pushed predicate (`where`, `where_params`), and the extension
  applies it inside its parallel scan: `SELECT <cols> FROM t WHERE <where>` is bound in the caller's context and given DuckDB's own
  expression rewriter and filter pushdown; the resulting table filters run in DuckDB's scan (zone maps skip row groups, vectors return
  only matching rows) and what DuckDB keeps above its scan is evaluated per chunk before decoding; matching rows are staged per task and
  committed in row order. A plan of any other shape is an error. Agent scans in library mode are REFUSED at install
  (`assemble_library_program`): a body that calls `scan_where` has no host side in ABI 4 (the binary's export is a Python program; a
  callback into the extension is not implemented). A body that does not call it is installed; its handles are inert.

## Defaults changed with this section

`string_encoding = "dict"` and `join_chain = true` (a query whose tables lack declared unique keys, or with a nullable key, a self-join, a subquery or an OR join keeps the general FROM-order form).

## In-DuckDB execution (`[engine] in_duckdb`)

Default `false`. Nothing in a container run reads it. With it on:

* `declarative_spec/assemble_library.py` may be used: the same `verus!` part as the binary (spec, agent body, host lemmas, verified
  loaders), with `main` replaced by the fixed C entry point `lemma_run` (ABI version 4, `db_extension/duckdb_ext/src/include/lemma_abi.h`);
  it runs every runtime check `main` runs before `run_query` and returns an error (status 2) instead of rows when one fails. With
  `assumptions = false` its `run_query` may decline: status 1 (DECLINED), no rows; the extension then raises `Lemma: declined: ...`
  unless the user set `lemma_route_unproved`, which lets DuckDB answer, labelled `engine=duckdb` in `lemma_last_query()`. A decline
  in any round of `measure_in_duckdb` makes its result `status: DECLINED`. With `[sql]
  templates` a query template's parameters are passed as `LemmaParam`s, checked (type, `requires` range) before any column is
  decoded; the extension takes them as `lemma_query('<template>', v1, ...)`. A `stateful` spec is refused (needs the caller's data
  version; next step in `db_extension/duckdb_ext/README.md`).
* `research_loop/in_duckdb.py` `install_executor` verifies and compiles that library (`verus --crate-type=cdylib --compile`, the
  `target_cpu` of `[prover]`) and installs `${LEMMA_HOME:-~/.local/share/lemma}/executors/<sha256 of the normalized SQL>/`
  (`lib.so`, `manifest.json`, `query.sql`). Off, it raises `InDuckdbDisabled` and installs nothing. `LEMMA_HOME` is a path, not a
  setting (listed in `NOT_CONFIG`).
* `LEMMA_GENERATOR` (the shell command DuckDB's `lemma('<sql>')` runs to generate an executor, read by the extension at LOAD; default
  `lemma generate`; deliberately not a SQL setting) and `LEMMA_JOB_ID` (set by the extension for that job; every container the
  pipeline starts is labelled `lemma.job=<id>` so a cancel removes it, `research_loop/job_label.py`) are not settings (`NOT_CONFIG`).
* `research_loop/official_measure.py` `measure_in_duckdb` times `SELECT * FROM lemma_query('<sql>')` end to end (scan + copy +
  checks + `run_query` + rows back) against DuckDB, interleaved like the official verdict (a template: each round on its
  binding, both sides); it refuses with the flag off.
  `research_loop/scripts/in_duckdb_bench.py` runs it.

The DuckDB side is the extension in `db_extension/duckdb_ext/` (its README: build, LOAD, `lemma_query`, `lemma_last_query`). Its own
settings are DuckDB session settings, not lemma.toml keys: `lemma_mode` (default false), `lemma_route_unproved` (default false;
experiments never set it), `lemma_enqueue_misses` (default false), `lemma_home`.

## Parked branches (not integrated, kept as branch/tag)

* `worktree-agent-a231dc03f073f5e80` / tag `archive/param-literals-wip-2026-10-07`: parameterized literals (`LEMMA_PARAM_LITERALS`), paused by Emil; the patch no longer applies to `parse_query.py` and `prompt.py`, so it needs a rebase before it can get a `[wip]` switch. Doc: `research_loop/menus/future_work_parameterized_literals.md`.
* `harness-prompt-traces`: Verus-error classification and per-column DuckDB catalog caps (imperative path); conflicts in `dataset_config.py`, `agent_sandbox.py` and a duplicate test file, and it changes catalog behaviour of every run.
* `worktree-agent-a440a08df90aee7f8`: exporter v3; rewrites the default data-export path of `decl_query_measure.py` in place (would need a dual path behind a switch).
* `worktree-agent-a0e34e79c6fe9763e`: four prompt/feedback hints; prompt text changed since, and any prompt edit changes the default agent context.
* `worktree-agent-aa1cf2f1a0245f3bf`: tools are integrated (`declarative_spec/fragment.py`, `research_loop/scripts/fragment_*.py`, `resample_eval.py`, `docs/SQL_FRAGMENT.md`); the four emitter fixes in that branch (column named `n`, ORDER BY MIN/MAX bound, `real`/`f64` in string literals, `add` rename) change emitted specs and stay on the branch with `tests/test_fragment_gaps.py`.
