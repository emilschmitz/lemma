-- Source: https://raw.githubusercontent.com/SolidLao/GenDB/main/benchmarks/sec-edgar/queries.sql
-- Upstream repo commit 0ccf053ade163137775cd2e9c6e1288ea89d524b (2026-06-08; holdout/gendb_sec_edgar/SOURCE.md verified byte-identical); file last changed in 72619a92a87f702e7bb2ab3590db38e32cab1537 (2026-02-24). Verbatim below.
-- Q24: joins=1, agg=True, sub=False, tables=2, rows=2, time=534.9ms
-- Rewritten from NOT EXISTS correlated subquery to LEFT JOIN anti-join.
-- MonetDB cannot decorrelate NOT EXISTS, causing it to hang on num (39M) x pre (9.6M).
-- The LEFT JOIN + IS NULL form is semantically equivalent and portable across all engines.
-- Original:
--   SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
--   FROM num n
--   WHERE n.uom = 'USD' AND n.ddate BETWEEN 20230101 AND 20231231
--         AND n.value IS NOT NULL
--         AND NOT EXISTS (
--             SELECT 1 FROM pre p
--             WHERE p.tag = n.tag AND p.version = n.version AND p.adsh = n.adsh
--         )
--   GROUP BY n.tag, n.version
--   HAVING COUNT(*) > 10
--   ORDER BY cnt DESC
--   LIMIT 100;
SELECT n.tag, n.version, COUNT(*) AS cnt, SUM(n.value) AS total
FROM num n
LEFT JOIN pre p ON n.tag = p.tag AND n.version = p.version AND n.adsh = p.adsh
WHERE n.uom = 'USD' AND n.ddate BETWEEN 20230101 AND 20231231
      AND n.value IS NOT NULL
      AND p.adsh IS NULL
GROUP BY n.tag, n.version
HAVING COUNT(*) > 10
ORDER BY cnt DESC
LIMIT 100;
