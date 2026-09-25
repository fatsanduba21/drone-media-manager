"""Store human people, subject, label and tags without touching media."""

import sqlalchemy as sa
from alembic import op

revision = "0010_editorial_fields"
down_revision = "0009_movement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editorial_fields",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_asset_id",
            sa.String(36),
            sa.ForeignKey("catalog_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("catalog_asset_id", "kind"),
    )
    op.create_table(
        "editorial_tags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_asset_id",
            sa.String(36),
            sa.ForeignKey("catalog_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("value", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("catalog_asset_id", "value"),
    )


def downgrade() -> None:
    op.drop_table("editorial_tags")
    op.drop_table("editorial_fields")
