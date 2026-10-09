from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, Iterator, TypeVar

from .numeric import GDReal


@dataclass(frozen=True)
class GDWeightedGroup:
    group_id: int
    weight: int


@dataclass(frozen=True)
class GDSequenceEntry:
    group_id: int
    count: int


@dataclass(frozen=True)
class GDGroupRemap:
    source_group: int
    target_group: int


T = TypeVar("T")


def _integral(value: Any, *, label: str = "value") -> int:
    if isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    try:
        return GDReal.from_value(value).to_integer_exact()
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError(f"{label} must be an integer, got {value!r}") from exc


class _IntegerPairList(Generic[T]):
    def __init__(
        self, raw: str, factory: Callable[[int, int], T],
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        self._tokens = [] if raw == "" else raw.split(".")
        if len(self._tokens) % 2:
            raise ValueError("Structured GD pair list has an odd token count")
        for token in self._tokens:
            int(token)
        self._factory = factory
        self._on_change = on_change

    @property
    def raw_tokens(self) -> tuple[str, ...]:
        return tuple(self._tokens)

    def __len__(self) -> int:
        return len(self._tokens) // 2

    def __iter__(self) -> Iterator[T]:
        for i in range(len(self)):
            yield self[i]

    def __getitem__(self, index: int) -> T:
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        offset = index * 2
        return self._factory(int(self._tokens[offset]), int(self._tokens[offset + 1]))

    def _commit(self, previous: list[str]) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(self.to_raw_string())
        except Exception:
            self._tokens[:] = previous
            raise

    def _append_pair(self, first: int, second: int) -> None:
        previous = list(self._tokens)
        self._tokens.extend((str(first), str(second)))
        self._commit(previous)

    def _set_pair(self, index: int, first: int | None, second: int | None) -> None:
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        previous = list(self._tokens)
        offset = index * 2
        if first is not None:
            self._tokens[offset] = str(first)
        if second is not None:
            self._tokens[offset + 1] = str(second)
        if self._tokens != previous:
            self._commit(previous)

    def remove_at(self, index: int) -> None:
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        previous = list(self._tokens)
        del self._tokens[index * 2:index * 2 + 2]
        self._commit(previous)

    def to_raw_string(self) -> str:
        return ".".join(self._tokens)

    def __str__(self) -> str:
        return self.to_raw_string()


class GDWeightedGroupList(_IntegerPairList[GDWeightedGroup]):
    def __init__(self, raw: str, on_change: Callable[[str], None] | None = None):
        super().__init__(raw, GDWeightedGroup, on_change)

    def append(self, group_id: int, weight: Any) -> "GDWeightedGroupList":
        self._append_pair(int(group_id), _integral(weight, label="weight"))
        return self

    def set(self, index: int, *, group_id: int | None = None, weight: Any | None = None) -> "GDWeightedGroupList":
        self._set_pair(index, group_id, None if weight is None else _integral(weight, label="weight"))
        return self


class GDSequenceList(_IntegerPairList[GDSequenceEntry]):
    def __init__(self, raw: str, on_change: Callable[[str], None] | None = None):
        super().__init__(raw, GDSequenceEntry, on_change)

    def append(self, group_id: int, count: Any) -> "GDSequenceList":
        self._append_pair(int(group_id), _integral(count, label="count"))
        return self

    def set(self, index: int, *, group_id: int | None = None, count: Any | None = None) -> "GDSequenceList":
        self._set_pair(index, group_id, None if count is None else _integral(count, label="count"))
        return self


class GDGroupRemapList(_IntegerPairList[GDGroupRemap]):
    def __init__(self, raw: str, on_change: Callable[[str], None] | None = None):
        super().__init__(raw, GDGroupRemap, on_change)

    def append(self, source_group: int, target_group: int) -> "GDGroupRemapList":
        self._append_pair(int(source_group), int(target_group))
        return self

    def set(
        self, index: int, *, source_group: int | None = None,
        target_group: int | None = None,
    ) -> "GDGroupRemapList":
        self._set_pair(index, source_group, target_group)
        return self


_PARTICLE_FIELD_NAMES = (
    "max_particles", "duration", "lifetime", "lifetime_pm", "emission", "angle", "angle_pm",
    "speed", "speed_pm", "posvar_x", "posvar_y", "gravity_x", "gravity_y", "accel_rad",
    "accel_rad_pm", "accel_tan", "accel_tan_pm", "start_size", "start_size_pm", "start_spin",
    "start_spin_pm", "start_r", "start_r_pm", "start_g", "start_g_pm", "start_b", "start_b_pm",
    "start_a", "start_a_pm", "end_size", "end_size_pm", "end_spin", "end_spin_pm", "end_r",
    "end_r_pm", "end_g", "end_g_pm", "end_b", "end_b_pm", "end_a", "end_a_pm", "fade_in",
    "fade_in_pm", "fade_out", "fade_out_pm", "start_rad", "start_rad_pm", "end_rad", "end_rad_pm",
    "rot_sec", "rot_sec_pm", "mode", "mode_2", "additive", "start_spin_equals_end",
    "start_rot_is_dir", "dynamic_rotation", "texture", "uniform_obj_color", "friction_p",
    "friction_p_pm", "respawn", "respawn_pm", "order_sensitive", "start_size_equals_end",
    "start_rad_equals_end", "start_rgb_var_sync", "end_rgb_var_sync", "friction_s", "friction_s_pm",
    "friction_r", "friction_r_pm",
)
_PARTICLE_INT_FIELDS = {0, 51, 52, 57}
_PARTICLE_BOOL_FIELDS = {53, 54, 55, 56, 58, 63, 64, 65, 66, 67}


class GDParticleSettings:
    FIELD_NAMES = _PARTICLE_FIELD_NAMES

    def __init__(self, raw: str, on_change: Callable[[str], None] | None = None):
        self._tokens = [] if raw == "" else raw.split("a")
        self._on_change = on_change

    @property
    def raw_tokens(self) -> tuple[str, ...]:
        return tuple(self._tokens)

    @property
    def extra_tokens(self) -> tuple[str, ...]:
        return tuple(self._tokens[len(self.FIELD_NAMES):])

    @classmethod
    def index(cls, name: str) -> int:
        try:
            return cls.FIELD_NAMES.index(name)
        except ValueError as exc:
            raise KeyError(name) from exc

    def get(self, field: str | int) -> Any:
        index = self.index(field) if isinstance(field, str) else field
        if index < 0:
            raise IndexError(index)
        if index >= len(self._tokens):
            return None
        token = self._tokens[index]
        if index in _PARTICLE_BOOL_FIELDS:
            if token not in {"0", "1"}:
                return token
            return token == "1"
        if index in _PARTICLE_INT_FIELDS:
            try:
                return int(token)
            except ValueError:
                return token
        try:
            return GDReal(token)
        except ValueError:
            return token

    def set(self, field: str | int, value: Any) -> "GDParticleSettings":
        index = self.index(field) if isinstance(field, str) else field
        if index < 0:
            raise IndexError(index)
        if index in _PARTICLE_BOOL_FIELDS:
            if not isinstance(value, bool):
                raise TypeError("particle boolean field expects bool")
            raw = "1" if value else "0"
        elif index in _PARTICLE_INT_FIELDS:
            raw = str(_integral(value))
        else:
            raw = GDReal.from_value(value).raw
        previous = list(self._tokens)
        while len(self._tokens) <= index:
            self._tokens.append("0")
        self._tokens[index] = raw
        if self._tokens != previous and self._on_change is not None:
            try:
                self._on_change(self.to_raw_string())
            except Exception:
                self._tokens[:] = previous
                raise
        return self

    def as_dict(self) -> dict[str, Any]:
        return {name: self.get(i) for i, name in enumerate(self.FIELD_NAMES[:len(self._tokens)])}

    def to_raw_string(self) -> str:
        return "a".join(self._tokens)

    def __str__(self) -> str:
        return self.to_raw_string()
