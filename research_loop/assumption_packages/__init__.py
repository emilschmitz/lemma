"""Named assumption packages. Each package is a separate config.

Select one with ``LEMMA_ASSUMPTION_PACKAGE``. Unset measures the SEC product
catalog from ``LEMMA_DUCKDB_PATH`` and raises when that is unavailable. The
tiny prove_loop profile is only reachable by naming it here.
"""

from __future__ import annotations

from collections.abc import Callable

from research_loop.sec_table_assumptions import sec_prove_loop_catalog_assumptions
from research_loop.assumption_packages.sec_margin import sec_margin_catalog, sec_margin_dec_catalog
from research_loop.table_assumptions import CatalogAssumptions

PackageBuilder = Callable[[], CatalogAssumptions]

PACKAGES: dict[str, PackageBuilder] = {
    "sec_margin": sec_margin_catalog,
    "sec_margin_dec": sec_margin_dec_catalog,
    "prove_loop": sec_prove_loop_catalog_assumptions,
}


def assumption_package(name: str) -> CatalogAssumptions:
    """Build the named package. Unknown names raise."""
    key = name.strip()
    try:
        build = PACKAGES[key]
    except KeyError as exc:
        known = ", ".join(sorted(PACKAGES))
        raise ValueError(
            f"unknown LEMMA_ASSUMPTION_PACKAGE {name!r}; known: {known}"
        ) from exc
    return build()
