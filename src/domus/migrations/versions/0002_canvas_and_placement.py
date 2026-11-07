"""Canvases and placements: floor plans, wall photos, and device pins on them.

New tables only, so backups made before this revision still restore.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06
"""

# sa.Double is generic and untyped in generated code.
# pyright: reportUnknownArgumentType=false

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canvas",
        sa.Column("property_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("scale_px_per_m", sa.Double(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "scope_type IN ('property', 'building', 'floor', 'area')",
            name=op.f("ck_canvas_scope_type"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document.id"], name=op.f("fk_canvas_document_id_document")
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["property.id"], name=op.f("fk_canvas_property_id_property")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canvas")),
    )
    with op.batch_alter_table("canvas", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_canvas_document_id"), ["document_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_canvas_property_id"), ["property_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_canvas_scope_id"), ["scope_id"], unique=False)

    op.create_table(
        "placement",
        sa.Column("canvas_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("x", sa.Double(), nullable=False),
        sa.Column("y", sa.Double(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("shape", sa.String(length=16), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("x >= 0 AND x <= 1", name=op.f("ck_placement_x_normalized")),
        sa.CheckConstraint("y >= 0 AND y <= 1", name=op.f("ck_placement_y_normalized")),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"], name=op.f("fk_placement_asset_id_asset")
        ),
        sa.ForeignKeyConstraint(
            ["canvas_id"], ["canvas.id"], name=op.f("fk_placement_canvas_id_canvas")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_placement")),
    )
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_placement_asset_id"), ["asset_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_placement_canvas_id"), ["canvas_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_placement_canvas_id"))
        batch_op.drop_index(batch_op.f("ix_placement_asset_id"))

    op.drop_table("placement")
    with op.batch_alter_table("canvas", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_canvas_scope_id"))
        batch_op.drop_index(batch_op.f("ix_canvas_property_id"))
        batch_op.drop_index(batch_op.f("ix_canvas_document_id"))

    op.drop_table("canvas")
