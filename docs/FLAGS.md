# Configuration: `lemma.toml`

Every setting that shapes a container run, and the safety/infrastructure settings around it, lives in **one file: `lemma.toml`** at the repo root. One line per key, each with a comment. `python -m lemma_config dump` prints every key with its effective value and where it came from. The loader is `lemma_config.py` (stdlib `tomllib`); code calls `lemma_config.get("key")`, shell scripts `python3 -m lemma_config get <key>`.

## The rule

```
lemma.toml  <  environment variable LEMMA_<KEY>  <  explicit CLI flag
```

* The variable of a key is `LEMMA_` + the key upper-cased, in any section: `[measure] official_rounds` is `LEMMA_OFFICIAL_ROUNDS`. An empty variable counts as unset. Booleans are `0/1/true/false`.
* CLI flags exist on the launcher (`run_container_agent.py`: `--style --menu --agent --trusted-set --assumption-package --speed-bar-mult --max-iterations`); `container_batch.py` takes `model:query` pairs and passes the model as `--agent`.
* No other source. `research_loop/config.env` no longer owns any container-run setting (it keeps only the legacy imperative / overnight / OpenRouter ones, see its header).
* Startup check (`container_batch.py`, `run_container_agent.py`, `python -m lemma_config check`): an unknown `LEMMA_*` variable (typo or dead flag), a dead setting, a bad value or type, or a duck memory limit at or above the scope cap raises, listing the culprits. Nothing falls back to a default.
* Old spellings still work with a one-line deprecation message (table below). If both spellings are set to different values it raises.
* Every container run writes all keys with `value`, `section`, `source` (`file`/`env`/`cli`) and `origin` into the run manifest (`lemma_config`) and the `RESULT` line (`config`), with `git_sha` and `git_dirty`. A dirty tree (tracked files; untracked and gitignored data do not count) is refused unless `allow_dirty = true`.
* `container_batch.py` forwards nothing by name. The child reads `lemma.toml` itself; the batch passes only values that differ from the file (`lemma_config.forwarded_env`, plus `LEMMA_CONFIG_ORIGIN` so a flag is still reported as a flag).

## Sections (47 keys)

| Section | Keys |
| --- | --- |
| `[run]` | `spec_style menu agent_model trusted_set assumption_package speed_bar_mult max_iterations string_encoding join_chain examples narrow_cells parallel_vstd` |
| `[agent]` | `agent_timeout_sec agent_submit_ends_session agent_data_mode agent_resource_exhausted_retries claude_effort claude_thinking_tokens claude_tool_search mcp_iterate_rows` |
| `[prover]` | `verus_rlimit verus_timeout_sec run_timeout_sec target_cpu dense_slot_budget` |
| `[measure]` | `official_rounds official_duck_reps duck_memory_limit duck_threads` |
| `[data]` | `duckdb_path` |
| `[sql]` | `agg_times_constant derived_agg_expr cte_reuse left_join_count` (new SQL shapes of the transpiler, all default false; verdicts in `research_loop/menus/sql_<feature>_ADVERSARY_VERDICT.md`) |
| `[wip]` | `zero_copy cold_stream cold_stream_mode` (parked pin path, default off, see `research_loop/menus/pin_path_archive.md`; nothing here is used by a container run) |
| `[safety]` | `allow_dirty scope_memory_max egress_profile egress_allowlist heavy_lock heavy_min_avail_mb heavy_mem_max verus_mem_max verus_slots verus_min_avail_mb` |

Meaning, allowed values and defaults are in the file. `menu` selects a profile (`research_loop/menu_profile.py`); the next four axis keys override its values (the launcher takes them as authority and the selection printed first shows them as overrides).

## Resolved conflicts (one value each)

| Setting | Was | Now |
| --- | --- | --- |
| `agent_timeout_sec` | 600 (config.env, code, AGENTS.md), 750 (batch) | 750 (2 x 750 s = 25 min per attempt) |
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
