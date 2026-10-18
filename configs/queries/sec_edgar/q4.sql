-- Source: https://raw.githubusercontent.com/SolidLao/GenDB/main/benchmarks/sec-edgar/queries.sql
-- Upstream repo commit 0ccf053ade163137775cd2e9c6e1288ea89d524b (2026-06-08; holdout/gendb_sec_edgar/SOURCE.md verified byte-identical); file last changed in 72619a92a87f702e7bb2ab3590db38e32cab1537 (2026-02-24). Verbatim below.
-- Q4: joins=3, agg=True, sub=False, tables=4, rows=500, time=420.4ms
SELECT s.sic, t.tlabel, p.stmt,
       COUNT(DISTINCT s.cik) AS num_companies,
       SUM(n.value) AS total_value,
       AVG(n.value) AS avg_value
FROM num n
JOIN sub s ON n.adsh = s.adsh
JOIN tag t ON n.tag = t.tag AND n.version = t.version
JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version
WHERE n.uom = 'USD' AND p.stmt = 'EQ'
      AND s.sic BETWEEN 4000 AND 4999
      AND n.value IS NOT NULL AND t.abstract = 0
GROUP BY s.sic, t.tlabel, p.stmt
HAVING COUNT(DISTINCT s.cik) >= 2
ORDER BY total_value DESC
LIMIT 500;
