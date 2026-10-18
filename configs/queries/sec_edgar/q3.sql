-- Source: https://raw.githubusercontent.com/SolidLao/GenDB/main/benchmarks/sec-edgar/queries.sql
-- Upstream repo commit 0ccf053ade163137775cd2e9c6e1288ea89d524b (2026-06-08; holdout/gendb_sec_edgar/SOURCE.md verified byte-identical); file last changed in 72619a92a87f702e7bb2ab3590db38e32cab1537 (2026-02-24). Verbatim below.
-- Q3: joins=2, agg=True, sub=True, tables=2, rows=100, time=228.0ms
SELECT s.name, s.cik, SUM(n.value) AS total_value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND s.fy = 2022 AND n.value IS NOT NULL
GROUP BY s.name, s.cik
HAVING SUM(n.value) > (
    SELECT AVG(sub_total) FROM (
        SELECT SUM(n2.value) AS sub_total
        FROM num n2
        JOIN sub s2 ON n2.adsh = s2.adsh
        WHERE n2.uom = 'USD' AND s2.fy = 2022 AND n2.value IS NOT NULL
        GROUP BY s2.cik
    ) avg_sub
)
ORDER BY total_value DESC
LIMIT 100;
