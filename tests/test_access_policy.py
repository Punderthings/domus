"""Table-driven tests for the access policy (data-storage-backup.md 2.3.1, plan step 6)."""

from datetime import UTC, datetime, timedelta

import pytest

from domus.models.enums import AccessLevel as L
from domus.models.enums import Role, ScopeType, SubjectType
from domus.services.access import AccessPolicy, Rule, Subject, Target

NOW = datetime(2026, 11, 6, tzinfo=UTC)
ME = "m-1"  # the membership under test


def role_rule(scope: ScopeType, sid: str, role: Role, level: L, expires: datetime | None = None):
    return Rule(scope, sid, SubjectType.ROLE, role.value, level, expires)


def member_rule(scope: ScopeType, sid: str, level: L, member: str = ME):
    return Rule(scope, sid, SubjectType.MEMBERSHIP, member, level)


def level(role: Role, rules: list[Rule], target: Target) -> L:
    return AccessPolicy(Subject(role, ME), rules, NOW).level_for(target)


LIVING = Target(asset_chain=["light"], area_id="living", building_id="house")
BEDROOM = Target(asset_chain=["bedlight"], area_id="bedroom", building_id="house")


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.ADMIN, L.MANAGE),
        (Role.MAINTAINER, L.MANAGE),
        (Role.RESIDENT, L.CONTROL),
        (Role.GUEST, L.VIEW),
    ],
)
def test_role_defaults(role: Role, expected: L) -> None:
    assert level(role, [], LIVING) == expected


def test_admin_ignores_rules_and_critical() -> None:
    rules = [role_rule(ScopeType.AREA, "living", Role.ADMIN, L.HIDDEN)]
    target = Target(asset_chain=["x"], area_id="living", critical=True)
    assert level(Role.ADMIN, rules, target) == L.MANAGE


def test_shanes_guest_example() -> None:
    """Guests switch lights in public rooms but only see bedroom lights."""
    rules = [
        role_rule(ScopeType.AREA, "living", Role.GUEST, L.CONTROL),
        role_rule(ScopeType.AREA, "bedroom", Role.GUEST, L.VIEW),
    ]
    assert level(Role.GUEST, rules, LIVING) == L.CONTROL
    assert level(Role.GUEST, rules, BEDROOM) == L.VIEW


def test_teen_maintainer_example() -> None:
    """The teen maintainer can see but not touch the master bedroom, except the TV."""
    rules = [
        role_rule(ScopeType.AREA, "bedroom", Role.MAINTAINER, L.VIEW),
        member_rule(ScopeType.ASSET, "tv", L.CONTROL),
    ]
    assert level(Role.MAINTAINER, rules, BEDROOM) == L.VIEW
    tv = Target(asset_chain=["tv"], area_id="bedroom", building_id="house")
    assert level(Role.MAINTAINER, rules, tv) == L.CONTROL
    assert level(Role.MAINTAINER, rules, LIVING) == L.MANAGE


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        # asset beats tag beats area beats building
        (
            [
                role_rule(ScopeType.BUILDING, "house", Role.MAINTAINER, L.HIDDEN),
                role_rule(ScopeType.AREA, "living", Role.MAINTAINER, L.VIEW),
                role_rule(ScopeType.TAG, "smart", Role.MAINTAINER, L.CONTROL),
                role_rule(ScopeType.ASSET, "light", Role.MAINTAINER, L.MANAGE),
            ],
            L.MANAGE,
        ),
        (
            [
                role_rule(ScopeType.BUILDING, "house", Role.MAINTAINER, L.HIDDEN),
                role_rule(ScopeType.AREA, "living", Role.MAINTAINER, L.VIEW),
                role_rule(ScopeType.TAG, "smart", Role.MAINTAINER, L.CONTROL),
            ],
            L.CONTROL,
        ),
        (
            [
                role_rule(ScopeType.BUILDING, "house", Role.MAINTAINER, L.HIDDEN),
                role_rule(ScopeType.AREA, "living", Role.MAINTAINER, L.VIEW),
            ],
            L.VIEW,
        ),
        ([role_rule(ScopeType.BUILDING, "house", Role.MAINTAINER, L.HIDDEN)], L.HIDDEN),
    ],
)
def test_scope_precedence(rules: list[Rule], expected: L) -> None:
    target = Target(asset_chain=["light"], tag_ids=["smart"], area_id="living", building_id="house")
    assert level(Role.MAINTAINER, rules, target) == expected


def test_member_rule_beats_role_rule_at_same_scope() -> None:
    rules = [
        role_rule(ScopeType.AREA, "living", Role.RESIDENT, L.HIDDEN),
        member_rule(ScopeType.AREA, "living", L.CONTROL),
    ]
    assert level(Role.RESIDENT, rules, LIVING) == L.CONTROL


def test_other_members_rules_do_not_apply() -> None:
    rules = [member_rule(ScopeType.AREA, "living", L.HIDDEN, member="someone-else")]
    assert level(Role.RESIDENT, rules, LIVING) == L.CONTROL


def test_other_roles_rules_do_not_apply() -> None:
    rules = [role_rule(ScopeType.AREA, "living", Role.GUEST, L.HIDDEN)]
    assert level(Role.RESIDENT, rules, LIVING) == L.CONTROL


def test_expired_rule_is_ignored() -> None:
    past = NOW - timedelta(seconds=1)
    future = NOW + timedelta(days=1)
    assert (
        level(
            Role.GUEST, [role_rule(ScopeType.AREA, "living", Role.GUEST, L.CONTROL, past)], LIVING
        )
        == L.VIEW
    )
    assert (
        level(
            Role.GUEST, [role_rule(ScopeType.AREA, "living", Role.GUEST, L.CONTROL, future)], LIVING
        )
        == L.CONTROL
    )


def test_conflicting_tag_rules_fail_closed() -> None:
    rules = [
        role_rule(ScopeType.TAG, "a", Role.MAINTAINER, L.MANAGE),
        role_rule(ScopeType.TAG, "b", Role.MAINTAINER, L.VIEW),
    ]
    target = Target(asset_chain=["x"], tag_ids=["a", "b"])
    assert level(Role.MAINTAINER, rules, target) == L.VIEW


def test_child_asset_inherits_parent_rule() -> None:
    rules = [role_rule(ScopeType.ASSET, "furnace", Role.MAINTAINER, L.VIEW)]
    blower = Target(asset_chain=["blower", "furnace"], area_id="utility")
    assert level(Role.MAINTAINER, rules, blower) == L.VIEW


def test_own_rule_beats_parent_rule() -> None:
    rules = [
        role_rule(ScopeType.ASSET, "furnace", Role.MAINTAINER, L.VIEW),
        role_rule(ScopeType.ASSET, "blower", Role.MAINTAINER, L.MANAGE),
    ]
    blower = Target(asset_chain=["blower", "furnace"])
    assert level(Role.MAINTAINER, rules, blower) == L.MANAGE


@pytest.mark.parametrize("role", [Role.GUEST, Role.RESIDENT])
def test_rules_never_raise_guests_or_residents_above_control(role: Role) -> None:
    rules = [role_rule(ScopeType.ASSET, "light", role, L.MANAGE)]
    assert level(role, rules, LIVING) == L.CONTROL


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.MAINTAINER, L.CONTROL), (Role.RESIDENT, L.CONTROL), (Role.GUEST, L.VIEW)],
)
def test_critical_caps_manage(role: Role, expected: L) -> None:
    furnace = Target(asset_chain=["furnace"], area_id="utility", critical=True)
    assert level(role, [], furnace) == expected


def test_critical_with_rule_can_still_lower() -> None:
    rules = [role_rule(ScopeType.ASSET, "furnace", Role.MAINTAINER, L.HIDDEN)]
    furnace = Target(asset_chain=["furnace"], critical=True)
    assert level(Role.MAINTAINER, rules, furnace) == L.HIDDEN


def test_hidden_area_rule_hides_assets() -> None:
    rules = [role_rule(ScopeType.AREA, "closet", Role.GUEST, L.HIDDEN)]
    target = Target(asset_chain=["router"], area_id="closet")
    assert level(Role.GUEST, rules, target) == L.HIDDEN
