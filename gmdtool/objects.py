from __future__ import annotations

from typing import Any

from .catalog import Catalog, default_catalog
from .object import GDObject


class Trigger(GDObject):
    IS_TRIGGER = True


OBJECT_REGISTRY: dict[int, type[GDObject]] = {}
ALIAS_REGISTRY: dict[str, type[GDObject]] = {}


def get_object_class(object_id: int | None, *, catalog: Catalog | None = None) -> type[GDObject]:
    if object_id is None:
        return GDObject
    oid = int(object_id)
    cls = OBJECT_REGISTRY.get(oid)
    if cls is not None:
        return cls
    cat = catalog or default_catalog()
    schema = cat.get_object(oid)
    base = Trigger if schema is not None and schema.base == "trigger" else GDObject
    cls = type(
        f"OBJ_{oid}",
        (base,),
        {
            "OBJECT_ID": oid,
            "__module__": __name__,
            "__doc__": (
                f"Generated class for {schema.name} (Object ID {oid})."
                if schema is not None
                else f"Generated raw-capable class for Object ID {oid}."
            ),
        },
    )
    OBJECT_REGISTRY[oid] = cls
    globals()[cls.__name__] = cls
    return cls


def resolve_object_class(selector: Any, *, catalog: Catalog | None = None) -> type[GDObject]:
    if isinstance(selector, type) and issubclass(selector, GDObject):
        return selector
    cat = catalog or default_catalog()
    oid = cat.resolve_object_id(selector)
    return get_object_class(oid, catalog=cat)


def _bootstrap() -> None:
    cat = default_catalog()
    for oid in cat.known_object_ids:
        get_object_class(oid, catalog=cat)
    for name, oid in cat.aliases.items():
        if not name.isidentifier():
            continue
        cls = get_object_class(oid, catalog=cat)
        ALIAS_REGISTRY[name] = cls
        globals()[name] = cls


_bootstrap()


def __getattr__(name: str):
    if name.startswith("OBJ_"):
        try:
            oid = int(name[4:])
        except ValueError:
            pass
        else:
            return get_object_class(oid)
    try:
        return ALIAS_REGISTRY[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
