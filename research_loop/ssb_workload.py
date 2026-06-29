from sql_transpiler import transpile_sql_to_dafny

schema = {
    "LO_ORDERKEY": "int",
    "LO_LINENUMBER": "int",
    "LO_CUSTKEY": "int",
    "LO_PARTKEY": "int",
    "LO_SUPPKEY": "int",
    "LO_ORDERDATE": "int",
    "LO_ORDERPRIORITY": "string",
    "LO_SHIPPRIORITY": "int",
    "LO_QUANTITY": "int",
    "LO_EXTENDEDPRICE": "int",
    "LO_ORDTOTALPRICE": "int",
    "LO_DISCOUNT": "int",
    "LO_REVENUE": "int",
    "LO_SUPPLYCOST": "int",
    "LO_TAX": "int",
    "LO_COMMITDATE": "int",
    "LO_SHIPMODE": "string",
    
    "C_NAME": "string",
    "C_ADDRESS": "string",
    "C_CITY": "string",
    "C_NATION": "string",
    "C_REGION": "string",
    "C_PHONE": "string",
    "C_MKTSEGMENT": "string",
    
    "S_NAME": "string",
    "S_ADDRESS": "string",
    "S_CITY": "string",
    "S_NATION": "string",
    "S_REGION": "string",
    "S_PHONE": "string",
    
    "P_NAME": "string",
    "P_MFGR": "string",
    "P_CATEGORY": "string",
    "P_BRAND": "string",
    "P_COLOR": "string",
    "P_TYPE": "string",
    "P_SIZE": "int",
    "P_CONTAINER": "string",
    
    "D_YEAR": "int",
    "D_YEARMONTHNUM": "int",
    "D_WEEKNUMINYEAR": "int"
}

# 15 queries adapted from SSB-Flat and TPC-H workloads
queries = [
    # 1. SSB Q1.1 Flat style
    """
    SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) AS revenue
    FROM lineorder_flat
    WHERE LO_ORDERDATE >= 19930101 AND LO_ORDERDATE <= 19931231
      AND LO_DISCOUNT >= 1 AND LO_DISCOUNT <= 3
      AND LO_QUANTITY < 25
    """,
    # 2. SSB Q1.2 Flat style
    """
    SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) AS revenue
    FROM lineorder_flat
    WHERE LO_ORDERDATE >= 19940101 AND LO_ORDERDATE <= 19940131
      AND LO_DISCOUNT >= 4 AND LO_DISCOUNT <= 6
      AND LO_QUANTITY >= 26 AND LO_QUANTITY <= 35
    """,
    # 3. SSB Q1.3 Flat style
    """
    SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) AS revenue
    FROM lineorder_flat
    WHERE D_WEEKNUMINYEAR = 6 AND D_YEAR = 1994
      AND LO_DISCOUNT >= 5 AND LO_DISCOUNT <= 7
      AND LO_QUANTITY >= 26 AND LO_QUANTITY <= 35
    """,
    # 4. SSB Q2.1 Flat style (multi-column group by)
    """
    SELECT D_YEAR, P_BRAND, SUM(LO_REVENUE) AS brand_revenue
    FROM lineorder_flat
    WHERE P_CATEGORY = 'MFGR#12' AND S_REGION = 'AMERICA'
    GROUP BY D_YEAR, P_BRAND
    """,
    # 5. SSB Q2.2 Flat style (multi-column group by)
    """
    SELECT D_YEAR, P_BRAND, SUM(LO_REVENUE) AS brand_revenue
    FROM lineorder_flat
    WHERE P_BRAND = 'MFGR#2221' AND P_SIZE >= 10 AND S_REGION = 'ASIA'
    GROUP BY D_YEAR, P_BRAND
    """,
    # 6. SSB Q2.3 Flat style (multi-column group by)
    """
    SELECT D_YEAR, P_BRAND, SUM(LO_REVENUE) AS brand_revenue
    FROM lineorder_flat
    WHERE P_BRAND = 'MFGR#2221' AND S_REGION = 'EUROPE'
    GROUP BY D_YEAR, P_BRAND
    """,
    # 7. SSB Q3.1 Flat style (three-column group by)
    """
    SELECT C_NATION, S_NATION, D_YEAR, SUM(LO_REVENUE) AS revenue
    FROM lineorder_flat
    WHERE C_REGION = 'ASIA' AND S_REGION = 'ASIA'
      AND LO_ORDERDATE >= 19920101 AND LO_ORDERDATE <= 19971231
    GROUP BY C_NATION, S_NATION, D_YEAR
    """,
    # 8. SSB Q3.2 Flat style (three-column group by)
    """
    SELECT C_CITY, S_CITY, D_YEAR, SUM(LO_REVENUE) AS revenue
    FROM lineorder_flat
    WHERE C_NATION = 'UNITED STATES' AND S_NATION = 'UNITED STATES'
      AND LO_ORDERDATE >= 19920101 AND LO_ORDERDATE <= 19971231
    GROUP BY C_CITY, S_CITY, D_YEAR
    """,
    # 9. SSB Q3.3 Flat style (three-column group by)
    """
    SELECT C_CITY, S_CITY, D_YEAR, SUM(LO_REVENUE) AS revenue
    FROM lineorder_flat
    WHERE C_CITY = 'UNITED KI1' AND S_CITY = 'UNITED KI5'
      AND LO_ORDERDATE >= 19920101 AND LO_ORDERDATE <= 19971231
    GROUP BY C_CITY, S_CITY, D_YEAR
    """,
    # 10. SSB Q3.4 Flat style (three-column group by)
    """
    SELECT C_CITY, S_CITY, D_YEAR, SUM(LO_REVENUE) AS revenue
    FROM lineorder_flat
    WHERE C_CITY = 'UNITED KI1' AND S_CITY = 'UNITED KI5'
      AND LO_ORDERDATE >= 19971201 AND LO_ORDERDATE <= 19971231
    GROUP BY C_CITY, S_CITY, D_YEAR
    """,
    # 11. SSB Q4.1 Flat style (multi-column group by)
    """
    SELECT D_YEAR, C_NATION, SUM(LO_REVENUE - LO_SUPPLYCOST) AS profit
    FROM lineorder_flat
    WHERE C_REGION = 'AMERICA' AND S_REGION = 'AMERICA' AND P_MFGR = 'MFGR#1'
    GROUP BY D_YEAR, C_NATION
    """,
    # 12. SSB Q4.2 Flat style (multi-column group by)
    """
    SELECT D_YEAR, C_NATION, SUM(LO_REVENUE - LO_SUPPLYCOST) AS profit
    FROM lineorder_flat
    WHERE C_REGION = 'AMERICA' AND S_REGION = 'AMERICA'
      AND LO_ORDERDATE >= 19970101 AND LO_ORDERDATE <= 19981231
      AND P_MFGR = 'MFGR#1'
    GROUP BY D_YEAR, C_NATION
    """,
    # 13. SSB Q4.3 Flat style (three-column group by)
    """
    SELECT D_YEAR, S_NATION, P_CATEGORY, SUM(LO_REVENUE - LO_SUPPLYCOST) AS profit
    FROM lineorder_flat
    WHERE C_REGION = 'AMERICA' AND S_NATION = 'UNITED STATES'
      AND LO_ORDERDATE >= 19970101 AND LO_ORDERDATE <= 19971231
      AND P_CATEGORY = 'MFGR#14'
    GROUP BY D_YEAR, S_NATION, P_CATEGORY
    """,
    # 14. TPC-H Q6 Flat style
    """
    SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) AS revenue
    FROM lineorder_flat
    WHERE LO_ORDERDATE >= 19940101 AND LO_ORDERDATE <= 19941231
      AND LO_DISCOUNT >= 5 AND LO_DISCOUNT <= 7
      AND LO_QUANTITY < 24
    """,
    # 15. TPC-H Q1 Flat style (simplified to single aggregate and single group by)
    """
    SELECT LO_ORDERPRIORITY, SUM(LO_QUANTITY) AS sum_qty
    FROM lineorder_flat
    WHERE LO_ORDERDATE >= 19980901 AND LO_ORDERDATE <= 19981231
    GROUP BY LO_ORDERPRIORITY
    """
]

dummy_row = {
    "LO_ORDERKEY": 1,
    "LO_LINENUMBER": 1,
    "LO_CUSTKEY": 1,
    "LO_PARTKEY": 1,
    "LO_SUPPKEY": 1,
    "LO_ORDERDATE": 19940115,
    "LO_ORDERPRIORITY": "1-URGENT",
    "LO_SHIPPRIORITY": 0,
    "LO_QUANTITY": 15,
    "LO_EXTENDEDPRICE": 10000,
    "LO_ORDTOTALPRICE": 15000,
    "LO_DISCOUNT": 6,
    "LO_REVENUE": 9400,
    "LO_SUPPLYCOST": 6000,
    "LO_TAX": 2,
    "LO_COMMITDATE": 19940120,
    "LO_SHIPMODE": "TRUCK",
    "C_NAME": "Customer#001",
    "C_ADDRESS": "Addr 1",
    "C_CITY": "UNITED KI1",
    "C_NATION": "UNITED KINGDOM",
    "C_REGION": "AMERICA",
    "C_PHONE": "123",
    "C_MKTSEGMENT": "BUILDING",
    "S_NAME": "Supplier#001",
    "S_ADDRESS": "Addr 2",
    "S_CITY": "UNITED KI5",
    "S_NATION": "UNITED KINGDOM",
    "S_REGION": "AMERICA",
    "S_PHONE": "456",
    "P_NAME": "Part#001",
    "P_MFGR": "MFGR#1",
    "P_CATEGORY": "MFGR#14",
    "P_BRAND": "MFGR#142",
    "P_COLOR": "RED",
    "P_TYPE": "SMALL",
    "P_SIZE": 10,
    "P_CONTAINER": "BOX",
    "D_YEAR": 1994,
    "D_YEARMONTHNUM": 199401,
    "D_WEEKNUMINYEAR": 6
}

from concurrent.futures import ThreadPoolExecutor

def check_query(idx, sql_str, verify=False):
    try:
        # Transpile
        dafny_spec = transpile_sql_to_dafny(sql_str, schema)
        
        # Build dummy runner
        row_fields = []
        for col in schema:
            val = dummy_row[col]
            if schema[col] == 'int':
                row_fields.append(str(val))
            else:
                row_fields.append(f'"{val}"')
        row_expr = f"Row({', '.join(row_fields)})"
        
        runner_code = f"""
{dafny_spec}

method Main() {{
  var data := [{row_expr}];
  var res := MethodSpec(data);
  print "success\\n";
}}
"""
        # Save & run
        with tempfile.NamedTemporaryFile(suffix=".dfy", mode="w", delete=False) as tmp:
            tmp.write(runner_code)
            tmp_name = tmp.name
            
        try:
            cmd = ["dafny", "run", "--target:py"]
            if not verify:
                cmd.append("--no-verify")
            cmd.append(tmp_name)
            
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                return False, f"[ERROR] Dafny compilation/execution failed.\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
            else:
                return True, "[OK] Transpiled & Executed successfully!"
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
    except Exception as e:
        return False, f"[ERROR] Transpilation failed: {e}"

def main():
    verify = "--verify" in sys.argv
    max_workers = min(4, os.cpu_count() or 1)
    
    print(f"Checking {len(queries)} queries concurrently (max_workers={max_workers}, verify={verify})...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(check_query, idx, q, verify) for idx, q in enumerate(queries)]
        
        success_count = 0
        for idx, future in enumerate(futures):
            success, msg = future.result()
            print(f"Query {idx + 1}: {msg}")
            if success:
                success_count += 1
            
    print("\n-------------------------------------------")
    print(f"Verification Summary: {success_count} / {len(queries)} queries succeeded.")
    print("-------------------------------------------")
    if success_count == len(queries):
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
