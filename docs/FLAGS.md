# Flags and configuration settings

Scope: every environment variable, `config.env` key, launcher flag and menu axis read in non-test code at commit cd47a53 (`.py`, `.sh`, `.rs`, `Dockerfile`, `entrypoint.sh`). Line numbers are for that commit.
Generated files (`research_loop/generated`, `research_loop/runs`) and tests were not searched.

Reading order of a container run (`container_batch.py` -> `run_container_agent.py`):

1. `container_batch.py` builds `systemd-run --user --scope --slice=lemma.slice -p MemoryMax=6G -p MemorySwapMax=0 --setenv=... run_container_agent.py --style declarative --menu adversary_declarative0 --agent <model> --allow-override --max-iterations 2 --query-file <sql>` (container_batch.py:24-37). It forwards `AGENT_TIMEOUT_SEC` (default 750) and, only if set in the launching shell, `LEMMA_DUCKDB_PATH LEMMA_STRING_ENCODING LEMMA_JOIN_CHAIN LEMMA_EXAMPLES LEMMA_TPCH_DB LEMMA_NARROW_CELLS LEMMA_ASSUMPTION_PACKAGE LEMMA_CLAUDE_EFFORT LEMMA_TARGET_CPU LEMMA_DUCK_MEMORY_LIMIT LEMMA_DUCK_THREADS` (container_batch.py:25). Every other variable in the launching shell (for example `LEMMA_OFFICIAL_ROUNDS`, `LEMMA_VERUS_RLIMIT`) is read by the child from the inherited environment; it is not in the forwarding list.
2. `run_container_agent.py` resolves the menu (`menu_profile.activate_menu`), then `os.environ.update(agent_env(model, style))` (declarative_ladder.py:66-89), which overwrites `LEMMA_SPEC_STYLE`, `USE_AGENT_DOCKER=1`, `LEMMA_AGENT_BACKEND=cli`, `LEMMA_SERIOUS=1`, `LEMMA_RESEARCH_LOG=1`, `LEMMA_PARALLEL_VSTD=auto`, `AGENT_IMAGE`, `AGENT_ENV=""`, `AGENT_CMD` whatever the shell had.
3. `config.env` is not read as a whole by the declarative path. Only `AgentFlags` (`db_extension/agent/config.py:72`), `agent_sandbox.load_agent_config` (agent_sandbox.py:95-117) and `optimizer.harness_timeout_sec` (optimizer.py:390) read the file; the imperative `harness.py` entry points copy the whole file into `os.environ` with `setdefault` (harness.py:889-891). The process environment wins over the file in `AgentFlags` and `load_agent_config`; the file wins over the environment for `COMPILE_TIMEOUT_SEC` / `VERUS_VERIFY_TIMEOUT_SEC` in `harness_timeout_sec` (optimizer.py:394-401).

## Menu `adversary_declarative0` (research_loop/menu_profile.py:150-153, trust config research_loop/trust_configs/adversary_declarative0.py)

| Axis | Env override | Launcher flag | Profile value | Allowed |
| --- | --- | --- | --- | --- |
| style | `LEMMA_SPEC_STYLE` | `--style` (required) | declarative | `declarative`, `imperative` (spec_styles.py; `recursive` is rejected) |
| trusted_set | `LEMMA_TRUSTED_SET` | `--trusted-set` | declarative_default | `rocketship`, `fast`, `adversary_imperativespec0` (imperative only), `declarative_default` (declarative only); a set of the wrong style fails always (menu_profile.py:135-141, 166) |
| assumption_package | `LEMMA_ASSUMPTION_PACKAGE` | `--assumption-package` | none (unset) | see row 6 below |
| agent | `LEMMA_AGENT_MODEL` | `--agent` | claude-haiku-4-5-20251001 | model slug; `claude-*` runs Claude Code in the container, anything else the Cursor `agent` CLI |
| speed_bar_mult | `LEMMA_SPEED_BAR_MULT` | `--speed-bar-mult` | 1.0 | float > 0 |

Other profiles: `rocketship`, `adversary_imperativespec0`, `fast` (all imperative, agent grok-4.7-high, no speed bar).
An override that differs from a non-null profile value raises unless `--allow-override` or `LEMMA_MENU_ALLOW_OVERRIDE=1` (menu_profile.py:201-216, 235); `container_batch.py` always passes `--allow-override`. Two different overrides for one axis (env and flag) always raise.
`activate_menu` also sets `LEMMA_MENU`, `LEMMA_TRUST_CONFIG=adversary_declarative0` and the trust config env: `LEMMA_FAST_TRUSTEDS=0 LEMMA_ENABLE_PARALLEL=0 LEMMA_ENABLE_VECTOR_SCAN=0 LEMMA_ENABLE_SPILL_HASH=0 LEMMA_FOLD_SLOT_AXIOMATIC=0` (menu_profile.py:283-290). The declarative path reads none of those five.

## 1. Paper-run settings (shape the result of a container run)

"Frozen" = value of the frozen run: `LEMMA_STRING_ENCODING=dict`, `LEMMA_JOIN_CHAIN=1`, `LEMMA_DUCK_MEMORY_LIMIT=8GB`, `LEMMA_OFFICIAL_ROUNDS=5`, `LEMMA_EXAMPLES` unset (= full), model `claude-sonnet-5-5`, `--max-iterations 2`, `AGENT_TIMEOUT_SEC=750`, everything else default.

| # | Setting | Where read | Default | Allowed values | What it changes | Frozen |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `--style` / `LEMMA_SPEC_STYLE` | run_container_agent.py:214; menu_profile.py:249; optimizer.py:66-79 | launcher: required; optimizer with env unset: declarative | declarative, imperative | Whole chain: emitter, assembler, admission, prompt, measure | declarative |
| 2 | `--menu` / `LEMMA_MENU` | run_container_agent.py:215; menu_profile.py:283; optimizer.py:669 | launcher: required | rocketship, adversary_imperativespec0, fast, adversary_declarative0 | Sets all five axes at once plus the trust config env | adversary_declarative0 |
| 3 | `--trusted-set` / `LEMMA_TRUSTED_SET` | menu_profile.py:36,249 | profile (declarative_default) | see menu table | Host lemma block pasted into the spec; declarative_default adds no fast/parallel trusteds | declarative_default |
| 4 | `--agent` / `LEMMA_AGENT_MODEL` | run_container_agent.py:218; menu_profile.py:38 | profile: claude-haiku-4-5-20251001 | any slug; `container_batch.py` short names `haiku`, `sonnet` (container_batch.py:20) | Prover model | claude-sonnet-5-5 |
| 5 | `--speed-bar-mult` / `LEMMA_SPEED_BAR_MULT` | pipeline.py:263; menu_profile.py:39 | 1.0 | float > 0 (else ValueError) | Verdict is `median(ours) * mult < median(duck)` (official_measure.py:19) | 1.0 |
| 6 | `--assumption-package` / `LEMMA_ASSUMPTION_PACKAGE` | run_container_agent.py:169-173; assumption_packages/__init__.py:30-45; workload_config.py:349 | profile none, so launcher picks `sec_margin_dec` if the DuckDB file has DECIMAL columns, else `sec_margin` (declarative_draws.py:48-50). Outside the launcher, unset measures the SEC catalog from `LEMMA_DUCKDB_PATH` (sec_table_assumptions.py:106) | `sec_margin`, `sec_margin_dec`, `prove_loop`, a name in `assumption_packages/registry/*.json` (`ssb_sf1`), or a path to a `.json` file | Row caps, value caps, string caps, unique keys, nullable columns, join caps in the spec and in the loader asserts | default (sec_margin_dec, DB is sec_edgar_dec.duckdb) |
| 7 | `LEMMA_STRING_ENCODING` | string_encoding.py:21 | plain | plain, dict (else ValueError) | `dict`: string column loaded as code vector (u8/u16/u32 by catalog `max_distinct`) plus dictionary; mounts the dict_ examples | dict |
| 8 | `LEMMA_JOIN_CHAIN` | join_chain.py:28 | 0 | 0, 1 | `1`: fact table first, unique-key tables nested after it, `valid_cols_<t>` states key uniqueness; refused per query when no chain is found | 1 |
| 9 | `LEMMA_EXAMPLES` | principles.py:136 | full (unset or empty) | full, principles, none | Which verified example files, INDEX and prompt citations the agent sees; `principles` = 7 invented-schema files; `none` = no examples directory | unset (full) |
| 10 | `LEMMA_NARROW_CELLS` | schema_types.py:221 | 0 | 0, 1 | `1`: INTEGER/SMALLINT/TINYINT and capped DECIMAL columns loaded as i32/i16/i8; map-result group keys stay i64 | 0 |
| 11 | `LEMMA_PARALLEL_VSTD` | parallel.py:29,33; agent_env sets it (declarative_ladder.py:78) | module: off (also recorded as `off` in run_artifacts.py:190). Container run: forced to `auto`, any shell value is overwritten | unset/other = off, 1 = every spec gets `<table>_arc` params (shape without variant fails at emit), auto = only shapes that have a variant | Parallel (vstd thread/Arc) run_query signature and prompt text | auto (forced) |
| 12 | `LEMMA_TARGET_CPU` | pipeline.py:110 | x86-64-v3 | generic (no flag), x86-64-v3, native, any rustc target-cpu | rustc `-C target-cpu` of the compiled binary; native/v3 can SIGILL elsewhere | x86-64-v3 |
| 13 | `LEMMA_OFFICIAL_ROUNDS` | official_measure.py:36 | 5 | int >= 1 | Interleaved rounds (ours vs DuckDB, order alternates) of the official verdict | 5 |
| 14 | `LEMMA_OFFICIAL_DUCK_REPS` | official_measure.py:43 | 9 | int >= 1 | DuckDB executions per round (median); our side is the binary's own `TIMED_RUNS = 9` (assemble.py:10, constant, not a flag) | 9 |
| 15 | `LEMMA_DUCK_MEMORY_LIMIT` | decl_query_measure.py:45 | 3GB | DuckDB memory string | PRAGMA memory_limit on every host measure connection (reference and official re-time) | 8GB |
| 16 | `LEMMA_DUCK_THREADS` | decl_query_measure.py:46 | 8 | int | PRAGMA threads on the same connections | 8 |
| 17 | `LEMMA_VERUS_RLIMIT` | verus_limits.py:38 | 16 | float > 0 | Verus `--rlimit` (Z3 work per function/loop) | 16 |
| 18 | `LEMMA_VERUS_TIMEOUT_SEC` | verus_limits.py:45 | 300 | int > 0 | Wall limit of the whole verify + optimized rustc build | 300 |
| 19 | `LEMMA_RUN_TIMEOUT_SEC` | verus_limits.py:52 | 60 | int > 0 | Wall limit of one compiled-binary run (load, warm-up, timed runs); MCP harness waits verify + run + 60 s | 60 |
| 20 | `VERUS_MEM_MAX` | scripts/ram/verus_guarded.sh:8 | 6G | systemd size | `MemoryMax` of each Verus run (no output + kill message in feedback.py:274) | 6G |
| 21 | `AGENT_TIMEOUT_SEC` | session_clock.py:31; agent_sandbox.py:1105,1179,1591; config.py:58; container_batch.py:24 | `container_batch`: 750. Code and `config.env`: 600 | int | Wall seconds per agent session (kill = exit -9) | 750 |
| 22 | `--max-iterations` | run_container_agent.py:223 | 2 (`run_optimization_loop` default is 3, optimizer.py:656) | int | Agent sessions per query; the second starts from the best body so far | 2 |
| 23 | `AGENT_SUBMIT_ENDS_SESSION` | session_clock.py:27; config.py:65 | 0 | 0/1 (truthy: not ""/0/false/no/off) | `1`: a successful `submit_runquery` ends the session | 0 |
| 24 | `LEMMA_CLAUDE_EFFORT` | agent_sandbox.py:179,202 | unset = no `--effort` flag | low, medium, high, xhigh, max, none | Claude Code `--effort` | unset |
| 25 | `LEMMA_CLAUDE_THINKING_TOKENS` | agent_sandbox.py:180,212 | unset (CLI default) | int >= 0 | Env `MAX_THINKING_TOKENS` of the container agent | unset |
| 26 | `LEMMA_CLAUDE_TOOL_SEARCH` | agent_sandbox.py:181,192 | unset (CLI default) | true, false, auto, auto:N | Env `ENABLE_TOOL_SEARCH` of the container agent | unset |
| 27 | `LEMMA_DUCKDB_PATH` | declarative_draws.py:41-42 | `holdout/gendb_sec_edgar/duckdb/sec_edgar_dec.duckdb` | path to an existing file | The database: schema, catalog, reference timing, row counts. Launcher sets it to the resolved path | default |
| 28 | `LEMMA_MEASURE_DB` | drive.py:47; run_container_agent.py:166 | set by launcher to the resolved DB (declarative style) | path | Turns on the official full-table prepare/measure in `decl_data/` | = row 27 |
| 29 | `LEMMA_DENSE_SLOT_BUDGET` | dense_budget.py:37 | 4194304 (2^22) | int > 0 | Largest dense slot table (product of key dictionary sizes) a body may allocate; rejected before Verus, stated in the prompt | default |
| 30 | `LEMMA_MCP_ITERATE_ROWS` | dataset_config.py:372; measure_core.py:552 | 50000 | int, or 0/full/unlimited | Prompt blurb and the "probe pin" check at submit. The declarative harness ignores `dataset_size` for the measure (drive.py:243) and times the full tables | default |
| 31 | `LEMMA_AGENT_BACKEND` | config.py:54; agent_env | `cli` forced by launcher; `config.env`/code: openrouter | openrouter, cli | cli = container CLI agent; openrouter = host ReAct loop | cli |
| 32 | `LEMMA_DECL_ROWS`, `LEMMA_DECL_SEED` | drive.py:73,79 | popped by the launcher (run_container_agent.py:174-175) | int | Synthetic dev bar (no DuckDB file) | not set |

Hardcoded (not flags, shape the result): agent container `--memory 3g --memory-swap 3g --network none --cap-drop ALL` (agent_sandbox.py:1280-1283); scope `MemoryMax=6G MemorySwapMax=0` and `choom -n 800` (container_batch.py:28-30); Verus guard slots 1 (row 37).

## 2. Safety and infrastructure

| # | Setting | Where read | Default | Values | Effect |
| --- | --- | --- | --- | --- | --- |
| 1 | `USE_AGENT_DOCKER` | agent_sandbox.py:105,121 | config.env 0; forced 1 by launcher | 0/1 | Run the CLI agent in the Docker sandbox |
| 2 | `AGENT_IMAGE` | agent_sandbox.py:107; config.py:66 | config.env `lemma-agent:latest`; claude agents: `lemma-agent:claude` (agent_env) | image | Sandbox image |
| 3 | `AGENT_CMD` | agent_sandbox.py:108,1104; entrypoint.sh:56 | config.env: Cursor `agent ... grok-4.7-high`; claude agents: `claude -p --model M [--effort E] ...` (agent_sandbox.py:221) | shell line | What the container runs |
| 4 | `AGENT_ENV` | agent_sandbox.py:108,316 | config.env `CURSOR_API_KEY`; claude: empty | env names | Host env vars passed to the container by name |
| 5 | `AGENT_EGRESS_PROFILE` | agent_sandbox.py:110,1216 | inferred from the executable: claude -> anthropic, else cursor | cursor, anthropic, openai, openrouter, google (comma list) | Allowlisted API hosts (egress_bridge.py:25-70) |
| 6 | `LEMMA_EGRESS_ALLOWLIST` | agent_sandbox.py:113,1222; egress_bridge.py:373 | unset | comma host suffixes | Full allowlist override |
| 7 | `HTTPS_PROXY` / `https_proxy` | agent_sandbox.py:1250 | unset | URL | Allowlisted CONNECTs tunnel through it; allowlist is checked first |
| 8 | `LEMMA_EGRESS_SOCK`, `LEMMA_EGRESS_PROXY_PORT` | egress_bridge.py:20; egress_proxy_sidecar.py:11-12; entrypoint.sh:29 | `/tmp/lemma-egress.sock` (host), `/lemma-egress.sock` (container), port 8118 | path, int | In-container proxy sidecar to host bridge |
| 9 | `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `LEMMA_CLAUDE_CONFIG_DIR` | agent_sandbox.py:278-283 | unset; else host `~/.claude/.credentials.json` mounted read-only | key / token / dir | Credential order for the claude agent; passed by name or read-only mount. `container_batch` refreshes the login with one host `claude -p` call and stops the batch if it fails (container_batch.py:44-62) |
| 10 | `AGENT_CREDENTIALS_DIR`, `AGENT_AUTH_DIR`, `AGENT_CLI_DIR` | agent_sandbox.py:111-112,126,1257,1332 | `~/.cursor`; CLI dir autodetected | path | Cursor agent credentials and binary |
| 11 | `LEMMA_MCP_SOCK`, `LEMMA_MCP_SOCK_DIR`, `LEMMA_AGENT_MODE`, `LEMMA_QUERY_ID`, `LEMMA_RUN_RUNQUERY_BLURB`, `LEMMA_AGENT_WORKSPACE` | agent_sandbox.py:1202-1227; entrypoint.sh; mcp_socket.py | `/tmp` for socket dir; others set by host | | Unix-socket MCP between container and host (set by the host, not by users) |
| 12 | `LEMMA_AGENT_STREAM_LOG`, `LEMMA_AGENT_STDERR_LOG` | entrypoint.sh:128-129; agent_sandbox.py:1265 | `/workspace/logs/agent_stream.jsonl`, `agent_stderr.log` | path | Agent conversation and stderr traces |
| 13 | `AGENT_RESOURCE_EXHAUSTED_RETRIES` | agent_sandbox.py:825 | 8 | int >= 1 | Retries when the Cursor agent hits API quota (backoff 30 s doubling to 180 s are constants, not flags) |
| 14 | `HEAVY_LOCK` | heavy_phase.py:39; heavy.sh:11 | `/tmp/lemma_timing.lock` | path | Machine-wide lock: export and timed run take it exclusively, Verus takes it shared |
| 15 | `HEAVY_MIN_AVAIL_MB` | heavy_phase.py:42; heavy.sh:6 | 3500 in Python, 4000 in heavy.sh | MB | Wait until MemAvailable is at least this |
| 16 | `HEAVY_MEM_MAX` | heavy.sh:7 | 5G | systemd size | Scope memory cap of `heavy.sh` jobs |
| 17 | `LEMMA_HEAVY_LOCK_HELD` | heavy_phase.py:36; verus_guarded.sh:28 | unset | 1 | Caller already holds the lock; phase and guard do not take it again |
| 18 | `VERUS_SLOTS` | verus_guarded.sh:7 | 1 | int | Concurrent Verus runs machine-wide |
| 19 | `VERUS_MIN_AVAIL_MB` | verus_guarded.sh:18 | 3000 | MB | Do not start Verus below this MemAvailable |
| 20 | `LEMMA_VERUS_REAL` | verus_guarded.sh:9 | `$HOME/tools/verus/verus` | path | The Verus binary the guard wraps |
| 21 | `LEMMA_VERUS_BIN` | pipeline.py:31; declarative_manual.py:175 | unset = `scripts/ram/verus_guarded.sh` | path | Bypass the guard (only on purpose) |
| 22 | `LEMMA_MENU_ALLOW_OVERRIDE` | menu_profile.py:235 | unset | 1 | Same as `--allow-override` |
| 23 | `LEMMA_EXPERIMENT` | lemma_flags.py:74; run_artifacts.py:120; run_optimizer.py:113; workload_config.py:327 | 0. Not set by the container launcher | 0/1 | 1 = clean git tree required, commit SHA in manifest, no mock agent, no DuckDB fallback |
| 24 | `LEMMA_EXPERIMENT_ALLOW_DIRTY` | run_artifacts.py:123 | 0 | 0/1 | Skips the clean-tree check (forbidden for paper runs) |
| 25 | `LEMMA_ALLOW_DUCKDB_FALLBACK` | lemma_flags.py:89 | 0; forced off under `LEMMA_EXPERIMENT=1` | 0/1 | Demo UX may print DuckDB result after failure |
| 26 | `MOCK_AGENT` | lemma_flags.py:96; run_optimizer.py:112 | 1 in lemma_flags, forced 0 under EXPERIMENT; launcher passes `use_mock=False` | 0/1 | Fixture agent body |
| 27 | `LEMMA_RESEARCH_LOG` | lemma_flags.py:79; run_optimizer.py:111 | config.env 0; forced 1 by launcher | 0/1 | Harvest `research_loop/runs/<id>/` (manifest, workspace, logs) |
| 28 | `LEMMA_TEST_MOCK_ANTHROPIC_PORT`, `LEMMA_TEST_MOCK_ANTHROPIC_CA` | agent_sandbox.py:243-259 | unset | port + CA path (both or error) | Test-only mock model API; swaps egress profile to the reserved `.test` name |
| 29 | `LEMMA_LAPTOP_LEASE`, `_LEASE_SEC`, `_LEASE_POLL_SEC`, `_LEASE_HALT_CMD` | overnight_lemma.sh:268-271; lemma_laptop_lease_watch.sh:7-23 | 1, 720, 60, unset | | Spot VM halts when `$OUT/laptop_lease` is stale |
| 30 | `LEMMA_HALT_ON_FINISH`, `LEMMA_HALT_LOG`, `LEMMA_SELF_DESTRUCT_MIN`, `LEMMA_SCHEDULE_ACPI` | overnight_lemma.sh:84,251,353; lemma_guest_halt.sh:5 | 1, `$OUT/watchdog.log`, unset, 1 | | VM halt and shutdown scheduling |
| 31 | `LEMMA_BUDGET_USD`, `LEMMA_VM_USD_PER_HR` | overnight_lemma.sh:80-81 | 20, 2.0 | USD | Overnight spend cap |
| 32 | `LEMMA_PREFLIGHT_SSH`, `LEMMA_GCP_ZONE`, `LEMMA_REMOTE_HOST`, `LEMMA_REMOTE_REPO`, `LEMMA_OVERNIGHT_LOCK_FILE` | gcp_experiment_preflight.sh | | | Spot preflight: SHA gate, remote checks, one-VM lock |

## 3. Dev, legacy and imperative-path settings (one line each, grouped)

Imperative / overnight-Spot family driver (`overnight_lemma.sh`, `r2x_*_chain.sh`, `overnight_lemma.py`)
- `LEMMA_FAMILY` (r18), `LEMMA_OVERNIGHT_OUT`, `LEMMA_SHUFFLE_SEED` (1707), `LEMMA_SHUFFLE_N` (6), `LEMMA_SQL_FILE`, `LEMMA_SQL_ONLY`, `LEMMA_TPCH_DUCKDB_PATH`, `LEMMA_FAIL_STREAK` (6), `LEMMA_PARALLEL` (16 workers), `LEMMA_RESUME_AFTER_ABORT`, `LEMMA_HEARTBEAT_INTERVAL_SEC`, `LEMMA_TRACE_RUN_QUERY_LINE`, `LEMMA_SERIOUS`: family, sample and abort policy of the overnight batch.
- `LEMMA_HARVEST_GS_URI` (+ `_FAST`, `_MID`, `_ROCKET`), `LEMMA_HARVEST_INTERVAL_SEC` (300), `LEMMA_WAIT_FOR_WRAPPER`: GCS harvest.
- `LEMMA_EXPERIMENT_EVENT_URL`, `_EVENT_FILE`, `_TAG`, `LEMMA_EVENT_STORE_DIR`, `LEMMA_DUCKDB_CONTENTION_FILE`: SSE event stream.
- `lemma_fail_wake.py`: `LEMMA_LIVE_FAMILY` (r28rocket), `LEMMA_WAKE_SENTINEL`, `LEMMA_GCE_ZONE` (us-east1-c), `LEMMA_GCE_INSTANCE`, `LEMMA_VM_OUT`, `LEMMA_HARVEST_LOCAL`, `LEMMA_HARVEST_GS`, `LEMMA_WAKE_STATE`, `LEMMA_WAKE_POLL_SEC` (20), `LEMMA_TICK_SEC` (300), `LEMMA_NTFY_TOPIC`, `GCLOUD`.
- `LEMMA_KEEP_OPTIMIZING` (overnight 1), `LEMMA_STOP_ON_TIMED_SUCCESS` (optimizer.py:420,425): keep trying after a timed success.
- `LEMMA_BENCH_TIMEOUT_SEC` (code 120, overnight 600), `COMPILE_TIMEOUT_SEC` (180), `VERUS_VERIFY_TIMEOUT_SEC` (120): imperative harness walls. The declarative path only uses them inside `harness_timeout_sec`, as a lower bound for the MCP wait (measure_core.py:95).
- `ENABLE_VERUS_VERIFY` (1), `REQUIRE_PROOF` (1 when verify on), `ENABLE_TEMPLATES` (0): imperative harness switches.
- `LEMMA_FAST_TRUSTEDS`, `LEMMA_ENABLE_PARALLEL`, `LEMMA_ENABLE_VECTOR_SCAN`, `LEMMA_ENABLE_SPILL_HASH` (all 0), `LEMMA_HASH_SPILL_BYTES` (2^30), `LEMMA_EMIT_AGENT_PRIMITIVES` (0), `LEMMA_FOLD_SLOT_AXIOMATIC`, `LEMMA_FOLD_SLOT_INDUCTIVE`, `LEMMA_FOLD_SLOT_ASSUME_ALIAS`, `LEMMA_EXACT_SUM`, `LEMMA_TRUST_CONFIG` (product), `LEMMA_LOAD_FORMAT` (lemma_columnar), `LEMMA_LOAD_FROM_DUCKDB` (0), `LEMMA_DUCKDB_SIDECAR_EXPORT`, `LEMMA_FORCE_REGENERATE`: speed-trusted menu and loader switches of the imperative transpiler.
- `LEMMA_PIN_PRODUCT_CATALOG` (sec_table_assumptions.py:69): use paper SEC counts even on a slice.
- `LEMMA_DUCKDB_LIB_DIR` (duckdb_load_mode.py:26), `LEMMA_MEASURE_PATH` (auto), `LEMMA_BENCH_TBL`, `LEMMA_BENCH_TABLE`, `LEMMA_PRIMARY_TABLE`, `LEMMA_PROFILE_TABLE`, `LEMMA_DATASET_SIZE`, `LEMMA_WORKLOAD`, `LEMMA_EXPERIMENT_WORKLOAD`, `LEMMA_HOLDOUT_DATA`, `LEMMA_SCHEMA_JSON`, `LEMMA_RUN_DIR`, `LEMMA_METRICS_JSON`: workload, table and size selection of the imperative optimizer.
- `LEMMA_SSB_DIR`, `LEMMA_SSB_FLAT_TBL`, `LEMMA_SSB_SCALE` (1.333), `LEMMA_SSB_DBGEN_REPO`: SSB data.
- `LEMMA_AGENT_STATS` (1), `LEMMA_AGENT_HARDWARE` (1), `LEMMA_AGENT_DUCK_EXPLAIN` (0 in code), `LEMMA_ASSUMED_L1/L2/L3`: imperative `context.json` contents.
- `LEMMA_AGENT_GUIDANCE` (prescribe/tips/bare), `LEMMA_PRELIM_PROMPT` (0): imperative prompt variants (agent_sandbox.py:392,369).
- `AGENT_DATA_MODE` (none in config.env, stats in code), `AGENT_WORKLOAD_HINT` (1), `AGENT_MAX_TURNS` (40), `AGENT_NETWORK` (0), `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`, `OPENAI_API_KEY`, `LEMMA_MODEL_SOCK`, `LEMMA_MODEL_BRIDGE_PORT`, `LEMMA_MODEL_UPSTREAM`, `LEMMA_ANTHROPIC_UPSTREAM`: OpenRouter host ReAct backend (`LEMMA_AGENT_BACKEND=openrouter`).
- `LEMMA_MCP_TRANSPORT` (stdio), `LEMMA_MCP_HOST`, `LEMMA_MCP_PORT` (8765), `FASTMCP_HOST`, `FASTMCP_PORT`: standalone MCP server.
- `LEMMA_LOG_LEVEL` (INFO), `LEMMA_VERBOSE`, `LEMMA_DEMO*` (BOX, BOX_WIDTH, CLI_WIDTH, DUCKDB, NO_COLOR, STREAM_*, VIEW_DIR, VIEW_KEEP), `LEMMA_LIMIT_BOX`: logging and demo display.
- `LEMMA_DECL_ROWS`, `LEMMA_DECL_SEED`, `LEMMA_CHECK_TIMEOUT` (600), `LEMMA_SEC_PACKAGE`, `LEMMA_TPCH_PACKAGE`, `LEMMA_TPCH_SF`, `LEMMA_TPCH_DB`, `DECL_DEC`, `LEMMA_FILTER_DUCK_MEMORY`, `LEMMA_SHUFFLE_FILTER_WORKERS`, `LEMMA_HOLDOUT_SEED`, `LEMMA_SESSION_HOT_SYNTHETIC`, `LEMMA_RUN_HOLDOUT_BENCH`, `LEMMA_DUCKDB_H1_SMOKE`, `LEMMA_DUCKDB_EXPORT_DIR`, `LEMMA_DUCKDB_EXPORT_TABLES`, `LEMMA_DUCKDB_PIN_TABLES`, `LEMMA_E2E_JOBS`, `LEMMA_E2E_FORCE_ALL`, `LEMMA_DOCKER_NEWGRP`, `LEMMA_LOCAL_AGENT_LOG`, `LEMMA_PROVE_QUERY`, `LEMMA_PROVE_LIMITS`, `LEMMA_VERUS_DOCKER_IMAGE`, `LEMMA_REPO`, `VERUS_Z3_PATH`, `PROVE_MEASURE_SKIP_SF1`, `SPEED_ROWS`, `PYTHON`, `ADVERSARY_TIMEOUT_SEC`, `LEGACY_UNPROVED_EXEC`, `GEMINI_MODEL`: dev scripts, ladders, holdout and test harnesses.
- `DEFAULT_ROW_LIMIT`: see dead list.

Not environment variables though they match the naming pattern: `LEMMA_MAX_ROWS`, `LEMMA_MAX_ROWS_4`, `LEMMA_MAX_ROWS_CUBE`, `LEMMA_MAX_CELL_U64`, `LEMMA_MAX_MONEY_U64`, `LEMMA_MAX_NATIVE_U32`, `LEMMA_MAX_STRING_LEN`, `LEMMA_ABS_SUM_*` (Verus constants emitted into the spec from the catalog), `AGENT_EDIT_*`, `AGENT_HELPERS_*`, `AGENT_BODY_*`, `AGENT_START/END` (source region markers), `AGENT_LOOP_WAKE_<family>` (wake sentinel text), `LEMMA_PIN_INVALID`, `LEMMA_STREAM_INVALID` (Rust constants), `LEMMA_PIN_FFI_BUILD` (cfg define), `LEMMA_PROTOCOL` (Python constant), `VERUS_HOME`, `VERUS_SRC`, `VERUS_CANDIDATES` (Python constants), `VERUS_SMOOTHNESS` (doc name).

## Dead settings (read nowhere or with no effect in the path named)

- `DEFAULT_ROW_LIMIT` (`config.env`): read nowhere.
- `AGENT_WEB_SEARCH`, `AGENT_DOCS_MOUNT`, `AGENT_SUBMIT_ONLY_MEASURE`, `AGENT_MCP_URL`: parsed into `AgentFlags` (config.py:42-49,62-68), no consumer reads the fields (`AGENT_WEB_SEARCH` is only copied into the manifest, run_artifacts.py:31). The claude container agent has `WebSearch,WebFetch` disallowed in the command line (agent_sandbox.py:232) regardless.
- `LEMMA_ZERO_COPY`: only recorded in `arena_record.py:185`; no reader.
- `LEMMA_FLOAT_ABS_EPS`: named only in the docstring of `declarative_spec/future_float_error_bounds/float_eps.py`.
- `MAX_ITERATIONS`: read only by `run_optimizer.py:241` (imperative CLI). Container runs take `--max-iterations`; the env value is only copied to the manifest.
- `LEMMA_SERIOUS`: set to 1 by `agent_env` but read only by `overnight_lemma.sh`/`.py`; no effect in a container run.
- `LEMMA_TPCH_DB`: forwarded by `container_batch.py:25` but not read by `run_container_agent.py` or its callees (only `declarative_manual/oneshot/remeasure.py`). A TPC-H container run needs `LEMMA_DUCKDB_PATH` pointing at the TPC-H file.
- `LEMMA_MCP_ITERATE_ROWS` / `dataset_size`: no effect on what the declarative harness measures (drive.py:243 "reserved"); still used in the prompt blurb and the submit probe-pin check.
- `LEMMA_FAST_TRUSTEDS`, `LEMMA_ENABLE_PARALLEL`, `LEMMA_ENABLE_VECTOR_SCAN`, `LEMMA_ENABLE_SPILL_HASH`, `LEMMA_FOLD_SLOT_AXIOMATIC`: forced to 0 by the declarative menu and never read by `declarative_spec`.
- `LEMMA_AGENT_GUIDANCE`, `LEMMA_PRELIM_PROMPT`: read only by the imperative prompt builder; `declarative_spec/prompt.py` does not call them.
- `config.env` keys `LEMMA_ENABLE_PARALLEL`, `LEMMA_FAST_TRUSTEDS`, `LEMMA_ENABLE_VECTOR_SCAN`, `LEMMA_ENABLE_SPILL_HASH`, `LEMMA_HASH_SPILL_BYTES`, `LEMMA_LOAD_FORMAT`, `LEMMA_LOAD_FROM_DUCKDB`, `LEMMA_AGENT_STATS`, `LEMMA_AGENT_HARDWARE`, `LEMMA_AGENT_DUCK_EXPLAIN`, `LEMMA_LOG_LEVEL`: read from `os.environ` only (lemma_flags.py, agent_context.py:264-340, pipeline_log.py:14), so the file value applies only after an imperative `harness.py` entry has copied the file into the environment. In the declarative container path the code defaults apply.
- `LEMMA_MCP_URL` in `docker/docker-compose.agent.yml:52`: read nowhere.

## Conflicting settings and defaults

| Setting | Conflict |
| --- | --- |
| `LEMMA_SPEC_STYLE` | `overnight_lemma.sh:10` defaults to imperative; `optimizer._read_lemma_spec_style` (optimizer.py:66-79) treats unset as declarative; the launcher requires `--style`. A shell with the variable unset gives different styles per entry point. |
| `LEMMA_PARALLEL_VSTD` | Module default is off (`parallel.py:29`, manifest records `off`); container runs force `auto` (declarative_ladder.py:78) and overwrite a value exported in the shell. `container_batch.py` does not forward it. Not the same flag as `LEMMA_ENABLE_PARALLEL` (imperative parallel trusteds, 0). |
| `AGENT_TIMEOUT_SEC` | `config.env` 600, code 600 (session_clock.py:31, agent_sandbox.py:1105), `container_batch.py:24` 750 (2 x 750 s per attempt), `AGENTS.md` 600. The env value always wins over the file. |
| `AGENT_DATA_MODE` | Code default and `AGENTS.md` flag table: `stats`; `config.env`: `none`. `AgentFlags` reads the file, so the effective value in a run is `none`. The compose file sets `stats`. |
| `USE_AGENT_DOCKER`, `LEMMA_AGENT_BACKEND`, `AGENT_IMAGE`, `AGENT_ENV`, `AGENT_CMD`, `LEMMA_RESEARCH_LOG` | `config.env` values (0, openrouter, `lemma-agent:latest`, `CURSOR_API_KEY`, Cursor agent, 0) are overwritten for every container run by `agent_env`. |
| `LEMMA_DUCK_MEMORY_LIMIT` vs scope cap | Default 3GB was chosen below the 6G scope `MemoryMax` (decl_query_measure.py:38-41 docstring). Frozen value 8GB is above `MemoryMax=6G` of the launching scope; DuckDB spills only past its own limit, so the cgroup can kill the process before DuckDB spills. |
| `LEMMA_DUCKDB_PATH` | Container default is `sec_edgar_dec.duckdb` (DECIMAL, package `sec_margin_dec`); `overnight_lemma.sh:37` defaults to `sec_edgar.duckdb` (DOUBLE, package `sec_margin`). |
| Verus wall | `VERUS_VERIFY_TIMEOUT_SEC` 120 (imperative) vs `LEMMA_VERUS_TIMEOUT_SEC` 300 (declarative); two independent knobs for the same step. |
| `harness_timeout_sec` | File value of `COMPILE_TIMEOUT_SEC` / `VERUS_VERIFY_TIMEOUT_SEC` overrides the environment (optimizer.py:394-401); everywhere else the environment overrides the file. |
| `MAX_ITERATIONS` / `--max-iterations` | Env 1 (run_optimizer, overnight), 4 (r24-r26 chains); launcher flag default 2; `run_optimization_loop` default 3. The launcher ignores the env. |
| `LEMMA_BENCH_TIMEOUT_SEC` | Code 120, overnight 600. |
| `LEMMA_AGENT_DUCK_EXPLAIN` | `config.env` 1 (and `AGENTS.md`), code default 0 (agent_context.py:264, lemma_flags.py). Env-only, so the file value is not applied unless exported. |
| `AGENT_NETWORK` | Only the OpenRouter tool container reads it (docker_runner.py:106). The CLI container is always `--network none` (agent_sandbox.py:1280); `AGENT_NETWORK=1` does not open it. |
| `LEMMA_EXPERIMENT` | `AGENTS.md` requires clean git and tracked SHA for paper runs, but the container launcher neither sets `LEMMA_EXPERIMENT` nor `LEMMA_EXPERIMENT_ALLOW_DIRTY`, so the clean-tree check (run_artifacts.py:120) does not run for container runs unless exported. |
| `HEAVY_MIN_AVAIL_MB` | 3500 in `heavy_phase.py`, 4000 in `heavy.sh`. |
