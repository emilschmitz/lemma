# Lemma

Verified query synthesis. Give it a SQL query and a database; an AI agent writes a native Rust
`run_query`, **Verus proves it computes exactly what the SQL says**, and the proved program is compiled
and timed against DuckDB. Inspired by [GenDB](https://arxiv.org/pdf/2603.02081), with a proof in place of
tests.

https://github.com/user-attachments/assets/7f7891c7-5ef6-406b-882b-8e01134ed37c

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
([protocol](research_loop/menus/TRUSTED_ADDITION_PROTOCOL.md)). Data assumptions (for example column
bounds) are checked against the real database. Limitations are in
[docs/paper/article_draft.md](docs/paper/article_draft.md).

## Quick start

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

## Using it on your own data

A proof is an IF-THEN: *if* the data satisfies the declared bounds, *then* the program computes the SQL.
So real use needs those bounds, called an **assumption package**: row caps per table, value caps per
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
