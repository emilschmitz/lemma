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
        self.assertIn("datatype Row = Row(category: string, value: int, age: int, name: string)", result)
        self.assertIn("function MethodSpec(data: seq<Row>): int", result)
        self.assertIn("row.value + MethodSpec(tail)", result)

    def test_basic_count(self):
        sql = "SELECT COUNT(*) FROM my_table WHERE category = 'A'"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("datatype Row = Row(category: string, value: int, age: int, name: string)", result)
        self.assertIn("function MethodSpec(data: seq<Row>): int", result)
        self.assertIn("var term := if row.category == \"A\" then 1 else 0;", result)

    def test_avg_no_groupby(self):
        sql = "SELECT AVG(value) FROM my_table WHERE age > 18"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("function SumHelper(data: seq<Row>): int", result)
        self.assertIn("function CountHelper(data: seq<Row>): int", result)
        self.assertIn("function MethodSpec(data: seq<Row>): int", result)
        self.assertIn("var sum := SumHelper(data);", result)
        self.assertIn("var count := CountHelper(data);", result)
        self.assertIn("if count == 0 then 0 else sum / count", result)

    def test_sum_groupby(self):
        sql = "SELECT category, SUM(value) FROM my_table GROUP BY category"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("function MethodSpec(data: seq<Row>): map<string, int>", result)
        self.assertIn("var key := row.category;", result)
        self.assertIn("tailMap[key := val + row.value]", result)

    def test_avg_groupby(self):
        sql = "SELECT category, AVG(value) FROM my_table GROUP BY category"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("function SumMapHelper(data: seq<Row>): map<string, int>", result)
        self.assertIn("function CountMapHelper(data: seq<Row>): map<string, int>", result)
        self.assertIn("function MethodSpec(data: seq<Row>): map<string, int>", result)
        self.assertIn("map k | k in sums && k in counts :: if counts[k] == 0 then 0 else sums[k] / counts[k]", result)

    def test_groupby_int_key(self):
        sql = "SELECT age, SUM(value) FROM my_table GROUP BY age"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("function MethodSpec(data: seq<Row>): map<int, int>", result)
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
        self.assertIn("datatype Row = Row(category: string, value: int, age: int, name: string)", result)
        self.assertIn("function MethodSpec(data: seq<Row>): int", result)
        self.assertIn("row.value + MethodSpec(tail)", result)

        sql_implicit = "SELECT SUM(value) val_alias FROM my_table"
        result_implicit = transpile_sql_to_dafny(sql_implicit, self.schema)
        self.assertIn("row.value + MethodSpec(tail)", result_implicit)

    def test_arithmetic_expressions(self):
        sql = "SELECT SUM(value * age) FROM my_table"
        result = transpile_sql_to_dafny(sql, self.schema)
        self.assertIn("row.value * row.age + MethodSpec(tail)", result)

        sql_complex = "SELECT SUM(value * (100 - age) / 2) FROM my_table"
        result_complex = transpile_sql_to_dafny(sql_complex, self.schema)
        self.assertIn("row.value * (100 - row.age) / 2 + MethodSpec(tail)", result_complex)

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
        self.assertIn("function MethodSpec(data: seq<Row>): map<(string, int), int>", result)
        self.assertIn("var key := (row.category, row.age);", result)
        self.assertIn("tailMap[key := val + row.value]", result)

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
        self.assertIn("row.value * -2", result)
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

if __name__ == '__main__':
    unittest.main()
