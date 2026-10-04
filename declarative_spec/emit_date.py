"""EXTRACT(year|month|day) over a DATE column as a spec function of days since 1970-01-01.

Howard Hinnant's ``civil_from_days``. Verus ``int`` division is Euclidean, which is the
floor division the algorithm needs for dates before 1970.
"""

from __future__ import annotations

SPEC_CIVIL_FNS = """pub open spec fn spec_civil_doe(days: int) -> int {
    (days + 719468) - ((days + 719468) / 146097) * 146097
}

pub open spec fn spec_civil_yoe(days: int) -> int {
    let doe = spec_civil_doe(days);
    (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365
}

pub open spec fn spec_civil_doy(days: int) -> int {
    let yoe = spec_civil_yoe(days);
    spec_civil_doe(days) - (365 * yoe + yoe / 4 - yoe / 100)
}

pub open spec fn spec_civil_mp(days: int) -> int {
    (5 * spec_civil_doy(days) + 2) / 153
}

pub open spec fn spec_civil_day(days: int) -> int {
    spec_civil_doy(days) - (153 * spec_civil_mp(days) + 2) / 5 + 1
}

pub open spec fn spec_civil_month(days: int) -> int {
    let mp = spec_civil_mp(days);
    if mp < 10 { mp + 3 } else { mp - 9 }
}

pub open spec fn spec_civil_year(days: int) -> int {
    spec_civil_yoe(days) + ((days + 719468) / 146097) * 400
        + (if spec_civil_month(days) <= 2 { 1int } else { 0int })
}"""


def with_civil_fns(text: str) -> str:
    """Define the civil-date spec functions just before the host lemmas when the spec calls them."""
    if "spec_civil_" in text and "spec fn spec_civil_year(" not in text:
        return text.replace("// HOST_LEMMAS_START", SPEC_CIVIL_FNS + "\n\n// HOST_LEMMAS_START", 1)
    return text
