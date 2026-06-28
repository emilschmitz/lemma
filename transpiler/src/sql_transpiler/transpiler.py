import re
import sqlglot
from sqlglot import exp

class UnsupportedContractError(Exception):
    """Raised when a SQL query falls outside the supported dashboard subset."""
    pass

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
    def __init__(self, name: str, params: list[tuple[str, str]], return_type: str, body):
        self.name = name
        self.params = params  # list of (name, type)
        self.return_type = return_type
        self.body = body

    def to_dafny(self) -> str:
        params_str = ", ".join(f"{name}: {type_}" for name, type_ in self.params)
        body_str = self.body.to_dafny() if hasattr(self.body, 'to_dafny') else str(self.body)
        
        # Indent the body nicely
        indented_body = "\n".join("  " + line for line in body_str.split("\n"))
        return (
            f"function {self.name}({params_str}): {self.return_type}\n"
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
            if col_type != 'int':
                raise UnsupportedContractError(f"Column '{real_col}' in expression must be of type 'int'.")
            return f"row.{real_col}"
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
                if col_type != 'int':
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
                if col_type == 'int':
                    if val_type != 'int':
                        raise UnsupportedContractError(f"Type mismatch: comparing int column '{real_col}' with non-int value.")
                elif col_type == 'string':
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

def transpile_sql_to_dafny(sql_str: str, schema_dict: dict[str, str]) -> str:
    """Translates SQL query to mathematical Dafny specification."""
    # 1. Parse and validate schema
    for col, col_type in schema_dict.items():
        if col_type not in ('int', 'string'):
            raise UnsupportedContractError(f"Unsupported column type in schema: {col_type}")

    # 2. Parse SQL
    query = parse_sql(sql_str, schema_dict)

    # 3. Generate schema datatype representation
    fields = [f"{col}: {schema_dict[col]}" for col in schema_dict]
    fields_str = ", ".join(fields)
    schema_dafny = f"datatype Row = Row({fields_str})"

    # 4. Determine key variables
    if query.groupby_columns:
        types = [schema_dict[col] for col in query.groupby_columns]
        if len(query.groupby_columns) == 1:
            key_type = types[0]
            ret_type = f"map<{key_type}, int>"
            key_expr = f"row.{query.groupby_columns[0]}"
        else:
            ret_type = f"map<({', '.join(types)}), int>"
            key_expr = f"({', '.join(f'row.{col}' for col in query.groupby_columns)})"
    else:
        ret_type = "int"
        key_expr = None
    
    # Construct WHERE clause condition for row
    where_expr = query.where_expr_dafny if query.where_expr_dafny else None

    # Helper function to generate a SUM or COUNT recursive body
    def make_recursive_body(func_name: str, is_sum: bool, return_type: str):
        # Base case
        cond = "|data| == 0"
        then_val = "map[]" if "map" in return_type else "0"
        
        # Else case
        if query.groupby_columns:
            # GROUP BY recursive logic
            term_expr = query.agg_expr_dafny if is_sum else "1"
            if where_expr:
                else_body = (
                    f"var tailMap := {func_name}(data[1..]);\n"
                    f"var row := data[0];\n"
                    f"if {where_expr} then\n"
                    f"  var key := {key_expr};\n"
                    f"  var val := if key in tailMap then tailMap[key] else 0;\n"
                    f"  tailMap[key := val + {term_expr}]\n"
                    f"else\n"
                    f"  tailMap"
                )
            else:
                else_body = (
                    f"var tailMap := {func_name}(data[1..]);\n"
                    f"var row := data[0];\n"
                    f"var key := {key_expr};\n"
                    f"var val := if key in tailMap then tailMap[key] else 0;\n"
                    f"tailMap[key := val + {term_expr}]"
                )
        else:
            # Single aggregation recursive logic
            term_expr = query.agg_expr_dafny if is_sum else "1"
            if where_expr:
                else_body = (
                    f"var row := data[0];\n"
                    f"var tail := data[1..];\n"
                    f"var term := if {where_expr} then {term_expr} else 0;\n"
                    f"term + {func_name}(tail)"
                )
            else:
                else_body = (
                    f"var row := data[0];\n"
                    f"var tail := data[1..];\n"
                    f"{term_expr} + {func_name}(tail)"
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
            spec_func = DafnyFunction("MethodSpec", [("data", "seq<Row>")], ret_type, spec_body)
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
            spec_func = DafnyFunction("MethodSpec", [("data", "seq<Row>")], "int", spec_body)
            functions.append(spec_func)
    else:
        # SUM or COUNT
        is_sum = (query.agg_type == 'SUM')
        spec_body = make_recursive_body("MethodSpec", is_sum=is_sum, return_type=ret_type)
        spec_func = DafnyFunction("MethodSpec", [("data", "seq<Row>")], ret_type, spec_body)
        functions.append(spec_func)

    # Combine everything
    functions_dafny = "\n\n".join(func.to_dafny() for func in functions)
    return f"{schema_dafny}\n\n{functions_dafny}"
