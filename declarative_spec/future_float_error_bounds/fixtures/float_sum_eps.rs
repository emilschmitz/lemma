// Worked example: a plain ungrouped SUM over a DOUBLE column, proved with the TRUE sum-error lemma, not the
// idealization. The accumulator is the host's opaque f64 fold of a ghost sequence of the terms added so far
// (`lemma_f64_left_fold_push` per add), and `lemma_f64_sum_within_eps` gives `|acc - real sum| <= FLOAT_ABS_EPS`
// once `host_f64_sum_error(n, cap) <= FLOAT_ABS_EPS` (the literal hypothesis states the epsilon's value).
// The ghost sequence collects the terms in the order they are added (last row first).
// AGENT_HELPERS_START
proof fn lemma_rss_push(s: Seq<f64>, x: f64)
    ensures real_sum_seq(s.push(x)) == real_sum_seq(s) + (x as real),
    decreases s.len(),
{
    reveal_with_fuel(real_sum_seq, 2);
    if s.len() == 0 {
        assert(s.push(x).len() == 1);
        assert(s.push(x).skip(1) =~= Seq::<f64>::empty());
        assert(s.push(x)[0] == x);
    } else {
        assert(s.push(x).skip(1) =~= s.skip(1).push(x));
        assert(s.push(x)[0] == s[0]);
        lemma_rss_push(s.skip(1), x);
    }
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut acc: f64 = 0.0;
    let mut any: bool = false;
    let mut i: usize = t.n;
    let ghost mut terms: Seq<f64> = Seq::empty();
    proof {
        lemma_f64_left_fold_empty();
        assert(sum_s(t, t.n as int) == 0real);
        assert(real_sum_seq(terms) == 0real);
    }
    while i > 0
        invariant
            i <= t.n,
            t.n <= ROW_CAP_t,
            valid_cols_t(t),
            f64_literals_ok(),
            acc == f64_left_fold(terms),
            terms.len() == (t.n - i) as int,
            real_sum_seq(terms) == sum_s(t, i as int),
            forall|j: int| 0 <= j < terms.len() ==> -(MAG_CAP_t_v as int as real) < #[trigger] (terms[j] as real) && (terms[j] as real) < (MAG_CAP_t_v as int as real),
            any <==> exists|i0: int| #![trigger row_hit(t, i0)] i as int <= i0 && row_hit(t, i0),
        decreases i,
    {
        i -= 1;
        let x = t.v[i];
        proof {
            assert(t.v@.len() == t.n as int);
            assert(-(MAG_CAP_t_v as real) < (t.v@[i as int] as real) && (t.v@[i as int] as real) < (MAG_CAP_t_v as real));
            reveal_with_fuel(sum_s, 2);
            lemma_f64_add_defined(acc, x);
        }
        let next = acc + x;
        proof {
            lemma_f64_left_fold_push(terms, x, acc, next);
            lemma_rss_push(terms, x);
            assert(row_hit(t, i as int));
            let old_terms = terms;
            terms = old_terms.push(x);
            assert forall|j: int| 0 <= j < terms.len() implies -(MAG_CAP_t_v as int as real) < #[trigger] (terms[j] as real) && (terms[j] as real) < (MAG_CAP_t_v as int as real) by {
                if j < old_terms.len() as int { assert(terms[j] == old_terms[j]); }
            };
        }
        acc = next;
        any = true;
    }
    proof {
        // n = t.n <= 100 terms below cap 1024: n^2 * cap * 2^-52 <= 1e-6.
        assert((MAG_CAP_t_v as int) == 1024);
        let n = terms.len() as int as real;
        assert(n <= 100real && n >= 0real);
        assert(n * n >= 0real) by (nonlinear_arith)
            requires n >= 0real;
        assert(n * n <= 10000real) by (nonlinear_arith)
            requires n <= 100real, n >= 0real;
        assert(n * n * 1024real * (1real / 4503599627370496real) <= 1real / 1000000real) by (nonlinear_arith)
            requires n * n <= 10000real, n * n >= 0real;
        assert((1024int as real) == 1024real);
        assert(host_f64_sum_error(terms.len() as int, 1024) == n * n * 1024real * (1real / 4503599627370496real));
        assert(host_f64_sum_error(terms.len() as int, 1024) <= (FLOAT_ABS_EPS as real));
        lemma_f64_sum_within_eps(acc, terms.len() as int, MAG_CAP_t_v as int, FLOAT_ABS_EPS, terms);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { s: if any { Some(acc) } else { None } });
    res
// AGENT_EDIT_END
