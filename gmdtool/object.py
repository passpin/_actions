from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, TYPE_CHECKING

from .catalog import Catalog, PropertySchema, default_catalog
from .codecs import decode_property, encode_property, raw_value
from .ids import IdNamespace, normalize_namespace, validate_mapping
from .numeric import GDReal
from .structured import GDGroupRemapList, GDSequenceList, GDWeightedGroupList

if TYPE_CHECKING:
    from .level import GDLevel


@dataclass(frozen=True)
class RawPropertyPair:
    key: str
    value: str


def _key_text(key: int | str) -> str:
    if isinstance(key, bool):
        raise TypeError("bool is not a raw property key")
    return str(key)


def _numeric_key(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def _same_key(left: str, right: str) -> bool:
    if left == right:
        return True
    lhs, rhs = _numeric_key(left), _numeric_key(right)
    return lhs is not None and rhs is not None and lhs == rhs


def _check_token(token: str) -> None:
    if "," in token or ";" in token:
        raise ValueError("Raw object tokens cannot contain ',' or ';'")


class GDObject:
    """Lossless ordered GD object with optional catalog-backed semantic views."""

    OBJECT_ID: int | None = None
    IS_TRIGGER = False

    _INTERNAL_NAMES = {
        "_pairs", "_malformed_tail", "_catalog", "_owner", "_uid",
    }

    def __init__(
        self,
        object_id: int | None = None,
        *,
        _pairs: Iterable[tuple[int | str, str] | RawPropertyPair] | None = None,
        _malformed_tail: str | None = None,
        _owner: "GDLevel | None" = None,
        _catalog: Catalog | None = None,
        _uid: str | None = None,
        **properties: Any,
    ) -> None:
        catalog = _catalog or default_catalog()
        object.__setattr__(self, "_catalog", catalog)
        object.__setattr__(self, "_owner", _owner)
        object.__setattr__(self, "_uid", _uid or uuid.uuid4().hex)
        object.__setattr__(self, "_malformed_tail", _malformed_tail)

        expected = self.OBJECT_ID if self.OBJECT_ID is not None else object_id
        if _pairs is None:
            if expected is None:
                raise TypeError("GDObject needs an object_id")
            pairs = [("1", str(expected))]
        else:
            pairs = []
            for pair in _pairs:
                if isinstance(pair, RawPropertyPair):
                    key, value = pair.key, pair.value
                else:
                    key, value = pair
                pairs.append((_key_text(key), str(value)))
        object.__setattr__(self, "_pairs", pairs)

        if expected is not None:
            raw_id = self.get_raw(1)
            if raw_id is None:
                self._pairs.insert(0, ("1", str(expected)))
            elif int(raw_id) != expected and self.OBJECT_ID is not None:
                # Parsed raw data should have been dispatched to the matching class.
                # Construction from a canonical OBJ_<ID> class should not silently
                # create a different object type.
                raise ValueError(
                    f"{type(self).__name__} expects object ID {expected}, raw data has {raw_id}"
                )

        for name, value in properties.items():
            self.set(name, value)

    @classmethod
    def parse(cls, raw: str, *, catalog: Catalog | None = None) -> "GDObject":
        if not isinstance(raw, str):
            raise TypeError("raw object must be str")
        tokens = raw.split(",")
        pairs = [(tokens[i], tokens[i + 1]) for i in range(0, len(tokens) - 1, 2)]
        tail = tokens[-1] if len(tokens) % 2 else None
        raw_id = None
        for key, value in reversed(pairs):
            if _same_key(key, "1"):
                try:
                    raw_id = int(value)
                except ValueError:
                    raw_id = None
                break
        from .objects import get_object_class
        object_cls = get_object_class(raw_id, catalog=catalog) if raw_id is not None else GDObject
        if object_cls is GDObject:
            return cls(object_id=raw_id, _pairs=pairs, _malformed_tail=tail, _catalog=catalog)
        return object_cls(_pairs=pairs, _malformed_tail=tail, _catalog=catalog)

    @classmethod
    def schema(cls, catalog: Catalog | None = None) -> tuple[PropertySchema, ...]:
        cat = catalog or default_catalog()
        return cat.properties_for(cls.OBJECT_ID)

    @classmethod
    def supports_property(cls, name_or_key: int | str, catalog: Catalog | None = None) -> bool:
        cat = catalog or default_catalog()
        return cat.find_property(cls.OBJECT_ID, name_or_key) is not None

    @property
    def uid(self) -> str:
        return self._uid

    @property
    def owner(self) -> "GDLevel | None":
        return self._owner

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    @property
    def object_id(self) -> int | None:
        raw = self.get_raw(1)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    @property
    def object_name(self) -> str:
        name = self._catalog.object_display_name(self.object_id)
        return name if name is not None else "Malformed object"

    @property
    def is_trigger(self) -> bool:
        schema = self._catalog.get_object(self.object_id)
        if schema is not None:
            return schema.base == "trigger"
        return self.IS_TRIGGER

    @property
    def raw_pairs(self) -> tuple[RawPropertyPair, ...]:
        return tuple(RawPropertyPair(k, v) for k, v in self._pairs)

    @property
    def malformed_tail(self) -> str | None:
        return self._malformed_tail

    def _mark_dirty(self) -> None:
        if self._owner is not None:
            self._owner._mark_dirty()

    def _sync_runtime_class(self) -> None:
        oid = self.object_id
        if oid is None:
            return
        try:
            from .objects import get_object_class
            cls = get_object_class(oid, catalog=self._catalog)
            if type(self) is not cls:
                self.__class__ = cls
        except (TypeError, AttributeError):
            # Class identity is a convenience; raw editing must never fail merely
            # because Python refuses a runtime __class__ reassignment.
            pass

    def clone(self, *, preserve_uid: bool = False) -> "GDObject":
        from .objects import get_object_class
        oid = self.object_id
        cls = get_object_class(oid, catalog=self._catalog) if oid is not None else GDObject
        kwargs = dict(
            _pairs=list(self._pairs),
            _malformed_tail=self._malformed_tail,
            _catalog=self._catalog,
            _uid=self._uid if preserve_uid else None,
        )
        return cls(**kwargs) if cls is not GDObject else GDObject(object_id=oid, **kwargs)

    def to_object_string(self) -> str:
        tokens = [token for pair in self._pairs for token in pair]
        if self._malformed_tail is not None:
            tokens.append(self._malformed_tail)
        return ",".join(tokens)

    def __str__(self) -> str:
        return self.to_object_string()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(id={self.object_id}, name={self.object_name!r}, uid={self._uid[:8]!r})"

    # ---------------- raw view ----------------

    def get_raw(self, key: int | str, default: str | None = None, *, occurrence: str | int = "last") -> str | None:
        token = _key_text(key)
        matches = [value for k, value in self._pairs if _same_key(k, token)]
        if not matches:
            return default
        if occurrence == "last":
            return matches[-1]
        if occurrence == "first":
            return matches[0]
        if isinstance(occurrence, int) and not isinstance(occurrence, bool):
            try:
                return matches[occurrence]
            except IndexError:
                return default
        raise ValueError("occurrence must be 'first', 'last', or an integer")

    def get_all_raw(self, key: int | str) -> tuple[str, ...]:
        token = _key_text(key)
        return tuple(value for k, value in self._pairs if _same_key(k, token))

    def set_raw(self, key: int | str, value: Any) -> "GDObject":
        """Raw escape hatch: replace only the last occurrence or append a new pair."""
        token = _key_text(key)
        raw = raw_value(value)
        _check_token(token)
        _check_token(raw)
        for index in range(len(self._pairs) - 1, -1, -1):
            old_key, old_value = self._pairs[index]
            if not _same_key(old_key, token):
                continue
            if old_value != raw:
                self._pairs[index] = (old_key, raw)
                self._mark_dirty()
                if _same_key(token, "1"):
                    self._sync_runtime_class()
            return self
        self._pairs.append((token, raw))
        self._mark_dirty()
        if _same_key(token, "1"):
            self._sync_runtime_class()
        return self

    def append_raw(self, key: int | str, value: Any) -> "GDObject":
        token = _key_text(key)
        raw = raw_value(value)
        _check_token(token)
        _check_token(raw)
        self._pairs.append((token, raw))
        self._mark_dirty()
        if _same_key(token, "1"):
            self._sync_runtime_class()
        return self

    def _set_semantic_raw(self, key: int, raw: str) -> "GDObject":
        """Write the effective semantic occurrence while preserving earlier duplicates.

        Semantic reads use the last raw occurrence of a key, matching ``get_raw``.
        Updating only that occurrence avoids rewriting shadowed/unknown historical data.
        """
        token = str(key)
        raw = str(raw)
        _check_token(raw)
        for index in range(len(self._pairs) - 1, -1, -1):
            old_key, old_value = self._pairs[index]
            if not _same_key(old_key, token):
                continue
            if old_value != raw:
                self._pairs[index] = (old_key, raw)
                self._mark_dirty()
                if key == 1:
                    self._sync_runtime_class()
            return self
        self._pairs.append((token, raw))
        self._mark_dirty()
        if key == 1:
            self._sync_runtime_class()
        return self

    def remove_raw(self, key: int | str, *, occurrence: str | int | None = None) -> "GDObject":
        token = _key_text(key)
        indexes = [i for i, (k, _) in enumerate(self._pairs) if _same_key(k, token)]
        if not indexes:
            return self
        if occurrence is None:
            targets = set(indexes)
        elif occurrence == "first":
            targets = {indexes[0]}
        elif occurrence == "last":
            targets = {indexes[-1]}
        elif isinstance(occurrence, int) and not isinstance(occurrence, bool):
            try:
                targets = {indexes[occurrence]}
            except IndexError:
                return self
        else:
            raise ValueError("occurrence must be None, 'first', 'last', or an integer")
        self._pairs[:] = [pair for i, pair in enumerate(self._pairs) if i not in targets]
        self._mark_dirty()
        if _same_key(token, "1"):
            self._sync_runtime_class()
        return self

    unset_raw = remove_raw

    def replace_raw_pairs(self, pairs: Iterable[tuple[int | str, Any] | RawPropertyPair], *, malformed_tail: str | None = None) -> "GDObject":
        prepared: list[tuple[str, str]] = []
        for pair in pairs:
            if isinstance(pair, RawPropertyPair):
                key, value = pair.key, pair.value
            else:
                key, value = pair
            key_text, value_text = _key_text(key), raw_value(value)
            _check_token(key_text)
            _check_token(value_text)
            prepared.append((key_text, value_text))
        if malformed_tail is not None:
            _check_token(malformed_tail)
        if prepared != self._pairs or malformed_tail != self._malformed_tail:
            self._pairs[:] = prepared
            object.__setattr__(self, "_malformed_tail", malformed_tail)
            self._mark_dirty()
            self._sync_runtime_class()
        return self

    # ---------------- semantic view ----------------

    def _effective_semantic(self, schema: PropertySchema) -> Mapping[str, Any] | None:
        """Resolve catalog semantic variants against this object's current state."""
        if not schema.variants:
            return schema.semantic

        default_semantic = schema.semantic
        for variant in schema.variants:
            if variant.get("default") is True:
                semantic = variant.get("semantic")
                if isinstance(semantic, Mapping):
                    default_semantic = semantic
                continue
            when = variant.get("when")
            if not isinstance(when, Mapping):
                continue
            property_name = when.get("property")
            if not isinstance(property_name, str) or "equals" not in when:
                continue
            condition_schema = self._catalog.find_property(self.object_id, property_name)
            if condition_schema is None:
                continue
            raw = self.get_raw(condition_schema.key)
            if raw is None:
                continue
            try:
                actual = decode_property(condition_schema, raw, catalog=self._catalog)
            except (ValueError, TypeError, OverflowError, ArithmeticError, UnicodeError):
                actual = raw
            expected = when["equals"]
            if condition_schema.enum and isinstance(expected, str):
                try:
                    expected = self._catalog.enum_value(condition_schema.enum, expected)
                except (KeyError, ValueError):
                    pass
            if actual == expected:
                semantic = variant.get("semantic")
                return semantic if isinstance(semantic, Mapping) else schema.semantic
        return default_semantic

    def _schema_for_read(self, name_or_key: int | str) -> PropertySchema | None:
        schema = self._catalog.find_property(self.object_id, name_or_key)
        if schema is not None:
            return schema
        # Global property data is only a conservative numeric-key inspection
        # fallback. Global semantic names can be contextually wrong in GD.
        key: int | None = None
        if isinstance(name_or_key, int) and not isinstance(name_or_key, bool):
            key = name_or_key
        elif isinstance(name_or_key, str):
            try:
                key = int(name_or_key)
            except ValueError:
                pass
        return self._catalog.global_property(key) if key is not None else None

    def get(self, name_or_key: int | str, default: Any = None) -> Any:
        schema = self._schema_for_read(name_or_key)
        raw_key = schema.key if schema is not None else name_or_key
        raw = self.get_raw(raw_key)
        if raw is None:
            return default
        if schema is None:
            return raw

        expected_raw = raw

        def write(new_raw: str) -> None:
            nonlocal expected_raw
            if self.get_raw(schema.key) != expected_raw:
                raise RuntimeError("Structured view is stale; read the property again before editing it")
            self._set_semantic_raw(schema.key, new_raw)
            expected_raw = new_raw

        try:
            return decode_property(
                schema, raw, catalog=self._catalog, on_change=write,
                semantic=self._effective_semantic(schema),
            )
        except (ValueError, TypeError, OverflowError, ArithmeticError, UnicodeError):
            return raw

    def set(self, name_or_key: int | str, value: Any) -> "GDObject":
        schema = self._catalog.find_property(self.object_id, name_or_key)
        if value is None:
            if schema is not None:
                return self.remove_raw(schema.key)
            if isinstance(name_or_key, int) or (isinstance(name_or_key, str) and name_or_key.lstrip("+-").isdigit()):
                return self.remove_raw(name_or_key)
            raise KeyError(f"Object {self.object_id} has no typed property {name_or_key!r}")
        if schema is None:
            if isinstance(name_or_key, int) or (isinstance(name_or_key, str) and name_or_key.lstrip("+-").isdigit()):
                return self.set_raw(name_or_key, value)
            raise KeyError(
                f"Object {self.object_id} has no typed property {name_or_key!r}; "
                "use set_raw(key, value) for undefined raw properties"
            )
        return self._set_semantic_raw(schema.key, encode_property(schema, value, catalog=self._catalog))

    def unset(self, name_or_key: int | str) -> "GDObject":
        schema = self._catalog.find_property(self.object_id, name_or_key)
        if schema is not None:
            return self.remove_raw(schema.key)
        return self.remove_raw(name_or_key)

    def __getitem__(self, name_or_key: int | str) -> Any:
        value = self.get(name_or_key, default=...)
        if value is ...:
            raise KeyError(name_or_key)
        return value

    def __setitem__(self, name_or_key: int | str, value: Any) -> None:
        self.set(name_or_key, value)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        catalog = object.__getattribute__(self, "_catalog")
        oid = self.object_id
        schema = catalog.find_property(oid, name)
        if schema is None:
            raise AttributeError(
                f"{type(self).__name__} has no typed property {name!r}; use get_raw()/set_raw() for raw data"
            )
        return self.get(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_") or name in self._INTERNAL_NAMES:
            object.__setattr__(self, name, value)
            return
        try:
            catalog = object.__getattribute__(self, "_catalog")
        except AttributeError:
            object.__setattr__(self, name, value)
            return
        schema = catalog.find_property(self.object_id, name)
        if schema is None:
            raise AttributeError(
                f"{type(self).__name__} has no typed property {name!r}; use set_raw() for undefined raw data"
            )
        self.set(name, value)

    # ---------------- common transforms / references ----------------

    def translate(self, dx: Any = 0, dy: Any = 0) -> "GDObject":
        dxv, dyv = GDReal.from_value(dx), GDReal.from_value(dy)
        new_x = None
        new_y = None
        if dxv != GDReal("0"):
            raw_x = self.get_raw(2)
            if raw_x is None:
                raise ValueError("Object has no x property")
            new_x = GDReal(raw_x) + dxv
        if dyv != GDReal("0"):
            raw_y = self.get_raw(3)
            if raw_y is None:
                raise ValueError("Object has no y property")
            new_y = GDReal(raw_y) + dyv
        if new_x is not None:
            self._set_semantic_raw(2, new_x.raw)
        if new_y is not None:
            self._set_semantic_raw(3, new_y.raw)
        return self

    def move_to(self, *, x: Any | None = None, y: Any | None = None) -> "GDObject":
        if x is not None:
            self._set_semantic_raw(2, GDReal.from_value(x).raw)
        if y is not None:
            self._set_semantic_raw(3, GDReal.from_value(y).raw)
        return self

    def _membership_keys(self) -> tuple[int, ...]:
        keys = [p.key for p in self._catalog.properties_for(self.object_id) if p.type == "groups"]
        for key in (57, 274):
            if key not in keys:
                keys.append(key)
        return tuple(keys)

    def membership_groups(self) -> tuple[int, ...]:
        out: list[int] = []
        for key in self._membership_keys():
            for raw in self.get_all_raw(key):
                if raw == "":
                    continue
                try:
                    values = [int(v) for v in raw.split(".")]
                except ValueError:
                    continue
                for ident in values:
                    if ident not in out:
                        out.append(ident)
        return tuple(out)

    def add_group(self, group_id: int) -> "GDObject":
        if isinstance(group_id, bool) or not isinstance(group_id, int):
            raise TypeError("group_id must be int")
        if group_id < 0 or group_id > 9999:
            raise ValueError("group_id must be in 0..9999")
        raw = self.get_raw(57)
        groups = [] if not raw else [int(v) for v in raw.split(".")]
        if group_id not in groups:
            groups.append(group_id)
            self._set_semantic_raw(57, ".".join(map(str, groups)))
        return self

    def remove_group(self, group_id: int) -> "GDObject":
        raw = self.get_raw(57)
        if raw is None:
            return self
        groups = [int(v) for v in raw.split(".") if v != ""]
        groups = [v for v in groups if v != group_id]
        if groups:
            self._set_semantic_raw(57, ".".join(map(str, groups)))
        else:
            self.remove_raw(57)
        return self

    def _semantic_keys(
        self, namespace: IdNamespace, *, kinds: frozenset[str] = frozenset({"reference"}),
        include_legacy_references: bool = True,
    ) -> tuple[int, ...]:
        """Return simple integer keys carrying IDs in ``namespace``.

        ``references.json`` is retained as a compatibility/evidence layer while
        source schemas migrate toward explicit semantic metadata.  It represents
        references, so it is only consulted when ``reference`` is requested.
        """
        ns = namespace.value
        keys: list[int] = []
        structured = {"groups", "weighted_groups", "sequence", "remap_list"}
        properties = self._catalog.properties_for(self.object_id)
        explicit_semantic_keys = {
            prop.key for prop in properties if prop.semantic is not None or prop.variants
        }
        for prop in properties:
            semantic = self._effective_semantic(prop) or {}
            if (
                semantic.get("namespace") == ns
                and semantic.get("kind") in kinds
                and prop.type not in structured
                and prop.key not in keys
            ):
                keys.append(prop.key)
        if include_legacy_references and "reference" in kinds:
            for key in self._catalog.reference_keys(ns, self.object_id):
                # Explicit source semantics (including conditional variants) are
                # authoritative over the legacy reference-key compatibility map.
                if key in explicit_semantic_keys:
                    continue
                if key not in keys:
                    keys.append(key)

        # A very small set of object-string properties have context-independent
        # semantics across ordinary objects (for example group membership and
        # color-channel references).  They live in the global property table so
        # raw-only Object IDs can still participate in relationship analysis.
        # Context-sensitive global labels remain inspection-only.
        for prop in self._catalog.universal_semantic_properties(ns, kinds):
            if (
                prop.key not in explicit_semantic_keys
                and prop.key not in keys
                and self.get_raw(prop.key) is not None
            ):
                keys.append(prop.key)

        return tuple(keys)

    @staticmethod
    def _append_unique(out: list[int], value: int) -> None:
        if value not in out:
            out.append(value)

    def references(
        self, namespace: str | IdNamespace, *, scope: Mapping[str | IdNamespace, int] | None = None,
    ) -> tuple[int, ...]:
        """IDs semantically referenced by this object.

        Definitions/identifiers are intentionally separate; for example a
        Collision Block *defines* a Block ID, while a Collision Trigger
        references one.
        """
        ns = normalize_namespace(namespace)
        out: list[int] = []

        normalized_scope = {normalize_namespace(k).value: int(v) for k, v in (scope or {}).items()}
        for key in self._semantic_keys(ns, kinds=frozenset({"reference"})):
            prop = self._catalog.find_property(self.object_id, key) or self._catalog.global_property(key)
            semantic = self._effective_semantic(prop) if prop is not None else None
            semantic = semantic or {}
            scope_ns = semantic.get("scope_namespace")
            scope_prop = semantic.get("scope_property")
            if normalized_scope and scope_ns:
                expected = normalized_scope.get(str(scope_ns))
                if expected is not None:
                    if not isinstance(scope_prop, str):
                        continue
                    scope_schema = self._catalog.find_property(self.object_id, scope_prop)
                    scope_raw = self.get_raw(scope_schema.key) if scope_schema is not None else None
                    try:
                        if scope_raw is None or int(scope_raw) != expected:
                            continue
                    except ValueError:
                        continue
            for raw in self.get_all_raw(key):
                try:
                    self._append_unique(out, int(raw))
                except ValueError:
                    pass

        if ns is IdNamespace.GROUP:
            for prop in self._catalog.properties_for(self.object_id):
                semantic = self._effective_semantic(prop) or {}
                if semantic.get("kind") != "structured_reference" or semantic.get("namespace") != "group":
                    continue
                for raw in self.get_all_raw(prop.key):
                    if not raw:
                        continue
                    try:
                        if prop.type == "weighted_groups":
                            for entry in GDWeightedGroupList(raw):
                                self._append_unique(out, entry.group_id)
                        elif prop.type == "sequence":
                            for entry in GDSequenceList(raw):
                                self._append_unique(out, entry.group_id)
                        elif prop.type == "remap_list":
                            for entry in GDGroupRemapList(raw):
                                self._append_unique(out, entry.source_group)
                                self._append_unique(out, entry.target_group)
                    except (ValueError, TypeError):
                        pass
        return tuple(out)

    def memberships(self, namespace: str | IdNamespace) -> tuple[int, ...]:
        """IDs this object belongs to in a semantic namespace.

        Group membership is special because Geometry Dash stores a dotted list
        in keys such as 57/274.  Other namespaces (Enter Channel, Material,
        Trigger Channel, SFX Group, ...) use normal integer properties and are
        driven entirely by catalog semantics.
        """
        ns = normalize_namespace(namespace)
        if ns is IdNamespace.GROUP:
            return self.membership_groups()
        out: list[int] = []
        for key in self._semantic_keys(
            ns, kinds=frozenset({"membership"}), include_legacy_references=False,
        ):
            for raw in self.get_all_raw(key):
                try:
                    self._append_unique(out, int(raw))
                except ValueError:
                    pass
        return tuple(out)

    def identifiers(
        self, namespace: str | IdNamespace, *, scope: Mapping[str | IdNamespace, int] | None = None,
    ) -> tuple[int, ...]:
        """IDs defined/identified by this object rather than merely referenced."""
        ns = normalize_namespace(namespace)
        out: list[int] = []
        normalized_scope = {normalize_namespace(k).value: int(v) for k, v in (scope or {}).items()}
        for key in self._semantic_keys(
            ns, kinds=frozenset({"identifier"}), include_legacy_references=False,
        ):
            prop = self._catalog.find_property(self.object_id, key) or self._catalog.global_property(key)
            semantic = self._effective_semantic(prop) if prop is not None else None
            semantic = semantic or {}
            scope_ns = semantic.get("scope_namespace")
            scope_prop = semantic.get("scope_property")
            if normalized_scope and scope_ns:
                expected = normalized_scope.get(str(scope_ns))
                if expected is not None:
                    if not isinstance(scope_prop, str):
                        continue
                    scope_schema = self._catalog.find_property(self.object_id, scope_prop)
                    scope_raw = self.get_raw(scope_schema.key) if scope_schema is not None else None
                    try:
                        if scope_raw is None or int(scope_raw) != expected:
                            continue
                    except ValueError:
                        continue
            for raw in self.get_all_raw(key):
                try:
                    self._append_unique(out, int(raw))
                except ValueError:
                    pass
        return tuple(out)

    def reference_details(self, namespace: str | IdNamespace | None = None) -> list[dict[str, Any]]:
        """Return JSON-serializable evidence for semantic ID references.

        This is intentionally descriptive rather than a control-flow model.
        Structured group references are expanded so an agent can see which
        property produced each relationship without parsing raw tokens.
        """
        namespaces = [normalize_namespace(namespace)] if namespace is not None else list(IdNamespace)
        details: list[dict[str, Any]] = []
        for ns in namespaces:
            for key in self._semantic_keys(ns, kinds=frozenset({"reference"})):
                prop = self._catalog.find_property(self.object_id, key) or self._catalog.global_property(key)
                for occurrence, raw in enumerate(self.get_all_raw(key)):
                    try:
                        value = int(raw)
                    except ValueError:
                        continue
                    detail = {
                        "namespace": ns.value,
                        "kind": "reference",
                        "key": key,
                        "property": None if prop is None else prop.name,
                        "value": value,
                        "occurrence": occurrence,
                    }
                    semantic = self._effective_semantic(prop) if prop is not None else None
                    semantic = semantic or {}
                    scope_ns = semantic.get("scope_namespace")
                    scope_prop = semantic.get("scope_property")
                    if isinstance(scope_ns, str) and isinstance(scope_prop, str):
                        scope_schema = self._catalog.find_property(self.object_id, scope_prop)
                        scope_raw = self.get_raw(scope_schema.key) if scope_schema is not None else None
                        try:
                            if scope_raw is not None:
                                detail["scope"] = {
                                    "namespace": scope_ns,
                                    "property": scope_prop,
                                    "value": int(scope_raw),
                                }
                        except ValueError:
                            pass
                    details.append(detail)

            if ns is not IdNamespace.GROUP:
                continue
            for prop in self._catalog.properties_for(self.object_id):
                semantic = self._effective_semantic(prop) or {}
                if semantic.get("kind") != "structured_reference" or semantic.get("namespace") != "group":
                    continue
                for occurrence, raw in enumerate(self.get_all_raw(prop.key)):
                    if not raw:
                        continue
                    try:
                        if prop.type == "weighted_groups":
                            for index, entry in enumerate(GDWeightedGroupList(raw)):
                                details.append({
                                    "namespace": "group", "kind": "structured_reference",
                                    "key": prop.key, "property": prop.name, "value": entry.group_id,
                                    "occurrence": occurrence, "index": index, "role": "group",
                                })
                        elif prop.type == "sequence":
                            for index, entry in enumerate(GDSequenceList(raw)):
                                details.append({
                                    "namespace": "group", "kind": "structured_reference",
                                    "key": prop.key, "property": prop.name, "value": entry.group_id,
                                    "occurrence": occurrence, "index": index, "role": "group",
                                })
                        elif prop.type == "remap_list":
                            for index, entry in enumerate(GDGroupRemapList(raw)):
                                details.extend([
                                    {
                                        "namespace": "group", "kind": "structured_reference",
                                        "key": prop.key, "property": prop.name, "value": entry.source_group,
                                        "occurrence": occurrence, "index": index, "role": "source",
                                    },
                                    {
                                        "namespace": "group", "kind": "structured_reference",
                                        "key": prop.key, "property": prop.name, "value": entry.target_group,
                                        "occurrence": occurrence, "index": index, "role": "target",
                                    },
                                ])
                    except (ValueError, TypeError):
                        pass
        return details

    def identifier_details(self, namespace: str | IdNamespace | None = None) -> list[dict[str, Any]]:
        """Return evidence for IDs defined by this object, including scoped-ID context."""
        namespaces = [normalize_namespace(namespace)] if namespace is not None else list(IdNamespace)
        details: list[dict[str, Any]] = []
        for ns in namespaces:
            for key in self._semantic_keys(
                ns, kinds=frozenset({"identifier"}), include_legacy_references=False,
            ):
                prop = self._catalog.find_property(self.object_id, key) or self._catalog.global_property(key)
                semantic = self._effective_semantic(prop) if prop is not None else None
                semantic = semantic or {}
                for occurrence, raw in enumerate(self.get_all_raw(key)):
                    try:
                        value = int(raw)
                    except ValueError:
                        continue
                    detail: dict[str, Any] = {
                        "namespace": ns.value,
                        "kind": "identifier",
                        "key": key,
                        "property": None if prop is None else prop.name,
                        "value": value,
                        "occurrence": occurrence,
                    }
                    scope_ns = semantic.get("scope_namespace")
                    scope_prop = semantic.get("scope_property")
                    if isinstance(scope_ns, str) and isinstance(scope_prop, str):
                        scope_schema = self._catalog.find_property(self.object_id, scope_prop)
                        scope_raw = self.get_raw(scope_schema.key) if scope_schema is not None else None
                        try:
                            if scope_raw is not None:
                                detail["scope"] = {
                                    "namespace": scope_ns,
                                    "property": scope_prop,
                                    "value": int(scope_raw),
                                }
                        except ValueError:
                            pass
                    details.append(detail)
        return details

    def group_references(self) -> tuple[int, ...]:
        return self.references(IdNamespace.GROUP)

    def item_references(self) -> tuple[int, ...]:
        return self.references(IdNamespace.ITEM)

    def control_references(self) -> tuple[int, ...]:
        return self.references(IdNamespace.CONTROL)

    def color_references(self) -> tuple[int, ...]:
        return self.references(IdNamespace.COLOR)

    def block_references(self) -> tuple[int, ...]:
        return self.references(IdNamespace.BLOCK)

    def _rewrite_key_values(self, key: int, transform) -> bool:
        changed = False
        token = str(key)
        for index, (raw_key, raw_value) in enumerate(self._pairs):
            if not _same_key(raw_key, token):
                continue
            new_value = transform(raw_value)
            if new_value is not None and new_value != raw_value:
                self._pairs[index] = (raw_key, new_value)
                changed = True
        if changed:
            self._mark_dirty()
        return changed

    def remap(
        self, namespace: str | IdNamespace, mapping: Mapping[int, int], *,
        memberships: bool = True, references: bool = True, identifiers: bool = True,
    ) -> "GDObject":
        ns = normalize_namespace(namespace)
        normalized = validate_mapping(ns, mapping)
        if not normalized:
            return self

        if ns is IdNamespace.GROUP and memberships:
            for key in self._membership_keys():
                def map_groups(raw: str) -> str | None:
                    if raw == "":
                        return raw
                    try:
                        before = [int(v) for v in raw.split(".")]
                    except ValueError:
                        return None
                    after = list(dict.fromkeys(normalized.get(v, v) for v in before))
                    return ".".join(map(str, after))
                self._rewrite_key_values(key, map_groups)

        kinds: set[str] = set()
        if memberships:
            kinds.add("membership")
        if references:
            kinds.add("reference")
        if identifiers:
            kinds.add("identifier")
        if kinds:
            for key in self._semantic_keys(ns, kinds=frozenset(kinds)):
                def map_single(raw: str) -> str | None:
                    try:
                        value = int(raw)
                    except ValueError:
                        return None
                    return str(normalized.get(value, value))
                self._rewrite_key_values(key, map_single)

        if ns is IdNamespace.GROUP and references:
            for prop in self._catalog.properties_for(self.object_id):
                semantic = self._effective_semantic(prop) or {}
                if semantic.get("kind") != "structured_reference" or semantic.get("namespace") != "group":
                    continue

                def map_structured(raw: str, kind=prop.type) -> str | None:
                    if raw == "":
                        return raw
                    try:
                        if kind == "weighted_groups":
                            value = GDWeightedGroupList(raw)
                            for i, entry in enumerate(list(value)):
                                value.set(i, group_id=normalized.get(entry.group_id, entry.group_id))
                        elif kind == "sequence":
                            value = GDSequenceList(raw)
                            for i, entry in enumerate(list(value)):
                                value.set(i, group_id=normalized.get(entry.group_id, entry.group_id))
                        elif kind == "remap_list":
                            value = GDGroupRemapList(raw)
                            for i, entry in enumerate(list(value)):
                                value.set(
                                    i,
                                    source_group=normalized.get(entry.source_group, entry.source_group),
                                    target_group=normalized.get(entry.target_group, entry.target_group),
                                )
                        else:
                            return None
                        return value.to_raw_string()
                    except (ValueError, TypeError):
                        return None

                self._rewrite_key_values(prop.key, map_structured)
        return self

    def remap_groups(self, mapping: Mapping[int, int], **kwargs) -> "GDObject":
        return self.remap(IdNamespace.GROUP, mapping, **kwargs)

    def remap_items(self, mapping: Mapping[int, int]) -> "GDObject":
        return self.remap(IdNamespace.ITEM, mapping)

    def remap_controls(self, mapping: Mapping[int, int]) -> "GDObject":
        return self.remap(IdNamespace.CONTROL, mapping)

    def remap_colors(self, mapping: Mapping[int, int]) -> "GDObject":
        return self.remap(IdNamespace.COLOR, mapping)

    def remap_blocks(self, mapping: Mapping[int, int]) -> "GDObject":
        return self.remap(IdNamespace.BLOCK, mapping)

    # ---------------- structured inspection ----------------

    def explain(self) -> dict[str, Any]:
        oid = self.object_id
        object_schema = self._catalog.get_object(oid)
        totals = Counter(k for k, _ in self._pairs)
        seen: Counter[str] = Counter()
        properties: list[dict[str, Any]] = []
        unknown: list[list[str]] = []
        for raw_key, raw in self._pairs:
            seen[raw_key] += 1
            numeric = _numeric_key(raw_key)
            schema = self._catalog.find_property(oid, numeric) if numeric is not None else None
            if schema is None and numeric is not None:
                schema = self._catalog.global_property(numeric)
            entry: dict[str, Any] = {
                "key": numeric if numeric is not None else raw_key,
                "raw_key": raw_key,
                "raw": raw,
                "occurrence": seen[raw_key] - 1,
            }
            if schema is None:
                entry["known"] = False
                entry["value"] = raw
                unknown.append([raw_key, raw])
            else:
                entry.update({
                    "known": True,
                    "name": schema.name,
                    "wire_type": schema.wire_type,
                    "type": schema.type,
                    "confidence": schema.confidence,
                    "sources": list(schema.sources),
                })
                semantic = self._effective_semantic(schema)
                if semantic is not None:
                    entry["semantic"] = dict(semantic)
                if schema.variants:
                    entry["semantic_variant"] = True
                if schema.constraints is not None:
                    entry["constraints"] = dict(schema.constraints)
                try:
                    value = decode_property(
                        schema, raw, catalog=self._catalog, semantic=semantic,
                    )
                    if isinstance(value, GDReal):
                        entry["value"] = value.raw
                        entry["numeric"] = True
                    elif isinstance(value, (tuple, list)):
                        entry["value"] = [int(v) if isinstance(v, int) else v for v in value]
                    elif hasattr(value, "to_raw_string"):
                        entry["value"] = value.to_raw_string()
                    else:
                        entry["value"] = value
                except Exception:
                    entry["value"] = raw
                    entry["decode_error"] = True
                if schema.enum and isinstance(entry.get("value"), int):
                    enum_name = self._catalog.enum_name(schema.enum, int(entry["value"]))
                    if enum_name is not None:
                        entry["enum_name"] = enum_name
            properties.append(entry)
        known_object = self._catalog.known_object(oid) or {}
        cpp_class = object_schema.cpp_class if object_schema else known_object.get("cpp_class")
        confidence = object_schema.confidence if object_schema else known_object.get("confidence", "unknown")
        result = {
            "uid": self._uid,
            "object_id": oid,
            "name": object_schema.name if object_schema else self.object_name,
            "class": type(self).__name__,
            "cpp_class": cpp_class,
            "schema_status": object_schema.schema_status if object_schema else "raw_only",
            "confidence": confidence,
            "properties": properties,
            "unknown": unknown,
            "malformed_tail": self._malformed_tail,
        }
        if not object_schema and known_object:
            if known_object.get("sources"):
                result["implementation_sources"] = list(known_object["sources"])
            if known_object.get("implementation_evidence"):
                result["implementation_evidence"] = dict(known_object["implementation_evidence"])
        return result

    def to_raw_json(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "pairs": [[k, v] for k, v in self._pairs],
            **({"malformed_tail": self._malformed_tail} if self._malformed_tail is not None else {}),
        }
