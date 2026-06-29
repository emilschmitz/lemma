#!/usr/bin/env python3
import os
import sys
import re
import json
import time
import subprocess
import argparse
import shutil

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

from sql_transpiler import transpile_sql_to_dafny, queries, schema

def load_env(env_path):
    env = {}
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env

def extract_dafny_code(scratchpad_path):
    if not os.path.exists(scratchpad_path):
        return None
    with open(scratchpad_path, "r") as f:
        content = f.read()
    
    # Match code blocks labeled dafny
    pattern = r"```dafny\s*([\s\S]*?)```"
    match = re.search(pattern, content)
    if not match:
        return None
    return match.group(1).strip()

def generate_row_expr(i_val_str="i"):
    """
    Generates a Dafny Row constructor expression dynamically based on the schema,
    using cyclic values to populate the fields of the sequence.
    """
    row_fields = []
    for col in schema:
        col_type = schema[col]
        if col_type == 'int':
            if col == "LO_ORDERDATE":
                expr = f"19930101 + ({i_val_str} % 365)"
            elif col == "LO_DISCOUNT":
                expr = f"{i_val_str} % 10"
            elif col == "LO_QUANTITY":
                expr = f"{i_val_str} % 50"
            elif col == "D_YEAR":
                expr = f"1992 + ({i_val_str} % 7)"
            elif col == "D_WEEKNUMINYEAR":
                expr = f"1 + ({i_val_str} % 52)"
            elif col in ("LO_EXTENDEDPRICE", "LO_REVENUE", "LO_SUPPLYCOST", "LO_ORDTOTALPRICE"):
                expr = f"1000 + ({i_val_str} % 1000)"
            else:
                expr = f"1 + ({i_val_str} % 100)"
        else:
            if col == "P_CATEGORY":
                expr = f'if {i_val_str} % 3 == 0 then "MFGR#12" else "MFGR#14"'
            elif col in ("S_REGION", "C_REGION"):
                expr = f'if {i_val_str} % 2 == 0 then "AMERICA" else "ASIA"'
            elif col == "P_BRAND":
                expr = f'if {i_val_str} % 4 == 0 then "MFGR#2221" else "MFGR#2222"'
            elif col in ("C_NATION", "S_NATION"):
                expr = f'if {i_val_str} % 5 == 0 then "UNITED STATES" else "UNITED KINGDOM"'
            elif col == "C_CITY":
                expr = f'if {i_val_str} % 2 == 0 then "UNITED KI1" else "UNITED KI2"'
            elif col == "S_CITY":
                expr = f'if {i_val_str} % 2 == 0 then "UNITED KI5" else "UNITED KI6"'
            elif col == "LO_ORDERPRIORITY":
                expr = f'if {i_val_str} % 2 == 0 then "1-URGENT" else "2-HIGH"'
            else:
                expr = '"dummy"'
        row_fields.append(expr)
    
    return f"Row({', '.join(row_fields)})"

def main():
    parser = argparse.ArgumentParser(description="Auto-research benchmarking harness")
    parser.add_argument("-q", "--query", type=int, default=1, help="Query index (1-15) from SSB queries. Default: 1")
    parser.add_argument("-d", "--dataset-size", type=int, default=50000, help="Dataset size for benchmarking. Default: 50000")
    args = parser.parse_args()

    # Validate query index
    if args.query < 1 or args.query > len(queries):
        print(json.dumps({
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": f"Invalid query index. Choose 1 to {len(queries)}."
        }))
        sys.exit(1)

    sql_query = queries[args.query - 1]
    
    # 1. Load Configurations
    config = load_env(os.path.join(CURRENT_DIR, "config.env"))
    dafny_verify_timeout = int(config.get("DAFNY_VERIFY_TIMEOUT_SEC", 30))
    compile_timeout = int(config.get("COMPILE_TIMEOUT_SEC", 30))

    # 2. Extract agent's optimized RunQuery code
    scratchpad_path = os.path.join(CURRENT_DIR, "agent_scratchpad.md")
    agent_code = extract_dafny_code(scratchpad_path)
    if not agent_code:
        print(json.dumps({
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": "Could not find any ```dafny ... ``` code block in agent_scratchpad.md."
        }))
        sys.exit(1)

    # 3. Transpile SQL query to Dafny
    try:
        dafny_spec = transpile_sql_to_dafny(sql_query, schema)
    except Exception as e:
        print(json.dumps({
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": f"SQL Transpilation failed: {e}"
        }))
        sys.exit(1)

    # 4. Generate the Main method and full source file
    # We dynamically construct the generator expression for the dataset size
    row_constructor = generate_row_expr("i")
    
    main_code = f"""
method {{:verify false}} Main() {{
  var data := seq({args.dataset_size}, i => {row_constructor});
  var opt_res := RunQuery(data);
  print "SUCCESS\\n";
}}
"""
    
    full_source = f"{dafny_spec}\n\n{agent_code}\n\n{main_code}"
    
    # We create a temporary build directory for codegen to keep the stable Cargo workspace cache
    temp_build_dir = os.path.join(CURRENT_DIR, "temp_build")
    os.makedirs(temp_build_dir, exist_ok=True)
    working_dfy_path = os.path.join(temp_build_dir, "working_query.dfy")
    
    with open(working_dfy_path, "w") as f:
        f.write(full_source)

    # 5. Static Proof Verification
    # Run dafny verify with timeout
    verify_cmd = [
        "dafny", "verify",
        "--allow-warnings",
        f"--verification-time-limit={dafny_verify_timeout}",
        working_dfy_path
    ]
    
    start_verify = time.perf_counter()
    verify_time_ms = -1
    try:
        verify_res = subprocess.run(
            verify_cmd,
            capture_output=True,
            text=True,
            timeout=dafny_verify_timeout
        )
        verify_time_ms = int((time.perf_counter() - start_verify) * 1000)
        if verify_res.returncode != 0:
            error_msg = verify_res.stdout + "\n" + verify_res.stderr
            shutil.rmtree(temp_build_dir, ignore_errors=True)
            print(json.dumps({
                "status": "FAILURE",
                "proof_verified": False,
                "latency_us": -1,
                "compiler_error": f"Dafny verification failed:\n{error_msg.strip()}",
                "verification_time_ms": verify_time_ms,
                "compilation_time_ms": -1
            }))
            sys.exit(0)
    except subprocess.TimeoutExpired:
        verify_time_ms = int((time.perf_counter() - start_verify) * 1000)
        shutil.rmtree(temp_build_dir, ignore_errors=True)
        print(json.dumps({
            "status": "FAILURE",
            "proof_verified": False,
            "latency_us": -1,
            "compiler_error": f"Dafny verification timed out after {dafny_verify_timeout} seconds.",
            "verification_time_ms": verify_time_ms,
            "compilation_time_ms": -1
        }))
        sys.exit(0)

    # 6. Translate/Build Target Code (Rust) in the temp directory
    stable_rust_dir = os.path.join(CURRENT_DIR, "working_query-rust")
    temp_rust_dir = os.path.join(temp_build_dir, "working_query-rust")
    needs_full_build = not os.path.exists(stable_rust_dir) or not os.path.exists(os.path.join(stable_rust_dir, "Cargo.toml"))
    
    start_compile = time.perf_counter()
    compile_time_ms = -1
    if needs_full_build:
        build_cmd = [
            "dafny", "build",
            "--target:rs",
            "--enforce-determinism",
            "--no-verify",
            "--allow-warnings",
            working_dfy_path
        ]
    else:
        build_cmd = [
            "dafny", "translate", "rs",
            "--enforce-determinism",
            "--no-verify",
            "--allow-warnings",
            working_dfy_path
        ]
    
    try:
        build_res = subprocess.run(
            build_cmd,
            cwd=temp_build_dir,
            capture_output=True,
            text=True,
            timeout=compile_timeout
        )
        if build_res.returncode != 0:
            error_msg = build_res.stdout + "\n" + build_res.stderr
            shutil.rmtree(temp_build_dir, ignore_errors=True)
            print(json.dumps({
                "status": "FAILURE",
                "proof_verified": True,
                "latency_us": -1,
                "compiler_error": f"Dafny build (codegen) failed:\n{error_msg.strip()}",
                "verification_time_ms": verify_time_ms,
                "compilation_time_ms": -1
            }))
            sys.exit(0)
    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_build_dir, ignore_errors=True)
        print(json.dumps({
            "status": "FAILURE",
            "proof_verified": True,
            "latency_us": -1,
            "compiler_error": f"Dafny build timed out after {compile_timeout} seconds.",
            "verification_time_ms": verify_time_ms,
            "compilation_time_ms": -1
        }))
        sys.exit(0)

    # 6b. Sync generated Rust files into stable, cached workspace
    try:
        if needs_full_build:
            shutil.rmtree(stable_rust_dir, ignore_errors=True)
            shutil.copytree(temp_rust_dir, stable_rust_dir)
        else:
            src_file_temp = os.path.join(temp_rust_dir, "src", "working_query.rs")
            src_file_stable = os.path.join(stable_rust_dir, "src", "working_query.rs")
            shutil.copy2(src_file_temp, src_file_stable)
            
            metadata_temp = os.path.join(temp_rust_dir, "src", "working_query-rs.dtr")
            metadata_stable = os.path.join(stable_rust_dir, "src", "working_query-rs.dtr")
            if os.path.exists(metadata_temp):
                shutil.copy2(metadata_temp, metadata_stable)
    except Exception as e:
        shutil.rmtree(temp_build_dir, ignore_errors=True)
        print(json.dumps({
            "status": "FAILURE",
            "proof_verified": True,
            "latency_us": -1,
            "compiler_error": f"Failed to sync generated Rust source into stable workspace: {e}",
            "verification_time_ms": verify_time_ms,
            "compilation_time_ms": -1
        }))
        sys.exit(0)

    shutil.rmtree(temp_build_dir, ignore_errors=True)

    # 7. Native Compilation using Cargo (Release Mode)
    cargo_toml_path = os.path.join(stable_rust_dir, "Cargo.toml")
    cargo_cmd = ["cargo", "build", "--release", "--manifest-path", cargo_toml_path]
    
    try:
        cargo_res = subprocess.run(
            cargo_cmd,
            capture_output=True,
            text=True,
            timeout=compile_timeout
        )
        compile_time_ms = int((time.perf_counter() - start_compile) * 1000)
        if cargo_res.returncode != 0:
            error_msg = cargo_res.stdout + "\n" + cargo_res.stderr
            print(json.dumps({
                "status": "FAILURE",
                "proof_verified": True,
                "latency_us": -1,
                "compiler_error": f"Cargo release build failed:\n{error_msg.strip()}",
                "verification_time_ms": verify_time_ms,
                "compilation_time_ms": compile_time_ms
            }))
            sys.exit(0)
    except subprocess.TimeoutExpired:
        compile_time_ms = int((time.perf_counter() - start_compile) * 1000)
        print(json.dumps({
            "status": "FAILURE",
            "proof_verified": True,
            "latency_us": -1,
            "compiler_error": f"Cargo build timed out after {compile_timeout} seconds.",
            "verification_time_ms": verify_time_ms,
            "compilation_time_ms": compile_time_ms
        }))
        sys.exit(0)

    # 8. Execution and Latency Profiling
    binary_path = os.path.join(stable_rust_dir, "target", "release", "working_query")
    if not os.path.exists(binary_path):
        print(json.dumps({
            "status": "FAILURE",
            "proof_verified": True,
            "latency_us": -1,
            "compiler_error": f"Compiled executable not found at {binary_path}.",
            "verification_time_ms": verify_time_ms,
            "compilation_time_ms": compile_time_ms
        }))
        sys.exit(0)

    try:
        start_time = time.perf_counter()
        run_res = subprocess.run(
            [binary_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        end_time = time.perf_counter()
        latency_us = int((end_time - start_time) * 1_000_000)

        stdout = run_res.stdout.strip()
        if run_res.returncode != 0:
            print(json.dumps({
                "status": "FAILURE",
                "proof_verified": True,
                "latency_us": -1,
                "compiler_error": f"Executable crashed during execution. Return code: {run_res.returncode}\nSTDERR: {run_res.stderr}",
                "verification_time_ms": verify_time_ms,
                "compilation_time_ms": compile_time_ms
            }))
            sys.exit(0)
        
        if "ERROR" in stdout or "runtime mismatch" in stdout:
            print(json.dumps({
                "status": "FAILURE",
                "proof_verified": True,
                "latency_us": -1,
                "compiler_error": f"Runtime mismatch: result of optimized method did not match reference spec.\nSTDOUT: {stdout}",
                "verification_time_ms": verify_time_ms,
                "compilation_time_ms": compile_time_ms
            }))
            sys.exit(0)

        # Successful execution
        print(json.dumps({
            "status": "SUCCESS",
            "proof_verified": True,
            "latency_us": latency_us,
            "compiler_error": "",
            "verification_time_ms": verify_time_ms,
            "compilation_time_ms": compile_time_ms
        }, indent=2))

    except subprocess.TimeoutExpired:
        print(json.dumps({
            "status": "FAILURE",
            "proof_verified": True,
            "latency_us": -1,
            "compiler_error": "Executable timed out (hung) during benchmarking execution.",
            "verification_time_ms": verify_time_ms,
            "compilation_time_ms": compile_time_ms
        }))
        sys.exit(0)

if __name__ == "__main__":
    main()
