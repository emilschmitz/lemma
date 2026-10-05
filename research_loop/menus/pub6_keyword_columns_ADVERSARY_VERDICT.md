# Adversary verdict: Rust-keyword columns in the bulk exporter (commit 57178eb)

Verdict: **SOUND** (no code change needed; no fixes made).

## What I ran
- `uv run pytest tests/test_keyword_columns_export.py tests/test_export_bulk_differential.py tests/test_decl_query_measure.py -q`: 60 passed.
- Throwaway differential (scratchpad `diff_old_new.py`): the exporter at 6ccdaf0 (`git show 6ccdaf0:research_loop/decl_query_measure.py`, temp copy, deleted afterwards) vs the new `_export_table`, on 400 random non-keyword schemas (names such as `x__y`, `r_abstract`, `abstract_`, `Id`, `r`; bigint/varchar/integer/double; random nullable columns, random NULLs, plain/`__valid`/`__dict` fields, deliberate type mismatches and a nonexistent field). Result: 400/400 identical, 274 byte-identical blobs and 126 identical error messages (same exception text).

## Findings
(a) Non-keyword behavior: unchanged. `rust_ident` only emits an `r#` prefix for Rust keywords, so the old `removeprefix("r#")` was a no-op for every non-keyword field the emitter produces. Only difference: a hypothetical non-keyword field spelled `r#foo` was silently mapped to `foo` before and is now refused. That is stricter, and the emitter never produces it.

(b) Collisions / key mismatch:
- `rust_ident("abstract")` = `r#abstract`; `rust_ident("r#abstract")` = `r_abstract` (the `#` becomes `_`), `rust_ident("Abstract")` = `r#abstract` (same column anyway, names are casefolded). `abstract_` stays `abstract_`. No new collision between a keyword and a non-keyword column.
- The emitter writes `pub {rust_ident(col)}__dict` / `__valid` (emit_surface.py 1634/1638), i.e. `r#match__dict`. The new lookup strips the suffix and gets `r#match`, which is exactly the `by_ident` key and exactly the `code_fields` key stored for the plain field `r#match`. Plain, `__valid` and `__dict` keys are consistent. Tested end to end (tests/test_keyword_columns_export.py).
- Pre-existing, not introduced here: `by_ident` is non-injective for other reasons (`a-b` and `a_b` both normalize to `a_b`; a column literally named `x__valid`/`x__dict` is misrouted as a suffix field; `r#abstract__valid` and a column `abstract__valid` are the same Rust identifier). Last-writer-wins in the dict comprehension could export the wrong column in those odd cases, identical in old and new code. Worth a fail-loud duplicate check in a later change, out of scope here.

(c) Plan-before-export: `_plan_table` only reads the model (`lookup_table`, `is_nullable`), consumes no state, and touches no connection. Table order is preserved (dict insertion order). Differences: a bad plan now raises before `dest.mkdir` and before the DuckDB connect, so a bad schema field no longer creates the output directory or opens the DB; error type is still `ValueError` with the same message. A duplicate struct suffix would collapse into one plan (old code exported it twice to the same file); the spec never emits that. No error is hidden: errors are the same set, raised earlier.

(d) Validation: nothing relaxed. All checks (field exists, type match, nullable for `__valid`, String column for `__dict`) are unchanged; the only edit makes the name match stricter. A `__dict` with no preceding code field still raises KeyError from `code_fields[base]`, as before.

(e) Differential results above. The test `test_a_bad_field_in_a_later_table_fails_before_any_table_is_exported` pins the ordering claim (monkeypatches `_export_planned`, asserts nothing exported).
