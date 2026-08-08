# Phase 0 — GCP machine bring-up (no agent spend)

Fresh VM setup for GenDB-comparable Lemma experiments. Same product path as local dev:
DuckDB + `lemma_lease` + host MCP measure with full harvest under `research_loop/runs/<id>/`.

## 1. Clone and install

```bash
git clone https://github.com/emilschmitz/lemma.git
cd lemma
uv sync
```

## 2. Build DuckDB + lease H1 e2e

```bash
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
# Build libduckdb + pin-session DB (see db_extension_lease README / AGENTS.md)
cd db_extension_lease/rust_bridge && cargo build --release
cd ../..
```

Verify binary:

```bash
ls db_extension_lease/rust_bridge/target/release/lemma_lease_h1_e2e
```

## 3. TPC-H SF10 (paper subset)

```bash
mkdir -p build/tpch_sf10
duckdb build/tpch_sf10/tpch_sf10.duckdb <<'SQL'
INSTALL tpch;
LOAD tpch;
CALL dbgen(sf=10);
SQL
export LEMMA_DUCKDB_PATH="$PWD/build/tpch_sf10/tpch_sf10.duckdb"
export LEMMA_WORKLOAD=tpch
```

Paper queries: Q1, Q3, Q6, Q9, Q18. (SF1 fixtures under `data/tpch-sf1/` are for local tiny runs only.)


## 4. SEC EDGAR holdout data

```bash
cd holdout/gendb_sec_edgar
bash setup_data.sh 3          # 2022–2024 quarters (~5 GB)
uv run python load_data.py    # loads into duckdb/sec_edgar.duckdb
cd ../..
```

## 5. Fresh diversity holdout queries

```bash
cd holdout/gendb_sec_edgar
bash make_lemma_holdout.sh    # LEMMA_HOLDOUT_SEED default 20260808
# → queries_lemma_holdout.sql + queries_lemma_holdout.seed.txt
cd ../..
```

## 6. Experiment env

```bash
export LEMMA_EXPERIMENT=1
export LEMMA_MEASURE_PATH=auto   # lease when binary + scan.duckdb exist
export LEMMA_DUCKDB_PATH=build/duckdb_pin_session/scan.duckdb
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
```

`LEMMA_EXPERIMENT=1` enables research harvest automatically (no separate `LEMMA_RESEARCH_LOG=1`).

## 7. Smoke lease measure

```bash
export LEMMA_DUCKDB_PATH=build/duckdb_pin_session/scan.duckdb
PYTHONPATH=. uv run python -c \
  "from db_extension.agent.lease_measure import run_lease_h1_measure; print(run_lease_h1_measure())"
```

## 8. Smoke optimizer (mock off, experiment on)

```bash
export PYTHONPATH=$PWD
export LEMMA_EXPERIMENT=1
export LEMMA_WORKLOAD=holdout
export MOCK_AGENT=0
export LEMMA_ALLOW_DUCKDB_FALLBACK=0
# OPENROUTER_API_KEY or LEMMA_AGENT_BACKEND=cli + CURSOR_API_KEY for a real agent
PYTHONPATH=. uv run python -m db_extension.run_optimizer \
  "SELECT SUM(amount) FROM scan_skew WHERE event_date BETWEEN 19960101 AND 19961231"
```

Without an API key this must **exit non-zero** with `CUSTOM_PIPELINE_FAILED` (fail loud).
Harvest dir: `research_loop/runs/<timestamp>_q<id>_<hex>/` with `meta/hardware.json`, `history.json`, harness logs.
