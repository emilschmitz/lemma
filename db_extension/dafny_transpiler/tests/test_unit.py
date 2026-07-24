import unittest
from sql_transpiler import transpile_sql_to_dafny, UnsupportedContractError

class TestTranspilerUnit(unittest.TestCase):
    def setUp(self):
        # Set up a standard schema dictionary for testing
        self.schema = {
            "category": "string",
            "value": "int",
            "age": "int",
            "name": "string"
        }

    def test_basic_sum(self):
        sql = "SELECT SUM(value) FROM my_table"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("datatype Row = Row(category: string, value: bv32, age: bv32, name: string)", result)
        self.assertIn("function {:verify false} MethodSpec(data: seq<Row>): int", result)
        self.assertIn("(row.value as int) + MethodSpec(tail)", result)

    def test_basic_count(self):
        sql = "SELECT COUNT(*) FROM my_table WHERE category = 'A'"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("datatype Row = Row(category: string, value: bv32, age: bv32, name: string)", result)
        self.assertIn("function {:verify false} MethodSpec(data: seq<Row>): int", result)
        self.assertIn("var term := if row.category == \"A\" then 1 else 0;", result)

    def test_avg_no_groupby(self):
        sql = "SELECT AVG(value) FROM my_table WHERE age > 18"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("function SumHelper(data: seq<Row>): int", result)
        self.assertIn("function CountHelper(data: seq<Row>): int", result)
        self.assertIn("function {:verify false} MethodSpec(data: seq<Row>): int", result)
        self.assertIn("var sum := SumHelper(data);", result)
        self.assertIn("var count := CountHelper(data);", result)
        self.assertIn("if count == 0 then 0 else sum / count", result)

    def test_sum_groupby(self):
        sql = "SELECT category, SUM(value) FROM my_table GROUP BY category"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("function {:verify false} MethodSpec(data: seq<Row>): map<string, int>", result)
        self.assertIn("var key := row.category;", result)
        self.assertIn("tailMap[key := val + (row.value as int)]", result)

    def test_avg_groupby(self):
        sql = "SELECT category, AVG(value) FROM my_table GROUP BY category"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("function SumMapHelper(data: seq<Row>): map<string, int>", result)
        self.assertIn("function CountMapHelper(data: seq<Row>): map<string, int>", result)
        self.assertIn("function {:verify false} MethodSpec(data: seq<Row>): map<string, int>", result)
        self.assertIn("map k | k in sums && k in counts :: if counts[k] == 0 then 0 else sums[k] / counts[k]", result)

    def test_groupby_int_key(self):
        sql = "SELECT age, SUM(value) FROM my_table GROUP BY age"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("function {:verify false} MethodSpec(data: seq<Row>): map<bv32, int>", result)
        self.assertIn("var key := row.age;", result)

    def test_where_multiple_conditions(self):
        sql = "SELECT SUM(value) FROM my_table WHERE category = 'A' AND age > 21 AND name != 'Bob'"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn('row.category == "A"', result)
        self.assertIn('row.age > 21', result)
        self.assertIn('row.name != "Bob"', result)

    def test_unsupported_queries(self):
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT SUM(value) FROM my_table JOIN other_table", self.schema)
        
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT SUM(value) FROM my_table WHERE value > (SELECT AVG(value) FROM my_table)", self.schema)

        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT MIN(value) FROM my_table", self.schema)

        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT SUM(non_existent) FROM my_table", self.schema)

        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT SUM(category) FROM my_table", self.schema)

        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT SUM(value) FROM my_table WHERE value = 'A'", self.schema)

        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT SUM(value) FROM my_table WHERE category > 'A'", self.schema)

        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT SUM(value) FROM my_table, other_table", self.schema)

        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT category, SUM(value) FROM my_table GROUP BY category, age", self.schema)

    def test_alias_support(self):
        sql = "SELECT SUM(value) AS val_alias FROM my_table"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("datatype Row = Row(category: string, value: bv32, age: bv32, name: string)", result)
        self.assertIn("function {:verify false} MethodSpec(data: seq<Row>): int", result)
        self.assertIn("(row.value as int) + MethodSpec(tail)", result)

        sql_implicit = "SELECT SUM(value) val_alias FROM my_table"
        result_implicit = transpile_sql_to_dafny(sql_implicit, self.schema)
        self.assertIn("(row.value as int) + MethodSpec(tail)", result_implicit)

    def test_arithmetic_expressions(self):
        sql = "SELECT SUM(value * age) FROM my_table"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("(row.value as int) * (row.age as int) + MethodSpec(tail)", result)

        sql_complex = "SELECT SUM(value * (100 - age) / 2) FROM my_table"
        result_complex = transpile_sql_to_dafny(sql_complex, self.schema)
        self.assertIn("(row.value as int) * (100 - (row.age as int)) / 2 + MethodSpec(tail)", result_complex)

    def test_ge_le_operators(self):
        sql = "SELECT COUNT(*) FROM my_table WHERE age >= 21 AND value <= 100"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("row.age >= 21 && row.value <= 100", result)

    def test_invalid_expressions_unsupported(self):
        # Non-int columns in math
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT SUM(value * category) FROM my_table", self.schema)
        
        # Invalid characters
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT SUM(value @ age) FROM my_table", self.schema)

    def test_multi_column_groupby(self):
        sql = "SELECT category, age, SUM(value) FROM my_table GROUP BY category, age"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("function {:verify false} MethodSpec(data: seq<Row>): map<(string, bv32), int>", result)
        self.assertIn("var key := (row.category, row.age);", result)
        self.assertIn("tailMap[key := val + (row.value as int)]", result)

    def test_division_by_zero_fails(self):
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT SUM(value / 0) FROM my_table", self.schema)
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT SUM(value / -0) FROM my_table", self.schema)

    def test_duplicate_groupby_fails(self):
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny("SELECT category, SUM(value) FROM my_table GROUP BY category, Category", self.schema)

    def test_negative_literals(self):
        sql = "SELECT SUM(value * -2) FROM my_table WHERE age > -5"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("(row.value as int) * -2", result)
        self.assertIn("row.age > -5", result)

    def test_between_compiles_to_conjunction(self):
        sql = "SELECT SUM(value) FROM my_table WHERE age BETWEEN 20 AND 30"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("row.age >= 20", result)
        self.assertIn("row.age <= 30", result)

    def test_in_compiles_to_disjunction(self):
        sql = "SELECT SUM(value) FROM my_table WHERE category IN ('A', 'B')"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn('row.category == "A"', result)
        self.assertIn('row.category == "B"', result)
        self.assertIn("||", result)

    def test_or_condition(self):
        sql = "SELECT SUM(value) FROM my_table WHERE age < 20 OR age > 30"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("row.age < 20", result)
        self.assertIn("row.age > 30", result)
        self.assertIn("||", result)

    def test_between_string_column_rejected(self):
        # BETWEEN on a string column should raise — strings have no ordering in Dafny
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny(
                "SELECT SUM(value) FROM my_table WHERE name BETWEEN 'A' AND 'Z'",
                self.schema
            )

    def test_in_type_mismatch_rejected(self):
        # IN with int column but string values should raise
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny(
                "SELECT SUM(value) FROM my_table WHERE age IN ('A', 'B')",
                self.schema
            )
        # IN with string column but int values should raise
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny(
                "SELECT SUM(value) FROM my_table WHERE category IN (1, 2)",
                self.schema
            )

    def test_in_empty_list_rejected(self):
        # IN () is degenerate SQL — should raise rather than emit invalid Dafny
        with self.assertRaises(UnsupportedContractError):
            transpile_sql_to_dafny(
                "SELECT SUM(value) FROM my_table WHERE category IN ()",
                self.schema
            )

    def test_columnar_valid_cols_global_bounds(self):
        from sql_transpiler import transpile_sql_to_dafny_columnar

        schema = {
            "qty": "int",
            "amount": "bigint",
            "label": "string",
        }
        result = transpile_sql_to_dafny_columnar(
            "SELECT SUM(amount) FROM t WHERE qty > 0",
            schema,
        )
        self.assertIn("const LemmaMaxRows: int :=", result)
        self.assertIn("const LemmaMaxNativeU32: int :=", result)
        self.assertIn("const LemmaMaxMoneyU64: int :=", result)
        self.assertIn("const LemmaMaxStringLen: int :=", result)
        self.assertIn("0 <= cols.n() <= LemmaMaxRows", result)
        self.assertIn("(cols.Getqty(i) as int) < LemmaMaxNativeU32", result)
        self.assertIn("(cols.Getamount(i) as int) < LemmaMaxMoneyU64", result)
        self.assertIn("|cols.Getlabel(i)| <= LemmaMaxStringLen", result)

    def test_columnar_agg_push_two_key_u32_string(self):
        from sql_transpiler import generate_cols_native_rs, transpile_sql_to_dafny_columnar

        schema = {
            "yr": "int",
            "brand": "string",
            "rev": "bigint",
        }
        sql = "SELECT yr, brand, SUM(rev) FROM t GROUP BY yr, brand"
        result = transpile_sql_to_dafny_columnar(sql, schema)
        self.assertIn("method {:extern} {:axiom} AggPush_yr_brand(agg: NativeAggMap", result)
        self.assertIn("cols.AggPush_yr_brand(agg, i, term)", result)

        rs = generate_cols_native_rs(schema, sql_str=sql)
        self.assertIn("pub fn AggPush_yr_brand", rs)
        self.assertIn("agg.AddStrKey(self.yr[i], self.brand[i].as_str(), delta)", rs)

        rs_no_group = generate_cols_native_rs(schema)
        self.assertNotIn("AggPush_yr_brand", rs_no_group)

    def test_columnar_agg_push_str_two_key_string_string(self):
        from sql_transpiler import generate_cols_native_rs, transpile_sql_to_dafny_columnar

        schema = {
            "flag": "varchar",
            "status": "varchar",
            "qty": "integer",
        }
        sql = "SELECT flag, status, SUM(qty) FROM t GROUP BY flag, status"
        result = transpile_sql_to_dafny_columnar(sql, schema)
        self.assertIn(
            "method {:extern} {:axiom} AggPushStr_flag_status(agg: NativeAggStrMap",
            result,
        )
        self.assertIn("NativeAggStrMap", result)

        rs = generate_cols_native_rs(schema, sql_str=sql)
        self.assertIn("pub fn AggPushStr_flag_status", rs)
        self.assertIn(
            "agg.AddStrPair(self.flag[i].as_str(), self.status[i].as_str(), delta)",
            rs,
        )

        rs_no_group = generate_cols_native_rs(schema)
        self.assertNotIn("AggPushStr_flag_status", rs_no_group)

    def test_column_projection_from_sql(self):
        from sql_transpiler import columns_used_by_query, project_schema_for_query, generate_cols_native_rs

        schema = {
            "A": "integer",
            "B": "varchar",
            "C": "bigint",
            "D": "varchar",
        }
        sql = "SELECT B, SUM(A) FROM t WHERE C > 0 GROUP BY B"
        used = columns_used_by_query(sql, schema)
        self.assertEqual(used, {"A", "B", "C"})
        projected = project_schema_for_query(sql, schema)
        self.assertEqual(set(projected.keys()), {"A", "B", "C"})
        rs = generate_cols_native_rs(projected, sql_str=sql)
        self.assertIn("pub a: Arc<Vec<u32>>", rs)
        self.assertIn("pub b: Arc<Vec<String>>", rs)
        self.assertIn("pub c: Arc<Vec<u64>>", rs)
        self.assertNotIn("pub d:", rs)

if __name__ == '__main__':
    unittest.main()
