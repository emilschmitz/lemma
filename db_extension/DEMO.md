# Lemma interactive demo

## Live demo (real agent)

```bash
chmod +x scripts/demo.sh
./scripts/demo.sh
```

Right pane (split terminal):

```bash
./scripts/demo_view/follow-agent-log.sh
```

This script:

1. Clears **all** cached optimized queries
2. Sets `LEMMA_DEMO=1`, `MOCK_AGENT=0`, `LEMMA_DATASET_SIZE=100000`
3. Drops you into the **official DuckDB CLI** (downloaded to `build/duckdb` on first run)

Requires the Cursor \`agent\` CLI on PATH (same auth as running \`agent\` in your shell).

## Mock demo (offline / no API key)

```bash
./scripts/mockdemo.sh
```

Same UX, but seeds a hardcoded RunQuery body (`MOCK_AGENT=1`, 2M rows, no LLM).

Override query: `DEMO_QUERY_ID=5 ./scripts/demo.sh`

## In the DuckDB shell

```sql
-- (1) Vanilla (DuckDB prints its own timing after the result)
SELECT SUM(...) FROM lineorder_flat WHERE ...;

-- (2) Lemma (demo steps on stdout, then result)
SELECT lemma('SELECT SUM(...) FROM lineorder_flat WHERE ...');

-- (3) Run (2) again → cached 💾 path
```

## Env toggles

| Variable | `demo.sh` | `mockdemo.sh` |
|----------|-----------|---------------|
| `LEMMA_DEMO` | on | on |
| `MOCK_AGENT` | **0** (real agent) | **1** (fixture) |
| `LEMMA_DATASET_SIZE` | 100,000 | 2,000,000 |
| `LEMMA_LOG_LEVEL` | WARN | WARN |

Production `config.env` keeps demo **off**.

## Re-run fresh pipeline

Run the script again — it clears cache every time.
