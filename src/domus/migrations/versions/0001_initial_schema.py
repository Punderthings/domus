"""Initial schema for v0.1 (data-storage-backup.md section 2).

Revision ID: 0001
Revises:
Create Date: 2026-11-06
"""

# sa.Double is generic and untyped in generated code.
# pyright: reportUnknownArgumentType=false

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("property_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("diff", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_log_at"), ["at"], unique=False)

    op.create_table(
        "blob",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("sha256", name=op.f("pk_blob")),
    )
    op.create_table(
        "product",
        sa.Column("manufacturer", sa.String(length=200), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("model_id", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("manual_url", sa.String(length=2048), nullable=True),
        sa.Column("support_url", sa.String(length=2048), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product")),
    )
    op.create_table(
        "property",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("default_currency", sa.String(length=3), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property")),
    )
    op.create_table(
        "user",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user")),
        sa.UniqueConstraint("email", name=op.f("uq_user_email")),
    )
    op.create_table(
        "access_rule",
        sa.Column("property_id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=36), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "level IN ('hidden', 'view', 'control', 'manage')", name=op.f("ck_access_rule_level")
        ),
        sa.CheckConstraint(
            "scope_type IN ('building', 'area', 'tag', 'asset')",
            name=op.f("ck_access_rule_scope_type"),
        ),
        sa.CheckConstraint(
            "subject_type IN ('role', 'membership')", name=op.f("ck_access_rule_subject_type")
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["property.id"], name=op.f("fk_access_rule_property_id_property")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_rule")),
    )
    with op.batch_alter_table("access_rule", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_access_rule_property_id"), ["property_id"], unique=False
        )
        batch_op.create_index("ix_access_rule_scope", ["scope_type", "scope_id"], unique=False)

    op.create_table(
        "api_token",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.String(length=200), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_api_token_user_id_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_token")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_token_token_hash")),
    )
    with op.batch_alter_table("api_token", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_api_token_user_id"), ["user_id"], unique=False)

    op.create_table(
        "auth_session",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_auth_session_user_id_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_session")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_session_token_hash")),
    )
    with op.batch_alter_table("auth_session", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_auth_session_user_id"), ["user_id"], unique=False)

    op.create_table(
        "building",
        sa.Column("property_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("year_built", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("site_x", sa.Double(), nullable=True),
        sa.Column("site_y", sa.Double(), nullable=True),
        sa.Column("rotation_deg", sa.Double(), nullable=True),
        sa.Column("footprint", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["property_id"], ["property.id"], name=op.f("fk_building_property_id_property")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_building")),
    )
    with op.batch_alter_table("building", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_building_property_id"), ["property_id"], unique=False)

    op.create_table(
        "document",
        sa.Column("property_id", sa.String(length=36), nullable=False),
        sa.Column("blob_sha256", sa.String(length=64), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("original_filename", sa.String(length=300), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=True),
        sa.Column("sensitivity", sa.String(length=16), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["blob_sha256"], ["blob.sha256"], name=op.f("fk_document_blob_sha256_blob")
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["property.id"], name=op.f("fk_document_property_id_property")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document")),
    )
    with op.batch_alter_table("document", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_document_blob_sha256"), ["blob_sha256"], unique=False)
        batch_op.create_index(batch_op.f("ix_document_property_id"), ["property_id"], unique=False)

    op.create_table(
        "membership",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("property_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "role IN ('admin', 'maintainer', 'resident', 'guest')", name=op.f("ck_membership_role")
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["property.id"], name=op.f("fk_membership_property_id_property")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_membership_user_id_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership")),
        sa.UniqueConstraint(
            "user_id", "property_id", name=op.f("uq_membership_user_id_property_id")
        ),
    )
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_membership_property_id"), ["property_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_membership_user_id"), ["user_id"], unique=False)

    op.create_table(
        "spatial_relation",
        sa.Column("property_id", sa.String(length=36), nullable=False),
        sa.Column("from_type", sa.String(length=16), nullable=False),
        sa.Column("from_id", sa.String(length=36), nullable=False),
        sa.Column("to_type", sa.String(length=16), nullable=False),
        sa.Column("to_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("via", sa.String(length=200), nullable=True),
        sa.Column("distance_m", sa.Double(), nullable=True),
        sa.Column("bearing_deg", sa.Double(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "from_type IN ('building', 'area')", name=op.f("ck_spatial_relation_from_type")
        ),
        sa.CheckConstraint(
            "to_type IN ('building', 'area')", name=op.f("ck_spatial_relation_to_type")
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["property.id"], name=op.f("fk_spatial_relation_property_id_property")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spatial_relation")),
    )
    with op.batch_alter_table("spatial_relation", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_spatial_relation_property_id"), ["property_id"], unique=False
        )

    op.create_table(
        "tag",
        sa.Column("property_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["property_id"], ["property.id"], name=op.f("fk_tag_property_id_property")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tag")),
        sa.UniqueConstraint("property_id", "name", name=op.f("uq_tag_property_id_name")),
    )
    with op.batch_alter_table("tag", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_tag_property_id"), ["property_id"], unique=False)

    op.create_table(
        "attachment",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document.id"], name=op.f("fk_attachment_document_id_document")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachment")),
    )
    with op.batch_alter_table("attachment", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_attachment_document_id"), ["document_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_attachment_target_id"), ["target_id"], unique=False)

    op.create_table(
        "floor",
        sa.Column("building_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("ha_floor_id", sa.String(length=128), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["building_id"], ["building.id"], name=op.f("fk_floor_building_id_building")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_floor")),
    )
    with op.batch_alter_table("floor", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_floor_building_id"), ["building_id"], unique=False)

    op.create_table(
        "area",
        sa.Column("property_id", sa.String(length=36), nullable=False),
        sa.Column("building_id", sa.String(length=36), nullable=True),
        sa.Column("floor_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("site_x", sa.Double(), nullable=True),
        sa.Column("site_y", sa.Double(), nullable=True),
        sa.Column("footprint", sa.JSON(), nullable=True),
        sa.Column("ha_area_id", sa.String(length=128), nullable=True),
        sa.Column("is_critical", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "floor_id IS NULL OR building_id IS NOT NULL", name=op.f("ck_area_floor_needs_building")
        ),
        sa.ForeignKeyConstraint(
            ["building_id"], ["building.id"], name=op.f("fk_area_building_id_building")
        ),
        sa.ForeignKeyConstraint(["floor_id"], ["floor.id"], name=op.f("fk_area_floor_id_floor")),
        sa.ForeignKeyConstraint(
            ["property_id"], ["property.id"], name=op.f("fk_area_property_id_property")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_area")),
    )
    with op.batch_alter_table("area", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_area_building_id"), ["building_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_area_floor_id"), ["floor_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_area_property_id"), ["property_id"], unique=False)

    op.create_table(
        "location",
        sa.Column("area_id", sa.String(length=36), nullable=False),
        sa.Column("parent_location_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("orientation", sa.String(length=32), nullable=True),
        sa.Column("position_note", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["area_id"], ["area.id"], name=op.f("fk_location_area_id_area")),
        sa.ForeignKeyConstraint(
            ["parent_location_id"],
            ["location.id"],
            name=op.f("fk_location_parent_location_id_location"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_location")),
    )
    with op.batch_alter_table("location", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_location_area_id"), ["area_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_location_parent_location_id"), ["parent_location_id"], unique=False
        )

    op.create_table(
        "asset",
        sa.Column("property_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=True),
        sa.Column("location_id", sa.String(length=36), nullable=True),
        sa.Column("parent_asset_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("install_date", sa.Date(), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("purchase_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("vendor", sa.String(length=200), nullable=True),
        sa.Column("warranty_expires", sa.Date(), nullable=True),
        sa.Column("sw_version", sa.String(length=64), nullable=True),
        sa.Column("hw_version", sa.String(length=64), nullable=True),
        sa.Column("is_critical", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["location_id"], ["location.id"], name=op.f("fk_asset_location_id_location")
        ),
        sa.ForeignKeyConstraint(
            ["parent_asset_id"], ["asset.id"], name=op.f("fk_asset_parent_asset_id_asset")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["product.id"], name=op.f("fk_asset_product_id_product")
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["property.id"], name=op.f("fk_asset_property_id_property")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset")),
    )
    with op.batch_alter_table("asset", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_asset_location_id"), ["location_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_asset_parent_asset_id"), ["parent_asset_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_asset_product_id"), ["product_id"], unique=False)
        batch_op.create_index(
            "ix_asset_property_category", ["property_id", "category"], unique=False
        )

    op.create_table(
        "asset_identifier",
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=256), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"], name=op.f("fk_asset_identifier_asset_id_asset")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_identifier")),
    )
    with op.batch_alter_table("asset_identifier", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_asset_identifier_asset_id"), ["asset_id"], unique=False
        )
        batch_op.create_index("ix_asset_identifier_kind_value", ["kind", "value"], unique=False)

    op.create_table(
        "asset_relation",
        sa.Column("from_asset_id", sa.String(length=36), nullable=False),
        sa.Column("to_asset_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["from_asset_id"], ["asset.id"], name=op.f("fk_asset_relation_from_asset_id_asset")
        ),
        sa.ForeignKeyConstraint(
            ["to_asset_id"], ["asset.id"], name=op.f("fk_asset_relation_to_asset_id_asset")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_relation")),
    )
    with op.batch_alter_table("asset_relation", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_asset_relation_from_asset_id"), ["from_asset_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_asset_relation_to_asset_id"), ["to_asset_id"], unique=False
        )

    op.create_table(
        "asset_tag",
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"], name=op.f("fk_asset_tag_asset_id_asset")
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], name=op.f("fk_asset_tag_tag_id_tag")),
        sa.PrimaryKeyConstraint("tag_id", "asset_id", name=op.f("pk_asset_tag")),
    )
    with op.batch_alter_table("asset_tag", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_asset_tag_asset_id"), ["asset_id"], unique=False)

    op.create_table(
        "maintenance_task",
        sa.Column("property_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("location_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("procedure", sa.Text(), nullable=True),
        sa.Column("schedule_kind", sa.String(length=32), nullable=False),
        sa.Column("interval_value", sa.Integer(), nullable=True),
        sa.Column("interval_unit", sa.String(length=8), nullable=True),
        sa.Column("rrule", sa.String(length=500), nullable=True),
        sa.Column("anchor_date", sa.Date(), nullable=True),
        sa.Column("next_due", sa.Date(), nullable=True),
        sa.Column("lead_days", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("assignee_role", sa.String(length=16), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"], name=op.f("fk_maintenance_task_asset_id_asset")
        ),
        sa.ForeignKeyConstraint(
            ["location_id"], ["location.id"], name=op.f("fk_maintenance_task_location_id_location")
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["property.id"], name=op.f("fk_maintenance_task_property_id_property")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_task")),
    )
    with op.batch_alter_table("maintenance_task", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_maintenance_task_asset_id"), ["asset_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_maintenance_task_location_id"), ["location_id"], unique=False
        )
        batch_op.create_index(
            "ix_maintenance_task_property_next_due", ["property_id", "next_due"], unique=False
        )

    op.create_table(
        "maintenance_event",
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("performed_on", sa.Date(), nullable=False),
        sa.Column("performed_by", sa.String(length=36), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("vendor", sa.String(length=200), nullable=True),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("readings", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"], name=op.f("fk_maintenance_event_asset_id_asset")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["maintenance_task.id"],
            name=op.f("fk_maintenance_event_task_id_maintenance_task"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_event")),
    )
    with op.batch_alter_table("maintenance_event", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_maintenance_event_asset_id"), ["asset_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_maintenance_event_task_id"), ["task_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("maintenance_event", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_maintenance_event_task_id"))
        batch_op.drop_index(batch_op.f("ix_maintenance_event_asset_id"))

    op.drop_table("maintenance_event")
    with op.batch_alter_table("maintenance_task", schema=None) as batch_op:
        batch_op.drop_index("ix_maintenance_task_property_next_due")
        batch_op.drop_index(batch_op.f("ix_maintenance_task_location_id"))
        batch_op.drop_index(batch_op.f("ix_maintenance_task_asset_id"))

    op.drop_table("maintenance_task")
    with op.batch_alter_table("asset_tag", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_asset_tag_asset_id"))

    op.drop_table("asset_tag")
    with op.batch_alter_table("asset_relation", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_asset_relation_to_asset_id"))
        batch_op.drop_index(batch_op.f("ix_asset_relation_from_asset_id"))

    op.drop_table("asset_relation")
    with op.batch_alter_table("asset_identifier", schema=None) as batch_op:
        batch_op.drop_index("ix_asset_identifier_kind_value")
        batch_op.drop_index(batch_op.f("ix_asset_identifier_asset_id"))

    op.drop_table("asset_identifier")
    with op.batch_alter_table("asset", schema=None) as batch_op:
        batch_op.drop_index("ix_asset_property_category")
        batch_op.drop_index(batch_op.f("ix_asset_product_id"))
        batch_op.drop_index(batch_op.f("ix_asset_parent_asset_id"))
        batch_op.drop_index(batch_op.f("ix_asset_location_id"))

    op.drop_table("asset")
    with op.batch_alter_table("location", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_location_parent_location_id"))
        batch_op.drop_index(batch_op.f("ix_location_area_id"))

    op.drop_table("location")
    with op.batch_alter_table("area", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_area_property_id"))
        batch_op.drop_index(batch_op.f("ix_area_floor_id"))
        batch_op.drop_index(batch_op.f("ix_area_building_id"))

    op.drop_table("area")
    with op.batch_alter_table("floor", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_floor_building_id"))

    op.drop_table("floor")
    with op.batch_alter_table("attachment", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_attachment_target_id"))
        batch_op.drop_index(batch_op.f("ix_attachment_document_id"))

    op.drop_table("attachment")
    with op.batch_alter_table("tag", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tag_property_id"))

    op.drop_table("tag")
    with op.batch_alter_table("spatial_relation", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_spatial_relation_property_id"))

    op.drop_table("spatial_relation")
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_membership_user_id"))
        batch_op.drop_index(batch_op.f("ix_membership_property_id"))

    op.drop_table("membership")
    with op.batch_alter_table("document", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_document_property_id"))
        batch_op.drop_index(batch_op.f("ix_document_blob_sha256"))

    op.drop_table("document")
    with op.batch_alter_table("building", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_building_property_id"))

    op.drop_table("building")
    with op.batch_alter_table("auth_session", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_auth_session_user_id"))

    op.drop_table("auth_session")
    with op.batch_alter_table("api_token", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_api_token_user_id"))

    op.drop_table("api_token")
    with op.batch_alter_table("access_rule", schema=None) as batch_op:
        batch_op.drop_index("ix_access_rule_scope")
        batch_op.drop_index(batch_op.f("ix_access_rule_property_id"))

    op.drop_table("access_rule")
    op.drop_table("user")
    op.drop_table("property")
    op.drop_table("product")
    op.drop_table("blob")
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_log_at"))

    op.drop_table("audit_log")
