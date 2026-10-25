"""`lemma generate`: what the DuckDB extension's ``lemma('<sql>')`` runs for a query without a proved executor.

    lemma generate --db SNAPSHOT --sql-file FILE [--source-db PATH] [--lift-constants | --no-lift-constants] [--regenerate]

``SNAPSHOT`` is the DuckDB file the extension wrote for this job: the tables the query reads, as the caller's transaction saw them
(the caller's own database is locked by the caller's DuckDB). With lifting on (the default; the extension passes its
``lemma_lift_constants`` setting), the query's literal constants in WHERE/HAVING comparisons become typed template parameters
(declarative_spec/lift.py says exactly which) and the pipeline proves the TEMPLATE, measured on the query's own values; the executor then
answers every query that differs only in those constants. Then ``lemma optimize``'s path: the sandboxed agent proves ``run_query``,
Verus verifies and compiles the library, and it is installed under ``$LEMMA_HOME/executors/<key>/`` (replacing an older one only after
the new one proved: ``install_executor`` stages and renames). The last line is ``INSTALLED <key>``; any failure installs nothing and
exits non-zero.
"""

from __future__ import annotations

import os
from pathlib import Path

from lemma_cli import cache
from lemma_cli.common import CliError, normalize_sql, say, sql_key


def target_sql(sql: str, db: Path, lift: bool) -> tuple[str, dict[str, str] | None]:
    """``(the SQL to prove, the binding that instantiates it to the query)``: the lifted template, or the query itself (binding None)."""
    if not lift:
        return normalize_sql(sql), None
    os.environ["LEMMA_TEMPLATES"] = "true"  # a `-- params:` header is a template for this process and the pipeline it starts
    from declarative_spec.lift import lift_constants
    from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema
    from research_loop.structural_catalog import structural_catalog_from_db

    lifted = lift_constants(sql, load_sec_schema(db), structural_catalog_from_db(db))
    if lifted is None:
        return normalize_sql(sql), None
    return lifted.template, lifted.binding


def generate(db_arg: str, sql_file: str, source_db: str | None, lift: bool, regenerate: bool) -> int:
    from lemma_cli.optimize import optimize_one

    db = Path(db_arg).expanduser().resolve()
    if not db.is_file():
        raise CliError(f"no database file {db}")
    sql = Path(sql_file).read_text().strip()
    if not sql:
        raise CliError("empty SQL")
    target, binding = target_sql(sql, db, lift)
    key = sql_key(target)
    if binding is None:
        say(f"lemma generate: no constant lifted; proving the query as written (key {key[:12]})")
    else:
        say(f"lemma generate: lifted {len(binding)} constant(s) into a query template (key {key[:12]}):\n{target}\n  this query's values: "
            + ", ".join(f"${k} = {v}" for k, v in binding.items()))
    if (cache.executor_dir(key) / "manifest.json").is_file() and not regenerate:
        say(f"INSTALLED {key} (already installed; --regenerate proves a new one)")
        return 0
    dest = optimize_one(target, db, force=True, binding=binding, source_db=Path(source_db) if source_db else None)
    say(f"INSTALLED {dest.name}")
    return 0
