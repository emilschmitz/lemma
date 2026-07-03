import os
import sys
import re
import json
import time
import subprocess
import argparse
import shutil
import pandas as pd
import duckdb
import matplotlib.pyplot as plt

# Ensure repo root on sys.path (this file lives in scripts/)
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Gemini 3.5 Flash Model API Pricing
# Source: Google Cloud Vertex AI & Google AI Studio official pricing documentation
# (https://cloud.google.com/vertex-ai/generative-ai/pricing)
# Retrieved Date: June 2026
INPUT_PRICE_PER_M = 1.50   # $1.50 per 1 million input tokens (standard pricing tier)
OUTPUT_PRICE_PER_M = 9.00  # $9.00 per 1 million output tokens


# Schema and queries from root queries module
from research_loop.ssb_workload import queries, schema

def generate_cyclic_columns(dataset_size):
    columns = {
        "LO_ORDERKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_LINENUMBER": [1 + (i % 100) for i in range(dataset_size)],
        "LO_CUSTKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_PARTKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_SUPPKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_ORDERDATE": [19930101 + (i % 365) for i in range(dataset_size)],
        "LO_ORDERPRIORITY": ["1-URGENT" if (i % 2 == 0) else "2-HIGH" for i in range(dataset_size)],
        "LO_SHIPPRIORITY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_QUANTITY": [i % 50 for i in range(dataset_size)],
        "LO_EXTENDEDPRICE": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_ORDTOTALPRICE": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_DISCOUNT": [i % 10 for i in range(dataset_size)],
        "LO_REVENUE": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_SUPPLYCOST": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_TAX": [1 + (i % 100) for i in range(dataset_size)],
        "LO_COMMITDATE": [1 + (i % 100) for i in range(dataset_size)],
        "LO_SHIPMODE": ["dummy"] * dataset_size,
        "C_NAME": ["dummy"] * dataset_size,
        "C_ADDRESS": ["dummy"] * dataset_size,
        "C_CITY": ["UNITED KI1" if (i % 2 == 0) else "UNITED KI2" for i in range(dataset_size)],
        "C_NATION": ["UNITED STATES" if (i % 5 == 0) else "UNITED KINGDOM" for i in range(dataset_size)],
        "C_REGION": ["AMERICA" if (i % 2 == 0) else "ASIA" for i in range(dataset_size)],
        "C_PHONE": ["dummy"] * dataset_size,
        "C_MKTSEGMENT": ["dummy"] * dataset_size,
        "S_NAME": ["dummy"] * dataset_size,
        "S_ADDRESS": ["dummy"] * dataset_size,
        "S_CITY": ["UNITED KI5" if (i % 2 == 0) else "UNITED KI6" for i in range(dataset_size)],
        "S_NATION": ["UNITED STATES" if (i % 5 == 0) else "UNITED KINGDOM" for i in range(dataset_size)],
        "S_REGION": ["AMERICA" if (i % 2 == 0) else "ASIA" for i in range(dataset_size)],
        "S_PHONE": ["dummy"] * dataset_size,
        "P_NAME": ["dummy"] * dataset_size,
        "P_MFGR": ["dummy"] * dataset_size,
        "P_CATEGORY": ["MFGR#12" if (i % 3 == 0) else "MFGR#14" for i in range(dataset_size)],
        "P_BRAND": ["MFGR#2221" if (i % 4 == 0) else "MFGR#2222" for i in range(dataset_size)],
        "P_COLOR": ["dummy"] * dataset_size,
        "P_TYPE": ["dummy"] * dataset_size,
        "P_SIZE": [1 + (i % 100) for i in range(dataset_size)],
        "P_CONTAINER": ["dummy"] * dataset_size,
        "D_YEAR": [1992 + (i % 7) for i in range(dataset_size)],
        "D_YEARMONTHNUM": [1 + (i % 100) for i in range(dataset_size)],
        "D_WEEKNUMINYEAR": [1 + (i % 52) for i in range(dataset_size)]
    }
    return columns

def run_duckdb_baseline(query_id, dataset_size):
    print(f"--- Running DuckDB Baseline (Query {query_id}, dataset size {dataset_size}) ---")
    con = duckdb.connect(database=':memory:')
    con.execute(f"""
        CREATE TABLE lineorder_flat AS 
        SELECT * FROM read_csv('{os.path.join(root_dir, "ssb-dbgen", "lineorder_flat.tbl")}', delim='|', header=True)
        LIMIT {dataset_size}
    """)
    
    sql = queries[query_id - 1]
    
    # Warmup
    con.execute(sql).fetchall()
    
    # Measure
    latencies_us = []
    for _ in range(5):
        start = time.perf_counter()
        con.execute(sql).fetchall()
        latencies_us.append(int((time.perf_counter() - start) * 1_000_000))
        
    avg_latency = sum(latencies_us) / len(latencies_us)
    print(f"DuckDB average latency: {avg_latency:.2f} us")
    return avg_latency

def estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.5)

def parse_transcript_tokens(transcript_path):
    if not transcript_path or not os.path.exists(transcript_path):
        return 0, 0
    input_tokens = 0
    output_tokens = 0
    with open(transcript_path, "r") as f:
        for line in f:
            try:
                data = json.loads(line)
                content = data.get("content", "")
                if data.get("source") == "USER_EXPLICIT":
                    input_tokens += estimate_tokens(content)
                elif data.get("source") == "MODEL":
                    output_tokens += estimate_tokens(content)
            except json.JSONDecodeError:
                continue
    return input_tokens, output_tokens

def generate_plots(query_id, history_path, duckdb_latency, output_dir):
    if not os.path.exists(history_path):
        return
    with open(history_path, "r") as f:
        history = json.load(f)
        
    iterations = [h["iteration"] for h in history]
    rust_latencies = [h["rust_latency_us"] for h in history]
    cumulative_cost = [h["cumulative_cost_usd"] for h in history]
    
    # Filter out failures from plotting latencies
    valid_iters = []
    valid_lats = []
    for i, lat in zip(iterations, rust_latencies):
        if lat > 0:
            valid_iters.append(i)
            valid_lats.append(lat)
            
    fig, ax1 = plt.subplots(figsize=(10, 5))
    
    # Plot Rust Latencies
    color = "tab:blue"
    ax1.set_xlabel("Optimization Iterations")
    ax1.set_ylabel("Execution Latency (us)", color=color)
    if valid_lats:
        ax1.plot(valid_iters, valid_lats, marker="o", color=color, linewidth=2, label="Rust (Verified)")
    ax1.axhline(y=duckdb_latency, color="green", linestyle="--", label="DuckDB (Baseline)")
    ax1.tick_params(axis="y", labelcolor=color)
    ax1.legend(loc="upper left")
    
    # Plot Cumulative Cost
    ax2 = ax1.twinx()
    color = "tab:red"
    ax2.set_ylabel("Cumulative Cost (USD)", color=color)
    ax2.plot(iterations, cumulative_cost, marker="x", color=color, linestyle=":", label="Cost")
    ax2.tick_params(axis="y", labelcolor=color)
    ax2.legend(loc="upper right")
    
    plt.title(f"Verified Query Optimizer Hill-Climbing Curves (Query {query_id})")
    fig.tight_layout()
    chart_path = os.path.join(output_dir, "hill_climbing_chart.png")
    plt.savefig(chart_path)
    plt.close()
    
    # Stacked bar plot for Time Breakdown
    exec_ms = []
    for h in history:
        lat = h.get("rust_latency_us", -1)
        exec_ms.append(lat / 1000.0 if lat > 0 else 0)
        
    transpile_ms = [max(0, h.get("transpile_time_ms", 0)) for h in history]
    verify_ms = [max(0, h.get("verification_time_ms", 0)) for h in history]
    compile_ms = [max(0, h.get("compilation_time_ms", 0)) for h in history]
    agent_ms = [max(0, h.get("agent_time_ms", 0)) for h in history]
    
    fig, ax = plt.subplots(figsize=(10, 5))
    
    import numpy as np
    bars_transpile = np.array(transpile_ms)
    bars_agent = np.array(agent_ms)
    bars_verify = np.array(verify_ms)
    bars_compile = np.array(compile_ms)
    bars_exec = np.array(exec_ms)
    
    ax.bar(iterations, bars_transpile, label="SQL Transpile")
    ax.bar(iterations, bars_agent, bottom=bars_transpile, label="Agent Coding / Search")
    ax.bar(iterations, bars_verify, bottom=bars_transpile + bars_agent, label="Dafny verification")
    ax.bar(iterations, bars_compile, bottom=bars_transpile + bars_agent + bars_verify, label="Rust/Cargo compile")
    ax.bar(iterations, bars_exec, bottom=bars_transpile + bars_agent + bars_verify + bars_compile, label="Rust execute")
    
    ax.set_xlabel("Iterations")
    ax.set_ylabel("Time (ms)")
    ax.set_title(f"Iteration Time Breakdown (Query {query_id})")
    ax.legend()
    
    breakdown_path = os.path.join(output_dir, "time_breakdown_chart.png")
    plt.tight_layout()
    plt.savefig(breakdown_path)
    plt.close()
    print(f"Time breakdown chart saved to {breakdown_path}")

def run_experiment(query_id, dataset_size, max_iterations, model=None):
    output_dir = f"experiments/Q{query_id}"
    os.makedirs(output_dir, exist_ok=True)
    
    history_path = os.path.join(output_dir, "history.json")
    history = []
    if os.path.exists(history_path):
        with open(history_path, "r") as f:
            history = json.load(f)
            
    # 1. Get DuckDB Baseline
    duckdb_latency = run_duckdb_baseline(query_id, dataset_size)
    
    current_best_latency = -1
    for h in history:
        if h["rust_latency_us"] > 0:
            if current_best_latency == -1 or h["rust_latency_us"] < current_best_latency:
                current_best_latency = h["rust_latency_us"]
                
    start_iter = len(history) + 1
    cumulative_cost = history[-1]["cumulative_cost_usd"] if history else 0.0
    
    print(f"\n=== Starting Auto-Research Optimization Loop (Query {query_id}) ===")
    print(f"Dataset Size: {dataset_size} rows")
    print(f"DuckDB Baseline: {duckdb_latency:.2f} us")
    print(f"Current best Rust latency: {current_best_latency} us")
    
    for iteration in range(start_iter, start_iter + max_iterations):
        print(f"\n--- Iteration {iteration} ---")
        
        # Get last execution details
        last_feedback = "No runs yet. Write the initial optimized RunQuery method."
        last_code = ""
        if history:
            last = history[-1]
            last_code = last.get("code", "")
            if last["status"] == "SUCCESS":
                last_feedback = f"Verification succeeded. Rust latency: {last['rust_latency_us']} us (DuckDB baseline: {duckdb_latency:.2f} us)."
            else:
                last_feedback = f"Failure: {last['compiler_error']}"
                
        # Generate prompt for agy CLI
        prompt = f"""
We are optimizing SQL Query {query_id} (SSB Flat workload).
The database schema has 41 columns. The benchmark size is {dataset_size} rows.

Your task is to write a faster, formally verified imperative 'method RunQuery(data: seq<Row>)' in Dafny.
Ensure the method is proved correct relative to the specification:
  ensures res == MethodSpec(data)

Previous code:
```dafny
{last_code}
```

Feedback:
{last_feedback}

Target DuckDB baseline latency: {duckdb_latency:.2f} microseconds.
Current best verified Rust latency: {current_best_latency if current_best_latency > 0 else 'N/A'} microseconds.

Optimization guidelines:
1. Avoid mathematical integers ('int') where possible to prevent heap-allocated 'BigInt' overhead. Use native integers/ranges, or restrict operations.
2. Minimize index-based sequence retrievals (data[i]) which execute key lookups under the hood.
3. Write your optimized code inside a ```dafny ... ``` block. Use inductive loop invariants so Dafny/Z3 can verify correctness statically.

IMPORTANT: Before writing any code, read the compilation reference guide at:
  {os.path.join(root_dir, "research_loop", "COMPILATION_GUIDE.md")}
This explains exactly how your Dafny code will be translated to Rust and what patterns
the post-processor can and cannot optimize. Writing post-processor-friendly Dafny is
essential for achieving fast execution — verified-but-slow is not good enough.

Note: The workspace root is `{root_dir}`.
The SQL transpiler queries and schemas are defined in `research_loop/ssb_workload.py`.
You must write your optimized Dafny method in a ```dafny ... ``` block, and it will be written to `{os.path.join(root_dir, "research_loop", "agent_scratchpad.md")}`.
"""
        
        log_file = os.path.join(output_dir, f"iter_{iteration}_agy.log")
        
        # Run agy CLI as a subprocess
        cmd = [
            "agy",
            "--log-file", log_file,
            "--print", prompt,
            "--dangerously-skip-permissions"
        ]
        if model:
            cmd += ["--model", model]
        
        print("Launching agy optimizer agent...")
        agent_start = time.perf_counter()
        subprocess.run(cmd, capture_output=True, text=True)
        agent_time = time.perf_counter() - agent_start
        agent_time_ms = int(agent_time * 1000)
        print(f"Agent finished in {agent_time:.2f} seconds.")
        
        # Extract Conversation ID
        conv_id = None
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                for line in f:
                    match = re.search(r"Created conversation ([\w-]+)", line)
                    if match:
                        conv_id = match.group(1)
                        break
                        
        print(f"Conversation ID: {conv_id}")
        
        # Copy and parse transcript
        transcript_dest = os.path.join(output_dir, f"iter_{iteration}_transcript.jsonl")
        input_toks, output_toks = 0, 0
        if conv_id:
            src_transcript = f"/home/emil/.gemini/antigravity-cli/brain/{conv_id}/.system_generated/logs/transcript.jsonl"
            if os.path.exists(src_transcript):
                shutil.copy2(src_transcript, transcript_dest)
                input_toks, output_toks = parse_transcript_tokens(transcript_dest)
                
        # Calculate cost
        cost = (input_toks * (INPUT_PRICE_PER_M / 1_000_000)) + (output_toks * (OUTPUT_PRICE_PER_M / 1_000_000))
        cumulative_cost += cost
        
        # Read the generated code in agent_scratchpad.md
        code = ""
        scratchpad_path = "research_loop/agent_scratchpad.md"
        if os.path.exists(scratchpad_path):
            with open(scratchpad_path, "r") as f:
                content = f.read()
                code_match = re.search(r"```dafny\s*([\s\S]*?)```", content)
                if code_match:
                    code = code_match.group(1).strip()
                    
        # Run verify/compile/benchmark harness
        print("Running verification and benchmark harness...")
        harness_cmd = [
            "uv", "run", "python", "research_loop/harness.py",
            "-q", str(query_id),
            "--dataset-size", str(dataset_size)
        ]
        harness_res = subprocess.run(harness_cmd, capture_output=True, text=True)
        
        try:
            metrics = json.loads(harness_res.stdout)
        except json.JSONDecodeError:
            metrics = {
                "status": "FAILURE",
                "proof_verified": False,
                "latency_us": -1,
                "compiler_error": f"Harness crashed: {harness_res.stderr}",
                "transpile_time_ms": -1,
                "verification_time_ms": -1,
                "compilation_time_ms": -1
            }
            
        print(f"Harness status: {metrics['status']}, Latency: {metrics['latency_us']} us")
        
        if metrics["status"] == "SUCCESS":
            lat = metrics["latency_us"]
            if current_best_latency == -1 or lat < current_best_latency:
                current_best_latency = lat
                
        # Record history
        record = {
            "iteration": iteration,
            "conversation_id": conv_id,
            "status": metrics["status"],
            "proof_verified": metrics["proof_verified"],
            "rust_latency_us": metrics["latency_us"],
            "compiler_error": metrics["compiler_error"],
            "transpile_time_ms": metrics.get("transpile_time_ms", -1),
            "verification_time_ms": metrics.get("verification_time_ms", -1),
            "compilation_time_ms": metrics.get("compilation_time_ms", -1),
            "agent_time_ms": agent_time_ms,
            "input_tokens": input_toks,
            "output_tokens": output_toks,
            "cost_usd": cost,
            "cumulative_cost_usd": cumulative_cost,
            "code": code
        }
        history.append(record)
        
        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)
            
        # Plot updated chart
        generate_plots(query_id, history_path, duckdb_latency, output_dir)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orchestrate query optimization experiments")
    parser.add_argument("-q", "--query", type=int, default=1, help="Query index (1-15)")
    parser.add_argument("-d", "--dataset-size", type=int, default=50000, help="Benchmark dataset size")
    parser.add_argument("-n", "--iterations", type=int, default=5, help="Number of iterations to run")
    parser.add_argument("-m", "--model", type=str, default=None, help="Model name to pass to agy (e.g. 'Claude Sonnet 4.6 (Thinking)')")
    args = parser.parse_args()
    
    run_experiment(args.query, args.dataset_size, args.iterations, model=args.model)
