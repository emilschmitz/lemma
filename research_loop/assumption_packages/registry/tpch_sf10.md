# Proposed assumptions: tpch_sf10_proposal

These are PROPOSALS measured on today's data. Each one is a claim that all future data obeys the same bound; a proof holds only IF the data does. A wrong claim makes proofs vacuous. Review every row.

| Bound | Measured | Proposed cap | What breaks if data exceeds it | Effect on proof/speed |
|---|---|---|---|---|
| customer: rows | 1500000 | 8388608 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| customer.c_custkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_custkey: max abs(value) | 1500000 | < 2097152 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| customer.c_name: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_name: max length | 18 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_name: distinct values | 1500000 | 8388608 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer.c_address: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_address: max length | 40 | 64 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_address: distinct values | 1500000 | 8388608 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer.c_nationkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_nationkey: max abs(value) | 24 | < 32 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| customer.c_phone: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_phone: max length | 15 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_phone: distinct values | 1499963 | 8388608 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer.c_acctbal: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_acctbal: max abs(value) (stored integer, value x 10^2) | 999999 | < 1048576 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| customer.c_mktsegment: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_mktsegment: max length | 10 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_mktsegment: distinct values | 5 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer.c_comment: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_comment: max length | 116 | 128 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_comment: distinct values | 1402532 | 8388608 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer: unique key (c_name) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| customer: unique key (c_address) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| lineitem: rows | 59986052 | 268435456 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| lineitem.l_orderkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_orderkey: max abs(value) | 60000000 | < 67108864 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineitem.l_partkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_partkey: max abs(value) | 2000000 | < 2097152 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineitem.l_suppkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_suppkey: max abs(value) | 100000 | < 131072 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineitem.l_linenumber: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_linenumber: max abs(value) | 7 | < 8 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineitem.l_quantity: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_quantity: max abs(value) (stored integer, value x 10^2) | 5000 | < 8192 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineitem.l_extendedprice: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_extendedprice: max abs(value) (stored integer, value x 10^2) | 10494950 | < 16777216 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineitem.l_discount: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_discount: max abs(value) (stored integer, value x 10^2) | 10 | < 16 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineitem.l_tax: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_tax: max abs(value) (stored integer, value x 10^2) | 8 | < 16 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineitem.l_returnflag: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_returnflag: max length | 1 | 1 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| lineitem.l_returnflag: distinct values | 3 | 16 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| lineitem.l_linestatus: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_linestatus: max length | 1 | 1 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| lineitem.l_linestatus: distinct values | 2 | 8 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| lineitem.l_shipdate: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_commitdate: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_receiptdate: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_shipinstruct: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_shipinstruct: max length | 17 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| lineitem.l_shipinstruct: distinct values | 4 | 16 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| lineitem.l_shipmode: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_shipmode: max length | 7 | 8 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| lineitem.l_shipmode: distinct values | 7 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| lineitem.l_comment: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineitem.l_comment: max length | 43 | 64 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| lineitem.l_comment: distinct values | 7920544 | 33554432 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| nation: rows | 25 | 128 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| nation.n_nationkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| nation.n_nationkey: max abs(value) | 24 | < 32 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| nation.n_name: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| nation.n_name: max length | 14 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| nation.n_name: distinct values | 25 | 128 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| nation.n_regionkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| nation.n_regionkey: max abs(value) | 4 | < 8 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| nation.n_comment: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| nation.n_comment: max length | 114 | 128 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| nation.n_comment: distinct values | 25 | 128 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| nation: unique key (n_name) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| nation: unique key (n_comment) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| orders: rows | 15000000 | 67108864 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| orders.o_orderkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| orders.o_orderkey: max abs(value) | 60000000 | < 67108864 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| orders.o_custkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| orders.o_custkey: max abs(value) | 1499999 | < 2097152 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| orders.o_orderstatus: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| orders.o_orderstatus: max length | 1 | 1 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| orders.o_orderstatus: distinct values | 3 | 16 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| orders.o_totalprice: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| orders.o_totalprice: max abs(value) (stored integer, value x 10^2) | 55882256 | < 67108864 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| orders.o_orderdate: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| orders.o_orderpriority: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| orders.o_orderpriority: max length | 15 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| orders.o_orderpriority: distinct values | 5 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| orders.o_clerk: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| orders.o_clerk: max length | 15 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| orders.o_clerk: distinct values | 10000 | 65536 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| orders.o_shippriority: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| orders.o_shippriority: max abs(value) | 0 | < 1 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| orders.o_comment: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| orders.o_comment: max length | 78 | 128 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| orders.o_comment: distinct values | 7922330 | 33554432 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part: rows | 2000000 | 8388608 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| part.p_partkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_partkey: max abs(value) | 2000000 | < 2097152 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| part.p_name: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_name: max length | 51 | 64 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_name: distinct values | 1999828 | 8388608 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part.p_mfgr: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_mfgr: max length | 14 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_mfgr: distinct values | 5 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part.p_brand: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_brand: max length | 8 | 8 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_brand: distinct values | 25 | 128 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part.p_type: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_type: max length | 25 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_type: distinct values | 150 | 1024 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part.p_size: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_size: max abs(value) | 50 | < 64 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| part.p_container: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_container: max length | 10 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_container: distinct values | 40 | 256 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part.p_retailprice: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_retailprice: max abs(value) (stored integer, value x 10^2) | 209899 | < 262144 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| part.p_comment: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_comment: max length | 22 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_comment: distinct values | 754704 | 4194304 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| partsupp: rows | 8000000 | 33554432 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| partsupp.ps_partkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| partsupp.ps_partkey: max abs(value) | 2000000 | < 2097152 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| partsupp.ps_suppkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| partsupp.ps_suppkey: max abs(value) | 100000 | < 131072 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| partsupp.ps_availqty: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| partsupp.ps_availqty: max abs(value) | 9999 | < 16384 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| partsupp.ps_supplycost: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| partsupp.ps_supplycost: max abs(value) (stored integer, value x 10^2) | 100000 | < 131072 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| partsupp.ps_comment: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| partsupp.ps_comment: max length | 198 | 256 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| partsupp.ps_comment: distinct values | 5772154 | 33554432 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| region: rows | 5 | 32 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| region.r_regionkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| region.r_regionkey: max abs(value) | 4 | < 8 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| region.r_name: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| region.r_name: max length | 11 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| region.r_name: distinct values | 5 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| region.r_comment: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| region.r_comment: max length | 115 | 128 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| region.r_comment: distinct values | 5 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| region: unique key (r_name) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| region: unique key (r_comment) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| supplier: rows | 100000 | 524288 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| supplier.s_suppkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_suppkey: max abs(value) | 100000 | < 131072 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| supplier.s_name: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_name: max length | 18 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| supplier.s_name: distinct values | 100000 | 524288 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| supplier.s_address: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_address: max length | 40 | 64 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| supplier.s_address: distinct values | 100000 | 524288 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| supplier.s_nationkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_nationkey: max abs(value) | 24 | < 32 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| supplier.s_phone: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_phone: max length | 15 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| supplier.s_phone: distinct values | 100000 | 524288 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| supplier.s_acctbal: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_acctbal: max abs(value) (stored integer, value x 10^2) | 999993 | < 1048576 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| supplier.s_comment: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_comment: max length | 100 | 128 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| supplier.s_comment: distinct values | 99557 | 524288 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| supplier: unique key (s_name) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| supplier: unique key (s_address) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| supplier: unique key (s_phone) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| join lineitem x orders on lineitem.l_orderkey=orders.o_orderkey | 59986052 | 268435456 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
| join orders x customer on orders.o_custkey=customer.c_custkey | 15000000 | 67108864 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
| join lineitem x part on lineitem.l_partkey=part.p_partkey | 59986052 | 268435456 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
| join lineitem x supplier on lineitem.l_suppkey=supplier.s_suppkey | 59986052 | 268435456 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
| join customer x nation on customer.c_nationkey=nation.n_nationkey | 1500000 | 8388608 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
| join supplier x nation on supplier.s_nationkey=nation.n_nationkey | 100000 | 524288 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
| join nation x region on nation.n_regionkey=region.r_regionkey | 25 | 128 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
| join partsupp x part on partsupp.ps_partkey=part.p_partkey | 8000000 | 33554432 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
| join partsupp x supplier on partsupp.ps_suppkey=supplier.s_suppkey | 8000000 | 33554432 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |

## Approval (2026-10-17)

Emil delegated the approval of this package ("if you ran the script like someone might do in production and got reasonable assumptions then just go ahead"). Applied rules, the same as tpch_sf1:
- every measured cap accepted as proposed (profile.py, margin 4, rounded to a power of two);
- unique keys: only the TPC-H primary keys (customer c_custkey, lineitem (l_orderkey, l_linenumber), nation n_nationkey, orders o_orderkey, part p_partkey, partsupp (ps_partkey, ps_suppkey), region r_regionkey, supplier s_suppkey), each verified unique on tpch_sf10.duckdb; the accidental uniqueness proposals (c_name, c_address, ...) are not claimed;
- no join caps (as tpch_sf1).
`python -m research_loop.assumption_packages.check` reports the package holds on research_loop/generated/tpch_sf10.duckdb (sha256 in configs/data/tpch_sf10.json).
