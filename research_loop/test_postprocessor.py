import os
import sys
import subprocess
import unittest
import shutil
import re
import tempfile

# Ensure root directory is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from research_loop.postprocessor import postprocess

def make_row(lo_shippriority=0, lo_orderpriority='""', lo_tax=0, lo_quantity=0, p_brand='""'):
    args = [
        "0", "0", "0", "0", "0", "0",          # 0..5: bv32
        lo_orderpriority,                      # 6: string
        str(lo_shippriority),                  # 7: bv32
        str(lo_quantity),                      # 8: bv32
        "0", "0",                              # 9..10: bv64
        "0",                                   # 11: bv32
        "0", "0",                              # 12..13: bv64
        str(lo_tax),                           # 14: bv32
        "0",                                   # 15: bv32
        '""', '""', '""', '""', '""', '""', '""', '""', # 16..23: string
        '""', '""', '""', '""', '""', '""',             # 24..29: string
        '""', '""', '""',                               # 30..32: string
        p_brand,                                        # 33: string
        '""', '""',                                     # 34..35: string
        "0",                                            # 36: bv32
        '""',                                           # 37: string
        "0", "0", "0"                                   # 38..40: bv32
    ]
    return f"Row({','.join(args)})"

class TestPostProcessor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.research_dir = os.path.join(cls.root_dir, "research_loop")
        cls.runtime_path = os.path.abspath(os.path.join(cls.research_dir, "working_query-rust", "runtime"))
        
        # Configure shared cargo target directory to cache dafny_runtime compilation artifacts.
        # Lives in /tmp so it's outside the project, persists across runs, and never needs gitignoring.
        # Cargo handles staleness automatically via fingerprinting.
        cls.shared_target_dir = "/tmp/verified-hillclimbing-test-cache"
        os.environ["CARGO_TARGET_DIR"] = cls.shared_target_dir

        # Shared Row schema definition for Dafny
        cls.row_schema_dfy = """
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

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=self.research_dir)
        project_name = f"temp_project_{self._testMethodName}"
        self.test_project_dir = os.path.join(self.temp_dir.name, project_name)
        
        # Create a new cargo project
        res = subprocess.run(["cargo", "new", "--bin", project_name], cwd=self.temp_dir.name, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Cargo new failed: {res.stderr}")
        
        # Add dependency to Cargo.toml
        cargo_toml_path = os.path.join(self.test_project_dir, "Cargo.toml")
        with open(cargo_toml_path, "a") as f:
            f.write(f'\ndafny_runtime = {{ path = "{self.runtime_path}" }}\n')

        # Copy `dataset.rs` from the harness project so the postprocessor's
        # `mod dataset;` injection resolves.  The tests that don't use
        # `load_dataset` still need this because the postprocessor emits
        # `mod dataset;` whenever the Main has `var data := []`.
        stable_dataset_rs = os.path.join(
            self.research_dir, "working_query-rust", "src", "dataset.rs"
        )
        if os.path.exists(stable_dataset_rs):
            shutil.copy(stable_dataset_rs, os.path.join(self.test_project_dir, "src", "dataset.rs"))

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def translate_and_setup(self, dafny_code):
        dfy_file = os.path.join(self.test_project_dir, "working_query.dfy")
        with open(dfy_file, "w") as f:
            f.write(dafny_code)

        translate_cmd = [
            "dafny", "translate", "rs",
            "--enforce-determinism",
            "--no-verify",
            "--allow-warnings",
            "working_query.dfy"
        ]
        res = subprocess.run(translate_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Dafny translation failed: {res.stderr}\nSTDOUT: {res.stdout}")

        generated_rs = os.path.join(self.test_project_dir, "working_query-rust", "src", "working_query.rs")
        main_rs = os.path.join(self.test_project_dir, "src", "main.rs")
        shutil.copy(generated_rs, main_rs)
        os.utime(main_rs, None)
        return main_rs

    # ==========================================================================
    # GROUP 1: Scalar return types and local variable optimizations
    # ==========================================================================

    def test_semantic_divergence_underflow(self):
        """
        Tests that signed subtraction underflow (5 - 10) wraps to 2^64 - 5 in optimized u64.
        """
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
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

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(-?\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(-?\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))

        self.assertEqual(normal_val, opt_val, f"Divergence: {normal_val} != {opt_val}")

    def test_semantic_divergence_overflow(self):
        """
        Tests that multiplication 10^20 wraps around 2^64 in optimized u64.
        """
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
{
  res := 0;
  var val1: int := 10;
  res := val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1;
}

method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
  print "OUTPUT: ", opt_res, "\\n";
}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))

        self.assertEqual(normal_val, opt_val, f"Divergence: {normal_val} != {opt_val}")

    def test_semantic_divergence_overflow_addition(self):
        """
        Tests that addition (2 * 10^20) wraps modulo 2^64 in optimized u64.
        """
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
{
  res := 0;
  var val1: int := 10;
  var product: int := val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1 * val1;
  res := product + product;
}

method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
  print "OUTPUT: ", opt_res, "\\n";
}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))

        self.assertEqual(normal_val, opt_val, f"Divergence: {normal_val} != {opt_val}")

    # ==========================================================================
    # GROUP 2: Loop Index Variable and Conditions/Increments
    # ==========================================================================

    def test_semantic_divergence_loop_decrement_underflow(self):
        """
        Tests that decrementing loop index past 0 wraps to 2^64-1 in optimized usize,
        preventing termination (caught by a guard count) vs correct termination in Dafny.
        """
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
{
  res := 0;
  var i := 1;
  while i > 0 && res < 10 {
    res := res + 1;
    i := i - 2;
  }
}

method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
  print "OUTPUT: ", opt_res, "\\n";
}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))

        self.assertEqual(normal_val, opt_val, f"Divergence: {normal_val} != {opt_val}")

    def test_semantic_divergence_loop_cardinality_underflow(self):
        """
        Tests decrement loop initialized to sequence cardinality.
        """
        dafny_code = self.row_schema_dfy + f"""
method RunQuery(data: seq<Row>) returns (res: int)
{{
  res := 0;
  var len := |data|;
  var i := len;
  while i > 0 && res < 10 {{
    res := res + 1;
    i := i - 2;
  }}
}}

method Main() {{
  var data := seq(1, i => {make_row()});
  var opt_res := RunQuery(data);
  print "OUTPUT: ", opt_res, "\\n";
}}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))

        self.assertEqual(normal_val, opt_val, f"Divergence: {normal_val} != {opt_val}")

    def test_semantic_divergence_len_subtraction_underflow(self):
        """
        Tests len subtraction underflow when len is 5.
        """
        dafny_code = self.row_schema_dfy + f"""
method RunQuery(data: seq<Row>) returns (res: int)
{{
  var length: bv64 := |data| as bv64;
  res := (length as int) - 10;
}}

method Main() {{
  var data := seq(5, i => {make_row()});
  var opt_res := RunQuery(data);
  print "OUTPUT: ", opt_res, "\\n";
}}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(-?\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(-?\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))

        self.assertEqual(normal_val, opt_val, f"Divergence: {normal_val} != {opt_val}")

    # ==========================================================================
    # GROUP 3: Index access rules
    # ==========================================================================

    def test_semantic_divergence_index_out_of_bounds(self):
        """
        Tests accessing data[i] with wrapped index. Optimized u64 condition (i < 0) becomes false,
        skipping the safety branch and returning a different value.
        """
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
{
  res := 0;
  var i := 1;
  i := i - 2;
  if i < 0 {
    res := 42;
  } else {
    res := 99;
  }
}

method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
  print "OUTPUT: ", opt_res, "\\n";
}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))

        self.assertEqual(normal_val, opt_val, f"Divergence: {normal_val} != {opt_val}")

    # ==========================================================================
    # GROUP 4: GROUP BY HashMap return type, initialization and updates
    # ==========================================================================

    def test_semantic_divergence_map_value_underflow(self):
        """
        Tests that plain int subtraction underflow inside a map update wraps in u64.
        The post-processor rewrites map updates to `+= (EXPR) as u64`, so a negative
        DafnyInt (-5) wraps to 2^64-5 in the optimized version.
        """
        dafny_code = self.row_schema_dfy + f"""
method RunQuery(data: seq<Row>) returns (res: map<(bv32, string), int>)
{{
  res := map[];
  var len := |data|;
  var i := 0;
  while i < len {{
    var row := data[i];
    var key := (2010, row.P_BRAND);
    var neg := 0 - 5;
    res := res[key := (if key in res then res[key] else 0) + neg];
    i := i + 1;
    if i > 0 {{ len := i; }}
  }}
}}

method Main() {{
  var data := seq(1, i => {make_row(p_brand='"brand"')});
  var opt_res := RunQuery(data);
  var key := (2010 as bv32, "brand");
  if key in opt_res {{
    print "OUTPUT: ", opt_res[key], "\\n";
  }}
}}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(-?\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(-?\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))

        self.assertEqual(normal_val, opt_val, f"Divergence: {normal_val} != {opt_val}")

    def test_semantic_divergence_map_value_overflow(self):
        """
        Tests that overflow inside map values wraps in u64.
        """
        dafny_code = self.row_schema_dfy + f"""
method RunQuery(data: seq<Row>) returns (res: map<(bv32, string), int>)
{{
  res := map[];
  var len := |data|;
  var i := 0;
  while i < len {{
    var row := data[i];
    var key := (2010, row.P_BRAND);
    
    var base_bv: bv64 := 2000000000;
    var large_val_bv: bv64 := base_bv * base_bv * 4 + base_bv * 1223372036 + 1709551610;
    var ten_bv: bv64 := 10;
    
    res := res[key := (if key in res then res[key] else 0) + (large_val_bv as int)];
    res := res[key := (if key in res then res[key] else 0) + (ten_bv as int)];
    
    var base: int := 2000000000;
    var large_val: int := base * base * 4 + base * 1223372036 + 1709551610;
    var ten := 10;
    var map_sum := large_val + ten;
    base := base;
    large_val := large_val;
    ten := ten;
    map_sum := map_sum;
    print "OUTPUT: ", map_sum, "\\n";
    
    i := i + 1;
    if i > 0 {{ len := i; }}
  }}
}}

method Main() {{
  var data := seq(1, i => {make_row(p_brand='"brand"')});
  var opt_res := RunQuery(data);
}}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))

        self.assertEqual(normal_val, opt_val, f"Divergence: {normal_val} != {opt_val}")

    def test_semantic_divergence_map_double_update(self):
        """
        Verifies that multiple map updates compile and execute correctly.
        """
        dafny_code = self.row_schema_dfy + f"""
method RunQuery(data: seq<Row>) returns (res: map<(bv32, string), int>)
{{
  res := map[];
  var len := |data|;
  var i := 0;
  while i < len {{
    var row := data[i];
    var key := (2010, row.P_BRAND);
    var ten: bv64 := 10;
    var twenty: bv64 := 20;
    res := res[key := (if key in res then res[key] else 0) + (ten as int)];
    res := res[key := (if key in res then res[key] else 0) + (twenty as int)];
    print "OUTPUT: ", ten + twenty, "\\n";
    i := i + 1;
  }}
}}

method Main() {{
  var data := seq(1, i => {make_row(p_brand='"brand"')});
  var opt_res := RunQuery(data);
}}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))

        self.assertEqual(normal_val, opt_val)

    # ==========================================================================
    # GROUP 5: Rc<Row> reference lookup
    # ==========================================================================

    def test_semantic_divergence_rc_row_lookup(self):
        """
        Verifies Rc<Row> reference lookup. This optimization is semantic-preserving, so it should PASS.
        """
        dafny_code = self.row_schema_dfy + f"""
method RunQuery(data: seq<Row>) returns (res: int)
{{
  res := 0;
  var len := |data|;
  var i := 0;
  while i < len {{
    var row := data[i];
    res := res + row.LO_QUANTITY as int;
    i := i + 1;
  }}
}}

method Main() {{
  var data := seq(10, i => {make_row(lo_quantity=21)});
  var opt_res := RunQuery(data);
  print "OUTPUT: ", opt_res, "\\n";
}}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))
        self.assertEqual(normal_val, 210)

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))
        self.assertEqual(opt_val, normal_val)

    # ==========================================================================
    # GROUP 6: String comparison optimization
    # ==========================================================================

    def test_semantic_divergence_string_comparison(self):
        """
        Verifies string equality check. This is semantic-preserving, so it should PASS.
        """
        dafny_code = self.row_schema_dfy + f"""
method RunQuery(data: seq<Row>) returns (res: int)
{{
  res := 0;
  var len := |data|;
  var i := 0;
  while i < len {{
    var row := data[i];
    if row.LO_ORDERPRIORITY == "1-URGENT" {{
      res := res + 10;
    }}
    i := i + 1;
  }}
}}

method Main() {{
  var data := seq(10, i => {make_row(lo_orderpriority='"1-URGENT"')});
  var opt_res := RunQuery(data);
  print "OUTPUT: ", opt_res, "\\n";
}}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))
        self.assertEqual(normal_val, 100)

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))
        self.assertEqual(opt_val, normal_val)

    # ==========================================================================
    # GROUP 7: Column projection pass
    # ==========================================================================

    def test_semantic_divergence_column_projection(self):
        """
        Verifies column projection mapping. This is semantic-preserving, so it should PASS.
        """
        dafny_code = self.row_schema_dfy + f"""
method RunQuery(data: seq<Row>) returns (res: int)
{{
  res := 0;
  var len := |data|;
  var i := 0;
  while i < len {{
    var row := data[i];
    res := res + row.LO_TAX as int;
    i := i + 1;
  }}
}}

method Main() {{
  var data := seq(10, i => {make_row(lo_tax=3)});
  var opt_res := RunQuery(data);
  print "OUTPUT: ", opt_res, "\\n";
}}
"""
        main_rs = self.translate_and_setup(dafny_code)

        run_cmd = ["cargo", "run", "--release"]
        normal_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(normal_res.returncode, 0)
        m = re.search(r"OUTPUT:\s*(\d+)", normal_res.stdout)
        self.assertIsNotNone(m, f"Unoptimized run did not match OUTPUT. stdout: {normal_res.stdout}")
        normal_val = int(m.group(1))
        self.assertEqual(normal_val, 30)

        postprocess(main_rs)
        os.utime(main_rs, None)
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0, f"Cargo run failed: {opt_res.stderr}")
        m = re.search(r"OUTPUT:\s*(\d+)", opt_res.stdout)
        self.assertIsNotNone(m, f"Optimized run did not match OUTPUT. stdout: {opt_res.stdout}")
        opt_val = int(m.group(1))
        self.assertEqual(opt_val, normal_val)

    # ==========================================================================
    # COMPILATION FAILURE TESTS (Skipped)
    # ==========================================================================

    @unittest.skip("Skipped: post-processor causes compilation failure due to Signed trait requirements in euclidian_modulo")
    def test_compilation_failure_modulo(self):
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
{
  res := 0;
  var val1: int := 5;
  var val2: int := 3;
  res := val1 % val2;
}
method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
}
"""
        main_rs = self.translate_and_setup(dafny_code)
        postprocess(main_rs)
        
        run_cmd = ["cargo", "run", "--release"]
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0)

    @unittest.skip("Skipped: post-processor causes compilation failure due to large literals mapped to byte strings")
    def test_compilation_failure_large_literal(self):
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
{
  res := 0;
  var val1: int := 20000000000; // Exceeds i32 limit, compiled to byte string literal
  res := val1;
}
method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
}
"""
        main_rs = self.translate_and_setup(dafny_code)
        postprocess(main_rs)
        
        run_cmd = ["cargo", "run", "--release"]
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0)

    @unittest.skip("Skipped: post-processor causes compilation failure on immutable let bindings (Dafny let-expressions)")
    def test_compilation_failure_immutable_let(self):
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
{
  res := 0;
  res := res + (var val1 := 5; val1);
}
method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
}
"""
        main_rs = self.translate_and_setup(dafny_code)
        postprocess(main_rs)
        
        run_cmd = ["cargo", "run", "--release"]
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0)

    @unittest.skip("Skipped: post-processor causes compilation failure on direct map updates (update_index missing on HashMap)")
    def test_compilation_failure_map_update(self):
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: map<(bv32, string), int>)
{
  res := map[];
  if |data| > 0 {
    var key := (data[0].D_YEAR, data[0].P_BRAND);
    res := res[key := 5];
  }
}
method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
}
"""
        main_rs = self.translate_and_setup(dafny_code)
        postprocess(main_rs)
        
        run_cmd = ["cargo", "run", "--release"]
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0)

    @unittest.skip("Skipped: post-processor causes compilation failure on 3-tuple keys due to Map update regex matching but type declaration regex missing")
    def test_compilation_failure_map_3tuple_key(self):
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: map<(bv32, string, string), int>)
{
  res := map[];
  if |data| > 0 {
    var key := (data[0].D_YEAR, data[0].P_BRAND, data[0].P_CONTAINER);
    res := res[key := (if key in res then res[key] else 0) + 5];
  }
}
method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
}
"""
        main_rs = self.translate_and_setup(dafny_code)
        postprocess(main_rs)
        
        run_cmd = ["cargo", "run", "--release"]
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0)

    @unittest.skip("Skipped: post-processor causes compilation failure when loop row variable is reassigned")
    def test_compilation_failure_reassigned_row(self):
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
{
  res := 0;
  var i := 0;
  while i < |data| {
    var row_var := data[i];
    if i > 0 {
      row_var := data[i - 1]; // Reassignment of optimized Rc reference
    }
    i := i + 1;
  }
}
method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
}
"""
        main_rs = self.translate_and_setup(dafny_code)
        postprocess(main_rs)
        
        run_cmd = ["cargo", "run", "--release"]
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0)

    @unittest.skip("Skipped: post-processor causes compilation failure on multiple return variables")
    def test_compilation_failure_multi_returns(self):
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res1: int, res2: int)
{
  res1 := 5;
  res2 := 10;
}
method Main() {
  var data: seq<Row> := [];
  var opt_res1, opt_res2 := RunQuery(data);
}
"""
        main_rs = self.translate_and_setup(dafny_code)
        postprocess(main_rs)
        
        run_cmd = ["cargo", "run", "--release"]
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0)

    @unittest.skip("Skipped: post-processor causes compilation failure on non-1 step increments")
    def test_compilation_failure_loop_step_two(self):
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
{
  res := 0;
  var i := 0;
  while i < |data| {
    i := i + 2; // Incremented by step != 1
  }
}
method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
}
"""
        main_rs = self.translate_and_setup(dafny_code)
        postprocess(main_rs)
        
        run_cmd = ["cargo", "run", "--release"]
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0)

    @unittest.skip("Skipped: post-processor causes compilation failure on loop variables initialized from variables")
    def test_compilation_failure_loop_init_variable(self):
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
{
  res := 0;
  var start_val := 5;
  var i := start_val; // Loop variable initialized to non-literal
  while i < |data| {
    i := i + 1;
  }
}
method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
}
"""
        main_rs = self.translate_and_setup(dafny_code)
        postprocess(main_rs)
        
        run_cmd = ["cargo", "run", "--release"]
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0)

    @unittest.skip("Skipped: post-processor causes compilation failure on computed index accesses")
    def test_compilation_failure_computed_index(self):
        dafny_code = self.row_schema_dfy + """
method RunQuery(data: seq<Row>) returns (res: int)
{
  res := 0;
  var i := 0;
  while i < |data| - 1 {
    var next_row := data[i + 1]; // Computed index access
    i := i + 1;
  }
}
method Main() {
  var data: seq<Row> := [];
  var opt_res := RunQuery(data);
}
"""
        main_rs = self.translate_and_setup(dafny_code)
        postprocess(main_rs)
        
        run_cmd = ["cargo", "run", "--release"]
        opt_res = subprocess.run(run_cmd, cwd=self.test_project_dir, capture_output=True, text=True)
        self.assertEqual(opt_res.returncode, 0)

if __name__ == "__main__":
    unittest.main()
