"""Golden hashes of the assumption-package path (lemma.toml ``assumptions = true``), taken from the emitter and assembler
of commit 5736d0f, before the flag existed. ``tests/test_assumptions_flag.py`` checks that ``assumptions = true`` still
produces these bytes; ``python tests/assumptions_golden.py`` regenerates the file (only ever from a commit whose
assumption-package output is meant to change).

Each case is a TPC-H query (``tests/fixtures/tpch22``) under the in-repo ``tpch_sf1`` package, in one string encoding:
the spec (emit) and the program the assembler stitches around an empty body with column files (the generated ``main``
with its load-time checks).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "tpch22"
GOLDEN = ROOT / "tests" / "fixtures" / "assumptions_on_golden.json"
CASES = (("q01", "dict"), ("q03", "dict"), ("q06", "plain"), ("q12", "dict"), ("q14", "plain"))


def spec_and_program(name: str, encoding: str) -> tuple[str, str]:
    from declarative_spec.assemble import assemble_declarative_program
    from declarative_spec.emit import emit_declarative_spec
    from research_loop.assumption_packages import assumption_package

    os.environ["LEMMA_STRING_ENCODING"] = encoding
    schema = json.loads((FIXTURES / "schema.json").read_text())
    spec = emit_declarative_spec((FIXTURES / f"{name}.sql").read_text().strip(), schema, assumption_package("tpch_sf1"))
    suffixes = re.findall(r"pub struct Cols_(\w+)\s*\{", spec)
    program = assemble_declarative_program(spec, "", column_bins={s: f"/data/{s}.bin" for s in suffixes})
    return spec, program


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> int:
    os.environ["LEMMA_ASSUMPTIONS"] = "1"
    os.environ["LEMMA_PARALLEL_VSTD"] = "off"
    os.environ["LEMMA_JOIN_CHAIN"] = "0"
    os.environ["LEMMA_AGENT_SCAN"] = "0"  # agent scans came later; the golden is the spec without scan handles
    out = {}
    for name, encoding in CASES:
        spec, program = spec_and_program(name, encoding)
        out[f"{name}_{encoding}"] = {"spec": digest(spec), "program": digest(program)}
    GOLDEN.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"wrote {GOLDEN} ({len(out)} cases)")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
