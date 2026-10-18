// Stateful contract (lemma.toml `stateful`), the degenerate case: the state owns the table and `execute` is a plain
// run_query body over it. TPC-H SF1 catalog (tpch_sf1):
//   SELECT SUM(l_extendedprice) AS rev FROM lineitem WHERE l_shipdate >= DATE '1994-01-01' AND l_shipdate < DATE '1995-01-01'
// AGENT_STATE_START
pub struct QAcc {
    pub lineitem: Cols_lineitem,
}
// AGENT_STATE_END
// AGENT_HELPERS_START
pub open spec fn qstate_inv(s: &QState) -> bool {
    s.acc.lineitem == s.db().lineitem
}
// AGENT_HELPERS_END
// AGENT_BUILD_START
    let snap: Ghost<QDb> = Ghost(QDb { lineitem: lineitem });
    QState { snap, acc: QAcc { lineitem } }
// AGENT_BUILD_END
// AGENT_EDIT_START
    let lineitem = &s.acc.lineitem;
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = lineitem.n;
    while i > 0
        invariant
            i <= lineitem.n,
            valid_cols_lineitem(lineitem),
            acc as int == sum_rev(lineitem, i as int),
            -((lineitem.n - i) as int) * 16777215int <= acc as int,
            acc as int <= ((lineitem.n - i) as int) * 16777215int,
            any <==> exists|i0: int| #![trigger row_hit(lineitem, i0)] i as int <= i0 && row_hit(lineitem, i0),
        decreases i,
    {
        i -= 1;
        let d = lineitem.l_shipdate[i];
        let x = lineitem.l_extendedprice[i];
        proof {
            assert(lineitem.l_shipdate@.len() == lineitem.n as int);
            assert(lineitem.l_extendedprice@.len() == lineitem.n as int);
            assert(row_hit(lineitem, i as int) <==> (d >= 8766 && d < 9131));
            assert(sum_rev_val(lineitem, i as int) == x as int);
            reveal_with_fuel(sum_rev, 2);
        }
        if d >= 8766 && d < 9131 {
            acc = acc + (x as i128);
            any = true;
            proof {
                assert(row_hit(lineitem, i as int));
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { rev: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].rev is Some <==> any);
    }
    res
// AGENT_EDIT_END
