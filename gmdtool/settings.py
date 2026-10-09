from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .numeric import GDReal

if TYPE_CHECKING:
    from .level import GDLevel


LEVEL_SETTING_FIELDS: dict[str, tuple[str, str]] = {
    "audio_track": ("kA1", "int"),
    "gamemode": ("kA2", "int"),
    "mini": ("kA3", "bool"),
    "speed": ("kA4", "int"),
    "background": ("kA6", "int"),
    "ground": ("kA7", "int"),
    "dual": ("kA8", "bool"),
    "is_start_position": ("kA9", "bool"),
    "two_player": ("kA10", "bool"),
    "flip_gravity": ("kA11", "bool"),
    "song_offset": ("kA13", "real"),
    "guidelines": ("kA14", "raw"),
    "fade_in": ("kA15", "bool"),
    "fade_out": ("kA16", "bool"),
    "ground_line": ("kA17", "int"),
    "font": ("kA18", "int"),
    "reverse_gameplay": ("kA20", "bool"),
    "platformer": ("kA22", "bool"),
    "middleground": ("kA25", "int"),
    "allow_multi_rotation": ("kA27", "bool"),
    "mirror": ("kA28", "bool"),
    "rotate_gameplay": ("kA29", "bool"),
    "allow_static_rotate": ("kA41", "bool"),
    "reverse_sync": ("kA42", "bool"),
    "no_time_penalty": ("kA43", "bool"),
    "decrease_boost_slide": ("kA45", "bool"),
    "colors": ("kS38", "raw"),
    "color_page": ("kS39", "int"),
}
_BY_KEY = {key: (name, kind) for name, (key, kind) in LEVEL_SETTING_FIELDS.items()}


def _decode(kind: str, raw: str) -> Any:
    try:
        if kind == "int":
            return int(raw)
        if kind == "real":
            return GDReal(raw)
        if kind == "bool":
            if raw not in {"0", "1"}:
                raise ValueError
            return raw == "1"
    except (ValueError, TypeError):
        return raw
    return raw


def _encode(kind: str, value: Any) -> str:
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("setting expects int")
        return str(value)
    if kind == "real":
        return GDReal.from_value(value).raw
    if kind == "bool":
        if not isinstance(value, bool):
            raise TypeError("setting expects bool")
        return "1" if value else "0"
    if not isinstance(value, str):
        raise TypeError("raw setting expects str")
    return value


def _split_header(header: str) -> tuple[list[tuple[str, str]], str | None]:
    if header == "":
        return [], None
    tokens = header.split(",")
    pairs = [(tokens[i], tokens[i + 1]) for i in range(0, len(tokens) - 1, 2)]
    tail = tokens[-1] if len(tokens) % 2 else None
    return pairs, tail


class GDLevelSettings:
    """Typed/raw view over the level-start header without owning separate state."""

    def __init__(self, level: "GDLevel") -> None:
        object.__setattr__(self, "_level", level)

    @property
    def raw_pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple(_split_header(self._level.header)[0])

    @property
    def malformed_tail(self) -> str | None:
        return _split_header(self._level.header)[1]

    def get_raw(self, key: str, default: str | None = None, *, occurrence: str | int = "last") -> str | None:
        pairs, _ = _split_header(self._level.header)
        values = [v for k, v in pairs if k == key]
        if not values:
            return default
        if occurrence == "last":
            return values[-1]
        if occurrence == "first":
            return values[0]
        if isinstance(occurrence, int) and not isinstance(occurrence, bool):
            try:
                return values[occurrence]
            except IndexError:
                return default
        raise ValueError("occurrence must be 'first', 'last', or int")

    def get_all_raw(self, key: str) -> tuple[str, ...]:
        pairs, _ = _split_header(self._level.header)
        return tuple(v for k, v in pairs if k == key)

    def _write(self, pairs: list[tuple[str, str]], tail: str | None) -> None:
        tokens = [token for pair in pairs for token in pair]
        if tail is not None:
            tokens.append(tail)
        self._level.header = ",".join(tokens)

    def set_raw(self, key: str, value: str) -> "GDLevelSettings":
        if not key or any(c in key for c in ",;") or any(c in value for c in ",;"):
            raise ValueError("header key/value contains delimiter")
        pairs, tail = _split_header(self._level.header)
        for i in range(len(pairs) - 1, -1, -1):
            if pairs[i][0] == key:
                pairs[i] = (key, value)
                self._write(pairs, tail)
                return self
        pairs.append((key, value))
        self._write(pairs, tail)
        return self

    def append_raw(self, key: str, value: str) -> "GDLevelSettings":
        pairs, tail = _split_header(self._level.header)
        pairs.append((key, value))
        self._write(pairs, tail)
        return self

    def remove_raw(self, key: str) -> "GDLevelSettings":
        pairs, tail = _split_header(self._level.header)
        new = [p for p in pairs if p[0] != key]
        if new != pairs:
            self._write(new, tail)
        return self

    def get(self, name_or_key: str, default: Any = None) -> Any:
        key, kind = LEVEL_SETTING_FIELDS.get(name_or_key, (name_or_key, _BY_KEY.get(name_or_key, ("", "raw"))[1]))
        raw = self.get_raw(key)
        return default if raw is None else _decode(kind, raw)

    def set(self, name_or_key: str, value: Any) -> "GDLevelSettings":
        key, kind = LEVEL_SETTING_FIELDS.get(name_or_key, (name_or_key, _BY_KEY.get(name_or_key, ("", "raw"))[1]))
        if value is None:
            return self.remove_raw(key)
        return self.set_raw(key, _encode(kind, value))

    def __getattr__(self, name: str) -> Any:
        if name in LEVEL_SETTING_FIELDS:
            return self.get(name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        elif name in LEVEL_SETTING_FIELDS:
            self.set(name, value)
        else:
            raise AttributeError(name)

    def as_dict(self, *, semantic_names: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, raw in self.raw_pairs:
            if semantic_names and key in _BY_KEY:
                name, kind = _BY_KEY[key]
                out[name] = _decode(kind, raw)
            else:
                out[key] = raw
        return out
