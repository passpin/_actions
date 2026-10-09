from __future__ import annotations

import json
from pathlib import Path

import pytest

import gmdtool
from gmdtool import GDLevel, GDObject, GDReal, GroupId, ItemId, ControlId
from gmdtool.catalog import default_catalog
from gmdtool.io import GMD
from gmdtool.objects import OBJECT_REGISTRY, get_object_class

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
BIG = FIXTURES / "2048 game preview.gmd"
IDS = FIXTURES / "Object_IDs.gmd.txt"


def test_catalog_coverage_and_generated_classes():
    catalog = default_catalog()
    assert len(catalog.known_object_ids) == 4073
    assert len(catalog.objects) >= 380
    assert len(OBJECT_REGISTRY) >= 4073
    assert get_object_class(901).__name__ == "OBJ_901"
    assert gmdtool.OBJ_901 is get_object_class(901)
    assert get_object_class(2743).__name__ == "OBJ_2743"
    assert catalog.validate() == []


def test_exact_real_semantics():
    assert GDReal("1") == GDReal("1.0") == 1
    assert hash(GDReal("1")) == hash(GDReal("1.0"))
    assert str(GDReal("0.1") + GDReal("0.2")) == "0.3"
    assert str(GDReal("1") / 8) == "0.125"
    with pytest.raises(ArithmeticError):
        _ = GDReal("1") / 3
    with pytest.raises(TypeError):
        GDReal.from_value(0.1)


def test_semantic_and_raw_views_share_state():
    obj = gmdtool.OBJ_901(move_x="10", target_group=42)
    assert obj.get_raw(28) == "10"
    assert obj.move_x == GDReal("10")
    assert obj.target_group == GroupId(42)

    obj.move_x = "120.0"
    assert obj.get_raw(28) == "120.0"

    obj.set_raw(28, "45")
    assert obj.move_x == GDReal("45")


def test_duplicate_raw_keys_and_unknown_raw_survive():
    obj = GDObject.parse("1,901,28,10,28,20,9999,abc")
    assert obj.get_all_raw(28) == ("10", "20")
    assert obj.get_raw(28) == "20"
    assert obj.get_raw(28, occurrence="first") == "10"
    assert obj.get_raw(9999) == "abc"

    obj.set_raw(28, "30")
    assert obj.get_all_raw(28) == ("10", "30")
    obj.append_raw(9999, "def")
    assert obj.get_all_raw(9999) == ("abc", "def")
    assert obj.to_object_string() == "1,901,28,10,28,30,9999,abc,9999,def"


def test_unknown_future_object_has_raw_capable_class():
    cls = get_object_class(99999)
    obj = cls(x=10) if cls.supports_property("x") else cls()
    assert obj.object_id == 99999
    obj.set_raw(12345, "hello")
    assert obj.get_raw(12345) == "hello"


def test_strict_bool_decode_falls_back_to_raw_and_validator_flags_it():
    obj = GDObject.parse("1,901,58,2")
    # Malformed typed data remains accessible rather than making parsing fail.
    assert obj.lock_to_player_x == "2"
    level = GDLevel()
    level.add(obj)
    report = level.validate()
    assert not report.ok
    assert any(i.code == "invalid-property" and i.key == 58 for i in report.errors)


def test_query_update_translate_and_rect():
    level = GDLevel()
    level.extend([
        gmdtool.OBJ_1(x=0, y=0, groups=[42]),
        gmdtool.OBJ_1(x=30, y=10, groups=[42]),
        gmdtool.OBJ_1(x=100, y=100),
    ])
    selected = level.objects.filter(1, groups__contains=42)
    assert len(selected) == 2
    selected.translate(10, 5)
    assert selected[0].x == GDReal("10")
    assert selected[1].y == GDReal("15")
    assert len(level.rect(0, 0, 50, 50, 1)) == 2


def test_transaction_rolls_back_nested_changes_and_new_objects():
    level = GDLevel()
    original = level.add(gmdtool.OBJ_1(x=10, y=20))
    original_uid = original.uid
    with pytest.raises(RuntimeError):
        with level.edit():
            original.x = 999
            with level.edit():
                level.add(gmdtool.OBJ_1(x=30, y=40))
            raise RuntimeError("rollback")
    assert len(level.objects) == 1
    assert level.objects.first().uid == original_uid
    assert level.objects.first().x == GDReal("10")


def test_id_allocation_reference_lookup_and_remap():
    level = GDLevel()
    block = level.add(gmdtool.OBJ_1(groups=[42]))
    move = level.move(42, x=30)
    assert move.target_group == GroupId(42)
    assert block in list(level.in_group(42))
    assert move in list(level.references(group=42))
    new_id = level.new_group()
    assert isinstance(new_id, GroupId)
    assert int(new_id) != 42
    level.remap_groups({42: 100})
    assert 100 in block.membership_groups()
    assert move.target_group == GroupId(100)


def test_namespace_types_are_distinct_semantically():
    assert GroupId(7) == 7
    assert ItemId(7) == 7
    assert ControlId(7) == 7
    assert str(GroupId(7)) == "7"
    assert gmdtool.OBJ_1(groups=[GroupId(7)]).get_raw(57) == "7"
    assert type(GroupId(7)) is not type(ItemId(7))
    assert type(ItemId(7)) is not type(ControlId(7))


def test_copy_isolated_remaps_membership_and_internal_group_reference():
    level = GDLevel()
    level.add(gmdtool.OBJ_1(x=0, y=0, groups=[42]))
    level.move(42, x=30, at=(0, 0)).add_group(42)
    selection = level.in_group(42)
    assert len(selection) == 2
    copied = selection.copy_isolated(dx=100)
    assert len(copied) == 2
    assert copied.group_map == {42: next(iter(copied.group_map.values()))}
    fresh = copied.group_map[42]
    assert fresh != 42
    assert all(fresh in obj.membership_groups() for obj in copied)
    copied_move = copied.filter(901).one()
    assert copied_move.target_group == GroupId(fresh)


def test_trigger_helpers_construct_known_objects():
    level = GDLevel()
    assert level.move(1, x=30, duration="0.5").object_id == 901
    assert level.spawn(2, delay="0.1").object_id == 1268
    assert level.toggle(3, active=False).object_id == 1049
    assert level.alpha(4, "0.5").object_id == 1007
    assert level.rotate(5, 90, center_group=6).object_id == 1346
    assert level.follow(7, 8, y_mod="0.5").object_id == 1347
    assert level.stop(9, control=True).object_id == 1616
    assert level.sequence([(10, 1), (11, 2)]).object_id == 3607
    assert level.validate().ok


def test_raw_json_roundtrip_preserves_layout_duplicates_and_unknowns():
    raw = "kA1,0;k,1;;1,901,28,10,28,20,9999,abc;"
    level = GDLevel.parse(raw)
    payload = level.to_raw_json()
    assert json.loads(json.dumps(payload)) == payload
    rebuilt = GDLevel.from_raw_json(payload)
    assert rebuilt.to_level_string() == raw


def test_patch_is_atomic_and_raw_capable():
    level = GDLevel()
    level.move(42, x=10)
    before = level.to_level_string()

    result = level.apply_patch({
        "format": "gmdtool.patch",
        "version": 1,
        "operations": [
            {
                "op": "update",
                "select": {"object_id": 901, "properties": {"target_group": 42}},
                "set": {"move_x": "120"},
                "raw": {"9999": "abc"},
            }
        ],
    })
    assert result["ok"]
    obj = level.objects.one()
    assert obj.move_x == GDReal("120")
    assert obj.get_raw(9999) == "abc"

    changed = level.to_level_string()
    with pytest.raises(ValueError):
        level.apply_patch({
            "operations": [
                {"op": "set_raw", "select": {"object_id": 901}, "key": 9999, "value": "def"},
                {"op": "does-not-exist"},
            ]
        })
    assert level.to_level_string() == changed
    assert level.to_level_string() != before


def test_diff_matches_clone_by_uid():
    before = GDLevel()
    before.add(gmdtool.OBJ_1(x=10, y=20))
    after = before.clone()
    after.objects.first().x = 30
    after.add(gmdtool.OBJ_1(x=40, y=50))
    diff = before.diff(after)
    assert diff["match_mode"] == "uid"
    assert diff["summary"]["changed"] == 1
    assert diff["summary"]["added"] == 1
    prop = diff["changed"][0]["properties"][0]
    assert prop["name"] == "x"


def test_real_2048_fixture_clean_roundtrip_byte_identical(tmp_path: Path):
    original = BIG.read_bytes()
    level = GMD.load(BIG)
    assert len(level.objects) == 22638
    assert level.summary()["distinct_object_ids"] == 28
    assert level.validate().ok
    out = tmp_path / "roundtrip.gmd"
    level.save(out)
    assert out.read_bytes() == original


def test_object_id_fixture_covers_all_known_ids_and_validates():
    level = GMD.load(IDS)
    ids = {obj.object_id for obj in level.objects}
    assert len(level.objects) == 8677
    assert len(ids) == 4073
    assert set(default_catalog().known_object_ids) <= ids
    assert level.validate().ok


def test_dirty_save_reload_and_unknown_property(tmp_path: Path):
    level = GMD.load(BIG)
    target = level.objects.first()
    target.set_raw(9999, "123456789")
    out = tmp_path / "dirty.gmd"
    level.save(out)
    loaded = GMD.load(out)
    assert loaded.objects.first().get_raw(9999) == "123456789"
    assert len(loaded.objects) == len(level.objects)


def test_raw_parsed_object_can_be_modified_semantically_and_survives_reload(tmp_path: Path):
    # Start from raw GD data, not from a typed constructor.
    level = GDLevel.parse("kA1,0;1,901,28,10,51,42,9999,abc;")
    obj = level.objects.one()

    assert type(obj).__name__ == "OBJ_901"
    assert obj.move_x == GDReal("10")
    assert obj.target_group == GroupId(42)
    assert obj.get_raw(9999) == "abc"

    # High-level semantic writes mutate the same ordered raw pair storage.
    obj.move_x = "444.5"
    obj.target_group = 99
    assert obj.get_raw(28) == "444.5"
    assert obj.get_raw(51) == "99"
    assert obj.get_raw(9999) == "abc"

    # Raw writes to known keys are immediately visible through the semantic view.
    obj.set_raw(28, "333.25")
    obj.set_raw(51, "88")
    assert obj.move_x == GDReal("333.25")
    assert obj.target_group == GroupId(88)

    # The relationship survives real .gmd serialization and reload.
    out = tmp_path / "raw_semantic_roundtrip.gmd"
    level.save(out)
    loaded = GMD.load(out)
    loaded_obj = loaded.objects.one()
    assert type(loaded_obj).__name__ == "OBJ_901"
    assert loaded_obj.move_x == GDReal("333.25")
    assert loaded_obj.target_group == GroupId(88)
    assert loaded_obj.get_raw(28) == "333.25"
    assert loaded_obj.get_raw(51) == "88"
    assert loaded_obj.get_raw(9999) == "abc"


def test_new_level_gmd_container_roundtrip(tmp_path: Path):
    level = GDLevel("kA1,0")
    level.metadata["k2"] = "AI generated test"
    level.add(gmdtool.OBJ_1(x=30, y=60))
    out = tmp_path / "new.gmd"
    level.save(out, validate=True)
    loaded = GMD.load(out)
    assert loaded.metadata["k2"] == "AI generated test"
    assert len(loaded.objects) == 1
    assert loaded.objects.first().x == GDReal("30")


def test_every_known_object_class_instantiates_and_roundtrips_object_id():
    catalog = default_catalog()
    for oid in catalog.known_object_ids:
        cls = get_object_class(oid)
        obj = cls()
        assert obj.object_id == oid
        assert obj.get_raw(1) == str(oid)
        parsed = GDObject.parse(obj.to_object_string())
        assert parsed.object_id == oid
        assert type(parsed) is cls


def test_semantic_write_only_updates_effective_duplicate_occurrence():
    obj = GDObject.parse("1,901,28,10,28,20,9999,abc")
    assert obj.move_x == GDReal("20")
    obj.move_x = "30"
    assert obj.get_all_raw(28) == ("10", "30")
    assert obj.to_object_string() == "1,901,28,10,28,30,9999,abc"


def test_level_bound_group_handle_is_int_compatible_and_explicit():
    from gmdtool import GroupHandle

    level = GDLevel()
    group = level.new.group()
    assert isinstance(group, GroupHandle)
    assert isinstance(group, GroupId)
    assert int(group) == 1
    assert str(group) == "1"

    block = level.add(gmdtool.OBJ_1(x=0, y=0))
    group.add(block)
    assert int(group) in block.membership_groups()
    assert block in group.objects

    move = group.move(x=30, duration="0.5")
    spawn = group.call(delay="0.1")
    alpha = group.alpha("0.5", duration="0.2")
    assert move.target_group == GroupId(int(group))
    assert spawn.target_group == GroupId(int(group))
    assert alpha.target_group == GroupId(int(group))
    assert move in group.references


def test_new_id_facade_can_allocate_in_batches():
    level = GDLevel()
    groups = level.new.groups(3)
    assert tuple(map(int, groups)) == (1, 2, 3)
    assert all(isinstance(g, GroupId) for g in groups)
    assert tuple(map(int, level.new.items(2))) == (1, 2)
    assert tuple(map(int, level.new.controls(2))) == (1, 2)


def test_collection_rejects_detached_objects():
    from gmdtool import ObjectCollection

    level = GDLevel()
    detached = gmdtool.OBJ_1(x=0, y=0)
    with pytest.raises(ValueError, match="owned by its level"):
        ObjectCollection(level, [detached])


def test_trigger_classification_uses_level_catalog_not_global_registry():
    from gmdtool import Catalog, Trigger

    # Seed the global class registry as a plain raw object first.
    plain_cls = get_object_class(99999)
    assert not issubclass(plain_cls, Trigger)

    custom = Catalog({
        "compiled_format_version": 1,
        "known_object_ids": [99999],
        "objects": [{
            "id": 99999,
            "name": "Custom Trigger",
            "base": "trigger",
            "properties": [],
            "confidence": "confirmed",
        }],
        "aliases": {},
        "enums": {},
        "sources": {},
        "references": {},
        "properties": {},
        "base_properties": {},
    })
    level = GDLevel(catalog=custom)
    obj = level.trigger(99999)
    assert obj.object_id == 99999
    assert obj.is_trigger



def test_object_trigger_view_prefers_owning_catalog_over_generated_class():
    from gmdtool import Catalog

    # OBJ_901 is globally generated as a Trigger from the default catalog, but
    # a custom catalog is the semantic source of truth for a level.
    custom = Catalog({
        "compiled_format_version": 1,
        "known_object_ids": [901],
        "objects": [{
            "id": 901,
            "name": "Custom Plain Object",
            "base": "object",
            "properties": [],
            "confidence": "confirmed",
        }],
        "aliases": {},
        "enums": {},
        "sources": {},
        "references": {},
        "properties": {},
        "base_properties": {},
    })
    level = GDLevel(catalog=custom)
    obj = level.add(gmdtool.OBJ_901())
    assert not obj.is_trigger
    with pytest.raises(TypeError, match="not a trigger"):
        level.add_triggers([obj])


def test_structured_view_can_be_mutated_repeatedly_but_detects_external_staleness():
    level = GDLevel()
    obj = level.sequence([(10, 1)])
    sequence = obj.sequence
    sequence.append(11, 2)
    sequence.append(12, 3)
    assert obj.get_raw(435) == "10.1.11.2.12.3"

    # An external raw write invalidates the old structured view rather than
    # silently overwriting a newer value.
    obj.set_raw(435, "20.1")
    with pytest.raises(RuntimeError, match="stale"):
        sequence.append(13, 4)


def test_group_handle_rejects_foreign_level_owned_object():
    left = GDLevel()
    right = GDLevel()
    group = left.new.group()
    foreign = right.add(gmdtool.OBJ_1(x=0, y=0))
    with pytest.raises(ValueError, match="another level"):
        group.add(foreign)


def test_selection_expect_and_describe_are_composable():
    level = GDLevel()
    level.extend([
        gmdtool.OBJ_1(x=0, y=0, groups=[42]),
        gmdtool.OBJ_1(x=30, y=0, groups=[42]),
        gmdtool.OBJ_901(x=60, y=0, target_group=42),
    ])
    selected = level.find(1).expect(2)
    assert selected.expect(at_least=1, at_most=3) is selected
    description = selected.describe(include_objects=True)
    assert description["count"] == 2
    assert description["object_counts"][0]["object_id"] == 1
    assert description["membership_groups"] == [42]
    assert description["position_bounds"] == ["0", "0", "30", "0"]
    assert len(description["objects"]) == 2
    with pytest.raises(gmdtool.SelectionCardinalityError):
        selected.expect(1)


def test_group_description_shows_members_inbound_and_outbound_structure():
    level = GDLevel()
    level.add(gmdtool.OBJ_1(x=0, y=0, groups=[42]))
    chained = level.move(99, x=30, at=(30, 0))
    chained.add_group(42)
    level.alpha(42, "0.5", at=(60, 0))

    info = level.group(42).describe(include_objects=True)
    assert info["group"] == 42
    assert info["members"]["count"] == 2
    assert info["referenced_by"]["count"] == 1
    assert info["outgoing_group_references"] == [99]
    assert len(info["members"]["objects"]) == 2


def test_explicit_build_scope_applies_groups_and_offsets_without_global_state():
    level = GDLevel()
    group = level.new.group()
    scope = level.scope(groups=[group], dx=100, dy=50)

    block = scope.create(1, x=0, y=0)
    move = scope.trigger(901, at=(30, 10), target_group=group, move_x=15)

    assert block.x == GDReal("100") and block.y == GDReal("50")
    assert move.x == GDReal("130") and move.y == GDReal("60")
    assert int(group) in block.membership_groups()
    assert int(group) in move.membership_groups()
    assert move.target_group == group
    assert len(level.objects) == 2


def test_color_and_block_namespaces_are_semantic_without_guessing_allocation_rules():
    level = GDLevel()
    color_trigger = level.add(gmdtool.OBJ_899(target_color=12, copied_color_id=7))
    block = level.add(gmdtool.OBJ_1816(block_id=5))
    collision = level.add(gmdtool.OBJ_1815(block_a=5, block_b=8, target_group=1))

    assert isinstance(color_trigger.target_color, gmdtool.ColorId)
    assert isinstance(color_trigger.copied_color_id, gmdtool.ColorId)
    assert color_trigger.color_references() == (7, 12) or set(color_trigger.color_references()) == {7, 12}

    assert isinstance(block.block_id, gmdtool.BlockId)
    assert block.identifiers("block") == (5,)
    assert collision.block_references() == (5, 8)
    assert list(level.identifiers(block=5)) == [block]
    assert list(level.references(block=5)) == [collision]
    assert level.used_ids("block") == (5, 8)

    level.remap_blocks({5: 9})
    assert block.block_id == gmdtool.BlockId(9)
    assert collision.block_a == gmdtool.BlockId(9)

    with pytest.raises(ValueError, match="Automatic allocation for color IDs is not defined"):
        level.allocate_ids("color")


def test_reference_details_preserve_property_evidence():
    level = GDLevel()
    move = level.add(gmdtool.OBJ_901(target_group=42, target_position_group=7))
    details = move.reference_details("group")
    assert {entry["value"] for entry in details} >= {42, 7}
    by_value = {entry["value"]: entry for entry in details}
    assert by_value[42]["property"] == "target_group"
    assert by_value[42]["key"] == 51


def test_level_relations_trace_group_returns_structural_edges_not_execution_claims():
    level = GDLevel()
    first = level.add(gmdtool.OBJ_901(target_group=20, groups=[10]))
    second = level.add(gmdtool.OBJ_1007(target_group=30, groups=[20]))
    level.add(gmdtool.OBJ_1(groups=[30]))

    overview = level.relations.overview("group")
    rows = {row["id"]: row for row in overview["ids"]}
    assert rows[10]["members"] == 1
    assert rows[20]["members"] == 1 and rows[20]["references"] == 1

    trace = level.relations.trace_group(10, depth=2, direction="outgoing")
    assert trace["groups"] == [10, 20, 30]
    pairs = {(edge["source_group"], edge["target_group"]) for edge in trace["edges"]}
    assert pairs == {(10, 20), (20, 30)}
    assert any(edge["object_uid"] == first.uid and edge["property"] == "target_group" for edge in trace["edges"])
    assert any(edge["object_uid"] == second.uid for edge in trace["edges"])


def test_object_template_snapshots_and_isolates_internal_groups_with_explicit_bindings():
    source = GDLevel()
    block = source.add(gmdtool.OBJ_1(x=0, y=0, groups=[10]))
    internal = source.add(gmdtool.OBJ_901(x=30, y=0, groups=[10], target_group=10, move_x=30))
    external = source.add(gmdtool.OBJ_901(x=60, y=0, groups=[10], target_group=99, move_x=30))

    template = source.in_group(10).template()
    assert template.describe()["internal_groups"] == [10]

    # Mutating the source after snapshot creation does not alter the template.
    block.add_group(20)
    internal.target_group = 20
    assert template.describe()["internal_groups"] == [10]

    target = GDLevel()
    first = template.instantiate(target, bind_groups={99: 1})
    # Binding target 1 is reserved from automatic internal-group allocation.
    assert first.group_map[99] == 1
    assert first.group_map[10] != 1
    first_internal = first.group_map[10]
    assert all(first_internal in obj.membership_groups() for obj in first)
    assert any(obj.object_id == 901 and obj.target_group == first_internal for obj in first)
    assert any(obj.object_id == 901 and obj.target_group == 1 for obj in first)

    second = template.instantiate(target, dx=300, bind_groups={99: 500})
    assert second.group_map[10] != first_internal
    assert second.group_map[99] == 500
    assert min(float(obj.x.decimal) for obj in second) >= 300


def test_object_template_can_bind_color_and_block_ids_without_auto_allocating_them():
    source = GDLevel()
    source.extend([
        gmdtool.OBJ_899(target_color=12),
        gmdtool.OBJ_1816(block_id=5),
        gmdtool.OBJ_1815(block_a=5, block_b=8, target_group=1),
    ])
    template = source.objects.template()
    target = GDLevel()
    created = template.instantiate(
        target,
        bind_colors={12: 22},
        bind_blocks={5: 15},
    )
    color = created.filter(899).one()
    block = created.filter(1816).one()
    collision = created.filter(1815).one()
    assert color.target_color == gmdtool.ColorId(22)
    assert block.block_id == gmdtool.BlockId(15)
    assert collision.block_a == gmdtool.BlockId(15)
    assert collision.block_b == gmdtool.BlockId(8)


def test_level_bound_color_and_block_handles_keep_ownership_explicit():
    level = GDLevel()
    color = level.color(12)
    assert isinstance(color, gmdtool.ColorHandle)
    trigger = color.trigger(red=255, green=10, blue=20, duration="0.5", at=(30, 60))
    assert trigger.target_color == gmdtool.ColorId(12)
    assert trigger in list(color.references)
    assert color.describe()["referenced_by"]["count"] == 1

    block_obj = level.add(gmdtool.OBJ_1816(block_id=5))
    collision = level.add(gmdtool.OBJ_1815(block_a=5, block_b=6, target_group=1))
    block = level.block(5)
    assert isinstance(block, gmdtool.BlockHandle)
    assert list(block.objects) == [block_obj]
    assert list(block.references) == [collision]
    info = block.describe()
    assert info["identified_by"]["count"] == 1
    assert info["referenced_by"]["count"] == 1


def test_catalog_declares_reference_namespaces_as_knowledge():
    catalog = gmdtool.default_catalog()
    assert set(catalog.reference_namespaces) >= {"group", "item", "control", "color", "block"}
    assert catalog.reference_namespaces["color"]["allocatable"] is False


def test_catalog_constraints_drive_numeric_range_validation():
    catalog = gmdtool.default_catalog()
    red = catalog.find_property(899, "red")
    opacity = catalog.find_property(899, "opacity")
    assert red is not None and red.constraints == {"min": 0, "max": 255}
    assert opacity is not None and opacity.constraints == {"min": 0, "max": 1}

    level = GDLevel()
    level.add(gmdtool.OBJ_899(red=300, green=0, blue=0, opacity="1.25", target_color=1))
    report = level.validate()
    errors = {(issue.code, issue.key) for issue in report.errors}
    assert ("property-above-maximum", 7) in errors
    assert ("property-above-maximum", 35) in errors
    assert all(issue.code not in {"color-out-of-range", "opacity-out-of-range"} for issue in report.issues)


def test_conditional_semantic_variants_drive_stop_target_namespace():
    level = GDLevel()
    stop = level.add(gmdtool.OBJ_1616(target_id=42, use_control_id=False))

    assert isinstance(stop.target_id, gmdtool.GroupId)
    assert stop.group_references() == (42,)
    assert stop.control_references() == ()
    assert list(level.references(group=42)) == [stop]

    stop.use_control_id = True
    assert isinstance(stop.target_id, gmdtool.ControlId)
    assert stop.group_references() == ()
    assert stop.control_references() == (42,)
    assert list(level.references(control=42)) == [stop]
    assert list(level.references(group=42)) == []

    target = next(p for p in stop.explain()["properties"] if p.get("name") == "target_id")
    assert target["semantic"] == {"kind": "reference", "namespace": "control"}
    assert target["semantic_variant"] is True
