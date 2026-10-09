from __future__ import annotations

from enum import Enum
from typing import Iterable, Mapping


class IdNamespace(str, Enum):
    """Semantic Geometry Dash ID namespaces understood by the runtime.

    Not every namespace is safe to auto-allocate.  In particular, color IDs
    include built-in/special channels, while block IDs have editor semantics
    that should not be guessed by the generic allocator.  Allocation therefore
    remains deliberately narrower than semantic understanding.
    """

    GROUP = "group"
    ITEM = "item"
    CONTROL = "control"
    COLOR = "color"
    BLOCK = "block"
    FORCE = "force"
    SONG_CHANNEL = "song_channel"
    TRIGGER_CHANNEL = "trigger_channel"
    MATERIAL = "material"
    GRADIENT = "gradient"
    AREA_EFFECT = "area_effect"
    ENTER_EFFECT = "enter_effect"
    ENTER_CHANNEL = "enter_channel"
    SFX_GROUP = "sfx_group"
    SFX_UNIQUE = "sfx_unique"


_ALLOCATABLE_NAMESPACES = frozenset({
    IdNamespace.GROUP,
    IdNamespace.ITEM,
    IdNamespace.CONTROL,
})


def normalize_namespace(value: str | IdNamespace) -> IdNamespace:
    if isinstance(value, IdNamespace):
        return value
    text = str(value).strip().lower().replace("-", "_")
    aliases = {
        "group": IdNamespace.GROUP,
        "groups": IdNamespace.GROUP,
        "item": IdNamespace.ITEM,
        "items": IdNamespace.ITEM,
        "control": IdNamespace.CONTROL,
        "controls": IdNamespace.CONTROL,
        "color": IdNamespace.COLOR,
        "colors": IdNamespace.COLOR,
        "colour": IdNamespace.COLOR,
        "colours": IdNamespace.COLOR,
        "color_channel": IdNamespace.COLOR,
        "color_channels": IdNamespace.COLOR,
        "block": IdNamespace.BLOCK,
        "blocks": IdNamespace.BLOCK,
        "collision_block": IdNamespace.BLOCK,
        "collision_blocks": IdNamespace.BLOCK,
        "force": IdNamespace.FORCE,
        "forces": IdNamespace.FORCE,
        "force_id": IdNamespace.FORCE,
        "song_channel": IdNamespace.SONG_CHANNEL,
        "song_channels": IdNamespace.SONG_CHANNEL,
        "trigger_channel": IdNamespace.TRIGGER_CHANNEL,
        "trigger_channels": IdNamespace.TRIGGER_CHANNEL,
        "material": IdNamespace.MATERIAL,
        "materials": IdNamespace.MATERIAL,
        "material_id": IdNamespace.MATERIAL,
        "gradient": IdNamespace.GRADIENT,
        "gradients": IdNamespace.GRADIENT,
        "gradient_id": IdNamespace.GRADIENT,
        "area_effect": IdNamespace.AREA_EFFECT,
        "area_effects": IdNamespace.AREA_EFFECT,
        "enter_effect": IdNamespace.ENTER_EFFECT,
        "enter_effects": IdNamespace.ENTER_EFFECT,
        "enter_channel": IdNamespace.ENTER_CHANNEL,
        "enter_channels": IdNamespace.ENTER_CHANNEL,
        "sfx_group": IdNamespace.SFX_GROUP,
        "sfx_groups": IdNamespace.SFX_GROUP,
        "sfx_unique": IdNamespace.SFX_UNIQUE,
        "sfx_unique_id": IdNamespace.SFX_UNIQUE,
        "unique_sfx": IdNamespace.SFX_UNIQUE,
    }
    try:
        return aliases[text]
    except KeyError as exc:
        raise ValueError(f"Unknown ID namespace: {value!r}") from exc


def namespace_is_allocatable(namespace: str | IdNamespace) -> bool:
    return normalize_namespace(namespace) in _ALLOCATABLE_NAMESPACES


class _SemanticId(int):
    namespace: IdNamespace

    def __new__(cls, value: int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{cls.__name__} must be created from int")
        if value < 0:
            raise ValueError(f"{cls.__name__} cannot be negative")
        if cls.namespace is IdNamespace.GROUP and value > 9999:
            raise ValueError("Geometry Dash group IDs must be in 0..9999")
        return int.__new__(cls, value)

    def __str__(self) -> str:
        return str(int(self))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({int(self)})"


class GroupId(_SemanticId):
    namespace = IdNamespace.GROUP


class ItemId(_SemanticId):
    namespace = IdNamespace.ITEM


class ControlId(_SemanticId):
    namespace = IdNamespace.CONTROL


class ColorId(_SemanticId):
    namespace = IdNamespace.COLOR


class BlockId(_SemanticId):
    namespace = IdNamespace.BLOCK


class ForceId(_SemanticId):
    namespace = IdNamespace.FORCE


class SongChannelId(_SemanticId):
    namespace = IdNamespace.SONG_CHANNEL


class TriggerChannelId(_SemanticId):
    namespace = IdNamespace.TRIGGER_CHANNEL


class MaterialId(_SemanticId):
    namespace = IdNamespace.MATERIAL


class GradientId(_SemanticId):
    namespace = IdNamespace.GRADIENT


class AreaEffectId(_SemanticId):
    namespace = IdNamespace.AREA_EFFECT


class EnterEffectId(_SemanticId):
    namespace = IdNamespace.ENTER_EFFECT


class EnterChannelId(_SemanticId):
    namespace = IdNamespace.ENTER_CHANNEL


class SFXGroupId(_SemanticId):
    namespace = IdNamespace.SFX_GROUP


class SFXUniqueId(_SemanticId):
    namespace = IdNamespace.SFX_UNIQUE


_ID_TYPE = {
    IdNamespace.GROUP: GroupId,
    IdNamespace.ITEM: ItemId,
    IdNamespace.CONTROL: ControlId,
    IdNamespace.COLOR: ColorId,
    IdNamespace.BLOCK: BlockId,
    IdNamespace.FORCE: ForceId,
    IdNamespace.SONG_CHANNEL: SongChannelId,
    IdNamespace.TRIGGER_CHANNEL: TriggerChannelId,
    IdNamespace.MATERIAL: MaterialId,
    IdNamespace.GRADIENT: GradientId,
    IdNamespace.AREA_EFFECT: AreaEffectId,
    IdNamespace.ENTER_EFFECT: EnterEffectId,
    IdNamespace.ENTER_CHANNEL: EnterChannelId,
    IdNamespace.SFX_GROUP: SFXGroupId,
    IdNamespace.SFX_UNIQUE: SFXUniqueId,
}


def semantic_id(namespace: str | IdNamespace, value: int) -> _SemanticId:
    ns = normalize_namespace(namespace)
    return _ID_TYPE[ns](value)


def validate_mapping(namespace: str | IdNamespace, mapping: Mapping[int, int]) -> dict[int, int]:
    ns = normalize_namespace(namespace)
    out: dict[int, int] = {}
    for old, new in mapping.items():
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (old, new)):
            raise TypeError(f"{ns.value} ID mappings must contain integers")
        if old < 0 or new < 0:
            raise ValueError(f"{ns.value} IDs must be non-negative")
        if ns is IdNamespace.GROUP and new > 9999:
            raise ValueError("Geometry Dash group IDs must be in 0..9999")
        out[old] = new
    return out


def allocate_ids(
    used: Iterable[int], namespace: str | IdNamespace, count: int = 1,
    *, start: int = 1, reuse_gaps: bool = False,
) -> list[int]:
    ns = normalize_namespace(namespace)
    if ns not in _ALLOCATABLE_NAMESPACES:
        raise ValueError(
            f"Automatic allocation for {ns.value} IDs is not defined; "
            "use an explicit ID until that namespace's allocation rules are modeled"
        )
    if count < 0:
        raise ValueError("count must be non-negative")
    if start < 1:
        raise ValueError("start must be positive")
    taken = set(int(v) for v in used)
    if count == 0:
        return []
    cursor = start if reuse_gaps else max(start, max(taken, default=0) + 1)
    result: list[int] = []
    while len(result) < count:
        if ns is IdNamespace.GROUP and cursor > 9999:
            raise ValueError("No unused Geometry Dash group ID remains in 1..9999")
        if cursor not in taken:
            result.append(cursor)
            taken.add(cursor)
        cursor += 1
    return result
