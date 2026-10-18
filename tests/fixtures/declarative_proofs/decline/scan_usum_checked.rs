// assumptions = false + agent_scan: the scan_filtered_sum.rs proof under the Option contract (no caps: the i128 sum is checked and
// declines on overflow). SELECT SUM(line) AS total FROM pre WHERE line > 5, reading only the rows DuckDB returns for
// the predicate `6 <= line <= i64::MAX` (scan_where_pre, the one DuckDB-filter trust). The proof walks the scanned rows backwards;
// between two scanned rows (and before the first, after the last) no row satisfies the predicate (lemma_scan_rows_pre), hence no row
// satisfies the WHERE (`line > 5` implies the predicate), so those rows add nothing to the fold (lemma_skip_gap).
// AGENT_HELPERS_START
proof fn lemma_skip_gap(pre: &Cols_pre, a: int, b: int)
    requires
        0 <= a <= b <= pre.n as int,
        forall|i: int| a <= i < b ==> !#[trigger] row_hit(pre, i),
    ensures
        sum_total(pre, a) == sum_total(pre, b),
        (exists|i0: int| #![trigger row_hit(pre, i0)] a <= i0 && row_hit(pre, i0)) <==> (exists|i0: int| #![trigger row_hit(pre, i0)] b <= i0 && row_hit(pre, i0)),
    decreases b - a,
{
    if a < b {
        lemma_skip_gap(pre, a + 1, b);
        assert(!row_hit(pre, a));
        assert(sum_total(pre, a) == sum_total(pre, a + 1));
        if exists|i0: int| #![trigger row_hit(pre, i0)] a <= i0 && row_hit(pre, i0) {
            let i0 = choose|i0: int| #![trigger row_hit(pre, i0)] a <= i0 && row_hit(pre, i0);
            assert(a + 1 <= i0);
        }
    }
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut pred: Vec<ScanAtom_pre> = Vec::new();
    pred.push(ScanAtom_pre::Range(ScanCol_pre::line, 6, 0x7fff_ffff_ffff_ffffi128));
    let out = scan_where_pre(pre_scan, &pred);
    let ghost idx = out.1@;
    let c = out.0;
    proof {
        lemma_scan_rows_pre(pre, pred@, pre.n as int);
        assert(idx == scan_rows_pre(pre, pred@, pre.n as int));
    }
    let m = c.n;
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut k: usize = m;
    while k > 0
        invariant
            m == c.n,
            m as int == idx.len(),
            c.line@.len() == m as int,
            pred@.len() == 1,
            pred@[0] == ScanAtom_pre::Range(ScanCol_pre::line, 6, 0x7fff_ffff_ffff_ffffi128),
            valid_cols_pre(pre),
            idx == scan_rows_pre(pre, pred@, pre.n as int),
            forall|j: int| #![trigger c.line@[j]] 0 <= j < m as int ==> c.line@[j] == pre.line@[idx[j]],
            forall|j: int| 0 <= j < idx.len() ==> 0 <= #[trigger] idx[j] < pre.n as int,
            forall|j: int| 0 <= j < idx.len() ==> scan_holds_pre(pre, pred@, #[trigger] idx[j]),
            forall|j1: int, j2: int| 0 <= j1 < j2 < idx.len() ==> #[trigger] idx[j1] < #[trigger] idx[j2],
            forall|i: int| 0 <= i < pre.n as int && #[trigger] scan_holds_pre(pre, pred@, i) ==> exists|j: int| 0 <= j < idx.len() && idx[j] == i,
            k <= m,
            acc as int == sum_total(pre, if k < m { idx[k as int] } else { pre.n as int }),
            any <==> exists|i0: int| #![trigger row_hit(pre, i0)] (if k < m { idx[k as int] } else { pre.n as int }) <= i0 && row_hit(pre, i0),
        decreases k,
    {
        let ghost p: int = if k < m { idx[k as int] } else { pre.n as int };
        k -= 1;
        let line = c.line[k];
        proof {
            let j = idx[k as int];
            assert(c.line@[k as int] == pre.line@[j]);
            assert(scan_holds_pre(pre, pred@, j));
            assert(scan_atom_holds_pre(pre, pred@[0], j));
            assert(j < p) by {
                if k + 1 < m {
                    assert(idx[k as int] < idx[k + 1]);
                }
            }
            assert forall|i: int| j + 1 <= i < p implies !#[trigger] row_hit(pre, i) by {
                if row_hit(pre, i) {
                    assert(scan_atom_holds_pre(pre, pred@[0], i));
                    assert(scan_holds_pre(pre, pred@, i));
                    let jj = choose|jj: int| 0 <= jj < idx.len() && idx[jj] == i;
                    if jj <= k {
                        if jj < k {
                            assert(idx[jj] < idx[k as int]);
                        }
                    } else if jj == k + 1 {
                        assert(idx[jj] == p);
                    } else {
                        assert(idx[k + 1] < idx[jj]);
                    }
                }
            }
            lemma_skip_gap(pre, j + 1, p);
            assert(row_hit(pre, j));
            assert(sum_total_val(pre, j) == line as int);
            assert(sum_total(pre, j) == line as int + sum_total(pre, j + 1));
        }
        match acc.checked_add(line as i128) {
            Some(next) => {
                acc = next;
            },
            None => {
                return None;
            },
        }
        any = true;
    }
    proof {
        let p: int = if 0 < m { idx[0] } else { pre.n as int };
        assert forall|i: int| 0 <= i < p implies !#[trigger] row_hit(pre, i) by {
            if row_hit(pre, i) {
                assert(scan_atom_holds_pre(pre, pred@[0], i));
                assert(scan_holds_pre(pre, pred@, i));
                let jj = choose|jj: int| 0 <= jj < idx.len() && idx[jj] == i;
                if jj > 0 {
                    assert(idx[0] < idx[jj]);
                }
            }
        }
        lemma_skip_gap(pre, 0, p);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { total: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].total is Some <==> any);
    }
    Some(res)
// AGENT_EDIT_END
