# Research Loop

An isolated sandboxed environment for running an autonomous, Karpathy-style optimization loop over analytial SQL queries. An optimizing agent iteratively writes a verified query implementation, which is checked against a Dafny formal specification, compiled to a native Rust binary, and benchmarked on real hardware.

> **Depends on** the `sql-transpiler` package from the `transpiler/` workspace member. Run `uv sync` at the project root before using.

## How It Works

```
Agent writes RunQuery → harness.py verifies (Dafny/Z3) → compiles (Rust/Cargo) → benchmarks → reports JSON
```

1. **Specification**: `harness.py` transpiles the target SQL query into a Dafny `MethodSpec` (the ground truth).
2. **Agent Code**: The agent writes an optimized `method RunQuery` into `agent_scratchpad.md`.
3. **Verification**: Dafny/Z3 formally proves that `RunQuery` satisfies `MethodSpec`. If the proof fails, the loop reports a failure immediately — no binary is produced.
4. **Compilation**: The verified Dafny code is translated to Rust and postprocessed to optimize performance (NB: this technically breaks the formal verification, see root README for details) and compiled to a release binary using `cargo build --release`.
5. **Benchmarking**: The binary is executed and wall-clock latency is measured in microseconds.
6. **Telemetry**: A JSON blob is emitted to stdout for the agent to interpret and iterate on.

## Running

```bash
# From the project root:
make loop                  # Query 1, 50k rows (default)

# Or directly:
uv run python research_loop/harness.py -q 1 --dataset-size 50000
uv run python research_loop/harness.py -q 4 --dataset-size 5000
```

Output:
```json
{
  "status": "SUCCESS",
  "proof_verified": true,
  "latency_us": 17618,
  "compiler_error": ""
}
```

## Files

| File | Purpose |
|---|---|
| `harness.py` | Orchestration script |
| `config.env` | Verification and compilation timeouts |
| `agent_scratchpad.md` | Legacy agent output (markdown); prefer `agent_workspace/runquery_agent.dfy` |
| `agent_workspace/` | Docker agent RW mount — body-only `runquery_agent.dfy` |
| `AGENT_SANDBOX.md` | Docker agent setup, env vars, loop/submit flow |
| `working_query-rust/` | Persistent Cargo workspace cache (keeps rebuild times ~0.8s) |

## Query Signatures

The `RunQuery` return type must match `MethodSpec` for the chosen query:

| Queries | Return Type |
|---|---|
| 1, 2, 3, 14 | `int` |
| 4, 5, 6, 11, 12 | `map<(int, string), int>` |
| 7, 8, 9, 10 | `map<(string, string, int), int>` |
| 13 | `map<(int, string, string), int>` |
| 15 | `map<string, int>` |

## Compilation Caching

- **First run / after `make clean`**: Detects missing `Cargo.toml`, triggers `dafny build --target:rs` to regenerate the full Cargo workspace (~15s).
- **All subsequent runs**: Uses `dafny translate rs` (source only) + incremental `cargo build --release` (~0.8s).
