import unittest
import subprocess
import tempfile
import os
import sqlite3
import re
from sql_transpiler import transpile_sql_to_dafny, UnsupportedContractError, parse_sql

@unittest.skipIf(os.environ.get("RUN_SLOW") != "1", "Skipping slow Dafny functional tests. Run with RUN_SLOW=1 to execute.")
class TestTranspilerFunctional(unittest.TestCase):
    def setUp(self):
        # Set up a rich schema dictionary and dummy dataset for functional verification
        self.schema = {
            "category": "string",
            "value": "int",
            "age": "int",
            "name": "string"
        }
        
        self.dummy_data = [
            {"category": "A", "value": 10, "age": 20, "name": "Alice"},
            {"category": "B", "value": 20, "age": 30, "name": "Bob"},
            {"category": "A", "value": 30, "age": 25, "name": "Charlie"},
            {"category": "C", "value": 15, "age": 22, "name": "David"},
            {"category": "B", "value": 25, "age": 35, "name": "Eve"},
            {"category": "A", "value": 5, "age": 19, "name": "Frank"},
        ]

    def evaluate_query_python(self, query_str):
        query = parse_sql(query_str, self.schema)
        
        # Helper to evaluate math expression over a row
        def eval_expr(expr_str, row):
            expr_str = expr_str.replace('/', '//')
            tokens = re.split(r'(\b[a-zA-Z_][a-zA-Z0-9_]*\b)', expr_str)
            eval_parts = []
            for token in tokens:
                if not token:
                    continue
                if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', token):
                    # Resolve case-insensitively
                    col_key = None
                    for rk in row:
                        if rk.lower() == token.lower():
                            col_key = rk
                            break
                    if col_key is not None:
                        eval_parts.append(str(row[col_key]))
                    else:
                        raise ValueError(f"Unknown column: {token}")
                else:
                    eval_parts.append(token)
            return eval("".join(eval_parts))

        # 1. Filter rows
        filtered_rows = []
        for row in self.dummy_data:
            if query.where_expr_dafny:
                py_cond = query.where_expr_dafny.replace("!=", "__NEQ__")
                py_cond = py_cond.replace("&&", "and").replace("||", "or").replace("!", "not")
                py_cond = py_cond.replace("__NEQ__", "!=")
                py_cond = re.sub(r'\brow\.([a-zA-Z_][a-zA-Z0-9_]*)\b', r'row["\1"]', py_cond)
                keep = eval(py_cond, {"row": row})
            else:
                keep = True
            if keep:
                filtered_rows.append(row)
                
        # 2. Group by
        groups = {}
        if query.groupby_columns:
            for row in filtered_rows:
                if len(query.groupby_columns) == 1:
                    key = row[query.groupby_columns[0]]
                else:
                    key = tuple(row[col] for col in query.groupby_columns)
                groups.setdefault(key, []).append(row)
        else:
            groups[None] = filtered_rows
            
        # 3. Aggregate
        results = {}
        for gkey, g_rows in groups.items():
            if query.agg_type == 'COUNT':
                val = len(g_rows)
            elif query.agg_type == 'SUM':
                val = sum(eval_expr(query.agg_column, r) for r in g_rows)
            elif query.agg_type == 'AVG':
                s = sum(eval_expr(query.agg_column, r) for r in g_rows)
                c = len(g_rows)
                val = s // c if c > 0 else 0
            else:
                raise ValueError(f"Unknown aggregation: {query.agg_type}")
            results[gkey] = val
            
        if query.groupby_columns:
            return results
        else:
            return results[None]

    def verify_query(self, query_str):
        # 1. Get expected result from Python reference evaluation
        expected = self.evaluate_query_python(query_str)
        
        # 2. Transpile SQL to Dafny
        dafny_spec = transpile_sql_to_dafny(query_str, self.schema)
        
        # 3. Generate the full Dafny program with runner
        row_exprs = []
        for row in self.dummy_data:
            vals = []
            for col in self.schema:
                val = row[col]
                if self.schema[col] == 'int':
                    vals.append(str(val))
                elif self.schema[col] == 'string':
                    vals.append(f'"{val}"')
            row_exprs.append(f"Row({', '.join(vals)})")
            
        data_seq = f"[{', '.join(row_exprs)}]"
        
        print_lines = ['print "---BEGIN---", "\\n";']
        if isinstance(expected, dict):
            print_lines.append('print "size:", |res|, "\\n";')
            for key in expected:
                if isinstance(key, tuple):
                    print_args = []
                    for i, k in enumerate(key):
                        if i > 0:
                            print_args.append('","')
                        if isinstance(k, str):
                            print_args.append(f'"{k}"')
                        else:
                            print_args.append(str(k))
                    dafny_print_key = ", ".join(print_args)
                    tuple_elements = []
                    for k in key:
                        if isinstance(k, str):
                            tuple_elements.append(f'"{k}"')
                        else:
                            tuple_elements.append(str(k))
                    dafny_key = f"({', '.join(tuple_elements)})"
                else:
                    if isinstance(key, str):
                        dafny_print_key = f'"{key}"'
                        dafny_key = f'"{key}"'
                    else:
                        dafny_print_key = str(key)
                        dafny_key = str(key)
                
                print_lines.append(
                    f'print {dafny_print_key}, ":", if {dafny_key} in res then res[{dafny_key}] else -999999, "\\n";'
                )
        else:
            print_lines.append('print res, "\\n";')
        print_lines.append('print "---END---", "\\n";')
        
        prints_str = "\n  ".join(print_lines)
        
        dafny_code = f"""
{dafny_spec}

method Main() {{
  var data := {data_seq};
  var res := MethodSpec(data);
  {prints_str}
}}
"""
        # 4. Write to a temp file and execute dafny
        with tempfile.NamedTemporaryFile(suffix=".dfy", mode="w", delete=False) as tmp:
            tmp.write(dafny_code)
            tmp_name = tmp.name
            
        try:
            cmd = ["dafny", "run", "--target:py"]
            if not os.environ.get("VERIFY_DAFNY"):
                cmd.append("--no-verify")
            cmd.append(tmp_name)
            
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )
            if res.returncode != 0:
                self.fail(
                    f"Dafny compilation or execution failed for query: {query_str}\n"
                    f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
                )
            
            # 5. Parse output
            lines = res.stdout.splitlines()
            in_block = False
            block_lines = []
            for line in lines:
                line_str = line.strip()
                if line_str == "---BEGIN---":
                    in_block = True
                    continue
                elif line_str == "---END---":
                    in_block = False
                    break
                if in_block:
                    block_lines.append(line_str)
                    
            # 6. Assert correctness
            if isinstance(expected, dict):
                parsed_dict = {}
                size = None
                for line in block_lines:
                    if line.startswith("size:"):
                        size = int(line.split(":")[1])
                    else:
                        key_part, val_part = line.split(":", 1)
                        elements = key_part.split(",")
                        if len(elements) == 1:
                            try:
                                key = int(elements[0])
                            except ValueError:
                                key = elements[0]
                        else:
                            parsed_elements = []
                            for e in elements:
                                try:
                                    parsed_elements.append(int(e))
                                except ValueError:
                                    parsed_elements.append(e)
                            key = tuple(parsed_elements)
                        val = int(val_part)
                        parsed_dict[key] = val
                self.assertEqual(size, len(expected), f"Map size mismatch for query: {query_str}")
                self.assertEqual(parsed_dict, expected, f"Result mapping mismatch for query: {query_str}")
            else:
                self.assertTrue(len(block_lines) > 0, "No output found between markers")
                actual_val = int(block_lines[0])
                self.assertEqual(actual_val, expected, f"Scalar result mismatch for query: {query_str}")
                
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)

    def test_functional_basic_sum(self):
        self.verify_query("SELECT SUM(value) FROM my_table")

    def test_functional_basic_count(self):
        self.verify_query("SELECT COUNT(*) FROM my_table")

    def test_functional_basic_avg(self):
        self.verify_query("SELECT AVG(value) FROM my_table")

    def test_functional_sum_groupby_string(self):
        self.verify_query("SELECT category, SUM(value) FROM my_table GROUP BY category")

    def test_functional_avg_groupby_string(self):
        self.verify_query("SELECT category, AVG(value) FROM my_table GROUP BY category")

    def test_functional_sum_groupby_int(self):
        self.verify_query("SELECT age, SUM(value) FROM my_table GROUP BY age")

    def test_functional_where_filter_string(self):
        self.verify_query("SELECT SUM(value) FROM my_table WHERE category = 'A'")

    def test_functional_where_filter_int_inequality(self):
        self.verify_query("SELECT SUM(value) FROM my_table WHERE age > 21")

    def test_functional_where_multiple_conditions(self):
        self.verify_query("SELECT COUNT(*) FROM my_table WHERE category = 'A' AND age > 19 AND name != 'Frank'")

    def test_functional_empty_dataset(self):
        orig = self.dummy_data
        self.dummy_data = []
        try:
            # SUM on empty set
            self.verify_query("SELECT SUM(value) FROM my_table")
            # COUNT on empty set
            self.verify_query("SELECT COUNT(*) FROM my_table")
            # AVG on empty set
            self.verify_query("SELECT AVG(value) FROM my_table")
            # SUM GROUP BY on empty set
            self.verify_query("SELECT category, SUM(value) FROM my_table GROUP BY category")
        finally:
            self.dummy_data = orig

    def test_functional_alias_support(self):
        self.verify_query("SELECT SUM(value) AS val_alias FROM my_table")
        self.verify_query("SELECT category, AVG(value) avg_val FROM my_table GROUP BY category")

    def test_functional_arithmetic_expressions(self):
        self.verify_query("SELECT SUM(value * age) FROM my_table")
        self.verify_query("SELECT SUM(value * (100 - age) / 2) FROM my_table")
        self.verify_query("SELECT category, SUM(value * 2) FROM my_table GROUP BY category")

    def test_functional_operators_ge_le(self):
        self.verify_query("SELECT COUNT(*) FROM my_table WHERE age >= 21 AND value <= 100")
        self.verify_query("SELECT SUM(value) FROM my_table WHERE age <= 20")

    def test_functional_ssb_flat_style_query(self):
        # A star-schema-benchmark flat-style query
        self.verify_query(
            "SELECT SUM(value * age) AS total_val_age "
            "FROM my_table "
            "WHERE age >= 20 AND age <= 30 AND value >= 10"
        )

    def test_functional_multi_column_groupby(self):
        # Test grouping by multiple columns (category: string, age: int)
        self.verify_query(
            "SELECT category, age, SUM(value) "
            "FROM my_table "
            "GROUP BY category, age"
        )
        self.verify_query(
            "SELECT category, age, COUNT(*) "
            "FROM my_table "
            "GROUP BY category, age"
        )

    def test_functional_case_insensitivity(self):
        # Test query parsing and mapping with mixed casing
        self.verify_query(
            "SELECT CATEGORY, AGE, SUM(VALUE) "
            "FROM my_table "
            "WHERE AGE > 20 "
            "GROUP BY category, Age"
        )

    def test_functional_select_order(self):
        # Test that having the aggregate first in select doesn't fail
        self.verify_query(
            "SELECT SUM(value), category "
            "FROM my_table "
            "GROUP BY category"
        )

    def test_functional_negative_literals(self):
        self.verify_query("SELECT SUM(value * -2) FROM my_table")
        self.verify_query("SELECT SUM(value) FROM my_table WHERE age > -10")
        self.verify_query("SELECT SUM(value * -1) FROM my_table WHERE age >= -5 AND age <= 100")

    def test_functional_or_condition(self):
        # OR between two int predicates
        self.verify_query("SELECT SUM(value) FROM my_table WHERE age < 21 OR age > 30")
        # OR between two string predicates
        self.verify_query("SELECT COUNT(*) FROM my_table WHERE category = 'A' OR category = 'C'")
        # OR combined with AND
        self.verify_query("SELECT SUM(value) FROM my_table WHERE age > 25 OR category = 'A'")

    def test_functional_between(self):
        self.verify_query("SELECT SUM(value) FROM my_table WHERE age BETWEEN 20 AND 30")
        self.verify_query("SELECT COUNT(*) FROM my_table WHERE age BETWEEN 19 AND 25")
        self.verify_query("SELECT category, SUM(value) FROM my_table WHERE age BETWEEN 20 AND 30 GROUP BY category")

    def test_functional_in(self):
        self.verify_query("SELECT SUM(value) FROM my_table WHERE category IN ('A', 'C')")
        self.verify_query("SELECT COUNT(*) FROM my_table WHERE category IN ('B')")
        self.verify_query("SELECT category, SUM(value) FROM my_table WHERE category IN ('A', 'B') GROUP BY category")

    def test_functional_single_row_dataset(self):
        orig = self.dummy_data
        self.dummy_data = [{"category": "A", "value": 42, "age": 30, "name": "Solo"}]
        try:
            self.verify_query("SELECT SUM(value) FROM my_table")
            self.verify_query("SELECT COUNT(*) FROM my_table")
            self.verify_query("SELECT AVG(value) FROM my_table")
            self.verify_query("SELECT category, SUM(value) FROM my_table GROUP BY category")
        finally:
            self.dummy_data = orig

    def test_functional_all_filtered_within_group(self):
        # WHERE eliminates some groups — those keys absent from result map
        self.verify_query(
            "SELECT category, SUM(value) FROM my_table WHERE age > 28 GROUP BY category"
        )
        # WHERE eliminates all rows — empty map
        self.verify_query(
            "SELECT category, SUM(value) FROM my_table WHERE age > 999 GROUP BY category"
        )

    def test_functional_negative_grouped_sum(self):
        self.verify_query("SELECT category, SUM(value * -1) FROM my_table GROUP BY category")
        self.verify_query("SELECT category, SUM(value * -2) FROM my_table WHERE age > 20 GROUP BY category")

    def test_functional_ssb_query1(self):
        """Real SSB Query 1 run through Dafny against a minimal dataset."""
        from sql_transpiler import queries, schema as ssb_schema
        # Build a minimal dataset: 3 rows with all SSB columns present
        minimal_data = []
        for i in range(3):
            row = {col: (i + 1 if t == "int" else "AMERICA") for col, t in ssb_schema.items()}
            row["LO_ORDERDATE"] = 19930101 + i
            row["LO_DISCOUNT"] = 2
            row["LO_QUANTITY"] = 25
            row["LO_EXTENDEDPRICE"] = 1000
            row["D_YEAR"] = 1993
            minimal_data.append(row)
        orig_data, orig_schema = self.dummy_data, self.schema
        self.dummy_data = minimal_data
        self.schema = ssb_schema
        try:
            self.verify_query(queries[0])  # SSB Query 1
        finally:
            self.dummy_data, self.schema = orig_data, orig_schema

if __name__ == '__main__':
    unittest.main()

