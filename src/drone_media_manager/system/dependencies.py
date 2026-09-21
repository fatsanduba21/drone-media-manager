"""Non-fatal probes for external media executables."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol

MAX_PROBE_OUTPUT_BYTES = 64 * 1024


class Runner(Protocol):
    def run(self, *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    name: str
    state: str
    output: str = ""
    detail: str | None = None
    returncode: int | None = None


def probe_executable(name: str, timeout_seconds: float = 5, *, runner: Runner | None = None) -> DependencyStatus:
    command_runner = runner or subprocess
    try:
        completed = command_runner.run(
            [name, "-version"], shell=False, timeout=timeout_seconds,
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return DependencyStatus(name=name, state="degraded", detail="not_found")
    except subprocess.TimeoutExpired:
        return DependencyStatus(name=name, state="degraded", detail="timeout")
    except OSError as error:
        return DependencyStatus(name=name, state="degraded", detail=type(error).__name__)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    output = (stdout + ("\n" + stderr if stderr else ""))[:MAX_PROBE_OUTPUT_BYTES]
    return DependencyStatus(
        name=name,
        state="healthy" if completed.returncode == 0 else "degraded",
        output=output,
        detail=None if completed.returncode == 0 else "nonzero_exit",
        returncode=completed.returncode,
    )
