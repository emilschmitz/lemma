# Lemma

Verified query synthesis. Give it a SQL query and a database; an AI agent writes a native Rust
`run_query`, **Verus proves it computes exactly what the SQL says**, and the proved program is compiled
and timed against DuckDB. Inspired by [GenDB](https://arxiv.org/pdf/2603.02081), with a proof in place of
tests.

https://github.com/user-attachments/assets/7f7891c7-5ef6-406b-882b-8e01134ed37c

## Quick start

Lemma makes a proved, compiled executor for a SQL query on your DuckDB database and runs it inside DuckDB 1.5.6.

**You need** Linux x86_64, Docker (your user may run containers), [uv](https://docs.astral.sh/uv/) (it brings Python), and credentials for
one agent harness (below). Nothing else: no source checkout, no git, no Verus or Rust. Lemma is one wheel; the agent runs in the Docker
sandbox, and the proof (Verus 0.2026.07.18.3a4d30b) and the compile of each executor (its Rust 1.96.0 toolchain) run in the prover image
`ghcr.io/emilschmitz/lemma-prover:0.2026.07.18.3a4d30b` that `lemma setup` pulls (no network at run time, memory-capped), next to the agent
image `ghcr.io/emilschmitz/lemma-agent-claude:<version>`. The bundled DuckDB CLI and extension run on glibc >= 2.28; the executors compiled in
the prover image need glibc >= 2.34 (Ubuntu 22.04+, Debian 12+, RHEL 9+). `lemma setup` checks every item and says what is missing. Network:
`install.sh` fetches the Python dependencies (uv, versions pinned to the release's `constraints.txt`), `lemma setup` pulls the two images; a
run reaches only the harness's model API. Offline: `install.sh --load-images` loads the images from a release built with them. Already have
Verus at `~/tools/verus` with its rustup toolchain? `lemma setup --prover host` (lemma.toml `prover`, `verus_home`; research runs default to
`host`). Build the images yourself instead of pulling: `lemma setup --build-images`.

```bash
tar -xzf lemma-0.1.0-linux-x86_64.tar.gz && ./lemma-0.1.0-linux-x86_64/install.sh   # ~/.local/bin/lemma, ~/.local/share/lemma/duckdb/
lemma setup                                    # Docker, DuckDB; pulls the prover and agent images, tests the sandbox; your Claude Code login
lemma optimize --db my.duckdb --sql "SELECT region, SUM(qty) AS q FROM orders GROUP BY region"   # or: lemma optimize --db my.duckdb q.sql
lemma duckdb my.duckdb                         # a full DuckDB; in it: SELECT * FROM lemma('<your SQL>');  (generates on first use)
lemma list                                     # installed executors (key, proof line, database, SQL); lemma remove KEY
```

`install.sh` is `uv tool install` of the wheel plus a copy of the DuckDB binaries; by hand that is
`uv tool install --constraints constraints.txt ./lemma-0.1.0-py3-none-any.whl` and `lemma setup --duckdb-from ./duckdb`.

`lemma optimize` runs the agent in the sandbox until Verus proves its `run_query` against the query's spec, then verifies the same
body again as a library and installs it under `~/.local/share/lemma/executors/<sha256 of the SQL>/` (`lib.so`, `manifest.json`; the
proved sources in `proved/`). If the proof or the install fails, nothing is installed. `--bench` also times it inside DuckDB against
DuckDB (cold = first call, scan included; warm = the input cache below). In your own DuckDB 1.5.6 (the extension is not signed):

```python
import duckdb, os
con = duckdb.connect("my.duckdb", config={"allow_unsigned_extensions": True})
con.execute(f"LOAD '{os.path.expanduser('~/.local/share/lemma/duckdb/lemma.duckdb_extension')}'")   # `lemma duckdb` prints this path
con.execute("SET lemma_mode = true")   # every SELECT with an installed executor runs the proved program
```

In Lemma mode a query without an executor is an error, never silently DuckDB's answer; `SET lemma_route_unproved = true` lets DuckDB
answer it, labelled `engine = duckdb` in `lemma_last_query()`. A proved program may DECLINE (no data assumptions: e.g. a checked overflow),
which is the same error or the same labelled route. All settings: [db_extension/duckdb_ext/README.md](db_extension/duckdb_ext/README.md).

**Verified vs trusted.** Verus proves that the agent's `run_query` returns exactly the result the query's specification states, and the
specification is generated from the SQL by the transpiler. Not proved: that the transpiler's specification means what DuckDB computes
(checked per query shape against DuckDB, not proved), the extension's scan and conversion of DuckDB's columns into the executor's inputs,
Verus, Z3 and rustc. The trusted items are listed in [docs/TRUSTED_FAMILIES.md](docs/TRUSTED_FAMILIES.md): the host's fixed helper
bridges, DuckDB evaluating a pushed-down filter correctly (agent scans), the input cache's data version, and only with
`exact_division = false` the float idealization. The agent cannot add trusted code (admission rejects `assume`, `external_body` and the like).

**The input cache.** The scan and conversion of the inputs often costs more than the proved program. A repeated query on unchanged data
reuses the converted inputs (`lemma_last_query()` says `cache = hit`); any committed write, or another open transaction, makes the next call
scan again. `SET lemma_cache = false` turns it off, `lemma_cache_max_mb` caps it. Details and the soundness argument:
[db_extension/duckdb_ext/README.md](db_extension/duckdb_ext/README.md) "Input cache".

**Harness and auth.** Claude Code is the default (`claude login`, or `lemma setup --auth api-key` with `ANTHROPIC_API_KEY`); also
`lemma setup --harness codex --auth api-key` (`CODEX_API_KEY`, default model gpt-6.1-sol) and `--harness gemini --auth api-key`
(`GEMINI_API_KEY`, default gemini-3.8-flash); `--model` picks another model. Export a key in your own shell: it reaches the container by
name only and is never written anywhere; a missing one stops setup, and nothing falls back to another harness or auth mode. Only Claude
Code reports spend, so `max_budget_usd` caps Claude runs only. Per-harness details: `research_loop/AGENT_SANDBOX.md` "Agent harnesses".
`lemma status` shows the choices, the image, the sandbox test and the installed executors.

**Building a release.** `scripts/release/build_product.sh` builds everything from a clean checkout in one go: the DuckDB CLI and extension
(`build_portable.sh`, in DuckDB's own manylinux_2_28 release image from whatever extension source is checked out, so they need glibc 2.28
only; heavy, about 40 minutes the first time, `--skip-duckdb-build` reuses it), the images (`build_images.sh`: tagged
`<registry>/lemma-agent-claude:<version>` and `<registry>/lemma-prover:<verus>`, `--save-images` adds `docker save` tarballs for offline
installs), the wheel (`build_wheel.py`: the runtime packages, `lemma.toml`, the guard scripts, the Dockerfiles, the agent's worked examples
and the Verus docs as package data; nothing is read from or written to a checkout at run time) and `dist/lemma-<version>-linux-x86_64/`
(+ `.tar.gz`) with `install.sh` and a short README. From a checkout you can instead run `uv tool install --editable .` and use the binaries
in `db_extension/duckdb_ext/build/release` (runs then record the git SHA; an installed wheel records its version and the wheel's sha256).

**Publishing a release** (Emil's decision; nothing in the scripts publishes without these explicit steps):

```bash
docker login ghcr.io -u emilschmitz                                   # a token with write:packages
scripts/release/build_product.sh --push                               # or: scripts/release/build_images.sh --push (after a build_product.sh)
gh release create v0.1.0 dist/lemma-0.1.0-linux-x86_64.tar.gz dist/lemma-0.1.0-linux-x86_64/lemma-0.1.0-py3-none-any.whl
# later, PyPI (`pip install lemma` / `uv tool install lemma`; the DuckDB binaries then come from `lemma setup --duckdb-from DIR`):
uv publish dist/lemma-0.1.0-linux-x86_64/lemma-0.1.0-py3-none-any.whl
```

The ghcr.io packages must be public for an anonymous `docker pull` (GitHub: package settings, visibility).
`lemma optimize --queue` proves the queries the extension enqueued (`SET lemma_enqueue_misses = true`) in `$LEMMA_HOME/queue/*.sql`.
No assumption step is needed: with the default `assumptions = false` the proof makes no claim about your data. `lemma assumptions --db my.duckdb`
belongs to the UNMAINTAINED assumption-package path and is required only with `assumptions = true`.

## How it works

```
SQL + catalog -> spec (transpiler) -> agent writes run_query -> Verus proves it meets the spec
              -> assemble -> compile -> run against DuckDB's data, timed vs DuckDB
```

- **Spec.** The transpiler turns the SQL into a Verus specification. It is the ground truth. It must be
  a real specification, never `arbitrary()` or a vacuous trusted stub. If a query cannot get a real
  spec, transpiling fails loudly.
- **Agent.** It edits only the marked `run_query` body (and proof helpers). It cannot add `assume`,
  `external_body` or other trusted code. The host rejects those and reassembles the file itself.
- **Proof.** Verus checks the body against the spec. A proof error is a proof error, not a timeout.
- **Execution.** The proved binary reads real columns and its output rows are checked against DuckDB.

Two spec styles share one pipeline, container and agent (`LEMMA_SPEC_STYLE`, default `declarative`):

| Style | Spec | Where |
|---|---|---|
| `declarative` (default) | `ensures` states what the result must satisfy | `declarative_spec/` |
| `imperative` | a recursive fold the body must match | `verus_transpiler/` |

The declarative path covers joins, group-by, HAVING, subqueries, NULLs (validity vectors),
dictionary-encoded strings, DECIMAL/DATE, float aggregates (as exact reals; rounding is an accepted
error), ratios, and a parallel path built on vstd threads.

## Trust

What is trusted is listed in [docs/TRUSTED_FAMILIES.md](docs/TRUSTED_FAMILIES.md): the host's fixed
helper bridges, the float idealization (a small fixed set of lemmas) and one IEEE division lemma. Adding any new
trusted item needs a written proposal and a separate adversary review
([protocol](research_loop/menus/TRUSTED_ADDITION_PROTOCOL.md)). By default there are no data assumptions
(`assumptions = false`, since 2026-10-17): the spec uses exact integers and the program may decline (see below). Limitations are in
[docs/paper/article_draft.md](docs/paper/article_draft.md).

## Quick start for development

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), Rust,
[Verus](research_loop/scripts/install_verus.md), and Docker for the agent sandbox.

```bash
./scripts/setup.sh
uv run python research_loop/harness.py -q 1 --dataset-size 50000
```

Run the agent in the sandbox (network off, only `api.anthropic.com` allowed; log in with Claude Code
on the host first, or pass `ANTHROPIC_API_KEY`):

```bash
uv run python research_loop/scripts/run_container_agent.py --style declarative \
    --menu adversary_declarative0 --agent claude-haiku-4-5-20251001 \
    --query-sql "SELECT SUM(line) AS total FROM pre WHERE line > 5"
```

Verus is memory hungry. Run it through `scripts/ram/verus_guarded.sh`, which caps concurrent runs and memory.

**Configuration lives in one file, `lemma.toml`** (repo root, one commented line per setting: run, agent, prover, measure, data, safety).
Precedence: `lemma.toml` < environment variable `LEMMA_<KEY>` (e.g. `[measure] official_rounds` is `LEMMA_OFFICIAL_ROUNDS`) < CLI flag.
A misspelled `LEMMA_*` variable, a bad value or a dead setting stops the launcher before any work (`uv run python -m lemma_config check`; `dump` lists
every value and where it came from). Every container run records the full effective config, the git SHA and `git_dirty` in its manifest and RESULT
line, and refuses to start from a dirty git tree (tracked files) unless `allow_dirty = true`. See `docs/FLAGS.md`.

## Using it on your own data

**Default (since 2026-10-17): no data assumptions** (`lemma.toml` `assumptions = false`, following JetStream, arXiv 2610.20527).
The spec states the exact answer over mathematical integers; `valid_cols_*` says only what the loader builds and checks (column
lengths, dictionary codes inside their dictionary, distinct dictionary entries). Cell types come from the SQL types alone
(DECIMAL(p,s) is i64 for p <= 18, else i128; BIGINT i64; INTEGER i32; DATE i32 days; VARCHAR a u32 dictionary code). `run_query`
returns `Option`: `Some(res)` satisfies the contract (`run_query_ok`), `None` DECLINES, for example when a checked addition
overflows. A declined run is reported as `DECLINED`: not a success, not a proof failure, and a failed query in experiments. The compiled
program prints `LEMMA_DECLINED` and exits with code 3; nothing substitutes another engine's answer (an in-DuckDB extension may route a
declined query to DuckDB only under its user flag `lemma_route_unproved`, labelled). Which columns get a NULL validity vector is read
from the database (a column with a NULL); the exporter refuses a NULL anywhere else. Details: `declarative_spec/decline.py`, `docs/FLAGS.md`.

### The assumption-package path (UNMAINTAINED, `assumptions = true`)

A proof is an IF-THEN: *if* the data satisfies the declared bounds, *then* the program computes the SQL.
That path needs those bounds, called an **assumption package**: row caps per table, value caps per
column (for DECIMAL, on the stored integer), string length caps, unique keys, which columns may be NULL,
and join-size caps. They also set the widths the proof reasons about, so tighter true bounds mean easier
proofs and faster code.

1. **Get a package.** The profiler proposes one from your data. It measures each table and column (same
   rules as the check below) and writes a JSON package plus a plain-language report of every bound: what was
   measured, the proposed cap (rounded up to a power of two, with margin), what breaks if data exceeds it, and
   the effect on proof and speed. Unique keys are proposals only.
   ```bash
   uv run python -m research_loop.assumption_packages.profile --db <duckdb file> --name mypkg --out mypkg.json
   ```
   These are your claims about your data, so review and approve each one; the Claude Code skill
   `.claude/skills/lemma-assumptions/SKILL.md` walks an agent through exactly that. Select the result with
   `LEMMA_ASSUMPTION_PACKAGE=mypkg.json` (a path, or a name in `research_loop/assumption_packages/registry/`).
   Hand-written Python packages still work (see `sec_margin_dec` for the real SEC EDGAR data).
2. **Check it against the database.** This lists every violated assumption with the measured value and
   exits non-zero. A table or column it names that the database lacks is also a violation.
   ```bash
   uv run python -m research_loop.assumption_packages.check --package mypkg.json --db <duckdb file>
   ```
3. **At run time** the loader re-checks the bounds on the pinned columns, so data that later breaks an
   assumption fails loudly instead of running a proof that no longer applies. Re-run the profiler and check after data grows.

The DuckDB extension in `db_extension/` is the interactive way in: `SELECT lemma('<sql>')` optimizes
the query with the agent, caches the proved program, and later calls reuse it
(`db_extension/DEMO.md`, `scripts/demo.sh`). Today it is a demo path. The path used for the measured
results is the launcher above. It is wired to the SEC database (`LEMMA_DUCKDB_PATH`); another database needs
its own assumption package and the schema loader pointed at it.

## Layout

| Path | Role |
|---|---|
| `declarative_spec/` | declarative emitter, parallel/dictionary/NULL support, prompt, assemble |
| `verus_transpiler/` | imperative transpiler |
| `research_loop/` | harness, menus (profiles), assumption packages, agent sandbox, scripts |
| `db_extension/` | optimizer loop, MCP host the agent calls, DuckDB bridge |
| `docker/agent/` | sandbox image and entrypoint |
| `holdout/` | GenDB SEC EDGAR and TPC-H data and queries |
| `tests/` | tests and verified example bodies (`tests/fixtures/declarative_proofs/`) |
| `docs/` | trusted families, verification chain, paper draft |

## Status

Research code, in progress. The declarative emitter produces specs for all of the GenDB SEC corpus on a
DECIMAL schema. Typechecking and per-shape reference proofs cover it; a corpus-wide check of every spec's
meaning against DuckDB is not done. Speedups against all-core DuckDB are measured per query shape, with
the prover labelled (manual Sonnet subagent or real Claude Code in the container). Some shapes win by
several times, selective scans do not yet. See `research_loop/menus/` for logs and verdicts.
