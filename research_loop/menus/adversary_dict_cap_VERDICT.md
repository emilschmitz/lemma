# Adversary verdict: dictionary-length cap from catalog max_distinct

Verdict: ACCEPT (no fixes needed).

1. Wrong cap fails loudly. The only loader is assemble.py main (_read_column_prelude + _runtime_checks); the new conjunct gets an assert! on dict.len(). Any valid_cols conjunct the loader cannot check raises ValueError (assemble.py line ~358), so it cannot be silently dropped (test covers this). The exporter (decl_query_measure) does not check it itself, but every timed/proved run goes through the binary's load, which panics.
2. Agent cannot touch it: cap comes from the host catalog, valid_cols/loader are outside AGENT_EDIT/helpers and are re-emitted by the host.
3. Semantics: dictionary = distinct non-NULL values (CAST AS VARCHAR, GROUP BY), equal to COUNT(DISTINCT) used by check.py; NULL cells reuse code 0, adding no entry; no unused entries. Only oddity: a nullable all-NULL column gets dict [""] (len 1) so a declared cap of 0 would fail at load; loud, not unsound, and a cap of 0 is unrealistic.
4. Code width (code_type) and cap use the same lookup; cap<=256 => u8 and the exporter refuses len > 2**bits. Consistent.
5. No code bugs found; loader/string_dict/group_close tests pass.
