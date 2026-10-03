"""Declarative SQL → Verus spec emitter (standalone from recursive transpiler)."""

from declarative_spec.admit import admit_declarative_body
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.parse import parse_declarative_sql
from declarative_spec.pipeline import verify_assembled

__all__ = [
    "DeclarativeUnsupported",
    "admit_declarative_body",
    "assemble_declarative_program",
    "emit_declarative_spec",
    "parse_declarative_sql",
    "verify_assembled",
]
