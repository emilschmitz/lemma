"""What the agent sees when a check fails: the Verus log reduced to the errors that matter.

The raw log has three problems for an agent that reads it once per check:

* a tail cut (`log[-4000:]`) drops the FIRST errors, which are usually the root cause;
* rustc warnings from the host's own generated structs (`non_camel_case_types` on `Cols_*`) come first;
* absolute host paths and line numbers of the assembled program, which is not the file the agent edits.

`format_failure` returns: the Verus summary line first, then the errors in source order (first N, with
a count of the omitted ones), warnings only when they point into the agent's own regions, and every
location rewritten to the agent's file (`runquery_agent.rs:LINE`) or marked host-owned. The full log is
written to the run directory by the caller; nothing here deletes information from that file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from declarative_spec.regions import EDIT_END, EDIT_START, HELPERS_END, HELPERS_START
from declarative_spec.verus_limits import _RLIMIT_HIT, verus_rlimit

AGENT_FILE = "runquery_agent.rs"
FULL_LOG_NAME = "verify_full.log"

MAX_ERRORS = 8
MAX_WARNINGS = 3
BLOCK_CHARS = 1500
TOTAL_CHARS = 7000
PREAMBLE_CHARS = 1500

_START = re.compile(r"^(error|warning)(\[[^\]]*\])?:", re.M)
_FOOTER = re.compile(r"^error: (aborting due to|could not compile)")
_SUMMARY = re.compile(r"^.*verification results::.*$", re.M)
_LOC = re.compile(r"^(\s*)(-->|:::)\s+(\S+?):(\d+):(\d+)", re.M)
_GUTTER = re.compile(r"^(\s*)(\d+)(\s*\|)", re.M)


@dataclass(frozen=True)
class Region:
    """A span of lines of the assembled program that is copied verbatim from the agent's file."""

    name: str
    assembled_first: int  # 1-based line in the assembled program of the region's first body line
    lines: int
    agent_first: int | None  # 1-based line of the same text in the agent's file, when known

    def maps(self, line: int) -> bool:
        return self.assembled_first <= line < self.assembled_first + self.lines


def _marker_line(text: str, marker: str) -> int | None:
    idx = text.find(marker)
    return None if idx == -1 else text.count("\n", 0, idx) + 1


def _region(assembled: str, agent_source: str | None, name: str, start: str, end: str) -> Region | None:
    a_marker = _marker_line(assembled, start)
    if a_marker is None:
        return None
    a_start = assembled.index(start) + len(start)
    a_end = assembled.find(end, a_start)
    if a_end == -1:
        return None
    body = assembled[a_start:a_end]
    # The assembler writes "\n" + body + "\n": the first body line sits on the line after the marker.
    lines = body.strip("\n").count("\n") + 1 if body.strip() else 0
    agent_first = None
    if agent_source is not None and start in agent_source and end in agent_source:
        g_start = agent_source.index(start) + len(start)
        g_end = agent_source.find(end, g_start)
        if g_end != -1:
            raw = agent_source[g_start:g_end].replace("\r\n", "\n")
            if raw.strip() == body.strip():
                leading = len(raw) - len(raw.lstrip())
                agent_first = _marker_line(agent_source, start) + raw.count("\n", 0, leading)
    return Region(name, a_marker + 1, lines, agent_first)


def regions_of(assembled: str, agent_source: str | None) -> list[Region]:
    out = []
    for name, start, end in (
        ("AGENT_EDIT body", EDIT_START, EDIT_END),
        ("AGENT_HELPERS", HELPERS_START, HELPERS_END),
    ):
        region = _region(assembled, agent_source, name, start, end)
        if region is not None and region.lines:
            out.append(region)
    return out


def _find_region(regions: list[Region], line: int) -> Region | None:
    for region in regions:
        if region.maps(line):
            return region
    return None


@dataclass
class _Block:
    kind: str  # "error" | "warning"
    text: str
    line: int | None  # line in the assembled program of the primary location
    in_agent: bool


def _scrub_paths(text: str, directory: Path | None) -> str:
    if directory is not None:
        for variant in {str(directory), str(directory.resolve())}:
            text = text.replace(variant.rstrip("/") + "/", "")
    # Remaining absolute paths: keep only the trailing components so no host layout leaks.
    def short(match: re.Match[str]) -> str:
        parts = [p for p in match.group(0).split("/") if p]
        if "vstd" in parts:
            return "vstd/" + "/".join(parts[parts.index("vstd") + 1 :])
        return "<host>/" + "/".join(parts[-2:])

    return re.sub(r"(?<![\w.)\]])/(?:[\w.+@-]+/)+[\w.+@-]+", short, text)


def _rewrite_block(text: str, regions: list[Region], assembled_name: str) -> tuple[str, int | None, bool]:
    """Rewrite one diagnostic block's locations and gutter line numbers. Returns text, primary line, in agent region."""
    primary: list[int | None] = [None]
    in_agent = [False]

    def loc(match: re.Match[str]) -> str:
        indent, arrow, path, line_s, col = match.groups()
        if Path(path).name != assembled_name:
            return match.group(0)  # a vstd or other path: scrubbed later
        line = int(line_s)
        region = _find_region(regions, line)
        if primary[0] is None and arrow == "-->":
            primary[0] = line
            in_agent[0] = region is not None
        if region is None:
            return f"{indent}{arrow} generated program line {line}:{col}  (host-owned code, not editable)"
        if region.agent_first is None:
            rel = line - region.assembled_first + 1
            return f"{indent}{arrow} {region.name} line {rel}:{col}"
        return f"{indent}{arrow} {AGENT_FILE}:{line - region.assembled_first + region.agent_first}:{col}  ({region.name})"

    def gutter(match: re.Match[str]) -> str:
        indent, num, bar = match.groups()
        line = int(num)
        region = _find_region(regions, line)
        if region is None:
            return f"{indent}host{bar}"
        if region.agent_first is None:
            return f"{indent}{line - region.assembled_first + 1}{bar}"
        return f"{indent}{line - region.assembled_first + region.agent_first}{bar}"

    # A snippet belongs to the span named by the last `-->` / `:::` line; only snippets of the assembled
    # program get their gutter rewritten (a vstd snippet keeps its own line numbers).
    out_lines = []
    current_is_assembled = True
    for raw in text.split("\n"):
        m = _LOC.match(raw)
        if re.match(r"(note|help)(\[[^\]]*\])?:", raw):
            current_is_assembled = True  # a sub-diagnostic starts a new span; its own `-->` line (if any) decides
        if m:
            current_is_assembled = Path(m.group(3)).name == assembled_name
            raw = _LOC.sub(loc, raw, count=1)
        elif current_is_assembled:
            raw = _GUTTER.sub(gutter, raw, count=1)
        out_lines.append(raw)
    return "\n".join(out_lines), primary[0], in_agent[0]


def _split_blocks(log: str) -> tuple[str, list[tuple[str, str]]]:
    """(preamble, [(kind, text)]) from a rustc/Verus log with the summary lines already removed."""
    starts = [m for m in _START.finditer(log)]
    if not starts:
        return log.strip(), []
    preamble = log[: starts[0].start()].strip()
    blocks = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(log)
        blocks.append((m.group(1), log[m.start() : end].rstrip()))
    return preamble, blocks


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n  ... (block truncated)"


def format_failure(
    log: str,
    *,
    assembled: str | None = None,
    agent_source: str | None = None,
    assembled_name: str = "declarative_query.rs",
    directory: Path | None = None,
    full_log_hint: str | None = None,
) -> str:
    """The text the agent sees for a failed check. See the module docstring for the shape."""
    summary_match = None
    for m in _SUMMARY.finditer(log):
        summary_match = m  # the last one wins: it is Verus's final tally
    summary = ""
    if summary_match is not None:
        found = re.search(r"verification results:: (\d+) verified, (\d+) errors", summary_match.group(0))
        summary = f"PROOF ERROR: {found.group(0)}." if found else summary_match.group(0).strip()
    body = _SUMMARY.sub("", log)

    regions = regions_of(assembled, agent_source) if assembled is not None else []
    preamble, raw_blocks = _split_blocks(body)

    errors: list[_Block] = []
    warnings: list[_Block] = []
    host_warnings = 0
    for kind, text in raw_blocks:
        if _FOOTER.match(text):
            continue
        rewritten, line, in_agent = _rewrite_block(text, regions, assembled_name)
        block = _Block(kind, rewritten, line, in_agent)
        if kind == "error":
            errors.append(block)
        elif in_agent:
            warnings.append(block)
        else:
            host_warnings += 1

    errors.sort(key=lambda b: -1 if b.line is None else b.line)  # stable: source order, location-less first

    parts: list[str] = []
    if summary:
        parts.append(summary)
    hits = log.count(_RLIMIT_HIT)
    if hits:
        parts.append(
            f"RLIMIT: Z3 ran out of resources on {hits} query(ies) ({_RLIMIT_HIT}, --rlimit {verus_rlimit():g}). "
            "Verus finished, so this is a proof error, not a wall timeout. "
            "Typical cause: a quantifier with a two-term trigger, or a quantifier over `res@`."
        )
    if preamble:
        text = _scrub_paths(preamble, directory)
        if not raw_blocks and len(text) > PREAMBLE_CHARS:  # unrecognised output: keep both ends
            half = PREAMBLE_CHARS // 2
            text = text[:half].rstrip() + "\n  ... (middle omitted) ...\n" + text[-half:].lstrip()
        parts.append(_clip(text, PREAMBLE_CHARS) if raw_blocks else text)

    # Choose which errors to show: those in the agent's regions first (they are the ones it can fix), then host ones,
    # up to the caps; show the chosen ones in source order.
    chosen: list[_Block] = []
    budget = TOTAL_CHARS
    for block in [b for b in errors if b.in_agent] + [b for b in errors if not b.in_agent]:
        if len(chosen) >= MAX_ERRORS:
            break
        size = min(len(block.text), BLOCK_CHARS)
        if chosen and budget - size < 0:
            break
        chosen.append(block)
        budget -= size
    chosen.sort(key=lambda b: -1 if b.line is None else b.line)
    shown = len(chosen)
    for block in chosen:
        parts.append(_clip(_scrub_paths(block.text, directory), BLOCK_CHARS))
    omitted = len(errors) - shown
    if omitted:
        where = f" Full log: {full_log_hint}." if full_log_hint else ""
        parts.append(f"... {omitted} more error(s) omitted (showing {shown} of {len(errors)}, yours first, displayed in source order).{where}")
    for block in warnings[:MAX_WARNINGS]:
        parts.append(_clip(_scrub_paths(block.text, directory), BLOCK_CHARS))
    if len(warnings) > MAX_WARNINGS:
        parts.append(f"... {len(warnings) - MAX_WARNINGS} more warning(s) in your regions omitted.")
    if host_warnings:
        parts.append(f"({host_warnings} warning(s) in host-owned code omitted: not yours to fix.)")
    if not errors and not summary and not preamble and not warnings:
        parts.append(
            "(Verus printed no diagnostics and no verdict. The prover process was most likely killed by its memory cap "
            "(VERUS_MEM_MAX, default 7G): the proof is too heavy for the machine, not wrong. Shrink it: move big loop bodies "
            "into helper lemmas, drop invariants and quantifiers you do not need, and keep each assert small.)"
        )
    return "\n\n".join(parts) + "\n"
