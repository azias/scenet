"""The `setting` block: places, masses, planes, and the atmosphere vocabulary.

The language surface only. Whether three greys read as depth is a question about a
picture and lives in `test_backdrop.py` and in the contact sheet; what is testable here
is that the vocabularies are closed, that a preset expands into a mass list an author
could have written, and that the two ways of saying where a panel is cannot be used at
once.
"""

from enum import StrEnum

import pytest
import yaml

from scenet import compile_source, parse_panel
from scenet.errors import PanelSyntaxError
from scenet.frontends.common import normalise
from scenet.ir import (
    Horizon,
    Mass,
    MassKind,
    PanelIR,
    Plane,
    SettingSpec,
    Spans,
    TimeOfDay,
    Weather,
)
from scenet.places import PLACES, Place


class TestTheVocabulariesAreClosed:
    """Everything in this language is a closed set, and setting is no exception.

    Free prose -- `setting: "a rainy street corner at midnight"` -- needs language
    understanding, which is exactly what the script frontend refuses to do on the
    grounds that guessing produces panels that are confidently wrong.
    """

    def test_mass_kinds_are_the_coco_stuff_supercategories(self):
        assert {kind.value for kind in MassKind} == {
            "building",
            "ceiling",
            "floor",
            "furniture",
            "ground",
            "plant",
            "sky",
            "solid",
            "structural",
            "wall",
            "water",
            "window",
        }

    def test_no_leaf_names_leaked_in(self):
        """COCO-Stuff's leaves are `building-other`, `wall-brick`, `sky-other`. The
        `-other` suffix marks the catch-all inside a supercategory, and it is not a word
        anyone should have to type."""
        assert not any("-" in kind.value for kind in MassKind)

    @pytest.mark.parametrize(
        ("enum", "expected"),
        [
            (Plane, {"foreground", "near", "mid", "far"}),
            (Spans, {"full", "left", "center", "right"}),
            (Horizon, {"high", "mid", "low"}),
            (TimeOfDay, {"dawn", "day", "dusk", "night"}),
            (Weather, {"clear", "rain", "fog", "snow"}),
        ],
    )
    def test_the_small_vocabularies(self, enum: type[StrEnum], expected: set[str]):
        assert {member.value for member in enum} == expected

    def test_prose_is_refused(self):
        with pytest.raises(PanelSyntaxError, match="mapping"):
            parse_panel('setting: "a rainy street corner at midnight"')


class TestSpansResolvesHorizontalExtent:
    """`spans` is resolved to an extent before the solver, and that is not cosmetic.

    Any construct that would reintroduce a left/right disjunction has to resolve it in
    the frontend, because Cassowary cannot express one. `spans` is what stops masses
    becoming an unordered `beside`.
    """

    def test_full_covers_the_whole_width(self):
        assert Spans.FULL.fractions == (0.0, 1.0)

    @pytest.mark.parametrize("spans", list(Spans))
    def test_every_span_is_ordered_and_inside_the_panel(self, spans: Spans):
        start, end = spans.fractions
        assert 0.0 <= start < end <= 1.0

    def test_left_and_right_overlap_in_the_middle(self):
        """Butting them exactly would leave a seam down the centre of the panel."""
        assert Spans.LEFT.fractions[1] > Spans.RIGHT.fractions[0]


class TestHorizonIsAFractionOfPanelHeight:
    def test_a_high_horizon_sits_nearer_the_top(self):
        assert Horizon.HIGH.fraction < Horizon.MID.fraction < Horizon.LOW.fraction

    @pytest.mark.parametrize("horizon", list(Horizon))
    def test_every_horizon_is_inside_the_panel(self, horizon: Horizon):
        assert 0.0 < horizon.fraction < 1.0


class TestTheSettingBlock:
    def test_a_panel_has_no_setting_by_default(self):
        assert PanelIR().setting.masses == ()

    def test_masses_can_be_authored_directly(self):
        panel = parse_panel(
            "setting: {horizon: mid, masses: ["
            "{kind: building, plane: far, spans: full}, "
            "{kind: plant, plane: mid, spans: left}]}"
        )
        assert [mass.kind for mass in panel.setting.masses] == [MassKind.BUILDING, MassKind.PLANT]
        assert panel.setting.masses[1].spans is Spans.LEFT

    def test_a_mass_defaults_to_the_middle_plane_across_the_whole_width(self):
        mass = Mass(kind=MassKind.SKY)
        assert (mass.plane, mass.spans) == (Plane.MID, Spans.FULL)

    def test_unknown_keys_are_rejected(self):
        with pytest.raises(PanelSyntaxError):
            parse_panel("setting: {masses: [{kind: sky, plane: far, opacity: 0.5}]}")

    def test_time_and_weather_default_to_a_clear_day(self):
        assert (SettingSpec().time, SettingSpec().weather) == (TimeOfDay.DAY, Weather.CLEAR)

    def test_weather_needs_no_masses(self):
        """Rain over an empty panel is a real thing to want, and nothing about it
        depends on there being a backdrop behind it."""
        panel = parse_panel("setting: {weather: rain}")
        assert panel.setting.masses == ()
        assert panel.setting.weather is Weather.RAIN


class TestPlaceIsAPresetNotASecondFormat:
    """The rule that keeps `place:` honest.

    A preset expands into a mass list the author could have written themselves. It is a
    library for convenience, never a parallel language -- so the expansion happens in the
    frontend and the IR has no `place` field at all, exactly as `alice left_of bob` is a
    sentence the frontend expands into a relation the IR never sees as text.
    """

    def test_every_place_expands_to_a_mass_list(self):
        for place, masses in PLACES.items():
            assert masses, f"{place.value} expands to nothing"
            assert all(isinstance(mass, Mass) for mass in masses)

    def test_every_expansion_is_authorable(self):
        """Whatever a preset produces, an author could have typed it."""
        for place, masses in PLACES.items():
            written = {
                "setting": {
                    "masses": [
                        {"kind": m.kind.value, "plane": m.plane.value, "spans": m.spans.value}
                        for m in masses
                    ]
                }
            }
            assert parse_panel(yaml.safe_dump(written)).setting.masses == masses, place.value

    def test_the_ir_has_no_place_field(self):
        assert "place" not in SettingSpec.model_fields

    def test_a_place_reaches_the_ir_as_masses(self):
        panel = parse_panel("setting: {place: docks}")
        assert panel.setting.masses == PLACES[Place.DOCKS]

    def test_a_place_keeps_the_other_setting_keys(self):
        panel = parse_panel("setting: {place: forest, time: dusk, weather: fog, horizon: low}")
        assert panel.setting.masses == PLACES[Place.FOREST]
        assert (panel.setting.time, panel.setting.weather) == (TimeOfDay.DUSK, Weather.FOG)
        assert panel.setting.horizon is Horizon.LOW

    def test_a_place_and_a_mass_list_cannot_both_be_given(self):
        """A place *is* a mass list. Writing both asks two questions at once."""
        with pytest.raises(PanelSyntaxError, match="place"):
            parse_panel("setting: {place: docks, masses: [{kind: sky, plane: far}]}")

    def test_an_unknown_place_names_the_ones_that_exist(self):
        with pytest.raises(PanelSyntaxError, match="docks"):
            parse_panel("setting: {place: dockside}")

    def test_the_starter_set_is_all_ten(self):
        assert {place.value for place in Place} == {
            "alley",
            "desert",
            "docks",
            "field",
            "forest",
            "mountain",
            "office",
            "room",
            "shore",
            "street",
        }

    def test_every_place_is_in_the_table(self):
        assert set(PLACES) == set(Place)

    def test_normalise_leaves_the_input_alone(self):
        """`normalise` is documented as returning a new mapping."""
        source = {"setting": {"place": "docks"}}
        normalise(source)
        assert source == {"setting": {"place": "docks"}}


class TestEveryPlaceIsUsable:
    @pytest.mark.parametrize("place", list(Place), ids=[p.value for p in Place])
    def test_it_compiles(self, place: Place):
        result = compile_source(
            f"{{panel: {{size: [1000, 700]}}, camera: {{shot: long_shot}}, "
            f"setting: {{place: {place.value}}}, cast: {{a: {{reference: alice}}}}}}"
        )
        assert result.core.backdrop is not None
        assert result.core.backdrop.masses
