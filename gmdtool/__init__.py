from __future__ import annotations

from .catalog import Catalog, ObjectSchema, PropertySchema, default_catalog
from .ids import (AreaEffectId, BlockId, ColorId, ControlId, EnterChannelId, EnterEffectId, ForceId, GradientId, GroupId, IdNamespace, ItemId, MaterialId, SFXGroupId, SFXUniqueId, SongChannelId, TriggerChannelId)
from .geode_bridge import GeodeBridge, GeodeBridgeError, GeodeUnavailable, GeodeProtocolError
from .io import GMD
from .level import GDLevel
from .numeric import GDReal
from .object import GDObject, RawPropertyPair
from .objects import Trigger, get_object_class, resolve_object_class
from .query import MultipleObjectsFound, ObjectCollection, SelectionCardinalityError
from .scripting import BlockHandle, BuildScope, ColorHandle, GroupHandle, NewIds
from .templates import ObjectTemplate
from .structured import (
    GDGroupRemap, GDGroupRemapList,
    GDParticleSettings,
    GDSequenceEntry, GDSequenceList,
    GDWeightedGroup, GDWeightedGroupList,
)

__version__ = "0.4.0.dev0"


def __getattr__(name: str):
    # Make `from gmdtool import OBJ_901` and catalog aliases work without
    # duplicating 4k generated names in this module.
    from . import objects as _objects
    try:
        return getattr(_objects, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc


__all__ = [
    "Catalog", "ObjectSchema", "PropertySchema", "default_catalog",
    "GeodeBridge", "GeodeBridgeError", "GeodeUnavailable", "GeodeProtocolError",
    "GMD", "GDLevel", "GDObject", "RawPropertyPair", "GDReal",
    "Trigger", "ObjectCollection", "MultipleObjectsFound", "SelectionCardinalityError",
    "GroupId", "ItemId", "ControlId", "ColorId", "BlockId", "ForceId",
    "SongChannelId", "TriggerChannelId", "MaterialId", "GradientId",
    "AreaEffectId", "EnterEffectId", "EnterChannelId", "SFXGroupId", "SFXUniqueId",
    "IdNamespace", "GroupHandle", "ColorHandle", "BlockHandle", "BuildScope", "NewIds", "ObjectTemplate",
    "GDParticleSettings", "GDWeightedGroup", "GDWeightedGroupList",
    "GDSequenceEntry", "GDSequenceList", "GDGroupRemap", "GDGroupRemapList",
    "get_object_class", "resolve_object_class",
]
