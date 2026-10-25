# Lemma

Full DuckDB 1.5.6 plus Lemma: give it a SQL query and your database, an AI agent writes a native program for it, Verus proves the program
computes exactly what the SQL says, and DuckDB runs the proved program from then on.

**You need** Linux x86_64 (glibc >= 2.34), Docker (your user may run containers), [uv](https://docs.astral.sh/uv/), and credentials for one
agent harness (Claude Code login by default, or an API key: `lemma setup --auth api-key` with `ANTHROPIC_API_KEY` exported).

## Install

```bash
tar -xzf lemma-<version>-linux-x86_64.tar.gz
./lemma-<version>-linux-x86_64/install.sh          # ~/.local/bin/lemma, ~/.local/share/lemma/duckdb/
lemma setup                                        # pulls the agent and prover images, tests the sandbox, checks your login
```

Offline machine: `./install.sh --load-images` loads the images shipped in `images/` (when the release has them) instead of pulling.

## First query

```bash
lemma optimize --db my.duckdb --sql "SELECT region, SUM(qty) AS q FROM orders GROUP BY region"
lemma duckdb my.duckdb -c "SELECT region, SUM(qty) AS q FROM orders GROUP BY region; SELECT * FROM lemma_last_query();"
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
