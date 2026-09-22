"""Command-line source inventory, snapshot submission, and worker polling."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from getpass import getpass
from threading import Event

from drone_media_manager.config import WorkerSettings, get_worker_settings
from drone_media_manager.ingest.fingerprint import fingerprint_inventory
from drone_media_manager.ingest.inventory import Inventory, build_inventory
from drone_media_manager.sources.discovery import (
    FilesystemReadOnlySource,
    source_from_explicit_path,
)
from drone_media_manager.worker.client import WorkerApiClient
from drone_media_manager.worker.credentials import CredentialStore
from drone_media_manager.worker.service import WorkerService
from drone_media_manager.worker.snapshots import default_snapshot_registry


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dmm-worker")
    parser.add_argument(
        "command", choices=("pair", "once", "run", "scan", "ingest", "submit", "verify")
    )
    parser.add_argument("path_or_id", nargs="?")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _inventory(path: str) -> Inventory:
    descriptor = source_from_explicit_path(path)
    return build_inventory(FilesystemReadOnlySource(descriptor))


def _print_inventory(inventory: Inventory) -> None:
    print(f"source={inventory.source.display_label}")
    print(f"kind={inventory.source.kind.value}")
    print(f"fingerprint={fingerprint_inventory(inventory)}")
    print(f"files={len(inventory.entries)} bytes={inventory.total_bytes}")
    for item in inventory.items:
        print(f"{item.pair_status.value} {item.stem}")


def _authenticated_client(
    settings_loader: Callable[[], WorkerSettings],
    client_factory: Callable[[str, str], WorkerApiClient],
    credential_store: CredentialStore,
) -> tuple[WorkerSettings, WorkerApiClient, str]:
    settings = settings_loader()
    token = credential_store.get_token(settings.worker_name)
    worker_id = credential_store.get_worker_id(settings.worker_name)
    if not token or not worker_id:
        raise ValueError("worker credentials are missing; run dmm-worker pair")
    return (
        settings,
        client_factory(str(settings.server_url).rstrip("/"), token),
        worker_id,
    )


def _snapshot_entries(inventory: Inventory) -> list[dict[str, object]]:
    pair_by_path = {
        entry.relative_path.as_posix(): item.pair_status.value
        for item in inventory.items
        for entry in item.entries
    }
    return [
        {
            "source_rel_path": entry.relative_path.as_posix(),
            "size_bytes": entry.stat.size,
            "mtime_ns": entry.stat.mtime_ns,
            "file_identity": entry.stat.file_identity,
            "pair_status": pair_by_path[entry.relative_path.as_posix()],
        }
        for entry in inventory.entries
    ]


def _submit(
    path: str,
    settings_loader: Callable[[], WorkerSettings],
    client_factory: Callable[[str, str], WorkerApiClient],
    credential_store: CredentialStore,
) -> int:
    inventory = _inventory(path)
    settings, client, worker_id = _authenticated_client(
        settings_loader, client_factory, credential_store
    )
    snapshot = client.create_snapshot(
        worker_id,
        inventory.source.kind.value,
        inventory.source.volume_identity,
        datetime.now(UTC) + timedelta(hours=24),
    )
    default_snapshot_registry(settings.snapshot_registry_path).register(
        snapshot.snapshot_id, inventory.source, inventory
    )
    revision = snapshot.revision
    entries = _snapshot_entries(inventory)
    for start in range(0, len(entries), 500):
        response = client.append_snapshot_entries(
            snapshot.snapshot_id, worker_id, revision, entries[start : start + 500]
        )
        revision = response.revision
    finalized = client.finalize_snapshot(
        snapshot.snapshot_id, worker_id, revision, len(entries)
    )
    print(
        f"snapshot={finalized.snapshot_id} status=FINALIZED revision={finalized.revision}"
    )
    return 0


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
    store = credential_store or CredentialStore()
    if args.command in {"scan", "ingest", "submit"}:
        if not args.path_or_id or not os.path.isdir(args.path_or_id):
            print("source path is required and must be a directory", file=sys.stderr)
            return 2
        if args.command == "scan":
            _print_inventory(_inventory(args.path_or_id))
            return 0
        if args.command == "ingest" and not args.dry_run:
            print("submit the immutable snapshot before ingest", file=sys.stderr)
            return 2
        if args.command == "ingest":
            try:
                inventory = _inventory(args.path_or_id)
                settings = settings_loader()
                usage = shutil.disk_usage(settings.omv_root)
                print(
                    f"dry-run fingerprint={fingerprint_inventory(inventory)} "
                    f"files={len(inventory.entries)} bytes={inventory.total_bytes} "
                    f"available={usage.free}"
                )
                return 0 if usage.free >= inventory.total_bytes else 4
            except (OSError, ValueError) as error:
                print(f"dry-run failed: {error}", file=sys.stderr)
                return 2
        try:
            return _submit(args.path_or_id, settings_loader, client_factory, store)
        except (OSError, ValueError, RuntimeError) as error:
            print(str(error), file=sys.stderr)
            return 2
    if args.command == "verify":
        if not args.path_or_id:
            return 2
        try:
            _, client, _ = _authenticated_client(settings_loader, client_factory, store)
            result = client.get_ingest(args.path_or_id)
            print(f"ingest={result.ingest_id} status={result.status}")
            return {"VERIFIED": 0, "INTERRUPTED": 3, "FAILED": 4}.get(result.status, 3)
        except (ValueError, RuntimeError) as error:
            print(str(error), file=sys.stderr)
            return 2
    settings = settings_loader()
    default_snapshot_registry(settings.snapshot_registry_path)
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
    if service_factory is WorkerService:
        service = WorkerService(
            client_factory(server_url, token),
            worker_id,
            snapshot_registry=default_snapshot_registry(),
            omv_root=settings.omv_root,
        )
    else:
        service = service_factory(client_factory(server_url, token), worker_id)
    if args.command == "once":
        service.run_once()
        return 0
    service.run_forever(Event())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
