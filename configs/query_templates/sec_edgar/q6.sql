-- params: p1 VARCHAR, p2 VARCHAR, p3 BIGINT
-- Lifted from configs/queries/sec_edgar/q6.sql by declarative_spec.lift.lift_constants (schema and structural catalog of sec_edgar_dec.duckdb); the query's own values: $p1 = USD, $p2 = IS, $p3 = 2023
-- Source: https://raw.githubusercontent.com/SolidLao/GenDB/main/benchmarks/sec-edgar/queries.sql
-- Upstream repo commit 0ccf053ade163137775cd2e9c6e1288ea89d524b (2026-06-08; holdout/gendb_sec_edgar/SOURCE.md verified byte-identical); file last changed in 72619a92a87f702e7bb2ab3590db38e32cab1537 (2026-02-24). Below: that query normalized (declarative_spec.sql_text.normalize_sql) with its lifted constants as parameters.
-- Q6: joins=2, agg=True, sub=False, tables=4, rows=200, time=445.9ms
SELECT s.name, p.stmt, n.tag, p.plabel, SUM(n.value) AS total_value, COUNT(*) AS cnt FROM num n JOIN sub s ON n.adsh = s.adsh JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version WHERE n.uom = $p1 AND p.stmt = $p2 AND s.fy = $p3 AND n.value IS NOT NULL GROUP BY s.name, p.stmt, n.tag, p.plabel ORDER BY total_value DESC LIMIT 200
