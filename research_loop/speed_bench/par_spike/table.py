import json
import sys
from pathlib import Path

D = Path(__file__).parent / "results"
for f in sys.argv[1:] or ["r2M.json", "r20M.json", "r100M.json"]:
    for e in json.loads((D / f).read_text()):
        u = {k: v["median"] / 1000 for k, v in e["us"].items()}
        ok = all(e["match_duck8"].values())
        print(
            f"{e['rows']//10**6:>4}M {e['id']:<16} single {u['single']:8.1f} | "
            + " ".join(f"p{t} {u[f'par{t}']:7.1f}" for t in (1, 2, 4, 8))
            + f" | duck8 {u['duck8']:8.1f} duck1 {u['duck1']:8.1f} ms | "
            + "x single p8 {:.2f}  best {:.2f} | x duck8 single {:.2f} p8 {:.2f} | match {} noisy {} idle {}".format(
                e["speedup_vs_single"]["par8"],
                max(e["speedup_vs_single"].values()),
                e["speedup_vs_duck8"]["single"],
                e["speedup_vs_duck8"]["par8"],
                ok,
                e["noisy"],
                min(e["idle_before_blocks"]),
            )
        )
