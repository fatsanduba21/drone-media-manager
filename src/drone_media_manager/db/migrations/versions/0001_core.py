"""Create the local SQLite core schema."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create core worker, job, and audit tables."""
    op.create_table(
        "workers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("token_digest", sa.String(length=255), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="OFFLINE"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.CheckConstraint("status IN ('OFFLINE', 'ONLINE', 'BUSY')", name="ck_workers_status"),
        sa.CheckConstraint("revision >= 0", name="ck_workers_revision_non_negative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column("lease_worker_id", sa.String(length=36), nullable=True),
        sa.Column("lease_token_digest", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'LEASED', 'RUNNING', 'COMPLETE', 'INTERRUPTED', 'FAILED')",
            name="ck_jobs_status",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_jobs_revision_non_negative"),
        sa.CheckConstraint("attempts >= 0", name="ck_jobs_attempts_non_negative"),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name="ck_jobs_progress_range"),
        sa.ForeignKeyConstraint(["lease_worker_id"], ["workers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workers_status_last_seen_at", "workers", ["status", "last_seen_at"])
    op.create_index("ix_jobs_status_available_at", "jobs", ["status", "available_at"])
    op.create_index("ix_jobs_lease_expires_at", "jobs", ["lease_expires_at"])
    op.create_index(
        "ix_audit_events_entity_type_entity_id_occurred_at",
        "audit_events",
        ["entity_type", "entity_id", "occurred_at"],
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_immutable_update
        BEFORE UPDATE ON audit_events
        BEGIN
            SELECT RAISE(ABORT, 'audit_events are immutable');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_immutable_delete
        BEFORE DELETE ON audit_events
        BEGIN
            SELECT RAISE(ABORT, 'audit_events are immutable');
        END
        """
    )


def downgrade() -> None:
    """Drop every application table created by this revision."""
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_immutable_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_immutable_update")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_type_entity_id_occurred_at", table_name="audit_events")
    op.drop_index("ix_jobs_lease_expires_at", table_name="jobs")
    op.drop_index("ix_jobs_status_available_at", table_name="jobs")
    op.drop_index("ix_workers_status_last_seen_at", table_name="workers")
    op.drop_table("audit_events")
    op.drop_table("jobs")
    op.drop_table("workers")
