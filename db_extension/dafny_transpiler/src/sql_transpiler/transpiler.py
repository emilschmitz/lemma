import os
import re
import sqlglot
from sqlglot import exp

from .value_bounds import (
    emit_bound_constants,
    emit_bound_lemmas,
    emit_valid_cols_accessor_lemmas,
    emit_valid_cols_predicate,
)

class UnsupportedContractError(Exception):
    """Raised when a SQL query falls outside the supported dashboard subset."""
    pass


# High-level types we distinguish in the transpiler.  DuckDB exposes many
# concrete names (INTEGER, BIGINT, VARCHAR, …); we collapse them to these
# two buckets because that's all the SQL→Dafny spec cares about.  Width
# (bv32 vs bv64) is decided later by `get_dafny_type`.
_INT_TYPES = frozenset({
    'int', 'integer', 'int4', 'int32', 'int2', 'smallint', 'int16',
    'int8', 'int64', 'bigint', 'hugeint', 'tinyint', 'int1',
    'usmallint', 'utinyint', 'uinteger', 'ubigint',
    'date',
    'decimal', 'numeric', 'double', 'float8', 'float', 'real',
})
_STRING_TYPES = frozenset({'string', 'varchar', 'text', 'char', 'bpchar'})


def _kind_of(col_type: str) -> str:
    """Collapse a DuckDB catalog type to 'int', 'string', or raise."""
    t = col_type.lower()
    if t in _INT_TYPES or t.split('(')[0] in _INT_TYPES:
        return 'int'
    if t in _STRING_TYPES or t.split('(')[0] in _STRING_TYPES:
        return 'string'
    raise UnsupportedContractError(f"Unrecognized column type {col_type!r}")

class DafnyLiteral:
    """Represents a literal value or a raw code fragment in Dafny."""
    def __init__(self, value: str):
        self.value = value

    def to_dafny(self) -> str:
        return str(self.value)

class DafnyIf:
    """Represents an if-then-else expression in Dafny."""
    def __init__(self, condition: str, then_expr, else_expr):
        self.condition = condition
        self.then_expr = then_expr
        self.else_expr = else_expr

    def to_dafny(self) -> str:
        then_str = self.then_expr.to_dafny() if hasattr(self.then_expr, 'to_dafny') else str(self.then_expr)
        else_str = self.else_expr.to_dafny() if hasattr(self.else_expr, 'to_dafny') else str(self.else_expr)
        return f"if {self.condition} then {then_str} else {else_str}"

class DafnyFunction:
    """Represents a mathematical function definition in Dafny."""
    def __init__(self, name: str, params: list[tuple[str, str]], return_type: str, body,
                 attrs: str = ""):
        self.name = name
        self.params = params  # list of (name, type)
        self.return_type = return_type
        self.body = body
        self.attrs = attrs  # e.g. "{:verify false}" — inserted after `function Name`

    def to_dafny(self) -> str:
        params_str = ", ".join(f"{name}: {type_}" for name, type_ in self.params)
        body_str = self.body.to_dafny() if hasattr(self.body, 'to_dafny') else str(self.body)
        attrs = f" {self.attrs}" if self.attrs else ""
        # Indent the body nicely
        indented_body = "\n".join("  " + line for line in body_str.split("\n"))
        return (
            f"function{attrs} {self.name}({params_str}): {self.return_type}\n"
            f"{{\n"
            f"{indented_body}\n"
            f"}}"
        )

class SQLQuery:
    """AST representation of a supported SQL query."""
    def __init__(self):
        self.table: str = ""
        self.agg_type: str = ""  # SUM, COUNT, AVG
        self.agg_column: str = ""  # Column name or "*"
        self.groupby_columns: list[str] = []
        self.where_conditions: list[tuple[str, str, any, str]] = []  # list of (col, op, val, val_type)
        self.agg_expr_dafny: str = ""
        self.where_expr_dafny: str = ""

    @property
    def groupby_column(self) -> str:
        return self.groupby_columns[0] if self.groupby_columns else None

    @groupby_column.setter
    def groupby_column(self, val: str):
        if val:
            self.groupby_columns = [val]
        else:
            self.groupby_columns = []

def parse_sql(sql_str: str, schema_dict: dict[str, str]) -> SQLQuery:
    """Parses a SQL statement within the supported dashboard contract boundary using sqlglot."""
    # Build a case-insensitive schema mapping to match columns correctly and preserve their original case
    schema_resolved = {k.lower(): (k, v) for k, v in schema_dict.items()}

    try:
        expression = sqlglot.parse_one(sql_str)
    except Exception as e:
        raise UnsupportedContractError(f"Query parsing failed: {e}")

    if not isinstance(expression, exp.Select):
        raise UnsupportedContractError("Query falls outside the supported dashboard subset.")

    # 1. Check for forbidden node types (JOINs, UNIONs, subqueries, complex predicates)
    for node in expression.walk():
        if isinstance(node, (
            exp.Join, exp.Union, exp.Subquery, exp.Having, exp.Order, 
            exp.Limit, exp.Exists, exp.Like,
            exp.Max, exp.Min, exp.Distinct
        )):
            raise UnsupportedContractError("Query falls outside the supported dashboard subset.")

    # 2. FROM clause validation
    from_clause = expression.args.get("from_")
    if not from_clause:
        raise UnsupportedContractError("Query must have a FROM clause.")
    if not isinstance(from_clause.this, exp.Table):
        raise UnsupportedContractError("Query falls outside the supported dashboard subset.")
    table_name = from_clause.this.name

    query = SQLQuery()
    query.table = table_name

    # 3. GROUP BY clause validation
    groupby_clause = expression.args.get("group")
    if groupby_clause:
        groupby_exprs = groupby_clause.expressions
        for groupby_node in groupby_exprs:
            if not isinstance(groupby_node, exp.Column):
                raise UnsupportedContractError("Query falls outside the supported dashboard subset.")
            groupby_col_lower = groupby_node.name.lower()
            if groupby_col_lower not in schema_resolved:
                raise UnsupportedContractError(f"Group by column '{groupby_node.name}' not found in schema.")
            groupby_col_canonical = schema_resolved[groupby_col_lower][0]
            if groupby_col_canonical in query.groupby_columns:
                raise UnsupportedContractError("Duplicate group-by columns are not supported.")
            query.groupby_columns.append(groupby_col_canonical)

    # Helper to strip alias
    def unwrap_alias(node):
        if isinstance(node, exp.Alias):
            return node.this
        return node

    # 4. SELECT items validation
    select_items = expression.expressions
    if query.groupby_columns:
        # Number of select items must equal number of groupby columns + 1 (for the aggregate)
        if len(select_items) != len(query.groupby_columns) + 1:
            raise UnsupportedContractError("Query falls outside the supported dashboard subset.")
        unwrapped = [unwrap_alias(item) for item in select_items]
        
        # Verify that all groupby columns are present, and exactly one aggregate is present
        select_cols = set()
        agg_node = None
        for item in unwrapped:
            if isinstance(item, exp.Column):
                col_lower = item.name.lower()
                if col_lower in schema_resolved:
                    select_cols.add(schema_resolved[col_lower][0])
            elif isinstance(item, (exp.Sum, exp.Count, exp.Avg)):
                agg_node = item
        
        if not agg_node or select_cols != set(query.groupby_columns):
            raise UnsupportedContractError("Query select clause must include all group by columns and the aggregate.")
    else:
        if len(select_items) != 1:
            raise UnsupportedContractError("Query falls outside the supported dashboard subset.")
        agg_node = unwrap_alias(select_items[0])
        if not isinstance(agg_node, (exp.Sum, exp.Count, exp.Avg)):
            raise UnsupportedContractError("Query falls outside the supported dashboard subset.")

    # Helper to recursively compile expression to Dafny
    def to_dafny_expr(node):
        if isinstance(node, exp.Column):
            col_lower = node.name.lower()
            if col_lower not in schema_resolved:
                raise UnsupportedContractError(f"Identifier '{node.name}' not found in schema.")
            real_col, col_type = schema_resolved[col_lower]
            if _kind_of(col_type) != 'int':
                raise UnsupportedContractError(f"Column '{real_col}' in expression must be of type 'int'.")
            return f"(row.{real_col} as int)"
        elif isinstance(node, exp.Literal):
            if node.is_number and node.this.isdigit():
                return str(node.this)
            raise UnsupportedContractError(f"Only integer literals supported in expressions.")
        elif isinstance(node, exp.Neg):
            return f"-{to_dafny_expr(node.this)}"
        elif isinstance(node, exp.Paren):
            return f"({to_dafny_expr(node.this)})"
        elif isinstance(node, exp.Mul):
            return f"{to_dafny_expr(node.left)} * {to_dafny_expr(node.right)}"
        elif isinstance(node, exp.Div):
            # Check for division by zero literal
            if isinstance(node.right, exp.Literal) and node.right.this == "0":
                raise UnsupportedContractError("Division by zero literal is not supported.")
            if isinstance(node.right, exp.Neg) and isinstance(node.right.this, exp.Literal) and node.right.this.this == "0":
                raise UnsupportedContractError("Division by zero literal is not supported.")
            return f"{to_dafny_expr(node.left)} / {to_dafny_expr(node.right)}"
        elif isinstance(node, exp.Add):
            return f"{to_dafny_expr(node.left)} + {to_dafny_expr(node.right)}"
        elif isinstance(node, exp.Sub):
            return f"{to_dafny_expr(node.left)} - {to_dafny_expr(node.right)}"
        elif isinstance(node, exp.Star):
            return "*"
        else:
            raise UnsupportedContractError(f"Unsupported expression construct: {type(node)}")

    # Parse and validate aggregation node
    if isinstance(agg_node, exp.Count):
        query.agg_type = "COUNT"
        if isinstance(agg_node.this, exp.Star):
            query.agg_column = "*"
            query.agg_expr_dafny = "1"
        else:
            if not isinstance(agg_node.this, exp.Column):
                raise UnsupportedContractError("COUNT argument must be * or a column.")
            col_lower = agg_node.this.name.lower()
            if col_lower not in schema_resolved:
                raise UnsupportedContractError(f"Aggregate column '{agg_node.this.name}' not found in schema.")
            real_col, _ = schema_resolved[col_lower]
            query.agg_column = real_col
            query.agg_expr_dafny = "1"
    else:
        query.agg_type = "SUM" if isinstance(agg_node, exp.Sum) else "AVG"
        query.agg_expr_dafny = to_dafny_expr(agg_node.this)
        # Preserve original sql string for functional test runner compatibility
        query.agg_column = agg_node.this.sql()

    # 5. Parse WHERE clause
    where_clause = expression.args.get("where")
    if where_clause:
        def compile_where_expr(node):
            if isinstance(node, exp.And):
                return f"({compile_where_expr(node.left)} && {compile_where_expr(node.right)})"
            elif isinstance(node, exp.Or):
                return f"({compile_where_expr(node.left)} || {compile_where_expr(node.right)})"
            elif isinstance(node, exp.Not):
                return f"!({compile_where_expr(node.this)})"
            elif isinstance(node, exp.Between):
                # Type guard: BETWEEN only makes sense for int columns
                if not isinstance(node.this, exp.Column):
                    raise UnsupportedContractError("BETWEEN left-hand side must be a column.")
                col_lower = node.this.name.lower()
                if col_lower not in schema_resolved:
                    raise UnsupportedContractError(f"BETWEEN column '{node.this.name}' not found in schema.")
                _, col_type = schema_resolved[col_lower]
                if _kind_of(col_type) != 'int':
                    raise UnsupportedContractError(
                        f"BETWEEN is only supported on int columns, not '{col_type}'.")
                low_val = compile_where_expr(node.args.get("low"))
                high_val = compile_where_expr(node.args.get("high"))
                this_val = compile_where_expr(node.this)
                return f"({this_val} >= {low_val} && {this_val} <= {high_val})"
            elif isinstance(node, exp.In):
                if not node.expressions:
                    raise UnsupportedContractError("IN () with empty list is not supported.")
                # Determine column type for validation
                if not isinstance(node.this, exp.Column):
                    raise UnsupportedContractError("IN left-hand side must be a column.")
                col_lower = node.this.name.lower()
                if col_lower not in schema_resolved:
                    raise UnsupportedContractError(f"IN column '{node.this.name}' not found in schema.")
                _, col_type = schema_resolved[col_lower]
                this_val = compile_where_expr(node.this)
                eqs = []
                for val_node in node.expressions:
                    val_str = compile_where_expr(val_node)
                    # Type-check each element
                    if isinstance(val_node, exp.Literal):
                        elem_type = 'string' if val_node.is_string else 'int'
                    elif isinstance(val_node, exp.Neg):
                        elem_type = 'int'
                    else:
                        elem_type = col_type  # column ref — assume matches
                    if elem_type != col_type:
                        raise UnsupportedContractError(
                            f"Type mismatch in IN list: column '{node.this.name}' is {col_type} "
                            f"but value {val_str!r} is {elem_type}.")
                    eqs.append(f"{this_val} == {val_str}")
                return f"({' || '.join(eqs)})"
            elif isinstance(node, (exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE)):
                op_map = {
                    exp.EQ: '==',
                    exp.NEQ: '!=',
                    exp.GT: '>',
                    exp.LT: '<',
                    exp.GTE: '>=',
                    exp.LTE: '<='
                }
                op = op_map[type(node)]
                
                # Check left side column
                if not isinstance(node.left, exp.Column):
                    raise UnsupportedContractError("Left hand side of comparison must be a column.")
                col_lower = node.left.name.lower()
                if col_lower not in schema_resolved:
                    raise UnsupportedContractError(f"Filter column '{node.left.name}' not found in schema.")
                real_col, col_type = schema_resolved[col_lower]
                
                # Check right side
                right_node = node.right
                if isinstance(right_node, exp.Literal):
                    if right_node.is_string:
                        val_resolved = f'"{right_node.this}"'
                        val_type = 'string'
                    elif right_node.is_number and right_node.this.isdigit():
                        val_resolved = str(right_node.this)
                        val_type = 'int'
                    else:
                        raise UnsupportedContractError("Query falls outside the supported dashboard subset.")
                elif isinstance(right_node, exp.Neg) and isinstance(right_node.this, exp.Literal):
                    neg_lit = right_node.this
                    if neg_lit.is_number and neg_lit.this.isdigit():
                        val_resolved = f"-{neg_lit.this}"
                        val_type = 'int'
                    else:
                        raise UnsupportedContractError("Query falls outside the supported dashboard subset.")
                elif isinstance(right_node, exp.Column):
                    rcol_lower = right_node.name.lower()
                    if rcol_lower not in schema_resolved:
                        raise UnsupportedContractError(f"Filter column '{right_node.name}' not found in schema.")
                    rreal_col, rcol_type = schema_resolved[rcol_lower]
                    val_resolved = f"row.{rreal_col}"
                    val_type = rcol_type
                else:
                    raise UnsupportedContractError("Query falls outside the supported dashboard subset.")
                
                # Type checking comparison
                kind = _kind_of(col_type)
                if kind == 'int':
                    if val_type != 'int':
                        raise UnsupportedContractError(f"Type mismatch: comparing int column '{real_col}' with non-int value.")
                elif kind == 'string':
                    if val_type != 'string':
                        raise UnsupportedContractError(f"Type mismatch: comparing string column '{real_col}' with non-string value.")
                    if op not in ('==', '!='):
                        raise UnsupportedContractError(f"Unsupported operator '{op}' for string type comparison.")
                
                # Append to where_conditions list for compatibility
                op_sql = '=' if op == '==' else op
                if isinstance(right_node, exp.Literal):
                    val_raw = right_node.this
                    val_t = 'string' if right_node.is_string else 'int'
                elif isinstance(right_node, exp.Neg) and isinstance(right_node.this, exp.Literal):
                    val_raw = -int(right_node.this.this)
                    val_t = 'int'
                else:
                    val_raw = right_node.name
                    val_t = 'column'
                query.where_conditions.append((real_col, op_sql, val_raw, val_t))
                
                return f"row.{real_col} {op} {val_resolved}"
            elif isinstance(node, exp.Literal):
                if node.is_string:
                    return f'"{node.this}"'
                elif node.is_number and node.this.isdigit():
                    return str(node.this)
                raise UnsupportedContractError("Unsupported literal type.")
            elif isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal):
                if node.this.is_number and node.this.isdigit():
                    return f"-{node.this}"
                raise UnsupportedContractError("Unsupported negative literal.")
            elif isinstance(node, exp.Column):
                col_lower = node.name.lower()
                if col_lower not in schema_resolved:
                    raise UnsupportedContractError(f"Identifier '{node.name}' not found in schema.")
                real_col, col_type = schema_resolved[col_lower]
                return f"row.{real_col}"
            elif isinstance(node, exp.Paren):
                return f"({compile_where_expr(node.this)})"
            else:
                raise UnsupportedContractError(f"Unsupported node in filter expression: {type(node)}")

        query.where_expr_dafny = compile_where_expr(where_clause.this)

    return query

def get_dafny_type(col: str, col_type: str) -> str:
    """Maps SQL column types to bounded native Dafny newtypes (compile to Rust primitives)."""
    col_type_lower = col_type.lower()
    if col_type_lower in ('bigint', 'int8', 'int64', 'hugeint',
                          'decimal', 'numeric', 'double', 'float8', 'float', 'real'):
        return 'NativeU64'
    if col_type_lower in ('integer', 'int4', 'int32', 'int',
                          'smallint', 'int2', 'int16',
                          'tinyint', 'int1',
                          'usmallint', 'utinyint', 'uinteger', 'ubigint',
                          'date'):
        return 'NativeU32'
    if col_type_lower in ('varchar', 'text', 'string', 'char', 'bpchar'):
        return 'string'
    raise UnsupportedContractError(f"Cannot map SQL type {col_type!r} (column {col!r}) to a Dafny type.")


def _native_preamble() -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    native_path = os.path.join(repo_root, "research_loop", "native.dfy")
    if os.path.exists(native_path):
        with open(native_path) as f:
            return f.read().strip() + "\n\n"
    return (
        'newtype {:extern "u32"} NativeU32 = x: int | 0 <= x < 4294967296\n'
        'newtype {:extern "u64"} NativeU64 = x: int | 0 <= x < 18446744073709551616\n'
        'newtype {:extern "i64"} NativeI64 = x: int | -9223372036854775808 <= x < 9223372036854775808\n\n'
    )


def _agg_value_type(agg_expr: str) -> str:
    """Native accumulator type for map/scalar aggregates."""
    return 'NativeI64' if '-' in agg_expr else 'NativeU64'


def transpile_sql_to_dafny(sql_str: str, schema_dict: dict[str, str]) -> str:
    """Translates SQL query to mathematical Dafny specification."""
    # 1. Parse and validate schema
    supported_types = (
        'int', 'string', 'bigint', 'int8', 'int64', 'integer', 'int4', 'int32',
        'varchar', 'text'
    )
    for col, col_type in schema_dict.items():
        if col_type.lower() not in supported_types:
            raise UnsupportedContractError(f"Unsupported column type in schema: {col_type}")

    # 2. Parse SQL
    query = parse_sql(sql_str, schema_dict)

    # 3. Generate schema datatype representation
    fields = [f"{col}: {get_dafny_type(col, schema_dict[col])}" for col in schema_dict]
    fields_str = ", ".join(fields)
    schema_dafny = f"datatype Row = Row({fields_str})"

    # 4. Determine key variables
    val_type = _agg_value_type(query.agg_expr_dafny)
    if query.groupby_columns:
        types = [get_dafny_type(col, schema_dict[col]) for col in query.groupby_columns]
        if len(query.groupby_columns) == 1:
            key_type = types[0]
            ret_type = f"map<{key_type}, {val_type}>"
            key_expr = f"row.{query.groupby_columns[0]}"
        else:
            ret_type = f"map<({', '.join(types)}), {val_type}>"
            key_expr = f"({', '.join(f'row.{col}' for col in query.groupby_columns)})"
    else:
        ret_type = val_type
        key_expr = None
    
    # Construct WHERE clause condition for row
    where_expr = query.where_expr_dafny if query.where_expr_dafny else None

    # Helper function to generate a SUM or COUNT recursive body
    def make_recursive_body(func_name: str, is_sum: bool, return_type: str):
        cond = "|data| == 0"
        then_val = "map[]" if "map" in return_type else f"0 as {return_type}"
        term_expr = query.agg_expr_dafny if is_sum else "1"

        if query.groupby_columns:
            if where_expr:
                else_body = (
                    f"var tailMap := {func_name}(data[1..]);\n"
                    f"var row := data[0];\n"
                    f"if {where_expr} then\n"
                    f"  var key := {key_expr};\n"
                    f"  var val := if key in tailMap then tailMap[key] else (0 as {val_type});\n"
                    f"  tailMap[key := val + ({term_expr}) as {val_type}]\n"
                    f"else\n"
                    f"  tailMap"
                )
            else:
                else_body = (
                    f"var tailMap := {func_name}(data[1..]);\n"
                    f"var row := data[0];\n"
                    f"var key := {key_expr};\n"
                    f"var val := if key in tailMap then tailMap[key] else (0 as {val_type});\n"
                    f"tailMap[key := val + ({term_expr}) as {val_type}]"
                )
        else:
            cast_term = f"({term_expr}) as {return_type}"
            if where_expr:
                else_body = (
                    f"var row := data[0];\n"
                    f"var tail := data[1..];\n"
                    f"var term := if {where_expr} then {cast_term} else (0 as {return_type});\n"
                    f"((term as int) + ({func_name}(tail) as int)) as {return_type}"
                )
            else:
                else_body = (
                    f"var row := data[0];\n"
                    f"var tail := data[1..];\n"
                    f"(({cast_term} as int) + ({func_name}(tail) as int)) as {return_type}"
                )

        return DafnyIf(cond, DafnyLiteral(then_val), DafnyLiteral(else_body))

    # Generate function definitions based on aggregation type
    functions = []
    
    if query.agg_type == 'AVG':
        if query.groupby_columns:
            # Generate SumMapHelper
            sum_body = make_recursive_body("SumMapHelper", is_sum=True, return_type=ret_type)
            sum_func = DafnyFunction("SumMapHelper", [("data", "seq<Row>")], ret_type, sum_body)
            functions.append(sum_func)
            
            # Generate CountMapHelper
            count_body = make_recursive_body("CountMapHelper", is_sum=False, return_type=ret_type)
            count_func = DafnyFunction("CountMapHelper", [("data", "seq<Row>")], ret_type, count_body)
            functions.append(count_func)
            
            # Generate MethodSpec combining them
            spec_body = DafnyLiteral(
                f"var sums := SumMapHelper(data);\n"
                f"var counts := CountMapHelper(data);\n"
                f"map k | k in sums && k in counts :: if counts[k] == 0 then 0 else sums[k] / counts[k]"
            )
            spec_func = DafnyFunction("MethodSpec", [("data", "seq<Row>")], ret_type, spec_body, attrs="{:verify false}")
            functions.append(spec_func)
        else:
            # Generate SumHelper
            sum_body = make_recursive_body("SumHelper", is_sum=True, return_type="int")
            sum_func = DafnyFunction("SumHelper", [("data", "seq<Row>")], "int", sum_body)
            functions.append(sum_func)
            
            # Generate CountHelper
            count_body = make_recursive_body("CountHelper", is_sum=False, return_type="int")
            count_func = DafnyFunction("CountHelper", [("data", "seq<Row>")], "int", count_body)
            functions.append(count_func)
            
            # Generate MethodSpec combining them
            spec_body = DafnyLiteral(
                f"var sum := SumHelper(data);\n"
                f"var count := CountHelper(data);\n"
                f"if count == 0 then 0 else sum / count"
            )
            spec_func = DafnyFunction("MethodSpec", [("data", "seq<Row>")], "int", spec_body, attrs="{:verify false}")
            functions.append(spec_func)
    else:
        # SUM or COUNT
        is_sum = (query.agg_type == 'SUM')
        spec_body = make_recursive_body("MethodSpec", is_sum=is_sum, return_type=ret_type)
        spec_func = DafnyFunction("MethodSpec", [("data", "seq<Row>")], ret_type, spec_body, attrs="{:verify false}")
        functions.append(spec_func)

    # Combine everything.
    # The spec is marked `{:verify false}` so Dafny doesn't waste time
    # re-verifying it; the agent's `RunQuery` is still proved against it via
    # the `ensures res == MethodSpec(data)` postcondition.  This trusts the
    # transpiler's emitted spec, not the RunQuery implementation.
    #
    functions_dafny = "\n\n".join(func.to_dafny() for func in functions)
    type_definitions = _native_preamble()
    return f"{type_definitions}{schema_dafny}\n\n{functions_dafny}"


# =============================================================================
# Columnar transpiler: emits a Cols struct + columnar MethodSpec + RunQuery
# skeleton so the agent writes a columnar body that verifies against a
# columnar spec.  No `RowAt` bridge needed.
# =============================================================================

def _col_dafny_type(col_type: str) -> str:
    """Return type for Get* accessors on native Cols (NativeU32/U64 or string)."""
    col_type_lower = col_type.lower()
    if col_type_lower in ('bigint', 'int8', 'int64', 'hugeint',
                          'decimal', 'numeric', 'double', 'float8', 'float', 'real'):
        return 'NativeU64'
    if col_type_lower in ('varchar', 'text', 'string', 'char', 'bpchar'):
        return 'string'
    return 'NativeU32'


def _col_rust_vec_type(col_type: str) -> str:
    col_type_lower = col_type.lower()
    if col_type_lower in ('bigint', 'int8', 'int64', 'hugeint',
                          'decimal', 'numeric', 'double', 'float8', 'float', 'real'):
        return 'u64'
    if col_type_lower in ('varchar', 'text', 'string', 'char', 'bpchar'):
        return 'String'
    return 'u32'


def _col_rust_get_return(col_type: str) -> str:
    col_type_lower = col_type.lower()
    if col_type_lower in ('varchar', 'text', 'string', 'char', 'bpchar'):
        return 'Sequence<DafnyChar>'
    if col_type_lower in ('bigint', 'int8', 'int64', 'hugeint',
                          'decimal', 'numeric', 'double', 'float8', 'float', 'real'):
        return 'u64'
    return 'u32'


def _to_col_expr(expr: str, idx: str) -> str:
    """Substitute `row.LO_X` with `cols.GetLO_X(idx)` in a Dafny expression."""
    import re
    return re.sub(
        r"\brow\.([A-Za-z_][A-Za-z0-9_]*)",
        lambda m: f"cols.Get{m.group(1)}({idx})",
        expr,
    )


def _emit_cols_class(
    schema_dict: dict[str, str],
    agg_push: tuple[str, str] | None = None,
    agg_push_str: tuple[str, str] | None = None,
) -> str:
    """Single extern ColsNative class — one Rust Object, direct slice accessors."""
    from .agg_push import emit_cols_agg_push_dafny
    from .agg_push_str import emit_cols_agg_push_str_dafny

    lines = [
        'class {:extern "ColsNative"} Cols {',
        '  function {:extern} n(): int',
    ]
    for col, col_type in schema_dict.items():
        ret = _col_dafny_type(col_type)
        lines.append(f'  function {{:extern}} Get{col}(i: int): {ret}')
        if ret == 'string':
            lines.append(f'  function {{:extern}} EqAt{col}(i: int, lit: string): bool')
    if agg_push is not None:
        lines.append(emit_cols_agg_push_dafny(*agg_push))
    if agg_push_str is not None:
        lines.append(emit_cols_agg_push_str_dafny(*agg_push_str))
    lines.append('}')
    return '\n'.join(lines)


def generate_cols_native_rs(
    schema_dict: dict[str, str],
    *,
    sql_str: str | None = None,
    groupby_columns: list[str] | None = None,
) -> str:
    """Schema-specific Rust ColsNative (Arc<Vec<T>> + Get*/EqAt* for Dafny translate).

    When `sql_str` or `groupby_columns` describes a 2-key group-by, also emits schema-driven
    `AggPush_*` (NativeU32 + string) or `AggPushStr_*` (string + string) hot-path helpers.
    """
    from .agg_push import emit_cols_agg_push_rust, resolve_two_key_u32_str_groupby
    from .agg_push_str import emit_cols_agg_push_str_rust, resolve_two_key_str_str_groupby

    if groupby_columns is None and sql_str is not None:
        groupby_columns = parse_sql(sql_str, schema_dict).groupby_columns
    agg_push = resolve_two_key_u32_str_groupby(
        groupby_columns, schema_dict, col_dafny_type=_col_dafny_type
    )
    agg_push_str = resolve_two_key_str_str_groupby(
        groupby_columns, schema_dict, col_dafny_type=_col_dafny_type
    )

    field_lines = ['    pub n: usize,']
    for col, col_type in schema_dict.items():
        rust_ty = _col_rust_vec_type(col_type)
        field_lines.append(f'    pub {col.lower()}: Arc<Vec<{rust_ty}>>,')

    get_methods = []
    for col, col_type in schema_dict.items():
        field = col.lower()
        ret = _col_rust_get_return(col_type)
        if ret == 'Sequence<DafnyChar>':
            get_methods.append(f'''
    pub fn Get{col}(&self, i: &DafnyInt) -> Sequence<DafnyChar> {{
        string_to_dafny_string(&self.{field}[usize::from(i.clone())])
    }}

    pub fn Get{col}_usize(&self, i: usize) -> Sequence<DafnyChar> {{
        string_to_dafny_string(&self.{field}[i])
    }}

    pub fn Get{col}_str_ref(&self, i: usize) -> &str {{
        &self.{field}[i]
    }}

    pub fn EqAt{col}(&self, i: &DafnyInt, lit: &Sequence<DafnyChar>) -> bool {{
        self.{field}[usize::from(i.clone())] == dafny_string_to_string(lit)
    }}

    pub fn EqAt{col}_usize(&self, i: usize, lit: &str) -> bool {{
        self.{field}[i] == lit
    }}''')
        else:
            get_methods.append(f'''
    pub fn Get{col}(&self, i: &DafnyInt) -> {ret} {{
        self.{field}[usize::from(i.clone())]
    }}

    pub fn Get{col}_usize(&self, i: usize) -> {ret} {{
        self.{field}[i]
    }}''')

    agg_push_methods = ""
    agg_import = ""
    imports: list[str] = []
    if agg_push is not None:
        imports.append("NativeAggMap")
        agg_push_methods = emit_cols_agg_push_rust(*agg_push)
    if agg_push_str is not None:
        imports.append("NativeAggStrMap")
        agg_push_methods += emit_cols_agg_push_str_rust(*agg_push_str)
    if imports:
        agg_import = f"use crate::native_agg::{{{', '.join(imports)}}};\n"

    return f'''{agg_import}use dafny_runtime::{{
    dafny_runtime_conversions::unicode_chars_true::{{dafny_string_to_string, string_to_dafny_string}},
    allocate_object, DynAny, DafnyChar, DafnyInt, DafnyPrint, Object, Rc, Sequence, UpcastObject,
}};
use std::fmt::{{Debug, Formatter, Result as FmtResult}};
use std::sync::Arc;

#[derive(Clone, Default)]
pub struct ColsNative {{
{chr(10).join(field_lines)}
}}

impl Debug for ColsNative {{
    fn fmt(&self, f: &mut Formatter<'_>) -> FmtResult {{
        f.debug_struct("ColsNative").field("n", &self.n).finish()
    }}
}}

impl DafnyPrint for ColsNative {{
    fn fmt_print(&self, _f: &mut Formatter, _in_seq: bool) -> FmtResult {{
        Ok(())
    }}
}}

impl UpcastObject<DynAny> for ColsNative {{
    fn upcast(&self) -> Object<DynAny> {{
        unsafe {{ Object::from_rc(Rc::new(self.clone()) as Rc<DynAny>) }}
    }}
}}

impl ColsNative {{
    pub fn _allocate_object() -> Object<ColsNative> {{
        allocate_object::<ColsNative>()
    }}

    pub fn n(&self) -> DafnyInt {{
        DafnyInt::from(self.n)
    }}
{"".join(get_methods)}{agg_push_methods}
}}
'''


def _native_where_cond(cond: str, idx: str, schema_dict: dict[str, str]) -> str:
    """Use EqAt for string column equality in columnar filters."""
    import re
    out = cond
    for col, col_type in schema_dict.items():
        if _col_dafny_type(col_type) != "string":
            continue
        col_pat = re.escape(col)
        out = re.sub(
            rf"cols\.Get{col_pat}\({re.escape(idx)}\)\s*==\s*(\"[^\"]*\")",
            rf"cols.EqAt{col}({idx}, \1)",
            out,
        )
    return out


def _native_i64_term(term_row_expr: str, idx: str) -> str:
    """Map aggregate row expr to native extern term (e.g. SubU64ToI64)."""
    import re
    m = re.match(
        r"\(row\.([A-Z0-9_]+) as int\) - \(row\.([A-Z0-9_]+) as int\)",
        term_row_expr.strip(),
    )
    if m:
        a, b = m.group(1), m.group(2)
        return f"SubU64ToI64(cols.Get{a}({idx}), cols.Get{b}({idx}))"
    return f"({_to_col_expr(term_row_expr, idx)}) as NativeI64"


def _native_u64_term(term_row_expr: str, idx: str) -> str:
    """Map SUM multiply-style aggregates to MulU64U32 when shape matches."""
    import re
    m = re.match(
        r"\(row\.([A-Z0-9_]+) as int\) \* \(row\.([A-Z0-9_]+) as int\)",
        term_row_expr.strip(),
    )
    if m:
        a, b = m.group(1), m.group(2)
        return f"MulU64U32(cols.Get{a}({idx}) as NativeU64, cols.Get{b}({idx}))"
    return f"({_to_col_expr(term_row_expr, idx)}) as NativeU64"


def transpile_sql_to_dafny_columnar(sql_str: str, schema_dict: dict[str, str]) -> str:
    """Translates SQL query into a columnar Dafny spec + RunQuery skeleton.

    Output structure (all on one logical program):
      - `datatype Cols = Cols(n: int, LO_X: seq<bv32>, ...)`
      - `function MethodSpec(cols: Cols): T`  (thin wrapper, calls Helper at 0)
      - `function MethodSpecHelper(cols: Cols, k: int): T`  (the recursive fold)
      - `method RunQuery(cols: Cols) returns (res: T)`  (the agent fills this in)
        * With a `// TODO: implement body` comment in the loop.

    The spec is a *fold* over the index range; the helper recurses on `k`.
    The agent's RunQuery does the same in reverse order with a loop invariant
    that ties `res + MethodSpecHelper(cols, i) == MethodSpec(cols)`.
    """
    # 1. Parse (same as row version).
    supported_types = (
        'int', 'string', 'bigint', 'int8', 'int64', 'integer', 'int4', 'int32',
        'varchar', 'text'
    )
    for col, col_type in schema_dict.items():
        if col_type.lower() not in supported_types:
            raise UnsupportedContractError(f"Unsupported column type in schema: {col_type}")
    query = parse_sql(sql_str, schema_dict)

    from .agg_push import agg_push_method_name, resolve_two_key_u32_str_groupby
    from .agg_push_str import agg_push_str_method_name, resolve_two_key_str_str_groupby

    agg_push = resolve_two_key_u32_str_groupby(
        query.groupby_columns, schema_dict, col_dafny_type=_col_dafny_type
    )
    agg_push_str = resolve_two_key_str_str_groupby(
        query.groupby_columns, schema_dict, col_dafny_type=_col_dafny_type
    )

    # 2. Emit the native `Cols` extern class (ColsNative in Rust).
    cols_class = _emit_cols_class(schema_dict, agg_push, agg_push_str)

    # 2b. ValidCols: global row/cell bounds (Lemma policy) + column alignment
    valid_cols_predicate = emit_valid_cols_predicate(schema_dict)

    # 3. Return type & WHERE-clause condition (in columnar form).
    if query.groupby_columns:
        types = [get_dafny_type(c, schema_dict[c]) for c in query.groupby_columns]
        val_type = _agg_value_type(query.agg_expr_dafny)
        if len(query.groupby_columns) == 1:
            ret_type = f"map<{types[0]}, {val_type}>"
        else:
            ret_type = f"map<({', '.join(types)}), {val_type}>"
    else:
        ret_type = _agg_value_type(query.agg_expr_dafny)

    where_at_k = _to_col_expr(query.where_expr_dafny, "k") if query.where_expr_dafny else None
    term_at_k = _to_col_expr(query.agg_expr_dafny, "k") if query.agg_expr_dafny else "0"

    # 4. Build the columnar `MethodSpecHelper` body.
    if query.agg_type == 'AVG':
        # Two helpers + a wrapper, like the row version.
        if query.groupby_columns:
            sum_h = _build_col_helper("SumMapHelper", query, "k", schema_dict, is_sum=True)
            cnt_h = _build_col_helper("CountMapHelper", query, "k", schema_dict, is_sum=False)
            helper_lines = [sum_h, cnt_h]
            spec_body = (
                "var sums := SumMapHelper(cols, 0);\n"
                "var counts := CountMapHelper(cols, 0);\n"
                "map k | k in sums && k in counts :: if counts[k] == 0 then 0 else sums[k] / counts[k]"
            )
        else:
            sum_h = _build_col_helper("SumHelper", query, "k", schema_dict, is_sum=True)
            cnt_h = _build_col_helper("CountHelper", query, "k", schema_dict, is_sum=False)
            helper_lines = [sum_h, cnt_h]
            spec_body = "var sum := SumHelper(cols, 0);\nvar count := CountHelper(cols, 0);\nif count == 0 then 0 else sum / count"
    else:
        is_sum = (query.agg_type == 'SUM')
        h = _build_col_helper("MethodSpecHelper", query, "k", schema_dict, is_sum=is_sum)
        helper_lines = [h]
        spec_body = "MethodSpecHelper(cols, 0)"

    helpers_dafny = "\n\n".join(helper_lines)
    type_defs = (
        _native_preamble()
        + emit_bound_constants()
        + "\n"
        + emit_bound_lemmas()
        + "\n"
        + emit_valid_cols_accessor_lemmas(schema_dict)
        + "\n"
    )

    # 5. The `RunQuery` skeleton for the agent.
    if query.groupby_columns:
        inv = (
            "  invariant 0 <= i <= cols.n()\n"
            "  invariant g == MethodSpecHelper(cols, i)\n"
            "  invariant agg.Snapshot() == g\n"
        )
        if agg_push is not None:
            u32_col, str_col = agg_push
            push_name = agg_push_method_name(u32_col, str_col)
            body_hint = (
                "    // TODO: if <filter using EqAt* for string cols> {\n"
                f"    //   var k0 := cols.Get{u32_col}(i);\n"
                f"    //   var k1 := cols.Get{str_col}(i);\n"
                "    //   var key := (k0, k1);\n"
                "    //   var term := <native agg term, e.g. SubU64ToI64(...)>;\n"
                f"    //   cols.{push_name}(agg, i, term);  // Rust: AddStrKey, no Dafny string alloc\n"
                "    //   ghost var prev := if key in g then g[key] else 0 as NativeI64;\n"
                "    //   g := g[key := AddI64(prev, term)];\n"
                "    // }\n"
            )
            run_body_init = (
                "//   var agg := new NativeAggMap();\n"
                "//   ghost var g: map<..., NativeI64> := map[];\n"
            )
            run_body_end = "//   res := agg.ToMap();\n"
        elif agg_push_str is not None:
            s0, s1 = agg_push_str
            push_name = agg_push_str_method_name(s0, s1)
            body_hint = (
                "    // TODO: if <filter using EqAt* for string cols> {\n"
                f"    //   var k0 := cols.Get{s0}(i);\n"
                f"    //   var k1 := cols.Get{s1}(i);\n"
                "    //   var key := (k0, k1);\n"
                "    //   var term := <native agg term>;\n"
                f"    //   cols.{push_name}(agg, i, term);  // Rust: AddStrPair, no Dafny string alloc\n"
                "    //   ghost var prev := if key in g then g[key] else 0 as NativeU64;\n"
                "    //   g := g[key := AddU64(prev, term)];\n"
                "    // }\n"
            )
            run_body_init = (
                "//   var agg := new NativeAggStrMap();\n"
                "//   ghost var g: map<(string, string), NativeU64> := map[];\n"
            )
            run_body_end = "//   res := agg.ToMap();\n"
        else:
            body_hint = (
                "    // TODO: if <filter using EqAt* for string cols> {\n"
                "    //   var k0 := cols.Get<group-int>(i);\n"
                "    //   var k1 := cols.Get<group-string>(i);\n"
                "    //   var key := (k0, k1);\n"
                "    //   var term := <native agg term, e.g. SubU64ToI64(...)>;\n"
                "    //   agg.Add(k0, k1, term);\n"
                "    //   ghost var prev := if key in g then g[key] else 0 as NativeI64;\n"
                "    //   g := g[key := AddI64(prev, term)];\n"
                "    // }\n"
            )
            run_body_init = (
                "//   var agg := new NativeAggMap();\n"
                "//   ghost var g: map<..., NativeI64> := map[];\n"
            )
            run_body_end = "//   res := agg.ToMap();\n"
    else:
        inv = "  invariant 0 <= i <= cols.n()\n  invariant res == MethodSpecHelper(cols, i)\n  invariant 0 <= res\n"
        body_hint = (
            "    // TODO: if <filter> { res := AddU64(res, <MulU64U32(...) or term>); }\n"
        )
        run_body_init = "//   res := 0 as NativeU64;\n"
        run_body_end = ""

    # 5. The `RunQuery` skeleton: emitted as a *comment* in the spec so the
    #   agent knows the correct signature, requires/ensures, invariant shape,
    #   and how to access column data.  The agent's scratchpad provides the
    #   actual `method RunQuery(...)` definition (which overrides this guide).
    run_query_skel = (
        "// === RunQuery skeleton (agent provides the body) ===\n"
        f"// method RunQuery(cols: Cols) returns (res: {ret_type})\n"
        "//   requires ValidCols(cols)\n"
        f"//   ensures res == MethodSpec(cols)\n"
        "// {\n"
        + run_body_init
        + "//   var i := cols.n();\n"
        + "//   while i > 0\n"
        + "".join("//   " + ln for ln in inv.splitlines(keepends=True))
        + "//   {\n"
        + "//     i := i - 1;\n"
        + "".join("//   " + ln for ln in body_hint.splitlines(keepends=True))
        + "//   }\n"
        + run_body_end
        + "// }\n"
    )

    # 6. Assemble the full Dafny program.
    spec_func = (
        f"function {{:verify false}} MethodSpec(cols: Cols): {ret_type}\n"
        "  requires ValidCols(cols)\n"
        "{\n"
        f"  {spec_body}\n"
        "}"
    )
    return f"{type_defs}{cols_class}\n\n{valid_cols_predicate}\n\n{helpers_dafny}\n\n{spec_func}\n\n{run_query_skel}"


def _build_col_helper(
    func_name: str, query: SQLQuery, idx_var: str, schema_dict: dict[str, str], is_sum: bool
) -> str:
    """Build a columnar `MethodSpecHelper` function body.

    The helper recurses on `idx_var` from 0 to `cols.n`.  At each step:
      - extract the WHERE-clause condition in columnar form (substituting
        `row.X` for `cols.X[idx_var]`)
      - extract the term / key expressions similarly
      - if the condition holds, update the accumulator (sum += term, or
        map[key := prev + term])

    We inline the base case and the body in one function with the *tight*
    precondition `0 <= idx < cols.n` on the body, and a *loose* one
    `0 <= idx <= cols.n` on the outer function.  Dafny can see that the
    access `cols.LO_X[idx]` is in the `idx < cols.n` branch, so no lemma
    is needed.
    """
    cond = _native_where_cond(_to_col_expr(query.where_expr_dafny, idx_var), idx_var, schema_dict) if query.where_expr_dafny else None
    if query.groupby_columns:
        if len(query.groupby_columns) == 1:
            key_expr_at_k = f"cols.Get{query.groupby_columns[0]}({idx_var})"
        else:
            key_expr_at_k = f"({', '.join(f'cols.Get{c}({idx_var})' for c in query.groupby_columns)})"
        val_type = _agg_value_type(query.agg_expr_dafny)
        term_expr_at_k = (
            _native_i64_term(query.agg_expr_dafny, idx_var)
            if val_type == "NativeI64"
            else (_native_u64_term(query.agg_expr_dafny, idx_var) if is_sum else "1")
        )
        add_fn = "AddI64" if val_type == "NativeI64" else "AddU64"
        if len(query.groupby_columns) == 1:
            ret_type = f"map<{get_dafny_type(query.groupby_columns[0], schema_dict[query.groupby_columns[0]])}, {val_type}>"
        else:
            ret_type = (
                f"map<({', '.join(get_dafny_type(c, schema_dict[c]) for c in query.groupby_columns)}), {val_type}>"
            )
        if cond:
            body_inner = (
                f"var tail := {func_name}(cols, {idx_var} + 1);\n"
                f"  if {cond} then\n"
                f"    var key := {key_expr_at_k};\n"
                f"    var val := if key in tail then tail[key] else (0 as {val_type});\n"
                f"    tail[key := {add_fn}(val, {term_expr_at_k})]\n"
                f"  else\n"
                f"    tail"
            )
        else:
            body_inner = (
                f"var tail := {func_name}(cols, {idx_var} + 1);\n"
                f"  var key := {key_expr_at_k};\n"
                f"  var val := if key in tail then tail[key] else (0 as {val_type});\n"
                f"  tail[key := {add_fn}(val, {term_expr_at_k})]"
            )
    else:
        term_expr_at_k = _native_u64_term(query.agg_expr_dafny, idx_var) if is_sum else "1"
        ret_type = _agg_value_type(query.agg_expr_dafny)
        if cond:
            body_inner = (
                f"(if {cond} then "
                f"AddU64({func_name}(cols, {idx_var} + 1), {term_expr_at_k}) "
                f"else {func_name}(cols, {idx_var} + 1))"
            )
        else:
            body_inner = f"AddU64({func_name}(cols, {idx_var} + 1), {term_expr_at_k})"

    base_val = "map[]" if query.groupby_columns else f"0 as {ret_type}"
    return (
        f"function {{:verify false}} {func_name}(cols: Cols, {idx_var}: int): {ret_type}\n"
        f"  requires 0 <= {idx_var} <= cols.n()\n"
        f"  requires ValidCols(cols)\n"
        f"  decreases cols.n() - {idx_var}\n"
        "{\n"
        f"  if {idx_var} < cols.n() then\n"
        f"    {body_inner}\n"
        f"  else {base_val}\n"
        "}\n"
    )
