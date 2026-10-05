# Adversary verdict: sandbox host-only data hiding (decl_data shadow)

Method: real `docker run` against `lemma-agent:claude` with exactly the launcher flags (`--network none --cap-drop ALL --cap-add DAC_OVERRIDE`, workspace rw, `shadow_mount_args(ws)`, context/ro ro at two places), temp workspace with `decl_data/bar.json`="SECRET" and `cols_num.bin`. Scripts: scratchpad `atk.py`, `symw.py`, `symw2.py`, `adm.py`, `res.py`. No tracked source modified. No tool/classifier refused any step.

## A. In-container routes (all BLOCKED)

| Route | Command | Result |
|---|---|---|
| umount | `umount /workspace/decl_data` | blocked: rc=32 "must be superuser" (CapEff is only DAC_OVERRIDE, `0x2`) |
| rmdir / rm -rf | `rmdir`, `rm -rf /workspace/decl_data` | blocked: "Device or resource busy" |
| mv decl_data | `mv /workspace/decl_data /workspace/d2` | blocked: EBUSY |
| mv parent | `mv /workspace /workspace2` | blocked: EBUSY (`/workspace` is a mount point) |
| mount --bind / tmpfs | `mount --bind /workspace/context /workspace/decl_data`, `mount -t tmpfs x /mnt` | blocked: permission denied (no CAP_SYS_ADMIN) |
| find / grep | `find / -xdev -name bar.json -o -name 'cols_*.bin'`; `grep -rs SECRET /` | blocked: no hits (only unrelated openssl/apt strings) |
| /proc traversal | `/proc/1/root/workspace/decl_data/bar.json`, `/proc/self/root/workspace/decl_data`, `/proc/self/cwd/decl_data`, `/proc/self/fd/N/decl_data` | blocked: empty dir / no such file (same mount namespace, so the tmpfs shadow applies) |
| symlinks | `ln -s decl_data /workspace/l1`, `ln -s /proc/self/root/workspace/decl_data l2`, `ln -s /workspace/decl_data l3`, `cat l3/bar.json` | blocked: links resolve in-container to the empty tmpfs |
| devices | `mknod /tmp/sda b 8 0` | blocked: EPERM; /dev is the minimal docker set |
| mountinfo | `grep workspace /proc/self/mountinfo` | blocked for data; see leak L1 (info only) |

mountinfo confirms layout: `/workspace` (rw bind) with `/workspace/decl_data` tmpfs `ro,nosuid,nodev,noexec,size=4k`.

## B. Host-side routes

### B1. MCP `path` argument -> `_resolve_under_workspace`: BLOCKED
Tested with symlinks (relative, absolute, via `decl_data/...`, `x/../decl_data/..`, absolute host path, `/etc/passwd` link): all refused (PermissionError for decl_data, ValueError for outside workspace). Residual: a theoretical TOCTOU (resolve, then a concurrent in-container swap of an intermediate directory for a symlink to decl_data before `read_text`). The read would then be of host-only content as a "body" and verus errors might echo it. Not exercised; narrow race, but not impossible.

### B2. Host writes follow agent-made symlinks: OPEN (integrity, and a reach to decl_data)
The agent controls the rw workspace. The host writes to workspace paths without `resolve()` or `O_NOFOLLOW`: `runquery_agent.rs`, `runquery_agent.edit.sha256` (`assemble_runquery.write_runquery_agent_file`), `declarative_build/declarative_query.rs` (`pipeline.compile_and_run`), `mcp_results/runs/*.json`, `latest_run.json`, `submitted.json`. Demonstrated (`symw.py` + `symw2.py`): after the container ran `ln -s <abs host path> /workspace/runquery_agent.rs` and `ln -s <ws>/decl_data/bar.json /workspace/runquery_agent.edit.sha256`, a host `Path.write_text` into the workspace overwrote a file outside the workspace (`victim: HOST WROTE SOURCE`) and **overwrote `decl_data/bar.json` with `deadbeef`**. So the agent can (a) tamper the timing bar / expect.json (corrupt or neutralise it), and (b) clobber arbitrary host files writable by the host user (partly agent-controlled content: the body is embedded). It cannot *read* decl_data this way (the write replaces content), but the tamper breaks the "bar the agent can't touch" claim. It needs the absolute host path: see L1/L2 (the assembled `declarative_query.rs` embeds `std::fs::read("<abs>/decl_data/cols_*.bin")`, which the agent can read from `declarative_build/` after any run; mountinfo gives the path relative to the filesystem root, and runs under `research_loop/runs/<id>` are guessable).
Fix suggestion: create/check host-written targets with `O_NOFOLLOW`, or have the host `unlink` (not follow) any symlink/non-regular entry in the workspace before each write, or write into a host-private dir and copy in.

### B3. Admission `_HOST_ESCAPE`: BYPASSABLE (the body compiles and runs on the HOST with decl_data readable)
`admit_declarative_body` results (`adm.py`):
- Blocked: plain `std::fs::read`, `::std::fs`, `r#"…"#` raw string before it, NBSP variant, `include_bytes!`, `unsafe`, etc.
- **Passes (ok=True) but should not:**
  1. block comments: `std /**/ :: /**/ fs::read("x")` and `std::/**/fs::read("x")`. `_strip_comments_and_strings` only strips `//`, not `/* */`, and the regex has no comment tolerance.
  2. lifetime hiding: `let a: &'a u8 = &1; let s = std::fs::read("x"); let b: &'b u8 = &1;`. The stripper treats `'a` as a char-literal quote and deletes everything up to the next `'`, hiding the code from every regex (this also hides `assume(`, `external`, `unsafe`, etc. from every other lint rule).
  3. `#[path = "/…/decl_data/bar.json"] mod m;` passes (no `mod`/`path` rule); a parse error of the included file would echo its bytes in the compiler error returned to the agent.
  4. Unlisted std modules: `std::path::Path::new(..).exists()`/`read_dir()`, `std::time`, `std::thread::sleep`, `std::hint`, `std::panic` all pass (`exists`/`read_dir` are a filesystem probe; `thread::sleep`/`time` are timing-bar-adjacent).
Whether Verus accepts an unspecified `std::fs` call in an exec fn was not tested (no `verus` binary here), so reachability depends on that; the lint itself is leaky and should not be the only barrier. If reachable, the binary runs with `cwd=declarative_build` as the host user and can read `decl_data/*` and report them through `QUERY_LATENCY` hacking or stderr (last 2000 chars of binary stderr is returned as `compiler_error` on failure, `pipeline.compile_and_run`).
Fix suggestion: strip `/* */` (nested), handle lifetimes vs char literals (`'a` followed by non-`'`), ban `#[path]`/`mod`, and allowlist rather than denylist (`std::` anywhere except explicitly allowed names).

### B4. What the host puts in the agent-visible workspace and tool output
- `mcp_results/runs/*.json`, `submitted.json`: only run metrics, `_SPEED_KEYS`, error text, body. No raw rows, no expected rows. By design: `duck_us`, `duck1_us`, `duck_threads`, `speedup*`, `official_tables` (row counts), `speed_bar_mult`, `verify_summary` (the bar's timing is intentionally exposed to the agent).
- Error text: `rows_match_error` / `_apply_speed_bar` return "got N rows, expected M" (and "got N groups, expected M" in the legacy path). That discloses the **expected result row count** (and a pass/fail bit on equality), which is the only expect.json content (`rows`) that reaches the agent. Low severity (correctness is proved anyway), but it is a leak beyond `_SPEED_KEYS`. The row values are never printed. Binary stdout is not returned.
- `declarative_build/declarative_query.rs` / binary (agent-readable): embeds the absolute host path of every `cols_*.bin` and `expect_rows` (= official table row counts, also in `official_tables`). L2: host path disclosure, no data.
- `/proc/self/mountinfo` (L1) discloses the workspace's host source path (relative to its filesystem root), which helps B2.

## C. Other mount sites
- `db_extension/agent/docker_runner.py` (legacy OpenRouter tool container) also applies `shadow_mount_args`; it mounts `data_dir:/data:ro` when `AGENT_DATA_MODE=full` (raw data by design of that mode, not decl_data).
- `research_loop/scripts/check_agent_mcp_ready.sh:167` mounts a workspace to `/workspace` with no shadow (readiness script, not the agent run; flagged for completeness).
- Cursor (non-claude) launch path in `agent_sandbox.py` uses the same `cmd` prefix, so it is shadowed.

## Overall verdict

In-container data access is **closed**: from inside the container, with the granted capabilities, I found no way to read `decl_data/cols_*.bin`, `expect.json` or `bar.json`, or to remove/replace the shadow mount; the MCP `path` resolver refuses every symlink variant tried.

Still reachable / open:
1. **B2 (open, demonstrated)**: agent-planted symlinks in the rw workspace make the host overwrite the timing bar files (and any other host-writable file) when it next writes `runquery_agent.rs`, `*.edit.sha256`, `declarative_query.rs` or `mcp_results/*`. Hiding is defeated for integrity of the bar; not for reading it.
2. **B3 (open, lint bypasses demonstrated)**: `/* */` comments, `'a` lifetime hiding, `#[path] mod`, and unlisted `std::path/time/thread` all pass admission. If Verus compiles such a body, the host-run binary can read decl_data.
3. Minor information leaks: expected row count in failure text; host absolute path via mountinfo and the embedded path in `declarative_build`; a narrow TOCTOU on `_resolve_under_workspace`.

By design (not findings): `_SPEED_KEYS` including `duck_us`/speedups/`official_tables`.

## Response to the open items (author, after the review)

- Host writes following agent-made symlinks: fixed. `research_loop/sandbox_hide.unlink_planted_symlinks` removes every symlink in the workspace before the MCP path resolve, the marked-file write, and the harness run. Test: `test_planted_symlinks_are_removed_before_the_host_writes`.
- Admission bypasses: block comments are now stripped (nested), lifetimes no longer start a string, `#[path]`, `mod`, `alloc::`, `libc::`, `mem::transmute` are rejected, and `std::`/`core::` paths are an allowlist of pure-compute modules (fs, env, io, process, net, path, os, arch, ffi, ptr are out). Tests: `test_admission_bypasses_found_by_the_adversary_are_closed` (5 cases) and the keep-working case.
- Minor leaks left as-is and reported: "got N rows, expected M" error text, host path strings, the narrow TOCTOU in `_resolve_under_workspace`, and `research_loop/scripts/check_agent_mcp_ready.sh:167` (readiness script, not an agent run, mounts without the shadow). The speed bar numbers returned by MCP (`_SPEED_KEYS`) are by design.
- Whether Verus itself would accept a body using a bypass was not testable (no verus binary in the review environment); the lint is the defence regardless.
