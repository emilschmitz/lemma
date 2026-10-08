# Proposed assumptions: ssb_sf1

These are PROPOSALS measured on today's data. Each one is a claim that all future data obeys the same bound; a proof holds only IF the data does. A wrong claim makes proofs vacuous. Review every row.

| Bound | Measured | Proposed cap | What breaks if data exceeds it | Effect on proof/speed |
|---|---|---|---|---|
| customer: rows | 30000 | 131072 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| customer.c_custkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_custkey: max abs(value) | 30000 | < 32768 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| customer.c_name: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_name: max length | 18 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_name: distinct values | 30000 | 131072 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer.c_address: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_address: max length | 24 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_address: distinct values | 30000 | 131072 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer.c_city: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_city: max length | 10 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_city: distinct values | 250 | 1024 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer.c_nation: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_nation: max length | 14 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_nation: distinct values | 25 | 128 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer.c_region: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_region: max length | 11 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_region: distinct values | 5 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer.c_phone: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_phone: max length | 15 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_phone: distinct values | 30000 | 131072 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer.c_mktsegment: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| customer.c_mktsegment: max length | 10 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| customer.c_mktsegment: distinct values | 5 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| customer: unique key (c_name) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| customer: unique key (c_address) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| customer: unique key (c_phone) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| date: rows | 2556 | 16384 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| date.d_datekey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_datekey: max abs(value) | 19981230 | < 33554432 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date.d_date: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_date: max length | 18 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| date.d_date: distinct values | 2556 | 16384 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| date.d_dayofweek: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_dayofweek: max length | 9 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| date.d_dayofweek: distinct values | 7 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| date.d_month: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_month: max length | 9 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| date.d_month: distinct values | 12 | 64 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| date.d_year: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_year: max abs(value) | 1998 | < 2048 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date.d_yearmonthnum: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_yearmonthnum: max abs(value) | 199812 | < 262144 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date.d_yearmonth: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_yearmonth: max length | 7 | 8 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| date.d_yearmonth: distinct values | 84 | 512 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| date.d_daynuminweek: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_daynuminweek: max abs(value) | 7 | < 8 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date.d_daynuminmonth: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_daynuminmonth: max abs(value) | 31 | < 32 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date.d_daynuminyear: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_daynuminyear: max abs(value) | 366 | < 512 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date.d_monthnuminyear: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_monthnuminyear: max abs(value) | 12 | < 16 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date.d_weeknuminyear: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_weeknuminyear: max abs(value) | 53 | < 64 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date.d_sellingseason: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_sellingseason: max length | 9 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| date.d_sellingseason: distinct values | 5 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| date.d_lastdayinweekfl: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_lastdayinweekfl: max abs(value) | 1 | < 2 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date.d_lastdayinmonthfl: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_lastdayinmonthfl: max abs(value) | 1 | < 2 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date.d_holidayfl: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_holidayfl: max abs(value) | 1 | < 2 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date.d_weekdayfl: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| date.d_weekdayfl: max abs(value) | 1 | < 2 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| date: unique key (d_date) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| lineorder: rows | 6001215 | 33554432 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| lineorder.lo_orderkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_orderkey: max abs(value) | 6000000 | < 8388608 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_linenumber: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_linenumber: max abs(value) | 7 | < 8 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_custkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_custkey: max abs(value) | 29999 | < 32768 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_partkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_partkey: max abs(value) | 200000 | < 262144 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_suppkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_suppkey: max abs(value) | 2000 | < 2048 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_orderdate: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_orderdate: max abs(value) | 19980802 | < 33554432 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_orderpriority: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_orderpriority: max length | 15 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| lineorder.lo_orderpriority: distinct values | 5 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| lineorder.lo_shippriority: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_shippriority: max abs(value) | 0 | < 1 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_quantity: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_quantity: max abs(value) | 50 | < 64 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_extendedprice: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_extendedprice: max abs(value) | 10494950 | < 16777216 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_ordtotalprice: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_ordtotalprice: max abs(value) | 55528516 | < 67108864 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_discount: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_discount: max abs(value) | 10 | < 16 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_revenue: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_revenue: max abs(value) | 10464950 | < 16777216 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_supplycost: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_supplycost: max abs(value) | 125939 | < 131072 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_tax: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_tax: max abs(value) | 8 | < 16 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_commitdate: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_commitdate: max abs(value) | 19981031 | < 33554432 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| lineorder.lo_shipmode: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| lineorder.lo_shipmode: max length | 7 | 8 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| lineorder.lo_shipmode: distinct values | 7 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part: rows | 200000 | 1048576 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| part.p_partkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_partkey: max abs(value) | 200000 | < 262144 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| part.p_name: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_name: max length | 21 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_name: distinct values | 8372 | 65536 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part.p_mfgr: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_mfgr: max length | 6 | 8 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_mfgr: distinct values | 5 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part.p_category: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_category: max length | 7 | 8 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_category: distinct values | 25 | 128 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part.p_brand1: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_brand1: max length | 9 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_brand1: distinct values | 1000 | 4096 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part.p_color: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_color: max length | 10 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_color: distinct values | 92 | 512 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part.p_type: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_type: max length | 25 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_type: distinct values | 150 | 1024 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| part.p_size: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_size: max abs(value) | 50 | < 64 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| part.p_container: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| part.p_container: max length | 10 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| part.p_container: distinct values | 40 | 256 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| supplier: rows | 2000 | 8192 | load fails: more rows than the proof's index range | sets integer widths of counters and loop indices; smaller is easier to prove and faster |
| supplier.s_suppkey: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_suppkey: max abs(value) | 2000 | < 2048 | load fails; sums over the column may overflow the proof's integer width | picks the cell width (u32/u64/i128); sums and products are proved against it |
| supplier.s_name: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_name: max length | 18 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| supplier.s_name: distinct values | 2000 | 8192 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| supplier.s_address: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_address: max length | 24 | 32 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| supplier.s_address: distinct values | 2000 | 8192 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| supplier.s_city: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_city: max length | 10 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| supplier.s_city: distinct values | 250 | 1024 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| supplier.s_nation: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_nation: max length | 14 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| supplier.s_nation: distinct values | 25 | 128 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| supplier.s_region: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_region: max length | 11 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| supplier.s_region: distinct values | 5 | 32 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| supplier.s_phone: NOT NULL | 0 NULL cells | no NULL | load fails on the first NULL cell | no validity vector; simplest and fastest |
| supplier.s_phone: max length | 15 | 16 | load fails on a longer string | bounds string comparison/hash work and buffer sizes |
| supplier.s_phone: distinct values | 2000 | 8192 | load fails when the dictionary outgrows the code width | picks the dictionary code width (u8/u16/u32); narrower is faster |
| supplier: unique key (s_name) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| supplier: unique key (s_address) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| supplier: unique key (s_phone) | no duplicates today | PROPOSAL only | if the user claims it and data repeats a key, proofs about joins on it are vacuous | lets a join add each outer cell once (tighter sums, no row-multiplication) |
| join lineorder x date on lineorder.lo_orderdate=date.d_datekey | 6001215 | 33554432 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
| join lineorder x customer on lineorder.lo_custkey=customer.c_custkey | 6001215 | 33554432 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
| join lineorder x supplier on lineorder.lo_suppkey=supplier.s_suppkey | 6001215 | 33554432 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
| join lineorder x part on lineorder.lo_partkey=part.p_partkey | 6001215 | 33554432 | load fails when the join has more tuples | bounds the join's output size, so counts and sums over it fit their integer widths |
