"""Exact rationals for AVG and `/` (lemma.toml [sql] exact_division, default on).

The rule is JetStream's (arXiv 2610.20527): arithmetic is exact, and division and AVG produce exact rationals. An AVG or a
division over exact operands (integers, DECIMAL, DATE arithmetic) is stated as the quotient ``n / d`` of two mathematical
integers. Nothing in the spec is a float and no float trusted item is pasted:

* a result field is a ``Rat { num: i128, den: i128 }`` and the spec says ``rat_is(r, n, d)``: ``r.den > 0`` and
  ``r.num * d == n * r.den`` (any equal fraction is fine; cross-multiplied, so no division is ever stated). A division by a
  SUM or COUNT that is 0 is data: ``r.den == 0`` and ``r.num`` has the sign of ``n``. The host prints a ``Rat`` as the
  double ``(num as f64) / (den as f64)`` outside the proof (``assemble._row_printer``): ``+inf``, ``-inf`` or NaN for the zero
  denominator, exactly DuckDB 1.5.6's DOUBLE division (``ieee_floating_point_ops`` is on; ``x / 0`` is not NULL there);
* an AVG or a division inside a comparison (HAVING, a scalar subquery in WHERE) is a pair of spec fns ``<f>_num`` /
  ``<f>_den`` with ``den > 0``, and the comparison is cross-multiplied into integers (``rat_compare``).
  An AVG that may be over no rows (a scalar subquery, an AVG over derived-table groups) also has ``<f>_nonempty``: SQL's
  AVG of no rows is NULL, so the comparison holds only when it is nonempty (refused under NOT, where NULL is not FALSE).
  An output AVG of no rows is the ``None`` of its ``Option<Rat>`` field (an ungrouped aggregate over no row).

A FLOAT/DOUBLE operand anywhere in the query is refused (``refuse_float_spec``): its exact statement needs an error bound,
which is future work (``declarative_spec/future_float_error_bounds/``). The f64 idealization is used only with the flag off.
"""

from __future__ import annotations

import re

from declarative_spec.parse import DeclarativeUnsupported

FLOAT_REFUSAL = (
    "a FLOAT/DOUBLE operand: lemma.toml [sql] exact_division (on) states AVG and `/` as exact rationals and refuses floats, "
    "whose exact statement needs an error-bound spec (future work, declarative_spec/future_float_error_bounds/); "
    "exact_division = false uses the f64 idealization instead"
)

RAT_DEFS = """// EXACT RATIONAL (lemma.toml [sql] exact_division): an AVG or a division is the exact quotient num / den of two integers;
// nothing about it is a float. The host prints it as the IEEE double quotient num / den, outside the proof.
pub struct Rat {
    pub num: i128,
    pub den: i128,
}

// `r` is the exact rational n / d. d != 0: r.den > 0 and r.num / r.den == n / d (cross-multiplied: any equal fraction).
// d == 0 (a division by a SUM or COUNT that is 0): r.den == 0 and r.num has the sign of n, so the printed double is
// +inf, -inf or NaN, which is what DuckDB's DOUBLE division by zero returns.
pub open spec fn rat_is(r: Rat, n: int, d: int) -> bool {
    if d != 0 {
        r.den > 0 && (r.num as int) * d == n * (r.den as int)
    } else {
        r.den == 0 && ((r.num as int) > 0 <==> n > 0) && ((r.num as int) < 0 <==> n < 0)
    }
}"""

_HOST_REGION = re.compile(r"// HOST_LEMMAS_START.*?// HOST_LEMMAS_END", re.S)
_FLOAT_WORD = re.compile(r"\bf64\b|\breal\b|\d+real\b|f64_literals_ok|abs_real")
_MAG_CONST = re.compile(r"^pub const (MAG_CAP_\w+): u64 = \d+;\n", re.M)


def drop_unread_float_caps(spec: str) -> str:
    """A float column's magnitude constant that nothing else in the spec reads (its column is not loaded) says nothing."""

    def keep(m: re.Match[str]) -> str:
        rest = spec[: m.start()] + spec[m.end() :]
        return m.group(0) if re.search(rf"\b{m.group(1)}\b", rest) else ""

    return _MAG_CONST.sub(keep, spec)


def refuse_float_spec(spec: str) -> None:
    """Fail loudly when the spec (outside the host lemma region) states any float value."""
    if _FLOAT_WORD.search(_HOST_REGION.sub("", spec)):
        raise DeclarativeUnsupported(FLOAT_REFUSAL)


_CMP = ("<=", ">=", "==", "!=", "<", ">")
_REAL_LIT = re.compile(r"^\(?\s*(-?\d+)real(?:\s*/\s*(\d+)real)?\s*\)?$")
_INT_LIT = re.compile(r"^-?\d+(?:int)?$")


def _match_open(text: str, close: int) -> int:
    depth = 0
    for k in range(close, -1, -1):
        if text[k] in ")]":
            depth += 1
        elif text[k] in "([":
            depth -= 1
            if depth == 0:
                return k
    raise DeclarativeUnsupported("internal: unbalanced spec text around an exact rational")


def _match_close(text: str, open_: int) -> int:
    depth = 0
    for k in range(open_, len(text)):
        if text[k] in "([":
            depth += 1
        elif text[k] in ")]":
            depth -= 1
            if depth == 0:
                return k
    raise DeclarativeUnsupported("internal: unbalanced spec text around an exact rational")


def _is_name(c: str) -> bool:
    return c.isalnum() or c in "_.#@"


def _left_operand(text: str, end: int) -> int:
    """Start of the operand that ends at ``end`` (exclusive; spaces already skipped)."""
    k = end
    while k > 0 and (text[k - 1] in ")]" or _is_name(text[k - 1])):
        if text[k - 1] in ")]":
            k = _match_open(text, k - 1)
        else:
            k -= 1
    if k > 0 and text[k - 1] == "-" and (k == 1 or not _is_name(text[k - 2]) and text[k - 2] not in ")]"):
        k -= 1
    return k


def _right_operand(text: str, start: int) -> int:
    """End (exclusive) of the operand that starts at ``start`` (spaces already skipped)."""
    k = start
    if k < len(text) and text[k] == "-":
        k += 1
    while k < len(text) and (text[k] in "([" or _is_name(text[k])):
        if text[k] in "([":
            k = _match_close(text, k) + 1
        else:
            k += 1
    return k


def _op_after(text: str, k: int) -> str | None:
    for op in _CMP:
        if text.startswith(op, k):
            return op
    return None


def _op_before(text: str, k: int) -> str | None:
    for op in _CMP:
        if k - len(op) >= 0 and text[k - len(op) : k] == op:
            if op in ("<", ">") and k - 2 >= 0 and text[k - 2] in "<>=!":
                continue
            return op
    return None


def _require_whole_comparison(text: str, a: int, b: int) -> None:
    """``text[a:b]`` must be a whole comparison: no arithmetic operator binds to either end (``x + 1 > tok`` is ``(x + 1) > tok``)."""
    before = text[:a].rstrip()
    after = text[b:].lstrip()
    if before.endswith(("+", "-", "*", "/", "%")) or after.startswith(("+", "-", "*", "/", "%")):
        raise DeclarativeUnsupported("an AVG or a division compared with an arithmetic expression that is not parenthesized")


def _side(operand: str, rats: dict[str, tuple[str, str]]) -> tuple[str, str]:
    """``operand`` as (numerator, denominator > 0) spec text."""
    operand = operand.strip()
    if operand in rats:
        return rats[operand]
    lit = _REAL_LIT.match(operand)
    if lit is not None:  # a decimal literal of the numeric rewrite (`1.5e0`, see emit_surface._real_literals): exact p / q
        return lit.group(1), lit.group(2) or "1"
    if re.search(r"\breal\b|\d+real\b|\bf64\b", operand):
        raise DeclarativeUnsupported(FLOAT_REFUSAL)
    if any(t in operand for t in rats):
        raise DeclarativeUnsupported("an AVG or a division inside arithmetic: only a comparison with it is stated exactly")
    return (operand if _INT_LIT.match(operand) else f"({operand})"), "1"


EMPTY_AVG_UNDER_NOT = (
    "a comparison with an AVG that may be over no rows (SQL NULL) under NOT: NOT of an unknown comparison is unknown, "
    "which the two-valued spec does not state yet"
)


def _negated(text: str, a: int) -> bool:
    """Is position ``a`` inside a negation: a ``!`` directly before it, or before any parenthesis that encloses it?"""
    if text[:a].rstrip().endswith("!"):
        return True
    depth = 0
    for k in range(a - 1, -1, -1):
        if text[k] in ")]":
            depth += 1
        elif text[k] in "([":
            if depth == 0:
                if text[:k].rstrip().endswith("!"):
                    return True
            else:
                depth -= 1
    return False


def rat_compare(text: str, rats: dict[str, tuple[str, ...]]) -> str:
    """Rewrite every comparison that has a token of ``rats`` on one side.

    A token maps to ``(num, den)`` spec text with den > 0, or ``(num, den, nonempty)`` for an AVG that may be over no rows
    (a scalar subquery, an AVG over the groups of a derived table): SQL's AVG of no rows is NULL, and a comparison with
    NULL is never TRUE, so the comparison is stated ``(nonempty && a OP n/d)``. That is exact under AND and OR in a
    WHERE / HAVING (a row passes only when the condition is TRUE); under NOT it is not (NOT NULL is NULL) and is refused.

    ``a OP n/d`` with d > 0 is ``a * d OP n``; ``n1/d1 OP n2/d2`` is ``n1 * d2 OP n2 * d1``. A token used any other way
    (in arithmetic, as a bare value) is refused: it has no exact integer statement here."""
    guards = {t: v[2] for t, v in rats.items() if len(v) > 2}
    rats = {t: (v[0], v[1]) for t, v in rats.items()}
    for token in sorted(rats, key=len, reverse=True):
        pattern = re.compile(rf"(?<![\w#]){re.escape(token)}(?!\w)")
        while (m := pattern.search(text)) is not None:
            left_end = m.start()
            while left_end > 0 and text[left_end - 1] == " ":
                left_end -= 1
            op = _op_before(text, left_end)
            if op is not None:
                end_of_left = left_end - len(op)
                while end_of_left > 0 and text[end_of_left - 1] == " ":
                    end_of_left -= 1
                start = _left_operand(text, end_of_left)
                lhs, rhs, a, b = text[start:end_of_left], token, start, m.end()
            else:
                k = m.end()
                while k < len(text) and text[k] == " ":
                    k += 1
                op = _op_after(text, k)
                if op is None:
                    raise DeclarativeUnsupported("an AVG or a division outside a comparison: only a comparison with it is stated exactly")
                s = k + len(op)
                while s < len(text) and text[s] == " ":
                    s += 1
                end = _right_operand(text, s)
                lhs, rhs, a, b = token, text[s:end], m.start(), end
            _require_whole_comparison(text, a, b)
            (ln, ld), (rn, rd) = _side(lhs, rats), _side(rhs, rats)
            # n1/d1 OP n2/d2 with d1, d2 > 0:  n1 * d2 OP n2 * d1
            left = ln if rd == "1" else f"{ln} * {rd}"
            right = rn if ld == "1" else f"{rn} * {ld}"
            empty = [guards[t] for t in (lhs.strip(), rhs.strip()) if t in guards]
            if empty and _negated(text, a):
                raise DeclarativeUnsupported(EMPTY_AVG_UNDER_NOT)
            compared = f"{left} {op} {right}"
            text = text[:a] + (f"({' && '.join(empty)} && {compared})" if empty else f"({compared})") + text[b:]
    return text


def finish_exact_spec(spec: str) -> str:
    """The last step of an exact-division spec: drop unread float caps, refuse a float, add ``Rat`` / ``rat_is`` when used."""
    spec = drop_unread_float_caps(spec)
    refuse_float_spec(spec)
    if "rat_is(" in spec and "spec fn rat_is(" not in spec:
        assert spec.count("// HOST_LEMMAS_START") == 1
        spec = spec.replace("// HOST_LEMMAS_START", RAT_DEFS + "\n\n// HOST_LEMMAS_START", 1)
    return spec
