# par_spike: vstd-thread parallel proved bodies (SPIKE, not wired into the pipeline)

Verus-verified parallel versions of speed-bench q01 (filter sum), q03 (group sum),
q04 (group count). Trusted base evaluated: `vstd::thread::spawn` / `JoinHandle::join`
(`~/tools/verus/vstd/thread.rs`). No new `external_body`, `assume`, `admit`, axiom or
`arbitrary` in these files; the only `external_body` are the `Cols::*_exec` getters copied
verbatim from `proved/q0N_*.rs`.

Design: the loader builds one owned chunk `Cols` per worker. `par_run_query(&mut Vec<Cols>)`
pops each chunk into `spawn(move || ...)`, whose closure ensures the worker's partial result
equals the spec fold over its own chunk and hands the chunk back. The parent joins in order
and merges with proved lemmas (`sc` / `cnt` / `sm` additivity over `+`). The final ensures
is stated over the concatenation of the chunks' columns; `lemma_same_as_single_threaded`
shows it equals the single-threaded `method_spec(whole)` for any whole table whose columns
are that concatenation. q03/q04 workers log rows whose key is >= DENSE (overflow) as
Vec; the parent replays them into the HashMapWithView sequentially (vstd has no hash map
iteration, so per-thread maps cannot be merged).

Verify only (cap 2M rows):

    ~/tools/verus/verus research_loop/speed_bench/par_spike/q01_par.rs --triggers-mode silent
    ~/tools/verus/verus research_loop/speed_bench/par_spike/q03_par.rs --triggers-mode silent
    ~/tools/verus/verus research_loop/speed_bench/par_spike/q04_par.rs --triggers-mode silent

Measure (from repo root; needs a python with duckdb, e.g. the main checkout's `.venv`).
Sets `LEMMA_MAX_ROWS` to the row count like `../measure.py`, verifies and compiles the
single-threaded and parallel bodies, interleaves blocks, waits for CPU idle >= 70%,
15 samples, DuckDB at 8 and 1 threads:

    python research_loop/speed_bench/par_spike/par_measure.py --rows 20000000  --out research_loop/speed_bench/par_spike/results/r20M.json
    python research_loop/speed_bench/par_spike/par_measure.py --rows 100000000 --out research_loop/speed_bench/par_spike/results/r100M.json
    python research_loop/speed_bench/par_spike/table.py

Spawn cost (after the 2M run built the binaries): `sh research_loop/speed_bench/par_spike/spawn_cost.sh`.

Memory-bandwidth probe (unverified measurement tool):

    rustc -O -C target-cpu=native research_loop/speed_bench/par_spike/bw.rs -o /tmp/bw && /tmp/bw

Results are in `results/` (json, `table.txt`, `bandwidth.txt`, `spawn_cost.txt`).
