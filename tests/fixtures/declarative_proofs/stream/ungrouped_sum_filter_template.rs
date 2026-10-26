// Stream contract (lemma.toml [run] stream), host test fixture: ungrouped_sum_filter.rs as a query template (in-DuckDB tests of the
// template parameters of a streaming executor, tests/test_in_duckdb_stream.py).
//   -- params: lo BIGINT, d0 DATE
//   SELECT SUM(b) AS sb FROM t WHERE a > $lo AND d < $d0
//   (t: a INTEGER, b BIGINT nullable, d DATE; SUM skips NULL cells and is NULL when no cell is summed)
// The state: the exact sum (i128, checked: an overflow declines), the rows that pass the WHERE, and the summed (non-NULL) cells.
// AGENT_STATE_START
pub struct QAcc {
    pub sum: i128,
    pub hits: u64,
    pub nb: u64,
}
// AGENT_STATE_END
// AGENT_HELPERS_START
pub open spec fn qacc_inv(s: &QAcc) -> bool {
    true
}

pub open spec fn st_val(s: &QAcc, k: Key) -> Agg {
    Agg { sum_sb: s.sum as int, hits: s.hits as int, n_hit_sb: s.nb as int }
}
// AGENT_HELPERS_END
// AGENT_INIT_START
    QAcc { sum: 0, hits: 0, nb: 0 }
// AGENT_INIT_END
// AGENT_STEP_START
    let ghost t = stream_table_t(c.sid);
    let ghost s0 = st_val(old(s), ());
    let lo = p.lo;
    let d0 = p.d0;
    let mut r: usize = 0;
    while r < c.len
        invariant
            chunk_ok_t(c),
            t == stream_table_t(c.sid),
            r <= c.len,
            lo == p.lo,
            d0 == p.d0,
            st_val(s, ()) == agg_plus(s0, agg_rng(&t, c.off as int, c.off + r, (), p)),
        decreases c.len - r,
    {
        let a = c.a[r];
        let d = c.d[r];
        let bv = c.b__valid[r];
        let b = c.b[r];
        proof {
            lemma_agg_step(&t, c.off as int, c.off + r + 1, (), p);
            assert(t.a@[c.off + r] == a && t.d@[c.off + r] == d && t.b__valid@[c.off + r] == bv);
            assert(bv ==> t.b@[c.off + r] == b);
        }
        if (a as i64) > lo && d < d0 {
            s.hits = match s.hits.checked_add(1) {
                Some(v) => v,
                None => return false,
            };
            if bv {
                s.sum = match s.sum.checked_add(b as i128) {
                    Some(v) => v,
                    None => return false,
                };
                s.nb = match s.nb.checked_add(1) {
                    Some(v) => v,
                    None => return false,
                };
            }
        }
        r += 1;
    }
    proof {
        assert forall|k: Key| #[trigger] st_val(s, k) == agg_plus(st_val(old(s), k), agg_rng(&t, c.off as int, c.off + c.len, k, p)) by {}
    }
    true
// AGENT_STEP_END
// AGENT_MERGE_START
    let sum = match a.sum.checked_add(b.sum) {
        Some(v) => v,
        None => return None,
    };
    let hits = match a.hits.checked_add(b.hits) {
        Some(v) => v,
        None => return None,
    };
    let nb = match a.nb.checked_add(b.nb) {
        Some(v) => v,
        None => return None,
    };
    Some(QAcc { sum, hits, nb })
// AGENT_MERGE_END
// AGENT_FINISH_START
    proof {
        lemma_agg_total(&t@, (), p);
        assert(st_val(&s, ()) == agg_rng(&t@, 0, t@.n as int, (), p));
    }
    let mut res: Vec<OutRow> = Vec::new();
    if s.nb > 0 {
        res.push(OutRow { sb: Some(s.sum) });
    } else {
        res.push(OutRow { sb: None });
    }
    proof {
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies (((exists|i0: int| #![trigger hit_sb(&t@, i0, p.lo, p.d0)] hit_sb(&t@, i0, p.lo, p.d0)) ==> ((res@[r].sb is Some) && (res@[r].sb->Some_0 as int) == sum_sb(&t@, 0, p.lo, p.d0))) && (!(exists|i0: int| #![trigger hit_sb(&t@, i0, p.lo, p.d0)] hit_sb(&t@, i0, p.lo, p.d0)) ==> (res@[r].sb is None))) by {
            assert(r == 0);
        }
    }
    Some(res)
// AGENT_FINISH_END
