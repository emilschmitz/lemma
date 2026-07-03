"""Human-readable demo output. Progress UI uses stderr when invoked via lemma(); stdout is the DuckDB box return."""
from __future__ import annotations

import os
import re
import sys
import threading
import time
import unicodedata
from contextlib import contextmanager
from typing import Iterator

_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_DIM = "\033[2m"
_RESET = "\033[0m"

_DEMO_TIME_DECIMALS = 6
_LABEL_START_COL = 4  # visual columns before label text
_LABEL_END = 34
_LABEL_FIELD_WIDTH = _LABEL_END - _LABEL_START_COL
_STATUS_WIDTH = 7
_GAP_BEFORE_TIME = 3
_TIME_WIDTH = 10
_TICK_SEC = 0.08

# Spaces after each demo emoji so label text starts at the same visual column.
# Heuristic unicode width is wrong for many symbols in Windows Terminal / VTE
# (e.g. 🏗 and ⚙ render 1 cell wide, not 2). Gaps are tuned for that renderer.
_EMOJI_GAP_AFTER: dict[str, int] = {
    "🏗": 3,
    "⚙": 3,
    "⚙️": 3,
}
_DEFAULT_EMOJI_GAP = 2


def demo_enabled() -> bool:
    return os.environ.get("LEMMA_DEMO", "0") not in ("0", "false", "False", "")


def verbose_enabled() -> bool:
    return os.environ.get("LEMMA_VERBOSE", "0") not in ("0", "false", "False", "")


def _lemma_extension() -> bool:
    """True when lemma() captures stdout for DuckDB's result cell (demo UI must use stderr)."""
    return demo_enabled() and not sys.stdout.isatty()


def _demo_stream():
    return sys.stderr if _lemma_extension() else sys.stdout


def _interactive_tty() -> bool:
    return _demo_stream().isatty()


def _ansi(code: str) -> str:
    if not _interactive_tty():
        return ""
    return code


def _out(line: str, *, end: str = "\n") -> None:
    if demo_enabled():
        print(line, file=_demo_stream(), end=end, flush=True)


def _display_width(text: str) -> int:
    plain = re.sub(r"\033\[[0-9;]*m", "", text)
    width = 0
    i = 0
    while i < len(plain):
        ch = plain[i]
        cp = ord(ch)
        if cp in (0xFE0F, 0x200D):
            i += 1
            continue
        if cp >= 0x1F300 or 0x2600 <= cp <= 0x27BF:
            width += 2
            i += 1
            continue
        if unicodedata.east_asian_width(ch) in ("F", "W"):
            width += 2
        else:
            width += 1
        i += 1
    return width


def format_demo_seconds_from_ms(ms: int | None) -> str:
    if ms is None or ms < 0:
        return ""
    return f"{ms / 1000.0:.{_DEMO_TIME_DECIMALS}f}"


def format_demo_seconds_from_us(us: int | None) -> str:
    if us is None or us < 0:
        return ""
    return f"{us / 1_000_000.0:.{_DEMO_TIME_DECIMALS}f}"


def _emoji_prefix(emoji: str) -> str:
    gap = _EMOJI_GAP_AFTER.get(emoji, _DEFAULT_EMOJI_GAP)
    return emoji + (" " * gap)


def _format_row(
    emoji: str,
    label: str,
    *,
    status: str | None = None,
    status_color: str = _GREEN,
    time_plain: str = "",
    time_color: str = "",
) -> str:
    prefix = _emoji_prefix(emoji)
    label_w = _display_width(label)
    if label_w >= _LABEL_FIELD_WIDTH:
        label_part = label
    else:
        label_part = label + (" " * (_LABEL_FIELD_WIDTH - label_w))
    line = prefix + label_part

    if status is not None:
        plain_status = f"{status:>{_STATUS_WIDTH}}"
        line += f"{_ansi(status_color)}{plain_status}{_ansi(_RESET)}"
    else:
        line += " " * _STATUS_WIDTH

    line += " " * _GAP_BEFORE_TIME

    if time_plain:
        padded = f"{time_plain:>{_TIME_WIDTH}}"
        if time_color:
            line += f"{_ansi(time_color)}{padded}{_ansi(_RESET)}"
        else:
            line += padded
    else:
        line += " " * _TIME_WIDTH

    return line


class _LiveStepHandle:
    def __init__(self, emoji: str, label: str, *, pass_fail: bool, count_up: bool) -> None:
        self.emoji = emoji
        self.label = label
        self.pass_fail = pass_fail
        self.count_up = count_up
        self._passed: bool | None = None
        self._start = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tty = False
        self._last_tick = -1
        self._result_latency_us: int | None = None
        self._live_line_active = False

    def set_passed(self, ok: bool) -> None:
        self._passed = ok

    def set_result_latency_us(self, us: int) -> None:
        self._result_latency_us = us

    def _elapsed_sec(self) -> float:
        return time.perf_counter() - self._start

    def _print_row(self, row: str, *, overwrite: bool = False) -> None:
        if overwrite:
            _out(f"\033[A\033[K{row}")
        else:
            _out(row)

    def _emit_tick(self, elapsed: float) -> None:
        row = _format_row(
            self.emoji,
            self.label,
            status=None,
            time_plain=f"{elapsed:.{_DEMO_TIME_DECIMALS}f}",
        )
        if self._tty:
            print(f"\r{row}", file=_demo_stream(), end="", flush=True)
        else:
            self._print_row(row, overwrite=self._live_line_active)
        self._live_line_active = True

    def _emit_final_row(self, row: str) -> None:
        stream = _demo_stream()
        if self._tty:
            if self._live_line_active:
                print("", file=stream)
            print(row, file=stream, flush=True)
        elif self._live_line_active:
            _out(f"\033[A\033[K{row}")
        else:
            _out(row)
        self._live_line_active = False

    def _tick_loop(self) -> None:
        while not self._stop.wait(_TICK_SEC):
            if self._tty:
                self._emit_tick(self._elapsed_sec())
            else:
                elapsed = self._elapsed_sec()
                tick = int(elapsed * 2)
                if tick != self._last_tick:
                    self._last_tick = tick
                    self._emit_tick(elapsed)

    def start(self) -> None:
        self._start = time.perf_counter()
        self._tty = _interactive_tty()
        if self.count_up:
            self._thread = threading.Thread(target=self._tick_loop, daemon=True)
            self._thread.start()

    def finish(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        elapsed = self._elapsed_sec()
        if self.pass_fail:
            ok = True if self._passed is None else self._passed
            word = "passed" if ok else "failed"
            color = _GREEN if ok else _RED
            row = _format_row(
                self.emoji,
                self.label,
                status=word,
                status_color=color,
                time_plain=f"{elapsed:.{_DEMO_TIME_DECIMALS}f}",
            )
            self._emit_final_row(row)
        else:
            if self._result_latency_us is not None:
                emoji = execution_emoji(self._result_latency_us)
                time_plain = format_demo_seconds_from_us(self._result_latency_us)
                time_color = _RED
            else:
                emoji = self.emoji
                time_plain = f"{elapsed:.{_DEMO_TIME_DECIMALS}f}"
                time_color = _RED if "Executing" in self.label else ""
            row = _format_row(
                emoji,
                self.label,
                status=None,
                time_plain=time_plain,
                time_color=time_color,
            )
            self._emit_final_row(row)


@contextmanager
def demo_live_step(
    emoji: str,
    label: str,
    *,
    pass_fail: bool = False,
    count_up: bool = True,
) -> Iterator[_LiveStepHandle]:
    if not demo_enabled():
        yield _LiveStepHandle(emoji, label, pass_fail=pass_fail, count_up=count_up)
        return
    handle = _LiveStepHandle(emoji, label, pass_fail=pass_fail, count_up=count_up)
    handle.start()
    try:
        yield handle
    finally:
        handle.finish()


def execution_emoji(latency_us: int) -> str:
    return "🦥" if latency_us >= 1_000_000 else "🔥"


def demo_banner(title: str) -> None:
    _out(f"\n{title.upper()}")


def demo_iteration(n: int, total: int) -> None:
    _out(f"\n{_ansi(_DIM)}── Iteration {n}/{total} ──{_ansi(_RESET)}")


def demo_step_done(emoji: str, label: str, ms: int | None, *, detail: str = "") -> None:
    """Static line (no live count) — prefer demo_live_step when work is slow."""
    if detail:
        label = f"{label} ({detail})"
    time_plain = format_demo_seconds_from_ms(ms)
    _out(_format_row(emoji, label, status=None, time_plain=time_plain))


def demo_step_pass_fail(emoji: str, label: str, ms: int | None, passed: bool) -> None:
    word = "passed" if passed else "failed"
    color = _GREEN if passed else _RED
    time_plain = format_demo_seconds_from_ms(ms)
    _out(_format_row(emoji, label, status=word, status_color=color, time_plain=time_plain))


def demo_execute(label: str, latency_us: int, *, cached: bool = False) -> None:
    emoji = "💾" if cached else execution_emoji(latency_us)
    _out(
        _format_row(
            emoji,
            label,
            status=None,
            time_plain=format_demo_seconds_from_us(latency_us),
            time_color=_RED,
        )
    )


def demo_duckdb_query(latency_us: int) -> None:
    _out(
        _format_row(
            "🦆",
            "DuckDB baseline",
            status=None,
            time_plain=format_demo_seconds_from_us(latency_us),
            time_color=_YELLOW,
        )
    )


def demo_note(msg: str) -> None:
    _out(f"{_ansi(_DIM)}{msg}{_ansi(_RESET)}")


def demo_query_result_table(df) -> None:
    if df.empty:
        _out("")
        _out("Empty result (0 rows)")
        _out("")
        return
    _out("")
    for line in df.to_string(index=False).splitlines():
        _out(line)
    _out("")


def demo_emit_box_result(df) -> None:
    """Write only the query result to stdout — becomes lemma()'s DuckDB result cell."""
    if not _lemma_extension():
        return
    if df.empty:
        print("", file=sys.stdout, flush=True)
        return
    if df.shape == (1, 1):
        print(str(df.iloc[0, 0]), file=sys.stdout, end="", flush=True)
        return
    print(df.to_csv(index=False).strip(), file=sys.stdout, flush=True)
