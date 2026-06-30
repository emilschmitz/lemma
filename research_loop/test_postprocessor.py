import os
import sys
import subprocess
import unittest
import shutil
import re

# Ensure root directory is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from research_loop.postprocessor import postprocess

class TestPostProcessor(unittest.TestCase):
    def setUp(self):
        self.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.research_dir = os.path.join(self.root_dir, "research_loop")
        self.test_project_dir = os.path.join(self.research_dir, "temp_test_project")
        
        # Cleanup any leftover temp projects
        if os.path.exists(self.test_project_dir):
            shutil.rmtree(self.test_project_dir)
            
        # Create a new cargo project
        res = subprocess.run(["cargo", "new", "--bin", "temp_test_project"], cwd=self.research_dir, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Cargo new failed: {res.stderr}")
        
        # Add dependency to Cargo.toml
        cargo_toml_path = os.path.join(self.test_project_dir, "Cargo.toml")
        with open(cargo_toml_path, "a") as f:
            f.write('\ndafny_runtime = { path = "../working_query-rust/runtime" }\n')

        # Shared Row schema definition for Dafny
        self.row_schema_dfy = """
datatype Row = Row(
  LO_ORDERKEY: bv32,
  LO_LINENUMBER: bv32,
  LO_CUSTKEY: bv32,
  LO_PARTKEY: bv32,
  LO_SUPPKEY: bv32,
  LO_ORDERDATE: bv32,
  LO_ORDERPRIORITY: string,
  LO_SHIPPRIORITY: bv32,
  LO_QUANTITY: bv32,
  LO_EXTENDEDPRICE: bv64,
  LO_ORDTOTALPRICE: bv64,
  LO_DISCOUNT: bv32,
  LO_REVENUE: bv64,
  LO_SUPPLYCOST: bv64,
  LO_TAX: bv32,
  LO_COMMITDATE: bv32,
  LO_SHIPMODE: string,
  C_NAME: string,
  C_ADDRESS: string,
  C_CITY: string,
  C_NATION: string,
  C_REGION: string,
  C_PHONE: string,
  C_MKTSEGMENT: string,
  S_NAME: string,
  S_ADDRESS: string,
  S_CITY: string,
  S_NATION: string,
  S_REGION: string,
  S_PHONE: string,
  P_NAME: string,
  P_MFGR: string,
  P_CATEGORY: string,
  P_BRAND: string,
  P_COLOR: string,
  P_TYPE: string,
  P_SIZE: bv32,
  P_CONTAINER: string,
  D_YEAR: bv32,
  D_YEARMONTHNUM: bv32,
  D_WEEKNUMINYEAR: bv32
)
"""

    def tearDown(self):
        if os.path.exists(self.test_project_dir):
            shutil.rmtree(self.test_project_dir)

    def translate_and_setup(self, dafny_code):
        dfy_file = os.path.join(self.test_project_dir, "working_query.dfy")
        with open(dfy_file, "w") as f:
            f.write(dafny_code)

        translate_cmd = [
            "dafny", "translate", "rs",
            "--enforce-determinism",
            "working_query.dfy"
        ]
        res = subprocess.run(translate_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Dafny translation failed: {res.stderr}\nSTDOUT: {res.stdout}")

        generated_rs = os.path.join(self.test_project_dir, "working_query-rust", "src", "working_query.rs")
        main_rs = os.path.join(self.test_project_dir, "src", "main.rs")
        shutil.copy2(generated_rs, main_rs)
        return main_rs

    def test_semantic_divergence_underflow(self):
        dafny_code = self.row_schema_dfy + """
function MethodSpec(data: seq<Row>): int {
  -5
}

method RunQuery(data: seq<Row>) returns (res: int)
  ensures res == MethodSpec(data)
{
  res := 0;
  var val1: int := 5;
  var val2: int := 10;
  res := val1 - val2;
}

method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
  print "OUTPUT: ", opt_res, "\\n";
}
"""
        main_rs = self.translate_and_setup(dafny_code)

        # Compile and run unoptimized
        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0, f"Cargo run failed: {normal_res.stderr}")
        
        normal_match = re.search(r"OUTPUT:\s*(-?\d+)", normal_res.stdout)
        self.assertTrue(normal_match)
        normal_val = int(normal_match.group(1))
        self.assertEqual(normal_val, -5)

        # Apply optimization
        postprocess(main_rs)

        # Compile and run optimized
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run with optimization failed: {opt_res.stderr}")
        
        opt_match = re.search(r"OUTPUT:\s*(\d+)", opt_res.stdout)
        self.assertTrue(opt_match)
        opt_val = int(opt_match.group(1))
        self.assertEqual(opt_val, 18446744073709551611)

    def test_compilation_failure_immutable_let(self):
        # We use a Dafny let-expression `var val1 := 5; val1` inside the addition.
        # This compiles to a Rust block containing `let val1 = int!(5);` (without `mut`).
        # The post-processor skips it because it doesn't have `mut`.
        # Since res is rewritten to `u64` but `val1` remains `DafnyInt`, this triggers a type mismatch.
        dafny_code = self.row_schema_dfy + """
function MethodSpec(data: seq<Row>): int {
  5
}

method RunQuery(data: seq<Row>) returns (res: int)
  ensures res == MethodSpec(data)
{
  res := 0;
  res := res + (var val1 := 5; val1);
}

method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
  print "OUTPUT: ", opt_res, "\\n";
}
"""
        main_rs = self.translate_and_setup(dafny_code)

        # Unoptimized runs fine
        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0, f"Cargo run failed: {normal_res.stderr}")

        # Apply optimization
        postprocess(main_rs)

        # Optimized run fails to compile due to type mismatch
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertNotEqual(opt_res.returncode, 0, "Compilation succeeded but was expected to fail due to type mismatch")
        self.assertIn("mismatched types", opt_res.stderr)
        print("SUCCESS: Confirmed compilation failure for immutable let variable!")

    def test_compilation_failure_map_update(self):
        # A GROUP BY query where the update index is a direct assignment res[key := 5]
        # rather than additive accumulation. The postprocessor does not replace update_index,
        # leading to compilation error since HashMap does not have update_index.
        dafny_code = self.row_schema_dfy + """
function MethodSpec(data: seq<Row>): map<(bv32, string), int> {
  if |data| > 0 then
    var key := (data[0].D_YEAR, data[0].P_BRAND);
    map[key := 5]
  else
    map[]
}

method RunQuery(data: seq<Row>) returns (res: map<(bv32, string), int>)
  ensures res == MethodSpec(data)
{
  res := map[];
  if |data| > 0 {
    var key := (data[0].D_YEAR, data[0].P_BRAND);
    res := res[key := 5]; // Direct assignment compiled to update_index
  }
}

method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
}
"""
        main_rs = self.translate_and_setup(dafny_code)

        # Unoptimized runs fine
        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0, f"Cargo run failed: {normal_res.stderr}")

        # Apply optimization
        postprocess(main_rs)

        # Optimized run fails to compile due to missing update_index method on HashMap
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertNotEqual(opt_res.returncode, 0, "Compilation succeeded but was expected to fail due to missing method")
        self.assertIn("no method named `update_index` found", opt_res.stderr)
        print("SUCCESS: Confirmed compilation failure for unhandled map update_index!")

if __name__ == "__main__":
    unittest.main()
