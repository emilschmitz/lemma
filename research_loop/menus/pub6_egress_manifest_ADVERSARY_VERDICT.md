# Adversary verdict: ce1acdb egress attribution + manifest `effective` (pub6 host fixes)

Verdict: SOUND AFTER FIXES. Tests: 48 passed before, 50 after (`tests/test_pub6_host.py`, `test_container_agent_summary.py`, `test_menu_profile.py`, `db_extension/tests/test_run_artifacts.py`).

## (a) Egress attribution
- Never dropped: every denied record lands in `egress_denied_in_agent_bash` or `egress_denied_cli_hosts`, and also in `egress_hosts` (the bridge log includes denied hosts). Unparseable or missing `ts`, a missing or empty `claude_raw.jsonl` -> counts as the run flag. The fail-safe direction is right.
- A background process that connects after its Bash call returned is outside the window -> run flag (false positive, safe).
- Timestamps: bridge is `time.gmtime` `...Z` (second FLOORED), stream is ISO with ms and Z. `fromisoformat` parses both, both UTC. Stream shape checked against `tests/fixtures/claude_stream_real_mock.jsonl` (assistant/user records carry `timestamp`). Same host kernel clock on Linux, so no container/host skew here (a Docker-Desktop VM would differ; not this setup).
- FIXED (real, minor): the +-1 s slack was symmetric. The floor error is one-directional (stamp <= real time), so slack after the tool_result only widened the window and hid a CLI denial in the first second of the next turn (the CLI's next request follows the result by ms). Now `start - 1 <= ts <= end`. Two tests added.
- NOT fixable by time: the bridge record has only ts/host/method (no pid or peer), so a CLI denial overlapping a Bash call (parallel tool calls, CLI background traffic during a long Bash) is attributed to Bash and does not set `egress_denied`. It is still listed by host. The comment now says `egress_denied=False` does not prove the CLI was never denied; the in-bash comment already says attribution by time, not proof.
- A Bash call with no tool_result runs to infinity: after a `-9` kill or a truncated last line, later denials go to the bash bucket. Acceptable (the CLI is dead then); unchanged.
- Garbled lines: non-JSON lines are skipped; a JSON line that is not an object would raise (loud). Pre-existing, not changed: `summarize_run` does `json.loads(line)["host"]` over the whole bridge log, so a bridge error record (`{"ok":false,"error":..}`, no host) raises KeyError.

## (b) Consumers
- `container_table.py` printed `denied=False` for in-bash denials: misleading; it now also prints `bash-denied=[hosts]`.
- AGENT_SANDBOX.md "egress_denied.jsonl stays empty" is about the file and still true as stated. `tests/test_claude_mock_e2e.py` asserts the file absent: unaffected.

## (c) Manifest `effective`
- Defaults match the code: string encoding `plain`; narrow cells `"0"` (only `"1"` enables); `LEMMA_PARALLEL_VSTD` off, `1`/`auto` enabled (`parallel.enabled/strict`), set to `auto` by `agent_env` for declarative before `begin_run`; `LEMMA_ENABLE_PARALLEL` read as `== "1"` in emit_externs (raw string recorded; `lemma_flags.env_bool` may accept other spellings, cosmetic).
- Order: `run()` sets `LEMMA_ASSUMPTION_PACKAGE` and calls `record_effective_axis` before `run_optimization_loop` -> `begin_run`, so `effective`, `menu` and env agree. Package is null in `effective` only when no launcher default applies (non-declarative style).
- `record_effective_axis` assert: reached only when `resolved.values[axis] is None` straight after `activate_menu` set `_active`. An env-preset package makes the axis non-None (env override), so it is skipped, same as the old `setdefault`. A second `run()` in the same process re-uses the updated selection and skips it. Caveat (pre-existing): the launcher's env var is not in `_saved`, so `deactivate_menu` leaves it in `os.environ`.
