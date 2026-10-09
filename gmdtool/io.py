from __future__ import annotations

import base64
import gzip
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .catalog import Catalog, default_catalog
from .level import GDLevel


def _decode_level(encoded: str) -> str:
    normalized = "".join(encoded.split())
    padding = "=" * ((4 - len(normalized) % 4) % 4)
    compressed = base64.urlsafe_b64decode(normalized + padding)
    return gzip.decompress(compressed).decode("utf-8")


def _encode_level(raw: str) -> str:
    compressed = gzip.compress(raw.encode("utf-8"), compresslevel=9, mtime=0)
    return base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")


def _atomic_write(path: str | Path, data: bytes) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists():
            try:
                os.chmod(temp_name, target.stat().st_mode & 0o7777)
            except OSError:
                pass
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _plist_dict(root: ET.Element) -> ET.Element:
    if root.tag == "dict":
        return root
    dictionary = root.find("dict")
    if dictionary is None:
        raise ValueError(".gmd has no plist <dict>")
    return dictionary


def _read_metadata(dictionary: ET.Element) -> tuple[dict[str, str], dict[str, str]]:
    children = list(dictionary)
    if len(children) % 2:
        raise ValueError("Unpaired plist key/value")
    metadata: dict[str, str] = {}
    tags: dict[str, str] = {}
    for i in range(0, len(children), 2):
        key_node, value_node = children[i], children[i + 1]
        if key_node.tag not in {"k", "key"}:
            raise ValueError(f"Expected plist key node, got <{key_node.tag}>")
        key = key_node.text or ""
        if key in metadata:
            raise ValueError(f"Duplicate plist key {key!r}")
        if value_node.tag == "t":
            value = "1"
        elif value_node.tag == "f":
            value = "0"
        else:
            value = value_node.text or ""
        metadata[key] = value
        tags[key] = value_node.tag
    return metadata, tags


def _serialize_dirty(level: GDLevel) -> tuple[bytes, str]:
    encoded = _encode_level(level.to_level_string())
    actual_count = str(len(level._objects))

    if level._source_xml is not None:
        root = ET.fromstring(level._source_xml)
    else:
        root = ET.Element("plist", {"version": "1.0", "gjver": "2.0"})
        ET.SubElement(root, "dict")
    dictionary = _plist_dict(root)

    # k4 and k48 are managed by the serializer, not caller metadata.
    desired = dict(level.metadata)
    desired["k4"] = encoded
    desired["k48"] = actual_count

    children = list(dictionary)
    seen: set[str] = set()
    i = 0
    while i + 1 < len(children):
        key_node, value_node = children[i], children[i + 1]
        key = key_node.text or ""
        seen.add(key)
        if key not in desired:
            dictionary.remove(key_node)
            dictionary.remove(value_node)
            i += 2
            continue
        value = desired[key]
        if key == "k4":
            value_node.tag = "s"
            value_node.text = value
        elif key == "k48":
            value_node.tag = "i"
            value_node.text = value
        elif level._original_metadata.get(key) != value:
            # Editing t/f as a free-form metadata string is ambiguous; promote
            # changed opaque metadata to <s> rather than silently keeping bool tags.
            if value_node.tag in {"t", "f"}:
                value_node.tag = "s"
            value_node.text = value
        i += 2

    for key, value in desired.items():
        if key in seen:
            continue
        key_node = ET.SubElement(dictionary, "k")
        key_node.text = key
        tag = "i" if key == "k48" else "s"
        value_node = ET.SubElement(dictionary, tag)
        value_node.text = value

    body = ET.tostring(root, encoding="utf-8", short_empty_elements=True)
    had_decl = level._source_xml is None or level._source_xml.lstrip().startswith("<?xml")
    if had_decl:
        body = b'<?xml version="1.0"?>' + body
    if level._source_had_bom:
        body = b"\xef\xbb\xbf" + body
    return body, encoded


class GMD:
    """Geometry Dash `.gmd` container IO."""

    @staticmethod
    def load(path: str | Path, *, catalog: Catalog | None = None) -> GDLevel:
        return GMD.load_bytes(Path(path).read_bytes(), catalog=catalog)

    @staticmethod
    def load_bytes(data: bytes, *, catalog: Catalog | None = None) -> GDLevel:
        had_bom = data.startswith(b"\xef\xbb\xbf")
        xml_bytes = data[3:] if had_bom else data
        source_xml = xml_bytes.decode("utf-8")
        root = ET.fromstring(source_xml)
        dictionary = _plist_dict(root)
        metadata, tags = _read_metadata(dictionary)
        try:
            encoded = metadata["k4"]
        except KeyError as exc:
            raise ValueError(".gmd contains no k4 level data") from exc
        raw = _decode_level(encoded)
        level = GDLevel.parse(raw, catalog=catalog or default_catalog())
        level.metadata.update(metadata)
        level._set_source(
            source_bytes=data,
            source_xml=source_xml,
            metadata_tags=tags,
            had_bom=had_bom,
        )
        return level

    @staticmethod
    def save(
        level: GDLevel,
        path: str | Path,
        *,
        validate: bool = False,
        check_references: bool = False,
    ) -> None:
        if validate:
            level.validate(check_references=check_references).raise_for_errors()
        if level.can_save_original and level._source_bytes is not None:
            _atomic_write(path, level._source_bytes)
            return
        data, encoded = _serialize_dirty(level)
        _atomic_write(path, data)

        # Re-read the just-produced XML metadata so in-memory state mirrors disk.
        xml_bytes = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
        xml = xml_bytes.decode("utf-8")
        root = ET.fromstring(xml)
        metadata, tags = _read_metadata(_plist_dict(root))
        level.metadata.clear()
        level.metadata.update(metadata)
        level._set_source(
            source_bytes=data,
            source_xml=xml,
            metadata_tags=tags,
            had_bom=data.startswith(b"\xef\xbb\xbf"),
        )

    encode_level = staticmethod(_encode_level)
    decode_level = staticmethod(_decode_level)
