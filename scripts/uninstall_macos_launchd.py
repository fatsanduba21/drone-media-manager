"""Remove only the launchd plist managed by the DMM installer."""

from __future__ import annotations

import argparse
import platform
from pathlib import Path

try:
    from .install_macos_launchd import managed_plist_path
except ImportError:  # pragma: no cover - direct script execution
    from install_macos_launchd import managed_plist_path


def uninstall(
    *,
    home: Path | None = None,
    confirm: bool = False,
    system_name: str | None = None,
) -> bool:
    """Remove the managed plist after explicit confirmation.

    No launchctl command is issued and no user data directory is touched.
    """
    if (system_name or platform.system()) != "Darwin":
        raise RuntimeError("macOS is required to uninstall the launchd service")
    if not confirm:
        raise RuntimeError("refusing to remove the service plist without --yes")
    destination = managed_plist_path(home)
    if not destination.exists():
        return False
    destination.unlink()
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="confirm plist removal")
    args = parser.parse_args(argv)
    removed = uninstall(confirm=args.yes)
    print("removed" if removed else "not installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
