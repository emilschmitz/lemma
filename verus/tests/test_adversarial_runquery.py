"""Adversarial run_query bodies: wrong implementations must fail Verus; honest must pass."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERUS_SRC = ROOT / "verus" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(VERUS_SRC) not in sys.path:
    sys.path.insert(0, str(VERUS_SRC))

from verus.research_loop.assemble_verified_program import assemble_verified_program  # noqa: E402
from verus.research_loop.harness import resolve_verus_bin, run_verus_verify  # noqa: E402
from verus_transpiler import transpile_sql_to_verus  # noqa: E402

SCALAR_SCHEMA = {"X": "bigint", "Y": "int"}
SCALAR_SQL = "SELECT SUM(X) FROM t WHERE Y >= 1"

GROUPBY_SCHEMA = {"K": "int", "S": "string", "V": "bigint"}
GROUPBY_SQL = "SELECT K, S, SUM(V) FROM t GROUP BY K, S"

_SCALAR_LOOP_HEAD = """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{{
    let mut res: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
        decreases i,
    {{
        i = i - 1;
{body}
        assert(res == method_spec_helper(cols, i as int));
    }}
    res
}}
"""

_HONEST_SCALAR_BODY = """\
        let y = cols.get_y_exec(i);
        if y >= 1 {
            let x = cols.get_x_exec(i);
            res = add_u64(res, x);
        }"""

ADVERSARIAL_SCALAR_BODIES: dict[str, str] = {
    "constant_zero": """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    0
}""",
    "wrong_filter": _SCALAR_LOOP_HEAD.format(
        body="""\
        let y = cols.get_y_exec(i);
        if y < 1 {
            let x = cols.get_x_exec(i);
            res = add_u64(res, x);
        }"""
    ),
    "wrong_column": _SCALAR_LOOP_HEAD.format(
        body="""\
        let y = cols.get_y_exec(i);
        if y >= 1 {
            let yval = cols.get_y_exec(i);
            res = add_u64(res, yval as u64);
        }"""
    ),
    "skip_half": _SCALAR_LOOP_HEAD.format(
        body="""\
        if i % 2 == 0 {
            let y = cols.get_y_exec(i);
            if y >= 1 {
                let x = cols.get_x_exec(i);
                res = add_u64(res, x);
            }
        }"""
    ),
    "double_count": _SCALAR_LOOP_HEAD.format(
        body="""\
        let y = cols.get_y_exec(i);
        if y >= 1 {
            let x = cols.get_x_exec(i);
            res = add_u64(res, x);
            res = add_u64(res, x);
        }"""
    ),
    "ignore_where": _SCALAR_LOOP_HEAD.format(
        body="""\
        let x = cols.get_x_exec(i);
        res = add_u64(res, x);"""
    ),
    "empty_loop": """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut res: u64 = 0;
    let mut i: usize = 0;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
        decreases i,
    {
        i = i - 1;
    }
    res
}""",
    "forward_loop_wrong_invariant": """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut res: u64 = 0;
    let mut i: usize = 0;
    while i < cols.n
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
        decreases cols.n - i,
    {
        let y = cols.get_y_exec(i);
        if y >= 1 {
            let x = cols.get_x_exec(i);
            res = add_u64(res, x);
        }
        i = i + 1;
    }
    res
}""",
}

_GROUPBY_LOOP_HEAD = """\
pub exec fn run_query(cols: &Cols) -> (res: HashMap<(u32, String), u64>)
    requires valid_cols(cols),
    ensures hashmap_u32_str_u64_view(res@) == method_spec(cols),
{{
    let mut agg = agg_new_u32_str_u64();
    let mut i: usize = cols.n;
    let ghost mut g: Map<(u32, Seq<char>), u64> = Map::empty();
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            g == method_spec_helper(cols, i as int),
            hashmap_u32_str_u64_view(agg@) == g,
        decreases i,
    {{
        i = i - 1;
{body}
        assert(g == method_spec_helper(cols, i as int) && hashmap_u32_str_u64_view(agg@) == g);
    }}
    agg
}}
"""

_HONEST_GROUPBY_BODY = """\
        {
            let k = cols.get_k_exec(i);
            let s = cols.get_s_exec(i);
            let v = cols.get_v_exec(i);
            agg_add_u32_str_u64(&mut agg, k, &s, v);
            proof {
                let ghost old_g = g;
                let key = (k, s@);
                let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                g = old_g.insert(key, (prev as int + v as int) as u64);
                assert(hashmap_u32_str_u64_view(agg@) == g);
            }
        }"""

HONEST_SCALAR_BODY = _SCALAR_LOOP_HEAD.format(body=_HONEST_SCALAR_BODY)
HONEST_GROUPBY_BODY = _GROUPBY_LOOP_HEAD.format(body=_HONEST_GROUPBY_BODY)

GROUPBY_EMPTY_MAP_BODY = """\
pub exec fn run_query(cols: &Cols) -> (res: HashMap<(u32, String), u64>)
    requires valid_cols(cols),
    ensures hashmap_u32_str_u64_view(res@) == method_spec(cols),
{
    agg_new_u32_str_u64()
}"""

ADVERSARIAL_GROUPBY_BODIES: dict[str, str] = {
    "groupby_empty_map": GROUPBY_EMPTY_MAP_BODY,
    "groupby_wrong_key": _GROUPBY_LOOP_HEAD.format(
        body="""\
        {
            let v = cols.get_v_exec(i);
            agg_add_u32_str_u64(&mut agg, 0u32, "x", v);
            proof {
                let ghost old_g = g;
                let key = (0u32, "x"@);
                let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                g = old_g.insert(key, (prev as int + v as int) as u64);
                assert(hashmap_u32_str_u64_view(agg@) == g);
            }
        }"""
    ),
    "groupby_wrong_delta": _GROUPBY_LOOP_HEAD.format(
        body="""\
        {
            let k = cols.get_k_exec(i);
            let s = cols.get_s_exec(i);
            let v = cols.get_v_exec(i);
            agg_add_u32_str_u64(&mut agg, k, &s, v.wrapping_add(v));
            proof {
                let ghost old_g = g;
                let key = (k, s@);
                let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                g = old_g.insert(key, (prev as int + (v as int) * 2) as u64);
                assert(hashmap_u32_str_u64_view(agg@) == g);
            }
        }"""
    ),
    "groupby_wrong_filter": _GROUPBY_LOOP_HEAD.format(
        body="""\
        let v = cols.get_v_exec(i);
        if v != 0 {
            let k = cols.get_k_exec(i);
            let s = cols.get_s_exec(i);
            agg_add_u32_str_u64(&mut agg, k, &s, v);
            proof {
                let ghost old_g = g;
                let key = (k, s@);
                let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                g = old_g.insert(key, (prev as int + v as int) as u64);
                assert(hashmap_u32_str_u64_view(agg@) == g);
            }
        } else {
            proof { }
        }"""
    ),
    "groupby_exec_ghost_desync": _GROUPBY_LOOP_HEAD.format(
        body="""\
        {
            let k = cols.get_k_exec(i);
            let s = cols.get_s_exec(i);
            let v = cols.get_v_exec(i);
            agg_add_u32_str_u64(&mut agg, k, &s, v);
            proof {
                let ghost old_g = g;
                let key = (k, s@);
                let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                g = old_g.insert(key, (prev as int + v as int + 1) as u64);
                assert(hashmap_u32_str_u64_view(agg@) == g);
            }
        }"""
    ),
}

TRUSTED_AGG_CHEAT_RS = """\
use vstd::prelude::*;
use std::collections::HashMap;

verus! {

// Residual TRUSTED gap: external_body axiomatizes ensures; exec body is not checked.
#[verifier::external_body]
pub open spec fn hashmap_u32_str_u64_view(hm: Map<(u32, String), u64>) -> Map<(u32, Seq<char>), u64> {
    arbitrary()
}

#[verifier::external_body]
pub exec fn agg_add_u32_str_u64(hm: &mut HashMap<(u32, String), u64>, k0: u32, k1: &str, delta: u64)
    ensures
        hashmap_u32_str_u64_view(final(hm)@) == hashmap_u32_str_u64_view(old(hm)@).insert(
            (k0, k1@),
            if hashmap_u32_str_u64_view(old(hm)@).contains_key((k0, k1@)) {
                (hashmap_u32_str_u64_view(old(hm)@)[(k0, k1@)] as int + delta as int) as u64
            } else {
                delta
            },
        ),
{
    // CHEAT: no-op — Verus still accepts because external_body trusts ensures.
}

fn main() {}

} // verus!
"""

TRUSTED_ADD_U64_CHEAT_RS = """\
use vstd::prelude::*;

verus! {

// Residual TRUSTED gap: external_body axiomatizes ensures; exec body is not checked.
#[verifier::external_body]
pub exec fn add_u64(a: u64, b: u64) -> (res: u64)
    ensures res == a + b,
{
    a
}

fn main() {}

} // verus!
"""

TRUSTED_LOAD_COLS_CHEAT_RS = """\
use vstd::prelude::*;

verus! {

pub struct Cols {
    pub n: usize,
    pub x: Vec<u64>,
    pub y: Vec<u32>,
}

pub open spec fn valid_cols(cols: &Cols) -> bool {
    cols.n <= 10
}

// Residual TRUSTED gap: I/O boundary ensures valid_cols but body may lie.
#[verifier::external_body]
pub exec fn load_cols(path: &str, limit: usize) -> (cols: Cols)
    ensures valid_cols(&cols),
{
    Cols { n: 0, x: vec![], y: vec![] }
}

fn main() {}

} // verus!
"""


def verify_assembled_run_query(
    *,
    schema: dict[str, str],
    sql: str,
    run_query_body: str,
    ret_type: str,
    timeout: int = 120,
) -> bool:
    """Transpile, assemble, write temp .rs, run verus; return True iff verification succeeds."""
    spec_rs = transpile_sql_to_verus(sql, schema, enable_templates=False)
    program = assemble_verified_program(
        spec_rs=spec_rs,
        run_query_body=run_query_body,
        schema_dict=schema,
        ret_type=ret_type,
        default_tbl="/dev/null",
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".rs", delete=False, encoding="utf-8"
    ) as f:
        f.write(program)
        rs_path = f.name
    try:
        ok, _msg = run_verus_verify(rs_path, timeout)
        return ok
    finally:
        os.unlink(rs_path)


def verify_verus_source(source: str, *, timeout: int = 60) -> bool:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".rs", delete=False, encoding="utf-8"
    ) as f:
        f.write(source)
        rs_path = f.name
    try:
        ok, _msg = run_verus_verify(rs_path, timeout)
        return ok
    finally:
        os.unlink(rs_path)


def assemble_verified_program_source(
    *,
    schema: dict[str, str],
    sql: str,
    run_query_body: str,
    ret_type: str,
    default_tbl: str = "/dev/null",
) -> str:
    spec_rs = transpile_sql_to_verus(sql, schema, enable_templates=False)
    return assemble_verified_program(
        spec_rs=spec_rs,
        run_query_body=run_query_body,
        schema_dict=schema,
        ret_type=ret_type,
        default_tbl=default_tbl,
    )


def compile_and_run_verified_program(
    program: str,
    tbl_path: str,
    *,
    limit: int = 1000,
    compile_timeout: int = 120,
) -> tuple[bool, str]:
    """Compile assembled program and run binary; return (ok, stdout)."""
    from verus.research_loop.harness import run_verus_compile

    with tempfile.TemporaryDirectory() as tmp:
        rs_path = os.path.join(tmp, "oracle_query.rs")
        with open(rs_path, "w", encoding="utf-8") as f:
            f.write(program)
        ok, msg, binary = run_verus_compile(rs_path, compile_timeout)
        if not ok or not binary:
            return False, msg
        res = subprocess.run(
            [binary, tbl_path, str(limit)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (res.stdout + "\n" + res.stderr).strip()
        if res.returncode != 0:
            return False, out
        return True, out


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestAdversarialRunQuery(unittest.TestCase):
    def test_honest_scalar_accepts(self) -> None:
        ok = verify_assembled_run_query(
            schema=SCALAR_SCHEMA,
            sql=SCALAR_SQL,
            run_query_body=HONEST_SCALAR_BODY,
            ret_type="u64",
        )
        self.assertTrue(ok, "honest scalar run_query should verify")

    def test_honest_groupby_accepts(self) -> None:
        ok = verify_assembled_run_query(
            schema=GROUPBY_SCHEMA,
            sql=GROUPBY_SQL,
            run_query_body=HONEST_GROUPBY_BODY,
            ret_type="map_u32_str_u64",
        )
        self.assertTrue(ok, "honest group-by run_query should verify")

    def test_residual_trusted_agg_add_body_can_lie(self) -> None:
        """Known residual gap: TRUSTED agg_add ensures are axioms; exec body may cheat."""
        ok = verify_verus_source(TRUSTED_AGG_CHEAT_RS)
        self.assertTrue(
            ok,
            "external_body agg_add with lying exec should still verify (trusted ensures)",
        )

    def test_residual_trusted_add_u64_body_can_lie(self) -> None:
        """Known residual gap: TRUSTED add_u64 ensures are axioms; exec may ignore b."""
        ok = verify_verus_source(TRUSTED_ADD_U64_CHEAT_RS)
        self.assertTrue(
            ok,
            "external_body add_u64 with lying exec should still verify (trusted ensures)",
        )

    def test_residual_trusted_load_cols_body_can_lie(self) -> None:
        """Known residual gap: TRUSTED load_cols ensures valid_cols; body may skip I/O."""
        ok = verify_verus_source(TRUSTED_LOAD_COLS_CHEAT_RS)
        self.assertTrue(
            ok,
            "external_body load_cols with lying exec should still verify (trusted ensures)",
        )


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestAdversarialScalarRejections(unittest.TestCase):
    def test_adversarial_scalar_cases_reject(self) -> None:
        for name, body in ADVERSARIAL_SCALAR_BODIES.items():
            with self.subTest(case=name):
                ok = verify_assembled_run_query(
                    schema=SCALAR_SCHEMA,
                    sql=SCALAR_SQL,
                    run_query_body=body,
                    ret_type="u64",
                )
                self.assertFalse(ok, f"{name} should be rejected by Verus")


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestAdversarialGroupByRejections(unittest.TestCase):
    def test_adversarial_groupby_cases_reject(self) -> None:
        for name, body in ADVERSARIAL_GROUPBY_BODIES.items():
            with self.subTest(case=name):
                ok = verify_assembled_run_query(
                    schema=GROUPBY_SCHEMA,
                    sql=GROUPBY_SQL,
                    run_query_body=body,
                    ret_type="map_u32_str_u64",
                )
                self.assertFalse(ok, f"{name} should be rejected by Verus")


if __name__ == "__main__":
    unittest.main()
