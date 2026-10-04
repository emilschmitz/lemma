"""Dictionary-encoded string columns (``LEMMA_STRING_ENCODING=dict``; the default is ``plain``).

A string column ``c`` is loaded as two vectors: ``c: Vec<u8|u16|u32>`` (one code per row) and
``c__dict: Vec<String>`` (the distinct values). The spec states every fact about the string cell through the
accessor ``t.c__dict@[t.c@[i] as int]@``, so the SQL meaning is unchanged. ``valid_cols`` requires the loader
relation: every code is below ``dict.len()`` and the dictionary entries are pairwise distinct. The generated
``main`` asserts both on the loaded data, like the other ``valid_cols`` facts; nothing here is ``external_body``.

The code width comes from the catalog (``ColumnAssumption.max_distinct``, a data assumption measured by
``assumption_packages/check.py``): u8 up to 256 distinct values, u16 up to 65536, else u32.
"""

from __future__ import annotations

import os

DICT_SUFFIX = "__dict"


def dict_mode() -> bool:
    mode = os.environ.get("LEMMA_STRING_ENCODING", "plain").strip() or "plain"
    if mode not in ("plain", "dict"):
        raise ValueError(f"LEMMA_STRING_ENCODING must be 'plain' or 'dict', got {mode!r}")
    return mode == "dict"


def code_type(max_distinct: int | None) -> str:
    if max_distinct is not None and max_distinct <= 2**8:
        return "u8"
    if max_distinct is not None and max_distinct <= 2**16:
        return "u16"
    return "u32"
