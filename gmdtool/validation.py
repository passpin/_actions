from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Iterable, TYPE_CHECKING

from .codecs import decode_property
from .catalog import PropertySchema
from .ids import IdNamespace
from .numeric import GDReal
from .structured import GDParticleSettings

if TYPE_CHECKING:
    from .level import GDLevel
    from .object import GDObject


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    object_index: int | None = None
    object_id: int | None = None
    key: int | str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ValidationError(ValueError):
    def __init__(self, report: "ValidationReport") -> None:
        self.report = report
        super().__init__(report.to_text())


class ValidationReport:
    def __init__(self, issues: Iterable[ValidationIssue] = ()) -> None:
        self.issues = tuple(issues)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors

    def __bool__(self) -> bool:
        return self.ok

    def raise_for_errors(self) -> "ValidationReport":
        if not self.ok:
            raise ValidationError(self)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "issues": [i.to_dict() for i in self.issues],
        }

    def to_text(self, *, limit: int = 50) -> str:
        lines = [f"{'valid' if self.ok else 'invalid'}: {len(self.errors)} errors, {len(self.warnings)} warnings"]
        for issue in self.issues[:limit]:
            location = ""
            if issue.object_index is not None:
                location += f" object[{issue.object_index}]"
            if issue.object_id is not None:
                location += f" OBJ_{issue.object_id}"
            if issue.key is not None:
                location += f" key={issue.key}"
            lines.append(f"{issue.severity} {issue.code}{location}: {issue.message}")
        if len(self.issues) > limit:
            lines.append(f"... {len(self.issues) - limit} more")
        return "\n".join(lines)


_PARTICLE_BOOL_FIELDS = {53, 54, 55, 56, 58, 63, 64, 65, 66, 67}
_PARTICLE_INT_FIELDS = {0, 51, 52, 57}


def _numeric_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, GDReal):
        return value.decimal
    if isinstance(value, int):
        return Decimal(int(value))
    return None


def _constraint_issues(
    obj: "GDObject", index: int, schema: PropertySchema, decoded: Any,
) -> list[ValidationIssue]:
    constraints = schema.constraints or {}
    if not constraints:
        return []
    value = _numeric_decimal(decoded)
    if value is None:
        return []

    out: list[ValidationIssue] = []
    for name, relation, code in (
        ("min", "below", "property-below-minimum"),
        ("max", "above", "property-above-maximum"),
    ):
        if name not in constraints:
            continue
        limit = Decimal(str(constraints[name]))
        violated = value < limit if name == "min" else value > limit
        if violated:
            out.append(ValidationIssue(
                "error", code,
                f"{schema.name}={decoded} is {relation} {name}imum {constraints[name]}",
                index, obj.object_id, schema.key,
            ))
    return out


def _behavior_issues(obj: "GDObject", index: int) -> list[ValidationIssue]:
    out: list[ValidationIssue] = []

    def add(severity: str, code: str, message: str, key=None):
        out.append(ValidationIssue(severity, code, message, index, obj.object_id, key))

    def int_value(key: int):
        raw = obj.get_raw(key)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def real_value(key: int):
        raw = obj.get_raw(key)
        if raw is None:
            return None
        try:
            return GDReal(raw)
        except ValueError:
            return None

    def true(key: int) -> bool:
        return obj.get_raw(key) == "1"

    for key, label in ((10, "duration"), (574, "respawn_time")):
        value = real_value(key)
        if value is not None and value < GDReal("0"):
            add("error", "negative-time", f"{label} cannot be negative ({value})", key)

    if obj.object_id == 901 and true(100) and not int_value(71):
        add("warning", "move-target-without-position", "use_target requires a target-position group", 71)
    if obj.object_id in {3016, 3660} and true(306) and true(307):
        add("warning", "advanced-follow-axis-conflict", "x_only and y_only are both enabled", 306)
    if obj.object_id == 1616 and true(535) and not int_value(51):
        add("warning", "stop-without-control-id", "Control target is unset/zero", 51)
    if obj.object_id == 3607 and obj.get_raw(435) == "":
        add("warning", "empty-sequence", "Sequence has no entries", 435)

    schema = obj.catalog.get_object(obj.object_id)
    if schema is not None and "shader" in schema.tags:
        z_min, z_max = int_value(196), int_value(197)
        if z_min is not None and z_max is not None and z_min > z_max:
            add("warning", "shader-layer-range-reversed", f"Minimum layer {z_min} exceeds maximum {z_max}", 196)
    return out


def validate_level(level: "GDLevel", *, check_references: bool = False) -> ValidationReport:
    issues: list[ValidationIssue] = []
    memberships = {gid for obj in level._objects for gid in obj.membership_groups()}

    for index, obj in enumerate(level._objects):
        def add(severity: str, code: str, message: str, key=None):
            issues.append(ValidationIssue(severity, code, message, index, obj.object_id, key))

        raw_ids = obj.get_all_raw(1)
        if not raw_ids:
            add("error", "missing-object-id", "Object has no property 1", 1)
        else:
            active = obj.object_id
            if active is None:
                add("error", "invalid-object-id", "Property 1 is not an integer", 1)
            else:
                for raw in raw_ids:
                    try:
                        value = int(raw)
                    except ValueError:
                        add("error", "invalid-object-id", f"Object ID token {raw!r} is not an integer", 1)
                        continue
                    if value != active:
                        add("error", "object-id-mismatch", f"Duplicate object ID {value} disagrees with active ID {active}", 1)

        for pair in obj.raw_pairs:
            try:
                key = int(pair.key)
            except ValueError:
                continue
            schema = level.catalog.find_property(obj.object_id, key)
            if schema is None:
                continue
            try:
                decoded = decode_property(schema, pair.value, catalog=level.catalog)
                if isinstance(decoded, GDParticleSettings) and pair.value != "":
                    if len(decoded.raw_tokens) < len(decoded.FIELD_NAMES):
                        raise ValueError(
                            f"Particle string has {len(decoded.raw_tokens)} values; expected at least {len(decoded.FIELD_NAMES)}"
                        )
                    for field in range(len(decoded.FIELD_NAMES)):
                        token = decoded.raw_tokens[field]
                        if field in _PARTICLE_BOOL_FIELDS:
                            if token not in {"0", "1"}:
                                raise ValueError(f"Particle bool field {field} must be 0 or 1")
                        elif field in _PARTICLE_INT_FIELDS:
                            int(token)
                        else:
                            GDReal(token)
                issues.extend(_constraint_issues(obj, index, schema, decoded))
            except (ValueError, TypeError, OverflowError, ArithmeticError, UnicodeError) as exc:
                add("error", "invalid-property", f"{schema.name}: {exc}", key)

        for ns in IdNamespace:
            for ident in obj.references(ns):
                if ident < 0:
                    add("error", f"invalid-{ns.value}-id", f"Negative {ns.value} ID {ident}")
                if ns is IdNamespace.GROUP and ident > 9999:
                    add("error", "group-id-out-of-range", f"Group {ident} exceeds 9999")
                if ns is IdNamespace.GROUP and check_references and ident != 0 and ident not in memberships:
                    add("warning", "dangling-group-reference", f"Group {ident} has no known member")
            for ident in obj.identifiers(ns):
                if ident < 0:
                    add("error", f"invalid-{ns.value}-id", f"Negative {ns.value} identifier {ident}")

        for ident in obj.membership_groups():
            if ident < 0 or ident > 9999:
                add("error", "group-id-out-of-range", f"Membership group {ident} outside 0..9999", 57)

        issues.extend(_behavior_issues(obj, index))

    raw_count = level.metadata.get("k48")
    if raw_count is not None:
        try:
            count = int(raw_count)
        except ValueError:
            issues.append(ValidationIssue("warning", "invalid-object-count", f"Metadata k48={raw_count!r}", key="k48"))
        else:
            if count != len(level._objects):
                issues.append(ValidationIssue("warning", "object-count-mismatch", f"Metadata k48={count}, actual={len(level._objects)}", key="k48"))

    return ValidationReport(issues)
