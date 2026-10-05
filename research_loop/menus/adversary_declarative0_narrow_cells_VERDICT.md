# Adversary verdict: LEMMA_NARROW_CELLS for integers and DECIMAL columns (commits 0c200cd, 4dd7ff0)

Reviewer: separate manual-adversary Sonnet subagent, 2026-10-05. Verdict: **ACCEPT WITH FIXES**. The flag stays opt-in (default off).

## What was tried

1. Width and cap boundaries through the exporter and through the generated binary (stub body, `verus_guarded.sh`):
   BIGINT cap 2^15 as i16: 32767 and -32768 pack, 32768 and -32769 are refused (`cannot pack ... as i16`); `nn` 128 as i8 refused;
   DECIMAL(10,2) 327.67 packs, 327.68 refused; DECIMAL(12,4) 3.2767 and -3.2768 pack, 3.2768 refused. `struct.pack` raises on overflow: nothing wraps.
   Generated binary: a DECIMAL cell at the cap (stored 1000 with cap 1000), at -cap, or above the cap but inside the width (327.67) panics
   (`value outside the catalog bound 999`); 9.99 and -9.99 pass.
2. Wide spec against narrow spec for 30 queries (sums, products, `a > 100000` on an i16 column, BETWEEN, IN, mixed widths, CASE with a literal 70000,
   MIN/MAX, AVG, GROUP BY on narrowed columns, joins narrow/narrow and i8/wide, decimal literals, nullable). The only difference in the emitted spec text is
   `Vec<i64>` becoming `Vec<iN>` in `Cols_t` (and an OutRow field type where a projected column is an output field). Every predicate and arithmetic
   expression is byte-identical (cells are read `as int`, literals are ints). No answer can change.
3. Nullable narrowed columns: i8 plus `__valid` vector, NULL default 0 fits; the NULL tests pass under the flag.
4. Cap smaller than the DuckDB type: BIGINT with cap 2^15 becomes i16 and a larger value is refused at export; a cap larger than the width picks the wider type.
5. Tests with `LEMMA_NARROW_CELLS=1`: `test_declarative_narrow_cells.py`, `test_declarative_nulls.py`, `test_declarative_emit.py` pass. Three failures in
   `test_nulls_adversary.py::test_what_the_rewrite_cannot_state_is_refused` (ORDER BY LIMIT, DISTINCT, GROUP BY ORDER BY) are stale tests after the NULLS-ordering
   merge; they fail identically with the flag off and on main. They do not hardcode i64.

## Finding A (open, pre-existing in both modes)

`valid_cols` and the generated runtime asserts carry **no** conjunct for an INTEGER column's `max_value_exclusive` (only DECIMAL gets one). A BIGINT column with
cap 1000 and a value of 5000 loads. Narrowing adds a hard type-width guard (loud refusal) but does not enforce the stated integer cap; the integer cap is a claim
`check.py` measures. Not unsound for the spec (cells are read as ints, the width is a stronger fact), but a sum bound derived from the cap relies on an unchecked cap
exactly as in wide mode. Fix applied here: the `_narrowed` docstring now says what is enforced (commit after 4dd7ff0). Still open: emit and assert the integer cap
conjunct in both modes.

## Recommendation on the default

Do not flip it yet. Before default: (1) resolve Finding A, (2) fix the three stale tests, (3) boundary regression tests (added: decimal boundaries at scale 2 and 4,
refusal beyond the width), (4) one end-to-end agent body on an i16 column with a literal larger than the width to see the agent-side compile behaviour.
