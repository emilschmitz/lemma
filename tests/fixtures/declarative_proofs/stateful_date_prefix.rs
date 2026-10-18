// Stateful contract (lemma.toml `stateful`): a scalar SUM over a date range answered from prefix sums over day buckets.
// TPC-H SF1 catalog (tpch_sf1):
//   SELECT SUM(l_extendedprice) AS rev FROM lineitem WHERE l_shipdate >= DATE '1994-01-01' AND l_shipdate < DATE '1995-01-01'
// (dates are days since 1970-01-01: the range is 8766 <= l_shipdate < 9131.)
// Bucket of a day d: 0 below day 0, d + 1 for 0 <= d < 65536, 65537 above. build: one backward pass adds each row to its
// bucket (sum and count), then a prefix pass: ps[j] / pc[j] = sum / count of the rows whose bucket is below j (65539
// entries), and the rows are dropped. execute: two lookups, ps[bkt(9131)] - ps[bkt(8766)], and the counts for NULL.
// For any range [lo, hi) of days inside 0..65536 the same state answers with two lookups.
// AGENT_STATE_START
pub struct QAcc {
    pub ps: Vec<i128>,
    pub pc: Vec<u64>,
}
// AGENT_STATE_END
// AGENT_HELPERS_START
pub open spec fn bkt(d: i32) -> int {
    if d < 0 { 0int } else if d < 65536 { d as int + 1 } else { 65537int }
}

pub open spec fn lt_sum(t: &Cols_lineitem, i: int, j: int) -> int
    decreases t.n as int - i
{
    if i < 0 || i >= t.n as int { 0int } else { (if bkt(t.l_shipdate@[i]) < j { t.l_extendedprice@[i] as int } else { 0int }) + lt_sum(t, i + 1, j) }
}

pub open spec fn lt_cnt(t: &Cols_lineitem, i: int, j: int) -> int
    decreases t.n as int - i
{
    if i < 0 || i >= t.n as int { 0int } else { (if bkt(t.l_shipdate@[i]) < j { 1int } else { 0int }) + lt_cnt(t, i + 1, j) }
}

pub open spec fn eq_sum(t: &Cols_lineitem, i: int, k: int) -> int
    decreases t.n as int - i
{
    if i < 0 || i >= t.n as int { 0int } else { (if bkt(t.l_shipdate@[i]) == k { t.l_extendedprice@[i] as int } else { 0int }) + eq_sum(t, i + 1, k) }
}

pub open spec fn eq_cnt(t: &Cols_lineitem, i: int, k: int) -> int
    decreases t.n as int - i
{
    if i < 0 || i >= t.n as int { 0int } else { (if bkt(t.l_shipdate@[i]) == k { 1int } else { 0int }) + eq_cnt(t, i + 1, k) }
}

pub open spec fn qstate_inv(s: &QState) -> bool {
    let li = s.db().lineitem;
    &&& s.acc.ps@.len() == 65539
    &&& s.acc.pc@.len() == 65539
    &&& forall|q: int| #![trigger s.acc.ps@[q]] 0 <= q < 65539 ==> s.acc.ps@[q] as int == lt_sum(&li, 0, q)
    &&& forall|q: int| #![trigger s.acc.pc@[q]] 0 <= q < 65539 ==> s.acc.pc@[q] as int == lt_cnt(&li, 0, q)
}

proof fn lemma_lt_zero(t: &Cols_lineitem, i: int)
    requires
        0 <= i <= t.n as int,
    ensures
        lt_sum(t, i, 0) == 0,
        lt_cnt(t, i, 0) == 0,
    decreases t.n as int - i,
{
    if i < t.n as int {
        lemma_lt_zero(t, i + 1);
    }
}

proof fn lemma_lt_split(t: &Cols_lineitem, i: int, j: int)
    requires
        0 <= i <= t.n as int,
    ensures
        lt_sum(t, i, j + 1) == lt_sum(t, i, j) + eq_sum(t, i, j),
        lt_cnt(t, i, j + 1) == lt_cnt(t, i, j) + eq_cnt(t, i, j),
    decreases t.n as int - i,
{
    if i < t.n as int {
        lemma_lt_split(t, i + 1, j);
    }
}

proof fn lemma_lt_bound(t: &Cols_lineitem, i: int, j: int)
    requires
        0 <= i <= t.n as int,
        valid_cols_lineitem(t),
    ensures
        -((t.n as int - i) * 16777215int) <= lt_sum(t, i, j) <= (t.n as int - i) * 16777215int,
        0 <= lt_cnt(t, i, j) <= t.n as int - i,
    decreases t.n as int - i,
{
    if i < t.n as int {
        lemma_lt_bound(t, i + 1, j);
        assert(t.l_extendedprice@[i] as int >= -16777215 && t.l_extendedprice@[i] as int <= 16777215);
    }
}

proof fn lemma_range(t: &Cols_lineitem, i: int)
    requires
        0 <= i <= t.n as int,
        valid_cols_lineitem(t),
    ensures
        sum_rev(t, i) == lt_sum(t, i, 9132) - lt_sum(t, i, 8767),
        lt_cnt(t, i, 9132) - lt_cnt(t, i, 8767) >= 0,
        (lt_cnt(t, i, 9132) - lt_cnt(t, i, 8767) > 0) <==> exists|j: int| #![trigger row_hit(t, j)] i <= j < t.n as int && row_hit(t, j),
    decreases t.n as int - i,
{
    if i < t.n as int {
        lemma_range(t, i + 1);
        let d = t.l_shipdate@[i];
        assert(row_hit(t, i) <==> (bkt(d) < 9132 && !(bkt(d) < 8767)));
        assert(sum_rev_val(t, i) == t.l_extendedprice@[i] as int);
        if row_hit(t, i) {
            assert(i <= i && i < t.n as int && row_hit(t, i));
        } else if exists|j: int| #![trigger row_hit(t, j)] i <= j < t.n as int && row_hit(t, j) {
            let j = choose|j: int| #![trigger row_hit(t, j)] i <= j < t.n as int && row_hit(t, j);
            assert(j != i);
            assert(i + 1 <= j < t.n as int && row_hit(t, j));
        }
    }
}
// AGENT_HELPERS_END
// AGENT_BUILD_START
    let snap: Ghost<QDb> = Ghost(QDb { lineitem: lineitem });
    let nb: usize = 65538;
    let mut sb: Vec<i128> = Vec::new();
    let mut kb: Vec<u64> = Vec::new();
    let mut z: usize = 0;
    while z < nb
        invariant
            z <= nb,
            nb == 65538,
            sb@.len() == z as int,
            kb@.len() == z as int,
            forall|c: int| 0 <= c < z as int ==> sb@[c] == 0 && kb@[c] == 0,
        decreases nb - z,
    {
        sb.push(0);
        kb.push(0);
        z += 1;
    }
    let mut i: usize = lineitem.n;
    while i > 0
        invariant
            i <= lineitem.n,
            valid_cols_lineitem(&lineitem),
            nb == 65538,
            sb@.len() == nb as int,
            kb@.len() == nb as int,
            forall|k: int| #![trigger sb@[k]] 0 <= k < nb as int ==> sb@[k] as int == eq_sum(&lineitem, i as int, k)
                && -((lineitem.n - i) as int) * 16777215int <= sb@[k] as int
                && sb@[k] as int <= ((lineitem.n - i) as int) * 16777215int,
            forall|k: int| #![trigger kb@[k]] 0 <= k < nb as int ==> kb@[k] as int == eq_cnt(&lineitem, i as int, k)
                && kb@[k] as int <= (lineitem.n - i) as int,
        decreases i,
    {
        i -= 1;
        let d = lineitem.l_shipdate[i];
        let x = lineitem.l_extendedprice[i];
        let b: usize = if d < 0 { 0 } else if d < 65536 { (d as usize) + 1 } else { 65537 };
        proof {
            assert(lineitem.l_shipdate@.len() == lineitem.n as int);
            assert(lineitem.l_extendedprice@.len() == lineitem.n as int);
            assert(b as int == bkt(d));
            assert(x as int >= -16777215 && x as int <= 16777215);
            assert forall|k: int| #[trigger] eq_sum(&lineitem, i as int, k) == (if bkt(d) == k { x as int } else { 0int }) + eq_sum(&lineitem, i as int + 1, k) by {
                reveal_with_fuel(eq_sum, 2);
            };
            assert forall|k: int| #[trigger] eq_cnt(&lineitem, i as int, k) == (if bkt(d) == k { 1int } else { 0int }) + eq_cnt(&lineitem, i as int + 1, k) by {
                reveal_with_fuel(eq_cnt, 2);
            };
        }
        let s0 = sb[b];
        sb.set(b, s0 + x as i128);
        let k0 = kb[b];
        kb.set(b, k0 + 1);
        proof {
            assert forall|k: int| #![trigger sb@[k]] 0 <= k < nb as int implies sb@[k] as int == eq_sum(&lineitem, i as int, k)
                && -((lineitem.n - i) as int) * 16777215int <= sb@[k] as int
                && sb@[k] as int <= ((lineitem.n - i) as int) * 16777215int by {
                if k != b as int {
                    assert(bkt(d) != k);
                }
            };
            assert forall|k: int| #![trigger kb@[k]] 0 <= k < nb as int implies kb@[k] as int == eq_cnt(&lineitem, i as int, k)
                && kb@[k] as int <= (lineitem.n - i) as int by {
                if k != b as int {
                    assert(bkt(d) != k);
                }
            };
        }
    }
    let mut ps: Vec<i128> = Vec::new();
    let mut pc: Vec<u64> = Vec::new();
    ps.push(0);
    pc.push(0);
    proof {
        lemma_lt_zero(&lineitem, 0);
    }
    let mut j: usize = 0;
    while j < nb
        invariant
            j <= nb,
            nb == 65538,
            valid_cols_lineitem(&lineitem),
            sb@.len() == nb as int,
            kb@.len() == nb as int,
            forall|k: int| #![trigger sb@[k]] 0 <= k < nb as int ==> sb@[k] as int == eq_sum(&lineitem, 0, k)
                && -(lineitem.n as int) * 16777215int <= sb@[k] as int
                && sb@[k] as int <= (lineitem.n as int) * 16777215int,
            forall|k: int| #![trigger kb@[k]] 0 <= k < nb as int ==> kb@[k] as int == eq_cnt(&lineitem, 0, k),
            ps@.len() == j as int + 1,
            pc@.len() == j as int + 1,
            forall|q: int| #![trigger ps@[q]] 0 <= q <= j as int ==> ps@[q] as int == lt_sum(&lineitem, 0, q),
            forall|q: int| #![trigger pc@[q]] 0 <= q <= j as int ==> pc@[q] as int == lt_cnt(&lineitem, 0, q),
        decreases nb - j,
    {
        let a = ps[j];
        let c = pc[j];
        let sv = sb[j];
        let kv = kb[j];
        proof {
            lemma_lt_split(&lineitem, 0, j as int);
            lemma_lt_bound(&lineitem, 0, j as int);
            lemma_lt_bound(&lineitem, 0, j as int + 1);
            assert(lineitem.n as int <= 33554432);
        }
        ps.push(a + sv);
        pc.push(c + kv);
        j += 1;
    }
    QState { snap, acc: QAcc { ps, pc } }
// AGENT_BUILD_END
// AGENT_EDIT_START
    let ghost li = s.db().lineitem;
    proof {
        lemma_range(&li, 0);
        lemma_lt_bound(&li, 0, 9132);
        lemma_lt_bound(&li, 0, 8767);
        assert(li.n as int <= 33554432);
    }
    let hi_s = s.acc.ps[9132];
    let lo_s = s.acc.ps[8767];
    let hi_c = s.acc.pc[9132];
    let lo_c = s.acc.pc[8767];
    let mut res: Vec<OutRow> = Vec::new();
    if hi_c > lo_c {
        res.push(OutRow { rev: Some(hi_s - lo_s) });
    } else {
        res.push(OutRow { rev: None });
    }
    proof {
        assert(res@.len() == 1);
        assert((exists|i0: int| #![trigger row_hit(&li, i0)] row_hit(&li, i0)) <==> hi_c > lo_c);
    }
    res
// AGENT_EDIT_END
