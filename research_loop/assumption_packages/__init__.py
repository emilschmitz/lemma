"""Named assumption packages. Each package is a separate config.

Select one with ``LEMMA_ASSUMPTION_PACKAGE``: a built-in name, a JSON file in ``registry/`` by name, or a path to a
JSON file (``json_io.py``; ``profile.py`` writes one from your data). Unset measures the SEC product
catalog from ``LEMMA_DUCKDB_PATH`` and raises when that is unavailable. The
tiny prove_loop profile is only reachable by naming it here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from research_loop.sec_table_assumptions import sec_prove_loop_catalog_assumptions
from research_loop.assumption_packages.json_io import load_catalog_json
from research_loop.assumption_packages.sec_margin import sec_margin_catalog, sec_margin_dec_catalog
from research_loop.table_assumptions import CatalogAssumptions

PackageBuilder = Callable[[], CatalogAssumptions]

PACKAGES: dict[str, PackageBuilder] = {
    "sec_margin": sec_margin_catalog,
    "sec_margin_dec": sec_margin_dec_catalog,
    "prove_loop": sec_prove_loop_catalog_assumptions,
}

REGISTRY_DIR = Path(__file__).parent / "registry"


def assumption_package(name: str) -> CatalogAssumptions:
    """Build the named package: a built-in, a JSON file in ``registry/`` (by name), or a JSON file path.

    Unknown names raise.
    """
    key = name.strip()
    if key in PACKAGES:
        return PACKAGES[key]()
    registered = REGISTRY_DIR / f"{key}.json"
    if registered.is_file():
        return load_catalog_json(registered)
    if key.endswith(".json"):
        return load_catalog_json(key)  # a missing file raises FileNotFoundError
    known = ", ".join(sorted(PACKAGES) + sorted(p.stem for p in REGISTRY_DIR.glob("*.json")))
    raise ValueError(
        f"unknown LEMMA_ASSUMPTION_PACKAGE {name!r}; known: {known}; or give a path to a .json file"
    )
