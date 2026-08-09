# Verification chain

Lemma ties SQL semantics to native execution through a fixed pipeline. The agent optimizes only the exec hot path; the host owns MethodSpec, Trusted view relations, and admission.

## 1. Transpile → MethodSpec (+ Trusted in `spec.rs`)

SQL + schema are transpiled to Verus. The host writes `context/ro/spec.rs` containing:

- `pub open spec fn method_spec(...)` — recursive open-spec fold (ground truth; **spec types** like `Map<…>`, `Seq<…>`, `u64`)
- `valid_cols` and query-projected `Cols`
- Trusted bridges (`hashmap_*_view`, `vec_*_view`, `agg_*`, …) relating **exec** types (`HashMap`, `Vec`, scalars) to spec types

The agent **reads** `spec.rs`; it does not own or redefine MethodSpec or Trusted helpers.

## 2. Agent edits `runquery_agent.rs` (AGENT_EDIT region only)

The host emits `runquery_agent.rs` with markers and **hints** (not locks) for a common exec encoding:

```
// AGENT_EDIT_START
// MethodSpec returns: Map<…>
// Trusted exec↔spec views in context/ro/spec.rs …
pub exec fn run_query(...) -> (res: HashMap<…>)   // agent chooses exec type
    requires valid_cols(cols),
    ensures hashmap_*_view(res@) == method_spec(cols),   // or direct == for scalars
{ ... }
// AGENT_EDIT_END
```

The agent may edit the **entire** `pub exec fn run_query` between those markers (signature, `requires`, `ensures`, body). Everything outside the markers is host-owned and fingerprinted.

Legacy workspaces may still use `AGENT_BODY_START`/`END` (body-only); new templates prefer `AGENT_EDIT`.

## 3. Admission (spec ↔ exec contract, no trust expansion)

`research_loop/admit_agent_runquery.py` validates the edit region before assembly:

| Check | Purpose |
|-------|---------|
| Fingerprint outside markers | Detect tampering with host shell / imports |
| Exactly one `pub exec fn run_query` | No extra entry points |
| `requires` includes `valid_cols(cols)` | Keep column bounds |
| `ensures` is `res == method_spec(cols)` **or** `VIEW(res@) == method_spec(cols)` for a Trusted `VIEW` in this query's spec | No `ensures true`, `|| true`, or invented views |
| Return type matches admitted relation | Direct `==`: exec type must equal MethodSpec `T` (scalars only; ghost `Map`/`Seq<char>` must use a view). View form: `VIEW` in `trusted_view_menu`, `exec_ret` matches agent `->` type |
| Forbidden: `external_body`, `arbitrary`, `assume`, `unimplemented!`, new `spec fn method_spec`, `mod`, … | No trust expansion |
| Non-empty executable body | No vacuous stubs |

`allowed_contract_from_method_spec` remains a **template hint** only; admission does not lock a single host-prescribed `rust_ret` / ensures line.

`proof`, `assert`, and `invariant` are allowed inside the admitted function.

## 4. Assemble: host spec + admitted `run_query` + load/main

The host splices the admitted `run_query` into the verified program with `spec.rs`, native bridges, and benchmark `main`. `format_result` in `main` uses the **admitted exec return type** when available (`AdmitResult.rust_ret`); `ret_type` still drives Trusted boundary helpers and loaders.

The agent never assembles the full crate.

## 5. Verus verify

Verus must prove `run_query` satisfies the admitted `ensures` against `method_spec` (and any proof obligations in the body). Failure is loud — no silent DuckDB fallback for “verified” success.

## 6. Native exec

After proof, the same `run_query` body runs natively for benchmarking (with Trusted view bridges at the spec/exec boundary only).

## Threat model

**Agent can:**

- Edit the full `run_query` function inside `AGENT_EDIT` markers
- Choose exec return encoding among admitted Trusted views for MethodSpec `T`
- Choose algorithms, loop order, and local proof steps
- Call host Trusted helpers from `spec.rs` (e.g. `agg_*`, views)

**Agent cannot:**

- Change host text outside markers (fingerprint rejection)
- Weaken `ensures` (`ensures true`, `|| true`, wrong view, missing `method_spec(cols)`)
- Use direct `res == method_spec(cols)` when MethodSpec returns ghost `Map` / `Seq<char>` (must use a Trusted view)
- Invent Trusted views or redefine `method_spec`
- Add Trusted surfaces (`external_body`, new `spec fn`, …)
- Skip proof via `assume`, `arbitrary`, or `unimplemented!`
- Introduce new modules or unsafe/extern at the edit boundary

Freedom is in the **implementation** and choice among **admitted** exec↔spec encodings — not in dropping equivalence to MethodSpec.

**Host guarantees:**

- MethodSpec is the semantic ground truth (spec types)
- Trusted relations in `spec.rs` define legal exec encodings
- Admission runs before every assemble / MCP validate / measure path that uses `AGENT_EDIT`
- Prefer failure over mocks (`AGENTS.md` pipeline contract)
