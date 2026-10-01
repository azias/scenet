"""Emanata: the marks a comic draws around a character rather than on them.

Plewds, squeans, grawlixes and briffits, from Mort Walker's *The Lexicon of Comicana*.
What separates them from a face is where they sit. A face is inside the head circle,
which balloons are already forbidden to cover; emanata are **outside** it, in exactly
the space balloons are placed in. That makes them a solver concern, and the decision
these tests pin down is how much of one.

The answer is: a soft cost and nothing more. Emanata stay out of the hull, so no actor
moves, the camera does not retreat, and every panel without marks lays out exactly as
it did before they existed. A balloon prefers not to cover them, and when a panel is
too crowded to oblige, covers them rather than failing.

Whether a plewd reads as sweat at `long_shot` is a question about a picture. That is
what `scripts/contact_sheet.py --marks` is for.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from scenet.assets.contract import Landmark, PuppetLibrary, default_library
from scenet.assets.emanata import MIN_EMANATA_DETAIL, ResolvedEmanata, build_emanata
from scenet.assets.face import MIN_FEATURE_RADIUS, FaceMark, ResolvedDisc, ResolvedStroke
from scenet.assets.kinematics import ResolvedPuppet, resolve
from scenet.core import CoreActor, FaceDisc, PanelCore
from scenet.diagnostics import diagnose_source
from scenet.emit.debug_svg import render_debug
from scenet.emit.svg import render
from scenet.errors import PanelSyntaxError
from scenet.frontends.script_front import parse_script
from scenet.geom import BBox, Point
from scenet.ir import CastMember, Mark, PanelIR
from scenet.pipeline import FRONTENDS, compile_ir, compile_scene, compile_source
from scenet.solve.balloons import (
    W_EMANATA_OCCLUSION,
    W_OCCLUSION,
    _emanata_cost,
    _emanata_shapes,
)

REPO = Path(__file__).parent.parent
DOCUMENTS = sorted(
    path
    for path in (REPO / "examples").rglob("*")
    if path.suffix in {".yaml", ".script"} and path.name != "manifest.yaml"
)
EVERY_MARK = "[plewds, squeans, grawlixes, briffits]"
SAYS = ", script: [{say: {by: a, text: 'What the--'}}]"


@pytest.fixture(scope="module")
def library() -> PuppetLibrary:
    return default_library()


def _source(marks: str, *, shot: str = "medium_shot", script: str = "") -> str:
    return (
        f"{{camera: {{shot: {shot}}}, "
        f"cast: {{a: {{reference: alice, at: center, marks: {marks}}}}}{script}}}"
    )


def _actor(marks: str, *, shot: str = "medium_shot") -> CoreActor:
    return compile_source(_source(marks, shot=shot)).core.actor("a")


def _posed(
    library: PuppetLibrary, face_radius: float, *, facing_right: bool = True
) -> ResolvedPuppet:
    """Alice, scaled so that her face circle has exactly this radius."""
    spec = library.get("alice")
    return resolve(
        spec,
        pose="standing_neutral",
        facing_right=facing_right,
        scale=face_radius / spec.face.radius,
        origin=Point(500, 500),
    )


class TestTheVocabulary:
    def test_it_is_walkers(self):
        """Comics-native, closed and citable -- the same three properties that made
        Blambot the source for captions and Comic Chat the source for faces."""
        assert {mark.value for mark in Mark} == {"plewds", "squeans", "grawlixes", "briffits"}

    def test_marks_default_to_none(self):
        assert CastMember(reference="alice").marks == ()

    def test_an_unknown_mark_is_rejected(self):
        with pytest.raises(PanelSyntaxError, match="sweat"):
            compile_source(_source("[sweat]"))

    def test_an_unknown_mark_is_located(self):
        """The checker has to point at the offending entry, not at the document."""
        (found,) = diagnose_source(
            "cast: {a: {reference: alice, marks: [plewds, sweat]}}\n",
            source=Path("x.panel.yaml"),
        )
        assert found.path[:3] == ("cast", "a", "marks")
        assert "sweat" in found.message

    def test_a_mark_listed_twice_is_rejected(self):
        """Harmless, but almost certainly a slip -- and the language rejects slips."""
        with pytest.raises(ValidationError, match="more than once"):
            CastMember(reference="alice", marks=(Mark.PLEWDS, Mark.PLEWDS))

    def test_authoring_order_does_not_matter(self):
        """They compose rather than sequence: sweating and reeling is the same state
        as reeling and sweating, and must compile to the same bytes."""
        one = compile_source(_source("[plewds, squeans]")).core.to_json()
        other = compile_source(_source("[squeans, plewds]")).core.to_json()
        assert one == other

    def test_they_compose_with_an_expression(self):
        """The reason this is a list and not a second `expression:`."""
        actor = compile_source(
            "{camera: {shot: medium_shot}, "
            "cast: {a: {reference: alice, expression: angry, marks: [plewds, grawlixes]}}}"
        ).core.actor("a")
        assert actor.expression == "angry"
        assert actor.marks == (Mark.GRAWLIXES, Mark.PLEWDS)
        assert actor.face_marks
        assert actor.emanata

    def test_the_script_frontend_accepts_them(self):
        source = (
            "---\ncast:\n  ALICE: {reference: alice, marks: [plewds]}\n---\n\n"
            "PANEL 1\n@shot: medium_shot\nShe is sweating.\n\nALICE\nIs it hot in here?\n"
        )
        (panel,) = parse_script(source).values()
        assert compile_ir(panel).core.actor("ALICE").marks == (Mark.PLEWDS,)

    def test_a_scene_panel_can_clear_inherited_marks(self):
        """Lists replace wholesale under `over`, so `marks: []` is how a panel says the
        sweating has stopped."""
        results = compile_scene(
            "cast: {a: {reference: alice, marks: [plewds]}}\n"
            "panels:\n"
            "  before: {}\n"
            "  after: {over: before, cast: {a: {marks: []}}}\n"
        )
        assert results["before"].core.actor("a").emanata
        assert results["after"].core.actor("a").emanata == ()


class TestWhereTheyAreDrawn:
    @pytest.mark.parametrize("mark", list(Mark))
    def test_every_mark_draws_something(self, library: PuppetLibrary, mark: Mark):
        drawn = build_emanata(_posed(library, 120), (mark,))
        assert drawn.marks
        assert drawn.zones

    @pytest.mark.parametrize("mark", [Mark.PLEWDS, Mark.SQUEANS, Mark.GRAWLIXES])
    def test_head_marks_sit_outside_the_head(self, library: PuppetLibrary, mark: Mark):
        """What makes them emanata rather than features -- and what makes them the
        solver's business at all."""
        posed = _posed(library, 120)
        for point in _points(build_emanata(posed, (mark,)).marks):
            assert point.distance_to(posed.face.centre) > posed.face.r

    @pytest.mark.parametrize("mark", [Mark.SQUEANS, Mark.GRAWLIXES])
    def test_reeling_and_swearing_go_over_the_head(self, library: PuppetLibrary, mark: Mark):
        posed = _posed(library, 120)
        for point in _points(build_emanata(posed, (mark,)).marks):
            assert point.y < posed.face.cy

    @pytest.mark.parametrize("facing_right", [True, False])
    def test_plewds_fly_mostly_off_the_back_of_the_head(
        self, library: PuppetLibrary, facing_right: bool
    ):
        """The side a character faces is the side their gaze and their balloons want,
        so that is the side the sweat mostly stays off."""
        posed = _posed(library, 120, facing_right=facing_right)
        behind = -1.0 if facing_right else 1.0
        offsets = [
            point.x - posed.face.cx for point in _points(build_emanata(posed, (Mark.PLEWDS,)).marks)
        ]
        assert sum(1 for dx in offsets if dx * behind > 0) > len(offsets) / 2

    def test_plewds_mirror_with_the_figure(self, library: PuppetLibrary):
        right = _posed(library, 120, facing_right=True)
        left = _posed(library, 120, facing_right=False)
        assert right.face.cx == pytest.approx(left.face.cx)
        cx = right.face.cx
        reflected = sorted(
            round(2 * cx - point.x, 6)
            for point in _points(build_emanata(left, (Mark.PLEWDS,)).marks)
        )
        assert reflected == sorted(
            round(point.x, 6) for point in _points(build_emanata(right, (Mark.PLEWDS,)).marks)
        )

    @pytest.mark.parametrize("facing_right", [True, False])
    def test_briffits_are_left_behind_on_the_ground(
        self, library: PuppetLibrary, facing_right: bool
    ):
        """A dust cloud is where the character *was*: behind them, at their feet."""
        posed = _posed(library, 120, facing_right=facing_right)
        points = _points(build_emanata(posed, (Mark.BRIFFITS,)).marks)
        ground = posed.landmarks[Landmark.FEET]
        assert all(point.y <= ground + 1e-6 for point in points)
        assert all(point.y > posed.landmarks[Landmark.KNEES] for point in points)
        centre_x = sum(point.x for point in points) / len(points)
        assert (centre_x < posed.face.cx) == facing_right

    @pytest.mark.parametrize("mark", list(Mark))
    def test_the_zone_covers_every_mark(self, library: PuppetLibrary, mark: Mark):
        """The zone is the whole of what the solver sees. A mark outside it is a mark
        a balloon can land on without paying for it."""
        drawn = build_emanata(_posed(library, 120), (mark,))
        zone = _union(drawn.zones).buffer(1e-6)
        for point in _points(drawn.marks):
            assert zone.contains(ShapelyPoint(point.x, point.y))

    def test_ids_are_unique_within_an_actor(self, library: PuppetLibrary):
        drawn = build_emanata(_posed(library, 120), tuple(sorted(Mark)))
        ids = [mark.id for mark in drawn.marks]
        assert len(ids) == len(set(ids))

    def test_the_four_marks_are_four_different_drawings(self, library: PuppetLibrary):
        posed = _posed(library, 120)
        drawings = {build_emanata(posed, (mark,)).marks for mark in Mark}
        assert len(drawings) == len(Mark)

    def test_no_marks_draw_nothing(self, library: PuppetLibrary):
        assert build_emanata(_posed(library, 120), ()) == ResolvedEmanata()


class TestLevelOfDetail:
    """A plewd at `long_shot` is a dot. Below the face's own threshold, it is nothing."""

    @pytest.mark.parametrize("mark", list(Mark))
    def test_above_the_threshold_they_are_drawn_in_full(self, library: PuppetLibrary, mark: Mark):
        drawn = build_emanata(_posed(library, MIN_EMANATA_DETAIL * 1.1), (mark,))
        assert any(isinstance(item, ResolvedStroke) for item in drawn.marks)

    @pytest.mark.parametrize("mark", [Mark.PLEWDS, Mark.SQUEANS, Mark.GRAWLIXES])
    def test_between_the_thresholds_they_are_dots(self, library: PuppetLibrary, mark: Mark):
        radius = (MIN_FEATURE_RADIUS + MIN_EMANATA_DETAIL) / 2
        drawn = build_emanata(_posed(library, radius), (mark,))
        assert drawn.marks
        assert all(isinstance(item, ResolvedDisc) and item.filled for item in drawn.marks)

    @pytest.mark.parametrize("mark", list(Mark))
    def test_below_the_face_threshold_they_are_not_drawn(self, library: PuppetLibrary, mark: Mark):
        """Tied to the face's threshold on purpose: a character too small to have a
        face is too small to be sweating."""
        drawn = build_emanata(_posed(library, MIN_FEATURE_RADIUS * 0.9), (mark,))
        assert drawn == ResolvedEmanata()

    def test_the_detail_threshold_sits_above_the_face_threshold(self):
        assert MIN_EMANATA_DETAIL > MIN_FEATURE_RADIUS

    def test_long_shot_draws_dots(self):
        actor = _actor("[plewds]", shot="long_shot")
        assert actor.emanata
        assert all(isinstance(mark, FaceDisc) and mark.filled for mark in actor.emanata)

    def test_stroke_width_follows_the_head(self):
        near = _actor("[grawlixes]", shot="medium_close_up")
        far = _actor("[grawlixes]", shot="medium_shot")
        assert _widest(near) > _widest(far)


class TestTheHullDecision:
    """Emanata stay out of the hull. This is the proof that doing so moves nothing."""

    def test_marks_do_not_change_the_figure(self):
        bare, marked = _actor("[]"), _actor(EVERY_MARK)
        assert marked.hull == bare.hull
        assert marked.transform == bare.transform
        assert marked.face_exclusion == bare.face_exclusion

    @pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
    def test_marking_every_actor_moves_no_actor(self, path: Path):
        """Every example in the repository, recompiled with every mark on every cast
        member. Each figure is exactly where it was -- and every panel still compiles,
        which is what a soft term buys over a hard one."""
        everything = tuple(sorted(Mark))
        for name, panel in FRONTENDS[path.suffix](path).items():
            plain = compile_ir(panel).core
            marked = compile_ir(_with_marks(panel, everything)).core
            for before, after in zip(plain.actors, marked.actors, strict=True):
                assert after.transform == before.transform, f"{path.name}:{name}"
                assert after.hull == before.hull, f"{path.name}:{name}"
                assert after.face_exclusion == before.face_exclusion, f"{path.name}:{name}"

    @pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
    def test_a_panel_without_marks_carries_none(self, path: Path):
        """The other half of "every existing layout is unchanged": nothing appears in
        a Core document that did not ask for it."""
        for panel in FRONTENDS[path.suffix](path).values():
            if any(member.marks for member in panel.cast.values()):
                continue
            for actor in compile_ir(panel).core.actors:
                assert actor.emanata == ()
                assert actor.emanata_zones == ()


class TestBalloonsKeepOffThem:
    def test_a_balloon_moves_off_the_grawlixes(self):
        """Without marks, the first place tried -- straight above the speaker -- wins.
        That is exactly where grawlixes go, and a balloon over them erases the oath."""
        bare = compile_source(_source("[]", script=SAYS)).core
        marked = compile_source(_source("[grawlixes]", script=SAYS)).core
        zone = _union(marked.actor("a").emanata_zones)

        assert _covered(bare, zone) > 0, "the case only tests something if it collides"
        assert _covered(marked, zone) < _covered(bare, zone)

    def test_the_cost_is_the_covered_fraction_of_the_box(self, library: PuppetLibrary):
        """Normalised exactly as hull occlusion is, so the weights are comparable --
        and with no forgiveness for the speaker. A balloon resting on its own speaker's
        shoulder reads naturally; one over its own speaker's sweat still hides it."""
        zones = build_emanata(_posed(library, 120), (Mark.GRAWLIXES,)).zones
        polygon = _union(zones)
        minx, miny, maxx, maxy = polygon.bounds
        candidate = BBox(minx, miny, maxx - minx, maxy - miny)
        cost = _emanata_cost(candidate, _emanata_shapes({"a": zones}))
        assert cost == pytest.approx(W_EMANATA_OCCLUSION * polygon.area / candidate.area)

    def test_it_costs_more_than_covering_a_body(self):
        """Covering a shoulder hides a shoulder. Covering a plewd deletes what the
        panel was saying about the character."""
        assert W_EMANATA_OCCLUSION > W_OCCLUSION

    def test_with_no_marks_the_term_is_exactly_zero(self):
        assert _emanata_cost(BBox(0, 0, 100, 100), []) == 0.0


class TestPanelCore:
    def test_it_survives_a_round_trip_through_json(self):
        core = compile_source(_source(EVERY_MARK)).core
        assert PanelCore.from_json(core.to_json()) == core
        assert core.actor("a").emanata_zones

    def test_it_is_deterministic(self):
        source = _source(EVERY_MARK, script=SAYS)
        first, second = compile_source(source).core, compile_source(source).core
        assert first.to_json() == second.to_json()
        assert render(first) == render(second)


class TestEmitters:
    def test_two_marked_actors_have_distinct_ids(self):
        """Two characters can sweat at once, and duplicate ids in one SVG document are
        malformed."""
        svg = render(
            compile_source(
                "{camera: {shot: medium_shot}, cast: {"
                "a: {reference: alice, marks: [plewds]}, "
                "b: {reference: bob, marks: [plewds], facing: left}}, staging: [a left_of b]}"
            ).core
        )
        assert _ids_are_unique(svg)
        assert 'id="emanata-a-plewd_0"' in svg
        assert 'id="emanata-b-plewd_0"' in svg

    def test_they_do_not_collide_with_face_ids(self):
        assert _ids_are_unique(render(compile_source(_source(EVERY_MARK)).core))

    def test_the_debug_overlay_shows_the_zone(self):
        assert "emanata-zone" in render_debug(compile_source(_source("[plewds]")).core)
        assert "emanata-zone" not in render_debug(compile_source(_source("[]")).core)


def _points(marks: Sequence[FaceMark]) -> list[Point]:
    """Every point a set of resolved marks is drawn through."""
    points: list[Point] = []
    for mark in marks:
        if isinstance(mark, ResolvedDisc):
            points.append(mark.centre)
        else:
            points.extend(mark.points)
    return points


def _with_marks(panel: PanelIR, marks: tuple[Mark, ...]) -> PanelIR:
    cast = {
        actor: member.model_copy(update={"marks": marks}) for actor, member in panel.cast.items()
    }
    return panel.model_copy(update={"cast": cast})


def _union(zones: Sequence[Sequence[Point]] | Sequence[Sequence[tuple[float, float]]]) -> Polygon:
    return unary_union(
        [Polygon([(p.x, p.y) if isinstance(p, Point) else p for p in zone]) for zone in zones]
    )


def _covered(core: PanelCore, zone: Polygon) -> float:
    """How much of the zone the panel's balloons sit on."""
    return sum(
        box(item.box.x, item.box.y, item.box.x + item.box.width, item.box.y + item.box.height)
        .intersection(zone)
        .area
        for item in core.balloons
    )


def _widest(actor: CoreActor) -> float:
    return max(mark.width for mark in actor.emanata)


def _ids_are_unique(svg: str) -> bool:
    ids = [chunk.split('"')[0] for chunk in svg.split(' id="')[1:]]
    return len(ids) == len(set(ids))
