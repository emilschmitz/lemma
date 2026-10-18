// assumptions = false + stateful: SELECT SUM(cost) AS total FROM pre WHERE line > 5, cost DECIMAL(38,2) (i128 cells, no cap).
// The state owns the table (the degenerate stateful case); `execute` adds with checked_add and declines (None) when the exact
// total leaves i128.
// AGENT_STATE_START
pub struct QAcc {
    pub pre: Cols_pre,
}
// AGENT_STATE_END
// AGENT_HELPERS_START
pub open spec fn qstate_inv(s: &QState) -> bool {
    s.acc.pre == s.db().pre
}
// AGENT_HELPERS_END
// AGENT_BUILD_START
    let snap: Ghost<QDb> = Ghost(QDb { pre: pre });
    QState { snap, acc: QAcc { pre } }
// AGENT_BUILD_END
// AGENT_EDIT_START
    let pre = &s.acc.pre;
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = pre.n;
    while i > 0
        invariant
            i <= pre.n,
            valid_cols_pre(pre),
            acc as int == sum_total(pre, i as int),
            any <==> exists|i0: int| #![trigger row_hit(pre, i0)] i as int <= i0 && row_hit(pre, i0),
        decreases i,
    {
        i -= 1;
        let line = pre.line[i];
        let cost = pre.cost[i];
        proof {
            assert(pre.line@.len() == pre.n as int);
            assert(pre.cost@.len() == pre.n as int);
            assert(row_hit(pre, i as int) <==> ((line as int) > 5));
            assert(sum_total_val(pre, i as int) == cost as int);
            reveal_with_fuel(sum_total, 2);
        }
        if line > 5 {
            match acc.checked_add(cost) {
                Some(next) => {
                    acc = next;
                },
                None => {
                    return None;
                },
            }
            any = true;
            proof {
                assert(row_hit(pre, i as int));
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { total: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].total is Some <==> any);
    }
    Some(res)
// AGENT_EDIT_END
