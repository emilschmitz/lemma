-- Local tiny SEC e2e queries (GenDB-style -- Qn: labels for parse_sql_file)

-- Q1: single-table GROUP BY (historically proveable)
SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile
ORDER BY cnt DESC;

-- Q2: EXISTS + support table (pin must not put stmt on num)
SELECT DISTINCT n.tag, n.version, COUNT(*) AS cnt
FROM num n
WHERE n.uom = 'shares' AND n.value IS NOT NULL
      AND EXISTS (SELECT 1 FROM pre p WHERE p.tag = n.tag AND p.version = n.version AND p.stmt = 'IS')
GROUP BY n.tag, n.version;

-- Q3: uncorrelated IN + inner GROUP BY / HAVING (MethodSpec fold)
SELECT n.tag, n.version
FROM num n
WHERE n.uom = 'USD' AND n.value IS NOT NULL
      AND n.tag IN (
          SELECT tag FROM pre
          WHERE stmt = 'IS'
          GROUP BY tag
          HAVING COUNT(*) > 1
      )
LIMIT 20;
