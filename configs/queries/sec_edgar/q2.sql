-- Source: https://raw.githubusercontent.com/SolidLao/GenDB/main/benchmarks/sec-edgar/queries.sql
-- Upstream repo commit 0ccf053ade163137775cd2e9c6e1288ea89d524b (2026-06-08; holdout/gendb_sec_edgar/SOURCE.md verified byte-identical); file last changed in 72619a92a87f702e7bb2ab3590db38e32cab1537 (2026-02-24). Verbatim below.
-- Q2: joins=2, agg=True, sub=False, tables=2, rows=100, time=98.0ms
-- Rewritten from correlated scalar subquery to decorrelated JOIN+GROUP BY.
-- PostgreSQL cannot decorrelate this, causing O(N^2) nested-loop scans on num (39M rows), can not finish within 10 minute timeout
-- DuckDB decorrelates automatically, but the explicit form is portable across all engines.
-- Original:
--   SELECT s.name, n.tag, n.value
--   FROM num n
--   JOIN sub s ON n.adsh = s.adsh
--   WHERE n.uom = 'pure' AND s.fy = 2022 AND n.value IS NOT NULL
--         AND n.value = (
--             SELECT MAX(n2.value)
--             FROM num n2
--             WHERE n2.tag = n.tag AND n2.adsh = n.adsh AND n2.uom = 'pure'
--         )
--   ORDER BY n.value DESC
--   LIMIT 100;
SELECT s.name, n.tag, n.value
FROM num n
JOIN sub s ON n.adsh = s.adsh
JOIN (
    SELECT adsh, tag, MAX(value) AS max_value
    FROM num
    WHERE uom = 'pure' AND value IS NOT NULL
    GROUP BY adsh, tag
) m ON n.adsh = m.adsh AND n.tag = m.tag AND n.value = m.max_value
WHERE n.uom = 'pure' AND s.fy = 2022 AND n.value IS NOT NULL
ORDER BY n.value DESC, s.name, n.tag
LIMIT 100;
