"""Resolving a setting into numeric masses, tones and atmosphere.

Two things are testable here and one is not. Testable: that the value ladder is
monotonic in depth at every time of day, that planes land in the right painter's order
around the cast, and that the same source produces the same polygons in a fresh
interpreter. Not testable: whether three greys read as depth. That is a question about
a picture, and `scripts/setting_sheet.py` is the instrument for it.
"""

import json
import math
import subprocess
import sys
import textwrap
from itertools import pairwise

import pytest

from scenet import compile_source
from scenet.geom import BBox
from scenet.ir import (
    Horizon,
    Mass,
    MassKind,
    Plane,
    SettingSpec,
    Spans,
    TimeOfDay,
    Weather,
)
from scenet.places import PLACES, Place
from scenet.solve.backdrop import (
    ATMOSPHERE,
    FOREGROUND_SPAN_KEEP,
    LADDER,
    PLANE_SCALE,
    depth_for,
    lightness,
    seed_for,
    solve_backdrop,
    tone_for,
)

PANEL = BBox(0.0, 0.0, 1000.0, 700.0)


def _setting(*masses: Mass, **kwargs) -> SettingSpec:
    return SettingSpec(masses=masses, **kwargs)


class TestTheValueLadder:
    """Aerial perspective, as a parametric rule rather than an interpretation.

    With distance, value contrast drops toward the atmosphere. Each time of day
    supplies two numbers -- the foreground value and the atmosphere value -- and the
    planes sit evenly between them, so monotonicity is true by construction rather than
    by tuning.
    """

    @pytest.mark.parametrize("time", list(TimeOfDay))
    def test_it_is_monotonic_in_depth(self, time: TimeOfDay):
        values = [lightness(tone) for tone in LADDER[time]]
        assert values == sorted(values), f"{time.value} is not monotonic"
        assert len(set(values)) == len(values), f"{time.value} has two rungs the same"

    @pytest.mark.parametrize("time", list(TimeOfDay))
    def test_every_rung_is_distinguishable(self, time: TimeOfDay):
        """A ladder whose rungs cannot be told apart is not a ladder."""
        values = [lightness(tone) for tone in LADDER[time]]
        gaps = [b - a for a, b in pairwise(values)]
        assert min(gaps) > 0.02

    @pytest.mark.parametrize("time", list(TimeOfDay))
    def test_it_has_a_rung_per_plane_plus_the_atmosphere(self, time: TimeOfDay):
        assert len(LADDER[time]) == len(Plane) + 1

    def test_night_is_darker_than_day_all_the_way_down(self):
        for night, day in zip(LADDER[TimeOfDay.NIGHT], LADDER[TimeOfDay.DAY], strict=True):
            assert lightness(night) < lightness(day)

    def test_night_is_a_compressed_ladder_not_a_filter(self):
        """Night does not shift a daytime ladder; it narrows it. That is what night
        does to a drawn scene."""

        def span(time: TimeOfDay) -> float:
            return lightness(LADDER[time][-1]) - lightness(LADDER[time][0])

        assert span(TimeOfDay.NIGHT) < span(TimeOfDay.DAY)

    @pytest.mark.parametrize("tone", [tone for rungs in LADDER.values() for tone in rungs])
    def test_every_tone_is_a_neutral_grey(self, tone: str):
        """The ladder is spaced in OKLab lightness and hardcoded. Neutral means the
        three channels agree, which is what makes 'a value ladder' the honest name."""
        assert len(tone) == 7
        assert tone.startswith("#")
        assert tone[1:3] == tone[3:5] == tone[5:7]


class TestToneFollowsThePlane:
    def test_a_nearer_plane_is_darker(self):
        for time in TimeOfDay:
            near = lightness(tone_for(MassKind.BUILDING, Plane.NEAR, time))
            far = lightness(tone_for(MassKind.BUILDING, Plane.FAR, time))
            assert near < far

    def test_the_kind_does_not_change_the_value(self):
        """Value comes from the plane and nothing else, which is what keeps the notan
        reading literal: masses at one distance are one mass."""
        at_mid = {tone_for(kind, Plane.MID, TimeOfDay.DAY) for kind in MassKind} - {
            tone_for(MassKind.SKY, Plane.MID, TimeOfDay.DAY),
            tone_for(MassKind.WINDOW, Plane.MID, TimeOfDay.DAY),
        }
        assert len(at_mid) == 1

    @pytest.mark.parametrize("plane", list(Plane))
    def test_sky_is_always_the_atmosphere(self, plane: Plane):
        """The sky is at infinite distance whatever plane it was filed under."""
        assert tone_for(MassKind.SKY, plane, TimeOfDay.DUSK) == LADDER[TimeOfDay.DUSK][ATMOSPHERE]

    def test_a_window_is_toned_one_plane_farther(self):
        """A window is a hole showing a more distant plane, so it sits on the ladder
        rather than off it."""
        assert tone_for(MassKind.WINDOW, Plane.MID, TimeOfDay.DAY) == tone_for(
            MassKind.BUILDING, Plane.FAR, TimeOfDay.DAY
        )

    def test_a_window_in_the_farthest_wall_shows_the_atmosphere(self):
        assert (
            tone_for(MassKind.WINDOW, Plane.FAR, TimeOfDay.DAY) == LADDER[TimeOfDay.DAY][ATMOSPHERE]
        )


class TestPlanesMapOntoTheExistingDepth:
    """`plane` reuses the painter's order that is already there. No second mechanism."""

    def test_backdrop_planes_are_behind_every_actor(self):
        """`depth_order` floors actor depth at 0, so a backdrop has to be negative."""
        for plane in (Plane.FAR, Plane.MID, Plane.NEAR):
            assert depth_for(plane, frontmost_actor=0) < 0

    def test_they_are_ordered_back_to_front(self):
        depths = [
            depth_for(plane, frontmost_actor=0) for plane in (Plane.FAR, Plane.MID, Plane.NEAR)
        ]
        assert depths == sorted(depths)

    @pytest.mark.parametrize("frontmost", [0, 1, 7])
    def test_the_foreground_sits_in_front_of_the_whole_cast(self, frontmost: int):
        assert depth_for(Plane.FOREGROUND, frontmost_actor=frontmost) > frontmost

    def test_a_foreground_mass_draws_over_the_actors(self):
        result = compile_source(
            "{cast: {a: {reference: alice}}, setting: {masses: "
            "[{kind: building, plane: foreground, spans: left}]}}"
        )
        backdrop = result.core.backdrop
        assert backdrop is not None
        assert backdrop.masses[0].depth > max(actor.depth for actor in result.core.actors)

    def test_a_nearer_plane_is_drawn_larger(self):
        """Size perspective alongside aerial perspective: the same mass nearer the
        reader is bigger, not merely darker."""
        assert PLANE_SCALE[Plane.FAR] < PLANE_SCALE[Plane.MID] < PLANE_SCALE[Plane.NEAR]
        assert PLANE_SCALE[Plane.NEAR] < PLANE_SCALE[Plane.FOREGROUND]


class TestGeometry:
    @pytest.mark.parametrize("kind", list(MassKind), ids=[k.value for k in MassKind])
    def test_every_kind_produces_something_drawable(self, kind: MassKind):
        backdrop = solve_backdrop(_setting(Mass(kind=kind)), PANEL)
        assert backdrop is not None
        assert backdrop.masses
        for mass in backdrop.masses:
            assert len(mass.polygon) >= 3, f"{kind.value} produced a degenerate polygon"

    @pytest.mark.parametrize("kind", list(MassKind), ids=[k.value for k in MassKind])
    def test_nothing_leaves_the_panel(self, kind: MassKind):
        backdrop = solve_backdrop(_setting(Mass(kind=kind, plane=Plane.FOREGROUND)), PANEL)
        assert backdrop is not None
        for mass in backdrop.masses:
            for point in mass.polygon:
                assert 0.0 <= point.x <= PANEL.width
                assert 0.0 <= point.y <= PANEL.height

    def test_a_foreground_mass_is_narrowed_so_it_frames_rather_than_buries(self):
        """A foreground mass is a repoussoir -- the doorway you are standing behind.
        `left` reaches past the middle of the panel, and a foreground mass that wide
        stops framing the composition and starts hiding it: the first contact sheet had
        `alley` covering everything of the figure above the knees."""
        backdrop = solve_backdrop(
            _setting(Mass(kind=MassKind.BUILDING, plane=Plane.FOREGROUND, spans=Spans.LEFT)),
            PANEL,
        )
        assert backdrop is not None
        assert max(point.x for point in backdrop.masses[0].polygon) < PANEL.width / 2

    @pytest.mark.parametrize("spans", [Spans.LEFT, Spans.CENTRE, Spans.RIGHT])
    def test_a_narrowed_foreground_keeps_its_own_side_of_the_panel(self, spans: Spans):
        """Narrowing holds the mass against its outer edge rather than recentring it: a
        foreground wall on the left has to stay on the left."""
        declared = spans.fractions
        backdrop = solve_backdrop(
            _setting(Mass(kind=MassKind.BUILDING, plane=Plane.FOREGROUND, spans=spans)), PANEL
        )
        assert backdrop is not None
        xs = [point.x / PANEL.width for point in backdrop.masses[0].polygon]
        assert min(xs) >= declared[0] - 0.01
        assert max(xs) <= declared[1] + 0.01
        assert max(xs) - min(xs) == pytest.approx(
            (declared[1] - declared[0]) * FOREGROUND_SPAN_KEEP, abs=0.01
        )

    def test_a_full_width_foreground_is_left_alone(self):
        """Asking for one is asking for a silhouette, which is a real thing to want."""
        backdrop = solve_backdrop(
            _setting(Mass(kind=MassKind.BUILDING, plane=Plane.FOREGROUND, spans=Spans.FULL)),
            PANEL,
        )
        assert backdrop is not None
        assert max(point.x for point in backdrop.masses[0].polygon) == pytest.approx(PANEL.width)

    @pytest.mark.parametrize("spans", list(Spans))
    @pytest.mark.parametrize("kind", list(MassKind), ids=[k.value for k in MassKind])
    def test_a_mass_stays_inside_its_span(self, kind: MassKind, spans: Spans):
        start, end = spans.fractions
        backdrop = solve_backdrop(_setting(Mass(kind=kind, spans=spans)), PANEL)
        assert backdrop is not None
        for mass in backdrop.masses:
            xs = [point.x for point in mass.polygon]
            assert min(xs) >= start * PANEL.width - 0.01
            assert max(xs) <= end * PANEL.width + 0.01

    @pytest.mark.parametrize("horizon", list(Horizon))
    def test_the_ground_starts_at_the_horizon_and_runs_down(self, horizon: Horizon):
        backdrop = solve_backdrop(_setting(Mass(kind=MassKind.GROUND), horizon=horizon), PANEL)
        assert backdrop is not None
        assert backdrop.horizon == pytest.approx(PANEL.height * horizon.fraction)
        ys = [point.y for point in backdrop.masses[0].polygon]
        assert min(ys) == pytest.approx(backdrop.horizon)
        assert max(ys) == pytest.approx(PANEL.height)

    def test_a_nearer_ground_starts_lower_so_the_bands_behind_it_show(self):
        """Ground, floor and water all run to the bottom edge, so a near quayside drawn
        from the horizon would simply erase the water behind it. Each one starts lower
        than the plane behind it, and the stack of bands is the depth cue."""
        backdrop = solve_backdrop(
            _setting(
                Mass(kind=MassKind.WATER, plane=Plane.MID),
                Mass(kind=MassKind.GROUND, plane=Plane.NEAR),
            ),
            PANEL,
        )
        assert backdrop is not None
        water, ground = backdrop.masses
        assert min(point.y for point in water.polygon) <= backdrop.horizon
        assert min(point.y for point in ground.polygon) > backdrop.horizon

    def test_the_farthest_ground_still_meets_the_horizon(self):
        """Whatever plane it was filed under. A strip of bare paper along the horizon
        reads as a mistake, and there is nothing behind the farthest band to reveal."""
        for plane in Plane:
            backdrop = solve_backdrop(_setting(Mass(kind=MassKind.GROUND, plane=plane)), PANEL)
            assert backdrop is not None
            top = min(point.y for point in backdrop.masses[0].polygon)
            assert top == pytest.approx(backdrop.horizon), plane.value

    def test_the_sky_stops_at_the_horizon(self):
        backdrop = solve_backdrop(_setting(Mass(kind=MassKind.SKY)), PANEL)
        assert backdrop is not None
        assert max(p.y for p in backdrop.masses[0].polygon) == pytest.approx(backdrop.horizon)

    def test_things_that_stand_in_the_world_rise_from_the_horizon(self):
        for kind in (MassKind.BUILDING, MassKind.PLANT, MassKind.SOLID):
            backdrop = solve_backdrop(_setting(Mass(kind=kind)), PANEL)
            assert backdrop is not None
            ys = [point.y for point in backdrop.masses[0].polygon]
            assert max(ys) == pytest.approx(backdrop.horizon)
            assert min(ys) < backdrop.horizon

    def test_furniture_and_windows_come_apart_into_separate_masses(self):
        """One authored mass may resolve to several polygons. A comb of blocks joined
        by a zero-height baseline would be one self-touching polygon, which is a lie
        about the shape."""
        for kind in (MassKind.FURNITURE, MassKind.WINDOW):
            backdrop = solve_backdrop(_setting(Mass(kind=kind)), PANEL)
            assert backdrop is not None
            assert len(backdrop.masses) > 1, kind.value
            assert len({mass.tone for mass in backdrop.masses}) == 1

    def test_mass_ids_are_stable_and_ordered(self):
        backdrop = solve_backdrop(_setting(*PLACES[Place.DOCKS]), PANEL)
        assert backdrop is not None
        assert [mass.id for mass in backdrop.masses] == [
            f"m{index}" for index in range(len(backdrop.masses))
        ]


class TestAtmosphere:
    def test_clear_weather_adds_nothing(self):
        backdrop = solve_backdrop(_setting(Mass(kind=MassKind.SKY)), PANEL)
        assert backdrop is not None
        assert backdrop.atmosphere is None

    def test_a_bare_setting_is_no_backdrop_at_all(self):
        """Every panel written before this block existed still compiles to what it
        always did."""
        assert solve_backdrop(SettingSpec(), PANEL) is None

    def test_weather_needs_no_masses(self):
        backdrop = solve_backdrop(SettingSpec(weather=Weather.RAIN), PANEL)
        assert backdrop is not None
        assert backdrop.masses == ()
        assert backdrop.atmosphere is not None

    @pytest.mark.parametrize("weather", [Weather.FOG, Weather.RAIN, Weather.SNOW])
    def test_every_weather_but_clear_carries_a_veil(self, weather: Weather):
        """Fog is the veil; rain and snow carry it as cloud."""
        backdrop = solve_backdrop(SettingSpec(weather=weather), PANEL)
        assert backdrop is not None
        assert backdrop.atmosphere is not None
        veil = backdrop.atmosphere.veil
        assert veil is not None
        assert 0.0 < veil.opacity <= 1.0
        assert veil.frequency > 0
        assert veil.octaves >= 1

    def test_fog_is_the_densest_veil(self):
        def opacity(weather: Weather) -> float:
            backdrop = solve_backdrop(SettingSpec(weather=weather), PANEL)
            assert backdrop is not None
            assert backdrop.atmosphere is not None
            assert backdrop.atmosphere.veil is not None
            return backdrop.atmosphere.veil.opacity

        assert opacity(Weather.FOG) > opacity(Weather.RAIN)

    def test_rain_falls_as_streaks_and_snow_as_flecks(self):
        rain = solve_backdrop(SettingSpec(weather=Weather.RAIN), PANEL)
        snow = solve_backdrop(SettingSpec(weather=Weather.SNOW), PANEL)
        assert rain is not None
        assert snow is not None
        assert rain.atmosphere is not None
        assert snow.atmosphere is not None
        assert rain.atmosphere.streaks
        assert not rain.atmosphere.flecks
        assert snow.atmosphere.flecks
        assert not snow.atmosphere.streaks

    def test_rain_falls_at_one_angle(self):
        """Rain drawn at scattered angles reads as static, not as weather."""
        backdrop = solve_backdrop(SettingSpec(weather=Weather.RAIN), PANEL)
        assert backdrop is not None
        assert backdrop.atmosphere is not None
        angles = {
            round(math.atan2(end.y - start.y, end.x - start.x), 6)
            for start, end in backdrop.atmosphere.streaks
        }
        assert len(angles) == 1

    def test_the_veil_takes_the_atmosphere_tone_of_the_hour(self):
        """Fog *is* the atmosphere arriving in the foreground, so it is tinted with it."""
        for time in TimeOfDay:
            backdrop = solve_backdrop(SettingSpec(weather=Weather.FOG, time=time), PANEL)
            assert backdrop is not None
            assert backdrop.atmosphere is not None
            assert backdrop.atmosphere.tone == LADDER[time][ATMOSPHERE]
            assert backdrop.atmosphere.veil is not None
            assert backdrop.atmosphere.veil.tone == LADDER[time][ATMOSPHERE]

    @pytest.mark.parametrize("weather", [Weather.RAIN, Weather.SNOW])
    def test_cloud_is_nearer_than_the_sky_it_covers(self, weather: Weather):
        """Which is also what makes a snowy panel legible: a snowy sky is overcast
        rather than bright, and white flakes need something to be white against."""
        backdrop = solve_backdrop(SettingSpec(weather=weather), PANEL)
        assert backdrop is not None
        assert backdrop.atmosphere is not None
        assert backdrop.atmosphere.veil is not None
        assert lightness(backdrop.atmosphere.veil.tone) < lightness(backdrop.atmosphere.tone)

    def test_rain_flips_to_stay_visible_but_snow_never_does(self):
        """A white streak is invisible against noon and a black one against midnight, so
        rain follows the ground it falls over. Snow does not: snow is white, and a black
        snowflake is not a thing any comic has drawn."""

        def falling(weather: Weather, time: TimeOfDay) -> str:
            backdrop = solve_backdrop(SettingSpec(weather=weather, time=time), PANEL)
            assert backdrop is not None
            assert backdrop.atmosphere is not None
            return backdrop.atmosphere.fall_tone

        assert lightness(falling(Weather.RAIN, TimeOfDay.DAY)) < lightness(
            falling(Weather.RAIN, TimeOfDay.NIGHT)
        )
        assert len({falling(Weather.SNOW, time) for time in TimeOfDay}) == 1

    def test_falling_weather_stays_inside_the_panel(self):
        for weather in (Weather.RAIN, Weather.SNOW):
            backdrop = solve_backdrop(SettingSpec(weather=weather), PANEL)
            assert backdrop is not None
            assert backdrop.atmosphere is not None
            points = [point for pair in backdrop.atmosphere.streaks for point in pair] + [
                circle.centre for circle in backdrop.atmosphere.flecks
            ]
            for point in points:
                assert -0.01 <= point.x <= PANEL.width + 0.01
                assert -0.01 <= point.y <= PANEL.height + 0.01


class TestDeterminism:
    """The project's own non-negotiable, and the one this feature is most able to break.

    Seeded silhouettes are exactly where an unseeded RNG or a salted hash would get in.
    """

    def test_the_same_setting_resolves_identically(self):
        setting = _setting(*PLACES[Place.STREET], time=TimeOfDay.DUSK, weather=Weather.RAIN)
        first = solve_backdrop(setting, PANEL)
        second = solve_backdrop(setting, PANEL)
        assert first == second

    def test_the_seed_comes_from_the_declared_content(self):
        one = seed_for(_setting(Mass(kind=MassKind.SKY)), 1000.0, 700.0)
        again = seed_for(_setting(Mass(kind=MassKind.SKY)), 1000.0, 700.0)
        other = seed_for(_setting(Mass(kind=MassKind.WATER)), 1000.0, 700.0)
        assert one == again
        assert one != other

    def test_the_panel_size_is_part_of_the_seed(self):
        setting = _setting(Mass(kind=MassKind.BUILDING))
        assert seed_for(setting, 1000.0, 700.0) != seed_for(setting, 900.0, 700.0)

    def test_it_survives_a_fresh_interpreter(self):
        """The test a same-process comparison cannot do.

        `hash()` is salted per process, so a seed derived from it agrees with itself all
        day and disagrees with tomorrow's build. Two subprocesses, each with its own
        salt, is what catches that.
        """
        program = textwrap.dedent("""
            from scenet import compile_source
            print(compile_source(
                "{panel: {size: [900, 600]}, cast: {a: {reference: alice}},"
                " setting: {place: docks, time: dusk, weather: snow}}"
            ).core.to_json())
        """)
        runs = [
            subprocess.run(  # noqa: S603 -- our own interpreter, running a literal in this file
                [sys.executable, "-c", program],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            for _ in range(2)
        ]
        assert json.loads(runs[0]) == json.loads(runs[1])
        assert runs[0] == runs[1]
