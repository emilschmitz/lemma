# Configuration: `lemma.toml`

Every setting that shapes a container run, and the safety/infrastructure settings around it, lives in **one file: `lemma.toml`** at the repo root. One line per key, each with a comment. `python -m lemma_config dump` prints every key with its effective value and where it came from. The loader is `lemma_config.py` (stdlib `tomllib`); code calls `lemma_config.get("key")`, shell scripts `python3 -m lemma_config get <key>`.

## The rule

```
lemma.toml  <  experiment file (configs/experiments/X.toml)  <  environment variable LEMMA_<KEY>  <  explicit CLI flag
```

* The variable of a key is `LEMMA_` + the key upper-cased, in any section: `[measure] official_rounds` is `LEMMA_OFFICIAL_ROUNDS`. An empty variable counts as unset. Booleans are `0/1/true/false`.
* CLI flags exist on the launcher (`run_container_agent.py`: `--style --menu --agent --trusted-set --assumption-package --speed-bar-mult --max-iterations`); `container_batch.py` takes `model:query` pairs and passes the model as `--agent`.
* The experiment file is the fourth source (`experiment`, origin = its path): `[settings]` use lemma.toml keys (unknown keys fail), and each `[[run]]` supplies `agent_model`, `duckdb_path`, `assumption_package`. A replicable run (`container_batch.py --experiment`) refuses any `env`/`cli` source; see AGENTS.md "Replicable experiments".
* No other source. `research_loop/config.env` no longer owns any container-run setting (it keeps only the legacy imperative / overnight / OpenRouter ones, see its header).
* Startup check (`container_batch.py`, `run_container_agent.py`, `python -m lemma_config check`): an unknown `LEMMA_*` variable (typo or dead flag), a dead setting, a bad value or type, or a duck memory limit at or above the scope cap raises, listing the culprits. Nothing falls back to a default. Two keys have no default at all: `duckdb_path` and `assumption_package` (empty in the file; a run without a value, from the file, `LEMMA_<KEY>` or a flag, stops at startup with a message; `assumption_package = "auto"` remains valid as an explicit value).
* Old spellings still work with a one-line deprecation message (table below). If both spellings are set to different values it raises.
* Every container run writes all keys with `value`, `section`, `source` (`file`/`experiment`/`env`/`cli`) and `origin` into the run manifest (`lemma_config`) and the `RESULT` line (`config`), with `git_sha`, `git_dirty` and `git_untracked_files` (a count; untracked files never make `git_dirty` true). A dirty tree (tracked files; untracked and gitignored data do not count) is refused unless `allow_dirty = true`.
* `container_batch.py` forwards nothing by name. The child reads `lemma.toml` itself; the batch passes only values that differ from the file (`lemma_config.forwarded_env`, plus `LEMMA_CONFIG_ORIGIN` so a flag is still reported as a flag).

## Sections (52 keys)

| Section | Keys |
| --- | --- |
| `[run]` | `spec_style menu agent_model trusted_set assumption_package speed_bar_mult max_iterations string_encoding join_chain examples narrow_cells pushdown agent_scan parallel_vstd` |
| `[agent]` | `agent_timeout_sec max_budget_usd agent_submit_ends_session agent_data_mode agent_resource_exhausted_retries claude_effort claude_thinking_tokens claude_tool_search mcp_iterate_rows` |
| `[prover]` | `verus_rlimit verus_timeout_sec run_timeout_sec target_cpu dense_slot_budget` |
| `[measure]` | `official_rounds official_duck_reps duck_memory_limit duck_threads` |
| `[data]` | `duckdb_path data_profile` |
| `[sql]` | `agg_times_constant derived_agg_expr cte_reuse left_join_count` (new SQL shapes of the transpiler, all default false; verdicts in `research_loop/menus/sql_<feature>_ADVERSARY_VERDICT.md`) |
| `[wip]` | `zero_copy cold_stream cold_stream_mode` (parked pin path, default off, see `research_loop/menus/pin_path_archive.md`; nothing here is used by a container run) |
| `[safety]` | `allow_dirty scope_memory_max egress_profile egress_allowlist heavy_lock heavy_min_avail_mb heavy_mem_max verus_mem_max verus_slots verus_min_avail_mb` |

Meaning, allowed values and defaults are in the file. `menu` selects a profile (`research_loop/menu_profile.py`); the next four axis keys override its values (the launcher takes them as authority and the selection printed first shows them as overrides).

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

## The agent prompt

Every run value the prompt states (DuckDB threads and memory limit, iterate cap, Verus rlimit, dense-slot budget, a non-default speed bar) is read from the effective config when the prompt is built; the worker count it mentions is read from the worked example's own header. Prompt sections carry a kind (task, rules, tools, limits, hardware, recipe, example-pointer, `declarative_spec/principles.py`); `examples = "none"` emits only the first five.

## Speed target and further sessions

* `speed_target` (float >= 1.0, default 10.0): the prompt (section "Target speedup", present in every examples mode) tells the agent to submit a first verified body that beats the reference engine, then keep trying faster verified bodies until this speedup, submitting each improvement and never replacing a submitted body with a slower or unverified one.
* `max_budget_usd` (float >= 0, default 20.0, 0 = no cap) is the model spend cap per query across all its agent sessions (Claude only). Each session's command gets `--max-budget-usd <remaining>` (cap minus the earlier sessions' spend). Spend is the sum of `total_cost_usd` of the `result` events in `workspace/logs/claude_raw.jsonl` (appended by every session; a session killed before its result event counts 0). No further session starts once the cap is used (`budget used`); the manifest records `cost_usd` per entry of `sessions` and a top-level `total_cost_usd`.
* The per-query wall budget is `max_iterations x agent_timeout_sec`. Until a body has beaten the bar the old rule holds (a further session only after a session that did not verify, at most `max_iterations`). After one has, a session that ends early with the best speedup (official measure or the agent's submitted run, whichever is higher) below `speed_target` is followed by another session that starts from the best body, with a short host message (best speedup, target, minutes left); its wall limit is the time left. Stop: target reached, budget used, or `max_idle_sessions` sessions in a row without a better speedup. `speed_target = 1.0` is the old behaviour (the first body that beats the bar ends the query). `speed_bar_mult`, the acceptance bar of `submit_runquery`, is unchanged.
* The manifest has `sessions`: per session start, end, agent seconds, session speedup, best speedup so far, and the stop reason on the last one.

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
  reference time includes its own filtering. See `docs/COMPARABILITY.md`.

## Defaults changed with this section

`string_encoding = "dict"` and `join_chain = true` (a query whose tables lack declared unique keys, or with a nullable key, a self-join, a subquery or an OR join keeps the general FROM-order form).

## Parked branches (not integrated, kept as branch/tag)

* `worktree-agent-a231dc03f073f5e80` / tag `archive/param-literals-wip-2026-10-07`: parameterized literals (`LEMMA_PARAM_LITERALS`), paused by Emil; the patch no longer applies to `parse_query.py` and `prompt.py`, so it needs a rebase before it can get a `[wip]` switch. Doc: `research_loop/menus/future_work_parameterized_literals.md`.
* `harness-prompt-traces`: Verus-error classification and per-column DuckDB catalog caps (imperative path); conflicts in `dataset_config.py`, `agent_sandbox.py` and a duplicate test file, and it changes catalog behaviour of every run.
* `worktree-agent-a440a08df90aee7f8`: exporter v3; rewrites the default data-export path of `decl_query_measure.py` in place (would need a dual path behind a switch).
* `worktree-agent-a0e34e79c6fe9763e`: four prompt/feedback hints; prompt text changed since, and any prompt edit changes the default agent context.
* `worktree-agent-aa1cf2f1a0245f3bf`: tools are integrated (`declarative_spec/fragment.py`, `research_loop/scripts/fragment_*.py`, `resample_eval.py`, `docs/SQL_FRAGMENT.md`); the four emitter fixes in that branch (column named `n`, ORDER BY MIN/MAX bound, `real`/`f64` in string literals, `add` rename) change emitted specs and stay on the branch with `tests/test_fragment_gaps.py`.
