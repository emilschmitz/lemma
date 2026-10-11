# Data profile

Exact statistics of the database for this query, computed by SQL on the data (no sampling, no query plan). They describe the data as it is;
they are not assumptions. Whatever you prove must hold for every database that satisfies the assumption package, not only for these numbers.

## Tables

| table | alias | rows |
|---|---|---|
| lineorder | lineorder | 6,001,171 |
| date | date | 2,556 |
| part | part | 200,000 |
| supplier | supplier | 2,000 |

## Columns used

### Columns of lineorder (lineorder, 6,001,171 rows)

| column | type | min | max | NULL fraction | distinct |
|---|---|---|---|---|---|
| lo_orderdate | INTEGER | 19920101 | 19980802 | 0 | 2,406 |
| lo_partkey | INTEGER | 1 | 200000 | 0 | 200,000 |
| lo_revenue | INTEGER | 81360 | 10474950 | 0 | 3,345,588 |
| lo_suppkey | INTEGER | 1 | 2000 | 0 | 2,000 |

### Columns of date (date, 2,556 rows)

| column | type | min | max | NULL fraction | distinct |
|---|---|---|---|---|---|
| d_datekey | INTEGER | 19920101 | 19981230 | 0 | 2,556 |
| d_year | INTEGER | 1992 | 1998 | 0 | 7 |

### Columns of part (part, 200,000 rows)

| column | type | min | max | NULL fraction | distinct |
|---|---|---|---|---|---|
| p_brand1 | VARCHAR | MFGR#111 | MFGR#559 | 0 | 1,000 |
| p_category | VARCHAR | MFGR#11 | MFGR#55 | 0 | 25 |
| p_partkey | INTEGER | 1 | 200000 | 0 | 200,000 |

### Columns of supplier (supplier, 2,000 rows)

| column | type | min | max | NULL fraction | distinct |
|---|---|---|---|---|---|
| s_region | VARCHAR | AFRICA | MIDDLE EAST | 0 | 5 |
| s_suppkey | INTEGER | 1 | 2000 | 0 | 2,000 |

## Filters (single-table conditions)

| table | condition | rows matching | selectivity |
|---|---|---|---|
| part | `p_category = 'MFGR#12'` | 7,883 / 200,000 | 0.039415 |
| supplier | `s_region = 'AMERICA'` | 378 / 2,000 | 0.189 |

## Joins (column equalities)

| join | distinct keys left (all / after filters) | distinct keys right (all / after filters) | keys in common after filters |
|---|---|---|---|
| lineorder.lo_orderdate = date.d_datekey | 2,406 / 2,406 | 2,556 / 2,556 | 2,406 |
| lineorder.lo_partkey = part.p_partkey | 200,000 / 200,000 | 200,000 / 7,883 | 7,883 |
| lineorder.lo_suppkey = supplier.s_suppkey | 2,000 / 2,000 | 2,000 / 378 | 378 |

## Rows after all joins and filters

Joined rows: 44,575.

| table | rows of the table that still match | of |
|---|---|---|
| lineorder | 44,575 | 6,001,171 |
| date | 2,406 | 2,556 |
| part | 7,857 | 200,000 |
| supplier | 378 | 2,000 |

## Group keys

| key | distinct values in its table | distinct values after filters and joins |
|---|---|---|
| `d_year` | 7 | 7 |
| `p_brand1` | 1,000 | 40 |

Result groups (before LIMIT): 280.

## Result

Result rows: 280.
