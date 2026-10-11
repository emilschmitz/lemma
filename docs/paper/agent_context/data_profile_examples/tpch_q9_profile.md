# Data profile

Exact statistics of the database for this query, computed by SQL on the data (no sampling, no query plan). They describe the data as it is;
they are not assumptions. Whatever you prove must hold for every database that satisfies the assumption package, not only for these numbers.

## Tables

| table | alias | rows |
|---|---|---|
| part | part | 200,000 |
| supplier | supplier | 10,000 |
| lineitem | lineitem | 6,001,215 |
| partsupp | partsupp | 800,000 |
| orders | orders | 1,500,000 |
| nation | nation | 25 |

## Columns used

### Columns of part (part, 200,000 rows)

| column | type | min | max | NULL fraction | distinct |
|---|---|---|---|---|---|
| p_name | VARCHAR | almond antique blue royal burnished | yellow white seashell lavender black | 0 | 199,997 |
| p_partkey | BIGINT | 1 | 200000 | 0 | 200,000 |

### Columns of supplier (supplier, 10,000 rows)

| column | type | min | max | NULL fraction | distinct |
|---|---|---|---|---|---|
| s_nationkey | INTEGER | 0 | 24 | 0 | 25 |
| s_suppkey | BIGINT | 1 | 10000 | 0 | 10,000 |

### Columns of lineitem (lineitem, 6,001,215 rows)

| column | type | min | max | NULL fraction | distinct |
|---|---|---|---|---|---|
| l_discount | DECIMAL(15,2) | 0.00 | 0.10 | 0 | 11 |
| l_extendedprice | DECIMAL(15,2) | 901.00 | 104949.50 | 0 | 933,900 |
| l_orderkey | BIGINT | 1 | 6000000 | 0 | 1,500,000 |
| l_partkey | BIGINT | 1 | 200000 | 0 | 200,000 |
| l_quantity | DECIMAL(15,2) | 1.00 | 50.00 | 0 | 50 |
| l_suppkey | BIGINT | 1 | 10000 | 0 | 10,000 |

### Columns of partsupp (partsupp, 800,000 rows)

| column | type | min | max | NULL fraction | distinct |
|---|---|---|---|---|---|
| ps_partkey | BIGINT | 1 | 200000 | 0 | 200,000 |
| ps_suppkey | BIGINT | 1 | 10000 | 0 | 10,000 |
| ps_supplycost | DECIMAL(15,2) | 1.00 | 1000.00 | 0 | 99,865 |

### Columns of orders (orders, 1,500,000 rows)

| column | type | min | max | NULL fraction | distinct |
|---|---|---|---|---|---|
| o_orderdate | DATE | 1992-01-01 | 1998-08-02 | 0 | 2,406 |
| o_orderkey | BIGINT | 1 | 6000000 | 0 | 1,500,000 |

### Columns of nation (nation, 25 rows)

| column | type | min | max | NULL fraction | distinct |
|---|---|---|---|---|---|
| n_name | VARCHAR | ALGERIA | VIETNAM | 0 | 25 |
| n_nationkey | INTEGER | 0 | 24 | 0 | 25 |

## Filters (single-table conditions)

| table | condition | rows matching | selectivity |
|---|---|---|---|
| part | `p_name LIKE '%green%'` | 10,664 / 200,000 | 0.05332 |

## Joins (column equalities)

| join | distinct keys left (all / after filters) | distinct keys right (all / after filters) | keys in common after filters |
|---|---|---|---|
| supplier.s_suppkey = lineitem.l_suppkey | 10,000 / 10,000 | 10,000 / 10,000 | 10,000 |
| partsupp.ps_suppkey = lineitem.l_suppkey | 10,000 / 10,000 | 10,000 / 10,000 | 10,000 |
| partsupp.ps_partkey = lineitem.l_partkey | 200,000 / 200,000 | 200,000 / 200,000 | 200,000 |
| part.p_partkey = lineitem.l_partkey | 200,000 / 10,664 | 200,000 / 200,000 | 10,664 |
| orders.o_orderkey = lineitem.l_orderkey | 1,500,000 / 1,500,000 | 1,500,000 / 1,500,000 | 1,500,000 |
| supplier.s_nationkey = nation.n_nationkey | 25 / 25 | 25 / 25 | 25 |

## Rows after all joins and filters

Joined rows: 319,404.

| table | rows of the table that still match | of |
|---|---|---|
| part | 10,664 | 200,000 |
| supplier | 9,865 | 10,000 |
| lineitem | 319,404 | 6,001,215 |
| partsupp | 42,624 | 800,000 |
| orders | 287,490 | 1,500,000 |
| nation | 25 | 25 |

## Group keys

| key | distinct values in its table | distinct values after filters and joins |
|---|---|---|
| `n_name` | 25 | 25 |
| `EXTRACT(YEAR FROM o_orderdate)` | 7 | 7 |

Result groups (before LIMIT): 175.

## Result

Result rows: 175.
