# verus-transpiler

SQL → Verus `MethodSpec` (+ RunQuery skeleton for the agent).

```python
from verus_transpiler import transpile_sql_to_verus
```

Pipeline contract: root `AGENTS.md`. Research loop: `research_loop/README.md`.
Unsupported SQL fails with `UnsupportedContractError` (prefer failure over mocks).
