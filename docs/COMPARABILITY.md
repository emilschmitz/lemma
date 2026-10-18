# Comparing with DuckDB the way GenDB did

GenDB (arXiv 2603.02081, section 4.1): hot runs, the whole database cached in RAM, DuckDB with its own automatic indexes
(primary keys, zonemaps) and no hand tuning, all cores of the machine, execution time of hot runs reported per query.
Generation time and cost are reported separately.

What we do, and where it differs:

| Item | GenDB | Lemma |
|---|---|---|
| Hot run | repeated runs, data in RAM | median of 9 timed runs after a warm-up, data already in memory |
| Cores | 2 x Xeon Gold 5218, 32 physical cores, DuckDB default | all 8 threads of this laptop (`LEMMA_DUCK_THREADS`, default 8) |
| DuckDB memory | 384 GB, never limiting | `LEMMA_DUCK_MEMORY_LIMIT`, default 3GB: it can make DuckDB spill and favours us. For TPC-H/SSB at SF1 set it to 8GB so DuckDB is never limited. |
| DuckDB indexes | automatic only | automatic only, none added |
| DuckDB version | v1.4.4 | 1.5.6 (installed here; not matched) |
| Load / layout cost | generated storage not in the hot time | column load / export not in the hot time; reported separately with the break-even |
| Filtering (pushdown, agent scans) | n/a | with `pushdown` / `agent_scan` on (the default) DuckDB applies the pushed predicate during the export, outside the binary's hot time, while DuckDB's own reference time includes its filter. The binary's time is then labelled `hot, excludes scan/filter` (`hot_label`, also in every RESULT line) and is NOT a reported number. The reported number is the in-DuckDB end-to-end measure (`measure_in_duckdb`, `reported_measure`): `lemma_query` scans the needed columns in DuckDB with the pushed predicate applied inside the scan, hands them over, checks them and runs the proved `run_query`, interleaved with DuckDB on the same connection. A body that calls `scan_where` cannot run in-DuckDB yet (refused at install), so it has no reportable number. With both flags off the binary's official rounds are the reported number, as before |
| Generation cost | minutes and dollars per query | proof + agent minutes per query, reported per query including failed attempts |
| Hardware | 64-core class server | 4 cores / 8 threads, 14 GB laptop: absolute times are not comparable, only ratios to DuckDB on the same machine |
| Scale | TPC-H SF10, SEC 2022-2024 (5 GB) | TPC-H SF1 (SF10 does not fit), full SEC (39M `num` rows) |

Rules for any number we publish: same machine for both sides in the same run, DuckDB unconstrained by memory, result rows
checked against DuckDB, per-query speedup (not only totals), failures listed.
