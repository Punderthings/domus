"""The access policy: who may see, control, or manage each building, area, and asset.

Design: data-storage-backup.md section 2.3.1 and the master plan section 2.

Resolution for a non-admin member:

1. Start from the role's default ceiling (maintainer ``manage``, resident
   ``control``, guest ``view``).
2. Apply the most specific matching, unexpired rule, in the order
   asset > tag > area > building. An asset without its own rule inherits a
   rule on its parent asset (and so on up the chain).
3. At the same scope, a rule for the specific membership beats a rule for the
   role. If several rules tie (for example two tags), the lowest level wins,
   so an ambiguous setup fails closed.
4. Guests and residents are never raised above ``control``.
5. Critical items (``is_critical`` on the asset, a parent asset, or its area)
   are capped at ``control``: only Admins can manage them.

Admins are never limited.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from domus.models import AccessRule, Area, Asset, AssetTag, Building, Location
from domus.models.enums import LEVEL_RANK, AccessLevel, Role, ScopeType, SubjectType

DEFAULT_CEILING: dict[Role, AccessLevel] = {
    Role.ADMIN: AccessLevel.MANAGE,
    Role.MAINTAINER: AccessLevel.MANAGE,
    Role.RESIDENT: AccessLevel.CONTROL,
    Role.GUEST: AccessLevel.VIEW,
}

# Rules may raise these roles, but never above this level.
RULE_CAP: dict[Role, AccessLevel] = {
    Role.RESIDENT: AccessLevel.CONTROL,
    Role.GUEST: AccessLevel.CONTROL,
}

ROLE_RANK: dict[Role, int] = {Role.GUEST: 0, Role.RESIDENT: 1, Role.MAINTAINER: 2, Role.ADMIN: 3}


def at_least(level: AccessLevel, minimum: AccessLevel) -> bool:
    return LEVEL_RANK[level] >= LEVEL_RANK[minimum]


def _min_level(levels: Iterable[AccessLevel]) -> AccessLevel:
    return min(levels, key=LEVEL_RANK.__getitem__)


@dataclass(frozen=True)
class Subject:
    """The member whose access is being checked."""

    role: Role
    membership_id: str | None = None


@dataclass(frozen=True)
class Rule:
    scope_type: ScopeType
    scope_id: str
    subject_type: SubjectType
    subject: str
    level: AccessLevel
    expires_at: datetime | None = None

    @classmethod
    def from_model(cls, row: AccessRule) -> Rule:
        return cls(
            scope_type=ScopeType(row.scope_type),
            scope_id=row.scope_id,
            subject_type=SubjectType(row.subject_type),
            subject=row.subject,
            level=AccessLevel(row.level),
            expires_at=row.expires_at,
        )


@dataclass(frozen=True)
class Target:
    """Everything the policy needs to know about one item.

    ``asset_chain`` lists the asset itself first, then its parent, and so on.
    """

    asset_chain: Sequence[str] = ()
    tag_ids: Sequence[str] = ()
    area_id: str | None = None
    building_id: str | None = None
    critical: bool = False


@dataclass
class AccessPolicy:
    """Pure access resolution over a set of rules; no database access."""

    subject: Subject
    rules: Sequence[Rule]
    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self._index: dict[tuple[ScopeType, str], list[Rule]] = {}
        for rule in self.rules:
            if not self._applies_to_subject(rule):
                continue
            if rule.expires_at is not None and rule.expires_at <= self.now:
                continue
            self._index.setdefault((rule.scope_type, rule.scope_id), []).append(rule)

    def _applies_to_subject(self, rule: Rule) -> bool:
        if rule.subject_type is SubjectType.ROLE:
            return rule.subject == self.subject.role.value
        return self.subject.membership_id is not None and rule.subject == self.subject.membership_id

    def _pick(self, scope_type: ScopeType, scope_ids: Iterable[str]) -> AccessLevel | None:
        """Return the level from the rules at one scope, or None if none match."""
        found = [r for sid in scope_ids for r in self._index.get((scope_type, sid), [])]
        if not found:
            return None
        member = [r.level for r in found if r.subject_type is SubjectType.MEMBERSHIP]
        if member:
            return _min_level(member)
        return _min_level(r.level for r in found)

    def level_for(self, target: Target) -> AccessLevel:
        role = self.subject.role
        if role is Role.ADMIN:
            return AccessLevel.MANAGE
        level = self._rule_level(target)
        if level is None:
            level = DEFAULT_CEILING[role]
        else:
            cap = RULE_CAP.get(role)
            if cap is not None and not at_least(cap, level):
                level = cap
        if target.critical and at_least(level, AccessLevel.MANAGE):
            level = AccessLevel.CONTROL
        return level

    def _rule_level(self, target: Target) -> AccessLevel | None:
        for asset_id in target.asset_chain:
            level = self._pick(ScopeType.ASSET, [asset_id])
            if level is not None:
                return level
        level = self._pick(ScopeType.TAG, target.tag_ids)
        if level is not None:
            return level
        if target.area_id is not None:
            level = self._pick(ScopeType.AREA, [target.area_id])
            if level is not None:
                return level
        if target.building_id is not None:
            return self._pick(ScopeType.BUILDING, [target.building_id])
        return None


class PropertyAccess:
    """Database-backed access checks for one member in one property.

    Loads the property's rules once and caches lookups, so a list endpoint can
    filter hundreds of rows without a query per row.
    """

    def __init__(
        self,
        session: Session,
        property_id: str,
        subject: Subject,
        now: datetime | None = None,
    ) -> None:
        self.session = session
        self.property_id = property_id
        self.subject = subject
        rows = session.scalars(
            select(AccessRule).where(
                AccessRule.property_id == property_id, AccessRule.deleted_at.is_(None)
            )
        ).all()
        self.policy = AccessPolicy(
            subject, [Rule.from_model(r) for r in rows], now or datetime.now(UTC)
        )
        self._areas: dict[str, Area | None] = {}
        self._locations: dict[str, Location | None] = {}
        self._assets: dict[str, Asset | None] = {}
        self._tags: dict[str, list[str]] = {}

    @property
    def is_admin(self) -> bool:
        return self.subject.role is Role.ADMIN

    def _area(self, area_id: str | None) -> Area | None:
        if area_id is None:
            return None
        if area_id not in self._areas:
            self._areas[area_id] = self.session.get(Area, area_id)
        return self._areas[area_id]

    def _location(self, location_id: str | None) -> Location | None:
        if location_id is None:
            return None
        if location_id not in self._locations:
            self._locations[location_id] = self.session.get(Location, location_id)
        return self._locations[location_id]

    def _asset(self, asset_id: str | None) -> Asset | None:
        if asset_id is None:
            return None
        if asset_id not in self._assets:
            self._assets[asset_id] = self.session.get(Asset, asset_id)
        return self._assets[asset_id]

    def _tag_ids(self, asset_id: str) -> list[str]:
        if asset_id not in self._tags:
            self._tags[asset_id] = list(
                self.session.scalars(select(AssetTag.tag_id).where(AssetTag.asset_id == asset_id))
            )
        return self._tags[asset_id]

    def prefetch_tags(self, asset_ids: Iterable[str]) -> None:
        """Load tag ids for many assets in one query."""
        wanted = [a for a in asset_ids if a not in self._tags]
        if not wanted:
            return
        for asset_id in wanted:
            self._tags[asset_id] = []
        rows = self.session.execute(
            select(AssetTag.asset_id, AssetTag.tag_id).where(AssetTag.asset_id.in_(wanted))
        )
        for asset_id, tag_id in rows:
            self._tags[asset_id].append(tag_id)

    def building_level(self, building: Building) -> AccessLevel:
        return self.policy.level_for(Target(building_id=building.id))

    def area_level(self, area: Area) -> AccessLevel:
        return self.policy.level_for(
            Target(area_id=area.id, building_id=area.building_id, critical=area.is_critical)
        )

    def location_level(self, location: Location) -> AccessLevel:
        area = self._area(location.area_id)
        if area is None:
            return AccessLevel.HIDDEN
        return self.area_level(area)

    def asset_level(self, asset: Asset) -> AccessLevel:
        chain: list[str] = []
        critical = False
        tag_ids: list[str] = []
        location_id: str | None = None
        current: Asset | None = asset
        seen: set[str] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            chain.append(current.id)
            critical = critical or current.is_critical
            tag_ids.extend(self._tag_ids(current.id))
            location_id = location_id or current.location_id
            current = self._asset(current.parent_asset_id)
        area = None
        location = self._location(location_id)
        if location is not None:
            area = self._area(location.area_id)
        return self.policy.level_for(
            Target(
                asset_chain=chain,
                tag_ids=tag_ids,
                area_id=area.id if area else None,
                building_id=area.building_id if area else None,
                critical=critical or bool(area and area.is_critical),
            )
        )

    def default_level(self) -> AccessLevel:
        """Level for property-wide records with no scope (products, tags)."""
        return self.policy.level_for(Target())
