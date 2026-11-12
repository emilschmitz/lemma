# Lemma

Full DuckDB 1.5.6 plus Lemma: give it a SQL query and your database, an AI agent writes a native program for it, Verus proves the program
computes exactly what the SQL says, and DuckDB runs the proved program from then on.

**You need** Linux x86_64 (glibc >= 2.34), Docker (your user may run containers), [uv](https://docs.astral.sh/uv/), and credentials for one
agent harness: an API key by default (`ANTHROPIC_API_KEY` exported in your shell; `lemma setup --harness codex` / `--harness gemini`
take `CODEX_API_KEY` / `GEMINI_API_KEY`). `lemma setup --auth login` uses your own CLI login instead, for your own personal use only.

## Install

From PyPI:

```bash
uv tool install lemma-db                           # the `lemma` command
export ANTHROPIC_API_KEY=...                       # your key, in your own shell (never in a file or a chat)
lemma setup --build-images                         # downloads the DuckDB binaries (sha256-checked), builds the images, tests the sandbox
lemma duckdb                                       # a full DuckDB 1.5.6 with Lemma
```

The first `lemma setup` downloads `lemma-<version>-duckdb-linux-x86_64.tar.gz` of the installed version from this GitHub release (it prints
the URL and size first) and installs it only if its sha256 is the one the wheel was built with; otherwise it stops and installs nothing.
`--build-images` builds the agent and prover images here (they are not on a registry yet).

Or from this release directory (the same wheel, every dependency pinned to `constraints.txt`, the DuckDB binaries copied, no download):

```bash
tar -xzf lemma-<version>-linux-x86_64.tar.gz
./lemma-<version>-linux-x86_64/install.sh          # ~/.local/bin/lemma, ~/.local/share/lemma/duckdb/
export ANTHROPIC_API_KEY=...
lemma setup --build-images
```

Offline machine: `./install.sh --load-images` loads the images shipped in `images/` (when the release has them); then `lemma setup`
without `--build-images` uses them.

## First query

```bash
lemma optimize --db my.duckdb --sql "SELECT region, SUM(qty) AS q FROM orders GROUP BY region"
lemma duckdb --lemma-mode my.duckdb -c "SELECT region, SUM(qty) AS q FROM orders GROUP BY region; SELECT * FROM lemma_last_query();"
lemma list                                         # installed executors; lemma remove KEY
```

`lemma duckdb` is a complete DuckDB 1.5.6 CLI (`~/.local/share/lemma/duckdb/duckdb`: CREATE TABLE, joins, `read_csv`, every DuckDB
feature). Plain SQL is plain DuckDB. To run a query through Lemma:

```sql
SELECT * FROM lemma('SELECT region, SUM(qty) AS q FROM orders WHERE year = 2024 GROUP BY region');  -- first time: generates + proves (minutes)
SELECT * FROM lemma('SELECT region, SUM(qty) AS q FROM orders WHERE year = 2025 GROUP BY region');  -- same template: reuses the proved executor
SELECT * FROM lemma_last_query();   -- engine = lemma, cache hit/miss
SELECT * FROM lemma_list();         -- saved executors; SELECT * FROM lemma_remove('<key prefix>'); lemma_jobs() for generations
```

`lemma duckdb --lemma-mode` routes every SELECT through Lemma instead (a query without an executor is then an error, unless
`SET lemma_route_unproved = true`, which lets DuckDB answer it, labelled `engine = duckdb`). From your own DuckDB 1.5.6:
`duckdb -unsigned my.duckdb`, then `LOAD '<home>/.local/share/lemma/duckdb/lemma.duckdb_extension';` (the full path; `lemma duckdb`
prints it).

More: https://github.com/emilschmitz/lemma (README "Quick start").
