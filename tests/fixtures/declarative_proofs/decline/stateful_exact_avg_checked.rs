// assumptions = false + stateful + exact_division: SELECT AVG(cost) AS avg_cost FROM pre WHERE line > 5, cost DECIMAL(38,2)
// (i128 cells, no cap). The state owns the table; `execute` builds the exact rational sum / (count * 100) with checked
// arithmetic and declines (None) when the sum leaves i128 (exact_avg_checked.rs in a state).
// AGENT_STATE_START
pub struct QAcc {
    pub pre: Cols_pre,
}
// AGENT_STATE_END
// AGENT_HELPERS_START
pub open spec fn qstate_inv(s: &QState) -> bool {
    s.acc.pre == s.db().pre
}

proof fn lemma_avg_some_hit(pre: &Cols_pre, i0: int)
    requires
        0 <= i0 <= pre.n as int,
        avg_avg_cost_count(pre, i0) > 0,
    ensures
        exists|j: int| #![trigger row_hit(pre, j)] row_hit(pre, j),
    decreases pre.n as int - i0,
{
    reveal_with_fuel(avg_avg_cost_count, 2);
    if i0 < pre.n as int && !row_hit(pre, i0) {
        lemma_avg_some_hit(pre, i0 + 1);
    }
}

proof fn lemma_avg_count_pos(pre: &Cols_pre, i0: int, j: int)
    requires
        0 <= i0 <= j,
        row_hit(pre, j),
    ensures
        avg_avg_cost_count(pre, i0) > 0,
    decreases pre.n as int - i0,
{
    reveal_with_fuel(avg_avg_cost_count, 2);
    lemma_avg_avg_cost_count_bound(pre, i0 + 1);
    if i0 < j {
        lemma_avg_count_pos(pre, i0 + 1, j);
    }
}
// AGENT_HELPERS_END
// AGENT_BUILD_START
    let snap: Ghost<QDb> = Ghost(QDb { pre: pre });
    QState { snap, acc: QAcc { pre } }
// AGENT_BUILD_END
// AGENT_EDIT_START
    let pre = &s.acc.pre;
    let mut acc: i128 = 0;
    let mut cnt: u64 = 0;
    let mut i: usize = pre.n;
    while i > 0
        invariant
            i <= pre.n,
            valid_cols_pre(pre),
            acc as int == avg_avg_cost_sum(pre, i as int),
            cnt as int == avg_avg_cost_count(pre, i as int),
            cnt as int <= (pre.n - i) as int,
        decreases i,
    {
        i -= 1;
        let line = pre.line[i];
        let cost = pre.cost[i];
        proof {
            assert(pre.line@.len() == pre.n as int);
            assert(pre.cost@.len() == pre.n as int);
            assert(row_hit(pre, i as int) <==> ((line as int) > 5));
            assert(avg_avg_cost_val(pre, i as int) == cost as int);
            reveal_with_fuel(avg_avg_cost_sum, 2);
            reveal_with_fuel(avg_avg_cost_count, 2);
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
            cnt = cnt + 1;
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    if cnt == 0 {
        proof {
            assert forall|i0: int| #![trigger row_hit(pre, i0)] !row_hit(pre, i0) by {
                if row_hit(pre, i0) {
                    lemma_avg_count_pos(pre, 0, i0);
                }
            }
        }
        res.push(OutRow { avg_cost: None });
    } else {
        let den = match (cnt as i128).checked_mul(100) {
            Some(d) => d,
            None => {
                return None;
            },
        };
        let r = Rat { num: acc, den: den };
        proof {
            assert(avg_avg_cost_den(pre, 0) == (cnt as int) * 100);
            assert(avg_avg_cost_num(pre, 0) == acc as int);
            assert(rat_is(r, avg_avg_cost_num(pre, 0), avg_avg_cost_den(pre, 0)));
            lemma_avg_some_hit(pre, 0);
        }
        res.push(OutRow { avg_cost: Some(r) });
    }
    Some(res)
// AGENT_EDIT_END
