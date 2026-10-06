# Adversary verdict: container_batch refresh_login (commit e1d58d3)

Verdict: PASS WITH FINDINGS

Reviewed `refresh_login`, `main`, and the new tests. `uv run pytest tests/test_container_batch.py -q` gives 7 passed. I did not call the real claude and did not run containers.

## Requirement check
- Command, `--model`, `--max-turns 1`, cwd `/tmp`, timeout 90 s: met.
- ANTHROPIC_API_KEY and CLAUDE_CODE_OAUTH_TOKEN removed from the child env: met.
- Exit 0 and non-empty stdout required; timeout, non-zero exit and empty output all raise and `main` returns 2 before the container run: met.
- Message says "log in with `claude` in your terminal": met.
- No credential file is read. Only stderr[:200] of claude is echoed, and stdout is never printed.
- `refreshed: true` is written per run: met.
- No fallback path exists in the code.
- Tests are not vacuous. The stub PATH is used: `subprocess.run(env=...)` resolves `claude` via the env's PATH, test 1 reads the stub's call log, and test 2 would raise FileNotFoundError if the stub were missed. Test 1 proves the env vars are blank in the child and that cwd is /tmp. The timeout test does reach the timeout path (`sleep 5` with timeout forced to 1).

## Findings
1. MEDIUM, stale token inside the window: the refresh runs before the `flock /tmp/lemma_timing.lock systemd-run ...` command, so it is not inside the lock. If another job holds the timing lock for a long time, the container starts with a token refreshed long ago. This contradicts "never continue with a stale token". Repro: hold the lock with `flock /tmp/lemma_timing.lock sleep 7200` and start a batch. The refresh happens at t=0 and the run starts at t=2h. Fix: refresh after taking the lock (run the refresh as part of the locked command), or make the refresh and the run one locked unit.
2. MEDIUM, other credential paths not stripped: only two variables are removed. ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL, CLAUDE_CODE_USE_BEDROCK/VERTEX and CLAUDE_CONFIG_DIR still pass through. With ANTHROPIC_AUTH_TOKEN set, `claude -p` exits 0 on that token without touching the OAuth login. The check then passes while the mounted OAuth token stays stale. This is a way to continue anyway. The spec named two variables, so this is a spec gap. Consider failing loudly if these are set, or whitelisting the env.
3. LOW, stale artifacts on a failed refresh: nothing deletes an old `<model>_<q>.refresh.json` or `.log` from a previous batch before the refresh. After a stop, the previous run's `refreshed: true` file remains and looks like proof for this run. The test only checks absence in a fresh tmp dir. Fix: unlink both before refreshing.
4. LOW, partial batch handling: if run 2's refresh fails after run 1 succeeded, `main` returns 2 and skips `container_table.py`. Run 1's log and refresh.json are intact, with no corruption, but no table is printed for the completed runs. There is no summary of which runs completed or which were skipped. The stop message names only the run that failed.
5. LOW, error details and test strength: stderr text from claude (up to 200 chars) is printed. It is unlikely to hold secrets, but the code does not guarantee it. The failure tests only assert the common "log in with" string, so they cannot tell the three failure modes apart (for example, whether the timeout branch ran). A missing `claude` binary gives a raw FileNotFoundError traceback. That is loud, so it is acceptable under fail-fast.
6. INFO, `refresh.json` is written before the container run, so it means "refresh succeeded", not "run used a valid token". The container run's own exit code is still ignored, which was already the case before this commit.

No finding allows the batch to continue after a refresh failure through the code path itself. Findings 1 and 2 are the ways to run on a stale token without a failure.

## Author response
1. MEDIUM refresh before the lock: fixed. The refresh now runs inside the lock (`container_batch.py --locked-run MARKER -- CMD`, exec'd by flock, then execvp of the systemd-run command); the batch stops when no marker exists after a run. Tests: `test_the_refresh_runs_inside_the_lock_before_the_container_command_and_is_recorded`, `test_the_batch_stops_when_a_run_left_no_refresh_marker...`.
2. MEDIUM other credential paths: ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL, CLAUDE_CODE_USE_BEDROCK/VERTEX now stripped as well. CLAUDE_CONFIG_DIR is deliberately NOT stripped: it names the login file the container mounts, so the refresh must act on the same one.
3. LOW stale markers/logs: deleted before each run (tested).
4/5. LOW: accepted (batch returns 2 with the loud message; a missing `claude` binary raises loudly).
