from __future__ import annotations

import gmdtool
from gmdtool import (
    AreaEffectId,
    EnterEffectId,
    ForceId,
    GradientId,
    SongChannelId,
    SFXGroupId,
    SFXUniqueId,
)
from gmdtool.catalog import default_catalog
from gmdtool.level import GDLevel


def test_expanded_reference_namespaces_are_catalog_backed():
    catalog = default_catalog()
    expected = {
        "group", "item", "control", "color", "block",
        "force", "song_channel", "trigger_channel", "material", "gradient",
        "area_effect", "enter_effect", "enter_channel", "sfx_group", "sfx_unique",
    }
    assert expected <= set(catalog.reference_namespaces)


def test_pulse_target_variant_switches_color_and_group_semantics():
    color_target = gmdtool.OBJ_1006(target_id=7, pulse_target_type=0)
    assert color_target.references("color") == (7,)
    assert color_target.references("group") == ()

    group_target = gmdtool.OBJ_1006(target_id=7, pulse_target_type=1)
    assert group_target.references("group") == (7,)
    assert group_target.references("color") == ()


def test_force_song_gradient_semantics_are_typed_and_queryable():
    level = GDLevel()
    force = level.add(gmdtool.OBJ_2069(force_id=3))
    song = level.add(gmdtool.OBJ_1934(song_channel=2))
    edit_song = level.add(gmdtool.OBJ_3605(song_channel=2))
    gradient = level.add(gmdtool.OBJ_2903(
        gradient_id=8,
        bottom_left_id=10,
        bottom_right_id=11,
        top_left_id=12,
        top_right_id=13,
    ))

    assert force.force_id == ForceId(3)
    assert force.memberships("force") == (3,)
    assert level.members(force=3).first() is force

    assert song.song_channel == SongChannelId(2)
    assert song.identifiers("song_channel") == (2,)
    assert edit_song.references("song_channel") == (2,)
    assert level.identifiers(song_channel=2).first() is song
    assert level.references(song_channel=2).first() is edit_song

    assert gradient.gradient_id == GradientId(8)
    assert gradient.identifiers("gradient") == (8,)
    assert set(gradient.references("group")) >= {10, 11, 12, 13}


def test_area_and_enter_effect_ids_are_distinct_namespaces():
    area = gmdtool.OBJ_3006(effect_id=9)
    enter = gmdtool.OBJ_3017(effect_id=9, enter_channel=4)
    stop_area = gmdtool.OBJ_3024(effect_id=9)
    stop_enter = gmdtool.OBJ_3023(effect_id=9)

    assert area.effect_id == AreaEffectId(9)
    assert enter.effect_id == EnterEffectId(9)
    assert area.identifiers("area_effect") == (9,)
    assert area.identifiers("enter_effect") == ()
    assert enter.identifiers("enter_effect") == (9,)
    assert enter.identifiers("area_effect") == ()
    assert stop_area.references("area_effect") == (9,)
    assert stop_enter.references("enter_effect") == (9,)


def test_sfx_unique_ids_are_scoped_by_sfx_group():
    level = GDLevel()
    a = level.add(gmdtool.OBJ_3602(sfx_group=5, unique_id=1))
    b = level.add(gmdtool.OBJ_3602(sfx_group=6, unique_id=1))
    edit_a = level.add(gmdtool.OBJ_3603(sfx_group=5, unique_id=1))
    edit_b = level.add(gmdtool.OBJ_3603(sfx_group=6, unique_id=1))

    assert a.sfx_group == SFXGroupId(5)
    assert a.unique_id == SFXUniqueId(1)
    assert set(level.identifiers("sfx_unique", 1)) == {a, b}
    assert level.identifiers("sfx_unique", 1, scope={"sfx_group": 5}).first() is a
    assert set(level.references("sfx_unique", 1)) == {edit_a, edit_b}
    assert level.references("sfx_unique", 1, scope={"sfx_group": 6}).first() is edit_b


def test_universal_memberships_make_raw_only_objects_structurally_visible():
    level = GDLevel()
    obj = level.add(gmdtool.OBJ_1(enter_channel=12, material_id=7, groups=[42]))
    assert obj.memberships("enter_channel") == (12,)
    assert obj.memberships("material") == (7,)
    assert level.members(enter_channel=12).first() is obj
    assert level.members(material=7).first() is obj
    assert level.members(group=42).first() is obj


def test_known_object_implementation_metadata_improves_raw_only_names():
    catalog = default_catalog()
    info = catalog.known_object(105)
    assert info is not None
    assert info["cpp_class"] == "EffectGameObject"
    assert catalog.get_object(105) is None
    assert catalog.object_display_name(105) == "EffectGameObject 105"
    assert gmdtool.OBJ_105().object_name == "EffectGameObject 105"


def test_scoped_relation_details_keep_sfx_group_context():
    sfx = gmdtool.OBJ_3602(sfx_group=5, unique_id=1)
    edit = gmdtool.OBJ_3603(sfx_group=5, unique_id=1)
    assert sfx.identifier_details("sfx_unique")[0]["scope"] == {
        "namespace": "sfx_group", "property": "sfx_group", "value": 5,
    }
    assert edit.reference_details("sfx_unique")[0]["scope"] == {
        "namespace": "sfx_group", "property": "sfx_group", "value": 5,
    }


def test_raw_only_explain_exposes_factory_implementation_metadata():
    info = gmdtool.OBJ_105().explain()
    assert info["schema_status"] == "raw_only"
    assert info["cpp_class"] == "EffectGameObject"
    assert info["confidence"] == "confirmed"
    assert "executable-2.2081" in info["implementation_sources"]
    assert info["implementation_evidence"]["basis"]


def test_reverse_verified_special_classes_get_partial_schemas():
    portal = gmdtool.OBJ_2064(target_group=42, teleport_static_force_enabled=True)
    assert portal.object_name == "Unlinked Orange Teleport Portal"
    assert portal.references("group") == (42,)
    assert portal.teleport_static_force_enabled is True

    animation = gmdtool.OBJ_2055(disable_animation_shine=True)
    assert animation.object_name == "Explosion Animation"
    assert animation.disable_animation_shine is True


def test_raw_only_human_name_is_a_selector_without_fake_schema():
    catalog = default_catalog()
    assert catalog.resolve_object_id("Large Beast Hazard") == 918
    assert catalog.get_object(918) is None
    known = catalog.known_object(918)
    assert known["name_sources"] == ["flowvix-object-ids"]
    assert gmdtool.OBJ_918().object_name == "Large Beast Hazard"
