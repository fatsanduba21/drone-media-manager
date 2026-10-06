"""Terminal progress for long CLI commands; domain code only sees ``Progress``.

Bars (tqdm) are used when the amount of work is known, spinners (Halo) when it
is not. Output goes to stderr so JSON reports on stdout stay machine-readable,
and everything is disabled when stderr is not a terminal or when
``DMM_NO_PROGRESS`` is set.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from halo import Halo  # type: ignore[import-untyped]
from tqdm import tqdm


class Progress(Protocol):
    def stage(self, label: str, total: int | None, *, unit: str = "item") -> None:
        """Start a step: a bar when ``total`` is known, else a spinner."""

    def advance(self, amount: int = 1) -> None: ...

    def note(self, text: str) -> None:
        """Name the item currently being processed."""

    def close(self) -> None: ...


class NullProgress:
    """Default for domain code and tests: reports nothing."""

    def stage(self, label: str, total: int | None, *, unit: str = "item") -> None:
        return

    def advance(self, amount: int = 1) -> None:
        return

    def note(self, text: str) -> None:
        return

    def close(self) -> None:
        return


NULL_PROGRESS = NullProgress()


def progress_enabled() -> bool:
    if os.environ.get("DMM_NO_PROGRESS"):
        return False
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


class TerminalProgress:
    """One active bar or spinner at a time, written to stderr."""

    def __init__(self, *, enabled: bool | None = None) -> None:
        self.enabled = progress_enabled() if enabled is None else enabled
        self._bar: Any = None
        self._spinner: Any = None
        self._label = ""

    def stage(self, label: str, total: int | None, *, unit: str = "item") -> None:
        self.close()
        self._label = label
        if not self.enabled:
            return
        if total is None:
            self._spinner = Halo(text=label, spinner="dots", stream=sys.stderr)
            self._spinner.start()
            return
        byte_unit = unit == "B"
        self._bar = tqdm(
            total=total,
            desc=label,
            unit=unit,
            unit_scale=byte_unit,
            unit_divisor=1024 if byte_unit else 1000,
            file=sys.stderr,
            dynamic_ncols=True,
            leave=True,
        )

    def advance(self, amount: int = 1) -> None:
        if self._bar is not None and amount:
            self._bar.update(amount)

    def note(self, text: str) -> None:
        if self._bar is not None:
            self._bar.set_postfix_str(text, refresh=False)
        elif self._spinner is not None:
            self._spinner.text = f"{self._label}: {text}"

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()
            self._bar = None
        if self._spinner is not None:
            self._spinner.succeed(self._label)
            self._spinner = None


@contextmanager
def terminal_progress() -> Iterator[TerminalProgress]:
    progress = TerminalProgress()
    try:
        yield progress
    except BaseException:
        if progress._spinner is not None:
            progress._spinner.fail(progress._label)
            progress._spinner = None
        raise
    finally:
        progress.close()
