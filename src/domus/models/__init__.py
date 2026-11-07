"""SQLAlchemy models. Importing this package registers every table on ``Base.metadata``."""

from domus.models.assets import Asset, AssetIdentifier, AssetRelation, AssetTag, Product, Tag
from domus.models.base import Base
from domus.models.canvas import Canvas, Placement
from domus.models.documents import Attachment, Blob, Document
from domus.models.maintenance import MaintenanceEvent, MaintenanceTask
from domus.models.space import Area, Building, Floor, Location, Property, SpatialRelation
from domus.models.users import AccessRule, ApiToken, AuditLog, AuthSession, Membership, User

__all__ = [
    "AccessRule",
    "ApiToken",
    "Area",
    "Asset",
    "AssetIdentifier",
    "AssetRelation",
    "AssetTag",
    "Attachment",
    "AuditLog",
    "AuthSession",
    "Base",
    "Blob",
    "Building",
    "Canvas",
    "Document",
    "Floor",
    "Location",
    "MaintenanceEvent",
    "MaintenanceTask",
    "Membership",
    "Placement",
    "Product",
    "Property",
    "SpatialRelation",
    "Tag",
    "User",
]
