"""Typed views of the Home Assistant registries Domus reads.

Field names are Home Assistant's own (``config/*_registry/list`` results).
Everything here comes from another system, so it is validated, unknown fields
are ignored, and strings are length-limited before they reach the database.
"""

from collections.abc import Sequence
from typing import Annotated, Any, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _pairs(value: Any) -> list[tuple[str, str]]:
    """HA sends ``connections`` and ``identifiers`` as lists of 2-item lists."""
    if not isinstance(value, list):
        return []
    out: list[tuple[str, str]] = []
    for item in cast(list[Any], value):
        if isinstance(item, list | tuple):
            pair = cast(Sequence[Any], item)
            if len(pair) == 2:
                out.append((str(pair[0])[:64], str(pair[1])[:256]))
    return out


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v)[:128] for v in cast(list[Any], value)]


def _clip(limit: int) -> BeforeValidator:
    """Cut over-long strings instead of rejecting the whole registry."""

    def clip(value: Any) -> Any:
        if value is None:
            return None
        return str(value)[:limit]

    return BeforeValidator(clip)


Opt16 = Annotated[str | None, _clip(16)]
Opt32 = Annotated[str | None, _clip(32)]
Opt64 = Annotated[str | None, _clip(64)]
Opt256 = Annotated[str | None, _clip(256)]
Str100 = Annotated[str, _clip(100)]
Str200 = Annotated[str, _clip(200)]

Pairs = Annotated[list[tuple[str, str]], BeforeValidator(_pairs)]
StrList = Annotated[list[str], BeforeValidator(_str_list)]
Id = Annotated[str, Field(min_length=1, max_length=128)]


class _Entry(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class HaFloor(_Entry):
    floor_id: Id
    name: Str200
    level: int | None = None


class HaArea(_Entry):
    area_id: Id
    name: Str200
    floor_id: Id | None = None
    labels: StrList = []


class HaLabel(_Entry):
    label_id: Id
    name: Str100
    color: Opt16 = None


class HaDevice(_Entry):
    id: Id
    name: Opt256 = None
    name_by_user: Opt256 = None
    manufacturer: Opt256 = None
    model: Opt256 = None
    model_id: Opt256 = None
    serial_number: Opt256 = None
    sw_version: Opt64 = None
    hw_version: Opt64 = None
    area_id: Id | None = None
    via_device_id: Id | None = None
    entry_type: Opt32 = None
    disabled_by: Opt32 = None
    connections: Pairs = []
    identifiers: Pairs = []
    labels: StrList = []

    @property
    def display_name(self) -> str:
        return (self.name_by_user or self.name or self.model or "Unnamed device")[:200]


class HaEntity(_Entry):
    entity_id: Id
    device_id: Id | None = None
    platform: Opt64 = None
    disabled_by: Opt32 = None

    @property
    def domain(self) -> str:
        return self.entity_id.partition(".")[0]


class HaRegistries(BaseModel):
    """Everything one import needs, fetched in one connection."""

    model_config = ConfigDict(frozen=True)

    floors: list[HaFloor] = []
    areas: list[HaArea] = []
    labels: list[HaLabel] = []
    devices: list[HaDevice] = []
    entities: list[HaEntity] = []
