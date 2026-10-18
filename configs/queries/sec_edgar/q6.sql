-- Source: https://raw.githubusercontent.com/SolidLao/GenDB/main/benchmarks/sec-edgar/queries.sql
-- Upstream repo commit 0ccf053ade163137775cd2e9c6e1288ea89d524b (2026-06-08; holdout/gendb_sec_edgar/SOURCE.md verified byte-identical); file last changed in 72619a92a87f702e7bb2ab3590db38e32cab1537 (2026-02-24). Verbatim below.
-- Q6: joins=2, agg=True, sub=False, tables=4, rows=200, time=445.9ms
SELECT s.name, p.stmt, n.tag, p.plabel,
       SUM(n.value) AS total_value, COUNT(*) AS cnt
FROM num n
JOIN sub s ON n.adsh = s.adsh
JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version
WHERE n.uom = 'USD' AND p.stmt = 'IS' AND s.fy = 2023
      AND n.value IS NOT NULL
GROUP BY s.name, p.stmt, n.tag, p.plabel
ORDER BY total_value DESC
LIMIT 200;
