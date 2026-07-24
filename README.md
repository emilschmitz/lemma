# Lemma

Verified query synthesis: SQL is transpiled to a Verus `MethodSpec`, an agent writes an optimized
`run_query`, Verus proves correctness, and the result is compiled to native Rust. H1 path agents
optimize **`SESSION_HOT_US`** on DuckDB-backed layouts (`db_extension_*`). A legacy OpenRouter
agent in `db_extension/` still splices Dafny bodies pending Verus migration.

Inspired by https://arxiv.org/pdf/2603.02081.

https://github.com/user-attachments/assets/7f7891c7-5ef6-406b-882b-8e01134ed37c

## Quick start (Verus harness)

```bash
./scripts/setup.sh
uv run python research_loop/harness.py -q 1 --dataset-size 50000
uv run python research_loop/benchmark_verified.py --smoke
```

Requires [Verus](research_loop/scripts/install_verus.md), [uv](https://docs.astral.sh/uv/), and Rust.

### H1 path measure

```bash
export LEMMA_DUCKDB_LIB_DIR="$PWD/build/libduckdb"
db_extension_paths/check_mem.sh uv run python db_extension_paths/measure_e2e_paths.py
```

See `DB_EXTENSION_PATHS.md` for copy/chunk/lease/storage paths.

### Legacy OpenRouter agent (Dafny bodies)

```bash
docker build -t lemma-agent:latest -f docker/agent/Dockerfile .
MOCK_AGENT=0 OPENROUTER_API_KEY=sk-or-... uv run python -m db_extension.run_optimizer "SELECT ..."
```

See `db_extension/AGENT.md`. Dafny verify/compile uses `research_loop/dafny_legacy/harness.py`.

## Layout

| Path | Role |
|------|------|
| `verus_transpiler/` | SQL → Verus transpiler |
| `research_loop/` | Verus verify, compile, benchmarks |
| `research_loop/dafny_legacy/` | Dafny harness (OpenRouter agent only) |
| `db_extension/` | DuckDB extension + OpenRouter agent |
| `db_extension_paths/` | Sidecar copy path (`lemma_copy`) |
| `db_extension_runtime/` | Chunk API (`lemma_chunk`) |
| `db_extension_lease/` | Pin/lease (`lemma_lease`) |
| `db_extension_storage/` | Storage scan (`lemma_storage`) |
| `holdout/` | Leakage-resistant eval (GenDB SEC, etc.) |

## Requirements

- Python 3.11+, [uv](https://docs.astral.sh/uv/)
- [Verus](https://github.com/verus-lang/verus) — primary verification
- [Rust/Cargo](https://rustup.rs/)
- Dafny 4.x — only for legacy OpenRouter agent path
- **g++**, **make**, **git**, **curl**, **unzip** — for `./scripts/setup.sh`
