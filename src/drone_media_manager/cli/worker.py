"""Command-line pairing and polling entry point for the Windows worker."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from getpass import getpass
from threading import Event

from drone_media_manager.config import WorkerSettings, get_worker_settings
from drone_media_manager.worker.client import WorkerApiClient
from drone_media_manager.worker.credentials import CredentialStore
from drone_media_manager.worker.service import WorkerService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dmm-worker")
    parser.add_argument(
        "command", choices=("pair", "once", "run", "scan", "ingest", "submit", "verify")
    )
    parser.add_argument("path_or_id", nargs="?")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_loader: Callable[[], WorkerSettings] = get_worker_settings,
    client_factory: Callable[[str, str], WorkerApiClient] = WorkerApiClient,
    service_factory: Callable[[WorkerApiClient, str], WorkerService] = WorkerService,
    credential_store: CredentialStore | None = None,
    prompt_secret: Callable[[str], str] = getpass,
) -> int:
    args = _parser().parse_args(argv)
    if args.command in {"scan", "ingest", "submit"}:
        if not args.path_or_id or not os.path.isdir(args.path_or_id):
            print("source path is required and must be a directory", file=sys.stderr)
            return 2
        if args.command == "ingest" and not args.dry_run:
            print("submit the immutable snapshot before ingest", file=sys.stderr)
            return 2
        return 0
    if args.command == "verify":
        return 0 if args.path_or_id else 2
    settings = settings_loader()
    store = credential_store or CredentialStore()
    server_url = str(settings.server_url).rstrip("/")
    if args.command == "pair":
        bootstrap = os.environ.get("DMM_WORKER_BOOTSTRAP_TOKEN") or prompt_secret(
            "Worker bootstrap token: "
        )
        registered = client_factory(server_url, bootstrap).register(
            settings.worker_name, ["ingest"]
        )
        store.set_credentials(
            settings.worker_name, registered.worker_id, registered.worker_token
        )
        return 0
    token = store.get_token(settings.worker_name)
    if not token:
        print("worker token is missing; run dmm-worker pair", file=sys.stderr)
        return 2
    worker_id = store.get_worker_id(settings.worker_name)
    if not worker_id:
        print(
            "worker identity is missing; re-pair with dmm-worker pair", file=sys.stderr
        )
        return 2
    service = service_factory(client_factory(server_url, token), worker_id)
    if args.command == "once":
        service.run_once()
        return 0
    service.run_forever(Event())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
