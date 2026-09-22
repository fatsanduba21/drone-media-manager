"""Generate the managed macOS launchd plist for the DMM server.

This module deliberately only writes the plist. Loading or starting launchd is
an explicit operator action documented in ``Docs/operations/mac-server.md``.
"""

from __future__ import annotations

import argparse
import platform
import plistlib
import shutil
from pathlib import Path
from typing import Any

LABEL = "com.drone-media-manager.server"
LOG_DIRECTORY_NAME = "DroneMediaManager"


def managed_plist_path(home: Path | None = None) -> Path:
    root = (home or Path.home()).expanduser().resolve()
    return root / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_plist(
    *,
    project_root: Path,
    uv_path: Path,
    home: Path | None = None,
) -> dict[str, Any]:
    """Return the deterministic launchd document without touching the system."""
    absolute_project = project_root.expanduser().resolve()
    absolute_uv = uv_path.expanduser().resolve()
    log_directory = (
        (home or Path.home()).expanduser().resolve()
        / "Library"
        / "Logs"
        / LOG_DIRECTORY_NAME
    )
    return {
        "Label": LABEL,
        "ProgramArguments": [str(absolute_uv), "run", "dmm-server", "run"],
        "WorkingDirectory": str(absolute_project),
        "RunAtLoad": False,
        "KeepAlive": True,
        "StandardOutPath": str(log_directory / "server.log"),
        "StandardErrorPath": str(log_directory / "server.error.log"),
        "EnvironmentVariables": {"DMM_PROJECT_ROOT": str(absolute_project)},
    }


def install(
    *,
    project_root: Path | None = None,
    home: Path | None = None,
    plist_path: Path | None = None,
    system_name: str | None = None,
    uv_path: Path | None = None,
) -> Path:
    """Write the managed plist and return its path; never invoke launchctl."""
    if (system_name or platform.system()) != "Darwin":
        raise RuntimeError("macOS is required to install the launchd service")

    detected_uv = uv_path
    if detected_uv is None:
        found_uv = shutil.which("uv")
        if found_uv is None:
            raise RuntimeError("uv was not found on PATH; install uv before continuing")
        detected_uv = Path(found_uv)
    if not detected_uv.exists():
        raise RuntimeError("uv path does not exist; install uv before continuing")

    destination = (plist_path or managed_plist_path(home)).expanduser().resolve()
    root = (project_root or Path(__file__).resolve().parents[1]).expanduser().resolve()
    document = build_plist(project_root=root, uv_path=detected_uv, home=home)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as stream:
        plistlib.dump(document, stream, sort_keys=True)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path)
    args = parser.parse_args(argv)
    print(install(project_root=args.project_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
