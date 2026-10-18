"""`lemma assumptions --db PATH`: profile the user's DuckDB, have the user approve every claim, check the package, record the approval.

Wraps research_loop/assumption_packages (profile.py, check.py); the walk-through mirrors .claude/skills/lemma-assumptions. A proof is
IF-THEN: IF the data obeys these bounds THEN the program computes the SQL, so the bounds are the USER's claims and there is no blanket
approval (no ``--yes``): each bound is shown and answered one by one.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path

from lemma_cli.common import CliError, lemma_home, read_json, say, sha256_file, write_json


def package_dir(db: Path) -> Path:
    return lemma_home() / "assumptions" / hashlib.sha256(str(db.resolve()).encode()).hexdigest()[:16]


def resolve_db(path: str) -> Path:
    db = Path(path).expanduser()
    if not db.is_file():
        raise CliError(f"database not found: {db}")
    return db.resolve()


def approved_package(db: Path) -> Path:
    """The approved package file for ``db``; otherwise a ``CliError`` carrying the exact command that creates one."""
    folder = package_dir(db)
    package, approval = folder / "package.json", read_json(folder / "approved.json")
    if not package.is_file() or not approval or approval.get("package_sha256") != sha256_file(package) or approval.get("db_path") != str(db):
        raise CliError(f"no approved assumption package for {db}. A proof only holds IF your data obeys the bounds you approve; create and approve them with:\n\n    lemma assumptions --db {db}\n")
    return package


def profile_to(db: Path, margin: int, value_margin: int, joins: tuple[str, ...]) -> Path:
    import duckdb

    from research_loop.assumption_packages.json_io import catalog_to_dict
    from research_loop.assumption_packages.profile import profile, render_report

    folder = package_dir(db)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "approved.json").unlink(missing_ok=True)  # a re-profile invalidates any earlier approval
    con = duckdb.connect(str(db), read_only=True)
    try:
        catalog, report, proposals = profile(con, margin=margin, value_margin=value_margin, joins=joins)
    finally:
        con.close()
    name = f"lemma_{folder.name}"
    write_json(folder / "package.json", {"name": name, **catalog_to_dict(catalog), "proposals": {"unique_keys": proposals}})
    (folder / "package.md").write_text(render_report(name, report))
    write_json(folder / "report.json", {"report": report})
    return folder


def assumptions(
    db_arg: str,
    *,
    margin: int = 4,
    value_margin: int = 1,
    joins: tuple[str, ...] = (),
    reprofile: bool = False,
    ask: Callable[[str], str] = input,
) -> int:
    from research_loop.assumption_packages.check import AssumptionViolation, check_package

    db = resolve_db(db_arg)
    folder = package_dir(db)
    if reprofile or not (folder / "package.json").is_file():
        profile_to(db, margin, value_margin, joins)
    package = folder / "package.json"
    report = read_json(folder / "report.json")["report"]
    doc = json.loads(package.read_text())
    say(f"Assumptions for {db}\nThese are YOUR claims about your data: a proof holds only IF the data obeys them. Answer y to approve each one, anything else stops.\n"
        f"(Edit {package} and re-run to change a cap; --reprofile measures again.)\n")
    try:
        for i, row in enumerate(report, 1):
            say(f"[{i}/{len(report)}] {row['bound']}\n    measured {row['measured']}, proposed cap {row['cap']}\n    if data exceeds it: {row['breaks']}\n    effect: {row['effect']}")
            if ask("    approve this claim? [y/N] ").strip().lower() != "y":
                say(f"\nNot approved. Nothing was recorded. Edit {package} (or run with --reprofile --margin N) and re-run `lemma assumptions --db {db}`.", err=True)
                return 1
        for table, keys in doc.get("proposals", {}).get("unique_keys", {}).items():
            for key in keys:
                say(f"UNIQUE KEY proposal: {table}({', '.join(key)}) has no duplicate today. Approving declares it can never have one.")
                if ask("    approve this key? [y/N] ").strip().lower() == "y":
                    entry = doc["tables"][table].setdefault("unique_keys", [])
                    if key not in entry:
                        entry.append(key)
    except EOFError as exc:
        raise CliError("approving assumptions needs an interactive terminal (every claim is answered one by one; there is no blanket yes)") from exc
    write_json(package, doc)
    try:
        check_package(str(package), str(db))
    except AssumptionViolation as exc:
        raise CliError(f"the approved package is false on this database:\n{exc}") from exc
    write_json(folder / "approved.json", {
        "package_sha256": sha256_file(package), "db_path": str(db), "approved_claims": len(report), "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    say(f"\nApproved and checked against the database. Package: {package}\nNext: lemma optimize --db {db} --sql QUERY.sql")
    return 0


def package_sha(db: Path) -> str:
    return sha256_file(approved_package(db))

