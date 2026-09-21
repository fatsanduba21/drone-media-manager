from __future__ import annotations

import subprocess

from drone_media_manager.system.dependencies import probe_executable


class FakeRunner:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def run(self, *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, **kwargs})
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(
            args=args[0] if args else [], returncode=0, stdout="ffmpeg version ok", stderr=""
        )


def test_missing_executable_is_degraded() -> None:
    runner = FakeRunner(FileNotFoundError())

    result = probe_executable("ffmpeg", runner=runner)

    assert result.state == "degraded"
    assert result.name == "ffmpeg"


def test_timeout_is_degraded_and_probe_is_bounded() -> None:
    runner = FakeRunner(subprocess.TimeoutExpired(["ffprobe", "-version"], 5))

    result = probe_executable("ffprobe", timeout_seconds=5, runner=runner)

    assert result.state == "degraded"
    call = runner.calls[0]
    assert call["args"] == (["ffprobe", "-version"],)
    assert call["shell"] is False
    assert call["timeout"] == 5
    assert call["capture_output"] is True


def test_probe_limits_reported_output() -> None:
    runner = FakeRunner()
    runner.run = lambda *args, **kwargs: subprocess.CompletedProcess(  # type: ignore[method-assign]
        args=args[0], returncode=0, stdout="x" * 100_000, stderr=""
    )

    result = probe_executable("ffmpeg", runner=runner)

    assert result.state == "healthy"
    assert len(result.output) <= 64 * 1024
