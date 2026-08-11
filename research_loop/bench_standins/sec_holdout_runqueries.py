"""Host-side capability `run_query` bodies for SEC EDGAR holdout queries (no admit())."""

from __future__ import annotations

from dataclasses import dataclass

from research_loop.bench_standins.sec_q1_runquery import SEC_Q1_RUNQUERY

SEC_Q24_RUNQUERY = r"""
#[verifier::external_body]
pub exec fn join_right_match_exec(num: &Cols_num, pre: &Cols_pre, li: usize) -> (m: bool)
    requires valid_cols_num(num), valid_cols_pre(pre), li < num.n,
    ensures m == join_right_match_helper(num, pre, li as int, 0),
{
    let mut ri: usize = 0;
    while ri < pre.n {
        if num.tag[li] == pre.tag[ri]
            && num.version[li] == pre.version[ri]
            && num.adsh[li] == pre.adsh[ri]
        {
            return true;
        }
        ri += 1;
    }
    false
}

#[verifier::external_body]
pub exec fn apply_having_filter_exec_q24(
    hm: HashMapWithView<(String, String), (u64, u64)>,
) -> (res: HashMapWithView<(String, String), (u64, u64)>)
    ensures
        res@
            == apply_having_filter(
                hm@,
                |kk: (Seq<char>, Seq<char>), vv: (u64, u64)| (vv.0 > 10),
            ),
{
    hm.into_iter().filter(|(_k, v)| v.0 > 10).collect()
}

pub exec fn run_query(num: &Cols_num, pre: &Cols_pre) -> (res: HashMapWithView<(String, String), (u64, u64)>)
    requires valid_cols_num(num), valid_cols_pre(pre),
    ensures res@ == method_spec(num, pre),
{
    let mut raw = agg_new_str_str__u64_u64();
    let mut i: usize = num.n;
    while i > 0
        invariant
            i <= num.n,
            valid_cols_num(num),
            valid_cols_pre(pre),
            raw@
                == join_anti_multi_agg_helper(num, pre, i as int),
        decreases i,
    {
        i = i - 1;
        assert(i < num.n);
        let matched = join_right_match_exec(num, pre, i);
        if !matched
            && num.eq_at_uom(i, "USD")
            && num.get_ddate_exec(i) >= 20230101
            && num.get_ddate_exec(i) <= 20231231
        {
            let tag = num.get_tag_exec(i);
            let ver = num.get_version_exec(i);
            let val = num.get_value_exec(i);
            agg_add_str_str__u64_u64(&mut raw, &tag, &ver, 1u64, val);
            proof {
                let ghost tail = join_anti_multi_agg_helper(num, pre, (i + 1) as int);
                let ghost key = (num.get_tag(i as int), num.get_version(i as int));
                let ghost prev = if tail.contains_key(key) {
                    tail[key]
                } else {
                    (0u64, 0u64)
                };
                let ghost expected = (
                    (prev.0 as int + 1) as u64,
                    (prev.1 as int + num.get_value(i as int) as int) as u64,
                );
                assert(expected == join_anti_multi_agg_helper(num, pre, i as int)[key]);
                assert(
                    raw@
                        == join_anti_multi_agg_helper(num, pre, i as int)
                );
            }
        } else {
            proof {
                assert(
                    join_anti_multi_agg_helper(num, pre, i as int)
                        == join_anti_multi_agg_helper(num, pre, (i + 1) as int)
                );
            }
        }
    }
    let res = apply_having_filter_exec_q24(raw);
    proof {
        let ghost m = join_anti_multi_agg_helper(num, pre, 0);
        assert(
            res@
                == apply_having_filter(m, |kk: (Seq<char>, Seq<char>), vv: (u64, u64)| (vv.0 > 10))
        );
        assert(res@ == method_spec(num, pre));
    }
    res
}
"""


@dataclass(frozen=True)
class HoldoutCapability:
    qnum: str
    status: str  # verified | blocked
    reason: str = ""
    runquery: str | None = None


SEC_HOLDOUT_CAPABILITY: dict[str, HoldoutCapability] = {
    "1": HoldoutCapability(
        qnum="1",
        status="verified",
        runquery=SEC_Q1_RUNQUERY.strip(),
    ),
    "2": HoldoutCapability(
        qnum="2",
        status="blocked",
        reason=(
            "missing Trusted join_projection_step_*: exec seq_push per qualifying "
            "join row over derived_m_map + spec_seq_take LIMIT (no single-table agg_step)"
        ),
    ),
    "3": HoldoutCapability(
        qnum="3",
        status="blocked",
        reason=(
            "missing Trusted join_method_spec_step_* + HAVING scalar subquery bridge "
            "(group SUM vs subquery_having_sq1_spec threshold)"
        ),
    ),
    "4": HoldoutCapability(
        qnum="4",
        status="blocked",
        reason=(
            "agg_step_* now emitted for this multi-agg shape; full Verus standin still "
            "needs join-scan step lemmas for 4-table nested fold (not query-hardcoded)"
        ),
    ),
    "6": HoldoutCapability(
        qnum="6",
        status="blocked",
        reason=(
            "agg_step_* now emitted for 4-string-key multi-agg; full Verus standin still "
            "needs 3-table nested-loop scan lemmas"
        ),
    ),
    "24": HoldoutCapability(
        qnum="24",
        status="verified",
        runquery=SEC_Q24_RUNQUERY.strip(),
    ),
}
