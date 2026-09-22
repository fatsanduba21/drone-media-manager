from __future__ import annotations

from types import SimpleNamespace

from drone_media_manager.ingest.release_policy import BackupPolicy, evaluate_release


def test_local_source_never_gets_card_format_notice() -> None:
    ingest = SimpleNamespace(
        source_kind="LOCAL", status="VERIFIED", items=[], manifest_status="VERIFIED"
    )

    decision = evaluate_release(ingest, BackupPolicy.NAS_ONLY)

    assert decision.card_format_allowed is False
    assert decision.reason == "source_is_not_removable"


def test_second_copy_requires_verified_backup() -> None:
    ingest = SimpleNamespace(
        source_kind="REMOVABLE",
        status="VERIFIED",
        items=[SimpleNamespace(status="VERIFIED")],
        manifest_status="VERIFIED",
        backup_verified=False,
    )

    decision = evaluate_release(ingest, BackupPolicy.REQUIRE_SECOND_COPY)

    assert decision.card_format_allowed is False
    assert decision.reason == "second_verified_copy_required"


def test_nas_only_allows_release_with_explicit_warning() -> None:
    ingest = SimpleNamespace(
        source_kind="REMOVABLE",
        status="VERIFIED",
        items=[SimpleNamespace(status="VERIFIED")],
        manifest_status="VERIFIED",
    )

    decision = evaluate_release(ingest, BackupPolicy.NAS_ONLY)

    assert decision.card_format_allowed is True
    assert (
        decision.warning
        == "Only one verified copy exists; keep the source card until a second copy is verified."
    )
