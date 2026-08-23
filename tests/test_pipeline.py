"""End-to-end compilation, and the invariants a compiled panel must satisfy.

The invariant tests are the important ones. A solver has an enormous space of possible
outputs and no obvious "correct" coordinate to assert against, so what can be checked
is that certain things are *never* true: no balloon over a face, none outside the
panel, none out of reading order. Those hold for every input or the compiler is wrong.
"""

import math
from itertools import pairwise
from pathlib import Path
from xml.etree import ElementTree

import pytest

from scenet.assets.contract import default_library
from scenet.core import PanelCore
from scenet.emit.debug_svg import render_debug
from scenet.emit.svg import fmt, render
from scenet.geom import BBox, Circle
from scenet.pipeline import compile_file, compile_source
from scenet.solve.balloons import READING_EPSILON

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

PANELS = [
    # A minimal panel: one actor, nothing said.
    "cast:\n  a: {reference: alice}\n",
    # Dialogue between two actors.
    """
camera: {shot: medium_shot}
cast:
  alice: {reference: alice, at: left_third, facing: right}
  bob:   {reference: bob,   at: right_third, facing: left}
staging:
  - alice left_of bob
  - alice ground_shared_with bob
script:
  - say: {by: alice, text: "You forgot your umbrella!", prefer: top_left}
  - say: {by: bob,   text: "I know."}
""",
    # A crowd, which forces the camera to retreat.
    """
camera: {shot: close_up}
cast:
  a: {reference: alice}
  b: {reference: bob}
  c: {reference: alice, pose: hands_on_hips}
script:
  - say: {by: a, text: "Everyone is here."}
  - say: {by: c, text: "So it seems."}
""",
    # Every balloon kind, and a wide shot.
    """
camera: {shot: full_shot, angle: high}
cast:
  a: {reference: alice, at: left_third}
  b: {reference: bob, at: right_third}
script:
  - say: {by: a, text: "Psst.", kind: whisper}
  - say: {by: b, text: "WHAT?!", kind: shout}
  - say: {by: a, text: "I wonder about him.", kind: thought}
""",
    # A tall narrow panel, to catch anything assuming a square.
    """
panel: {size: [500, 1100], margin: 20}
camera: {shot: medium_close_up}
cast:
  a: {reference: bob}
script:
  - say: {by: a, text: "Tight quarters in here."}
""",
]


@pytest.fixture(scope="module")
def compiled() -> list[PanelCore]:
    library = default_library()
    return [compile_source(source, library=library).core for source in PANELS]


class TestInvariants:
    """Properties that must hold for every panel the compiler accepts."""

    def test_balloons_never_cover_a_face(self, compiled: list[PanelCore]):
        """The one hard exclusion: a balloon over a face destroys the panel."""
        for index, core in enumerate(compiled):
            faces = [actor.face_exclusion.as_circle() for actor in core.actors]
            for balloon in core.balloons:
                for face in faces:
                    assert not balloon.box.as_bbox().intersects_circle(face), (
                        f"panel {index}: balloon {balloon.id} covers a face"
                    )

    def test_balloons_stay_inside_the_panel(self, compiled: list[PanelCore]):
        for index, core in enumerate(compiled):
            for balloon in core.balloons:
                assert core.bounds.contains(balloon.box.as_bbox()), (
                    f"panel {index}: balloon {balloon.id} leaves the panel"
                )

    def test_balloons_never_overlap_each_other(self, compiled: list[PanelCore]):
        for index, core in enumerate(compiled):
            boxes = [balloon.box.as_bbox() for balloon in core.balloons]
            for i, first in enumerate(boxes):
                for second in boxes[i + 1 :]:
                    assert first.overlap_area(second) == 0, f"panel {index}: balloons overlap"

    def test_reading_order_is_monotone(self, compiled: list[PanelCore]):
        """A balloon may sit below its predecessor or to its right, never both above
        and left. Violating this makes the panel read in the wrong order, which is a
        correctness bug rather than a cosmetic one."""
        for index, core in enumerate(compiled):
            ordered = sorted(core.balloons, key=lambda b: b.order)
            for previous, current in pairwise(ordered):
                below = current.box.y >= previous.box.y - READING_EPSILON
                right_of = current.box.x >= previous.box.right - READING_EPSILON
                assert below or right_of, f"panel {index}: {current.id} reads before {previous.id}"

    def test_every_tail_reaches_its_speaker(self, compiled: list[PanelCore]):
        """A balloon whose tail does not arrive at its speaker has no attributed
        voice, which is worse than no balloon at all."""
        for index, core in enumerate(compiled):
            for balloon in core.balloons:
                speaker = core.actor(balloon.speaker)
                face = speaker.face_exclusion.as_circle()
                end = balloon.tail.end
                distance = math.hypot(end[0] - face.cx, end[1] - face.cy)
                assert distance <= face.r * 1.35, (
                    f"panel {index}: tail of {balloon.id} does not reach {balloon.speaker}"
                )

    def test_tails_start_on_their_balloon(self, compiled: list[PanelCore]):
        for core in compiled:
            for balloon in core.balloons:
                box = balloon.box.as_bbox().expanded(1.5)
                start = balloon.tail.start
                assert box.x <= start[0] <= box.right
                assert box.y <= start[1] <= box.bottom

    def test_actors_never_overlap(self, compiled: list[PanelCore]):
        for index, core in enumerate(compiled):
            boxes = sorted((actor.bounds for actor in core.actors), key=lambda b: b.x)
            for first, second in pairwise(boxes):
                assert first.right <= second.x + 0.5, f"panel {index}: actors overlap"

    def test_every_actor_is_at_least_partly_visible(self, compiled: list[PanelCore]):
        """Bleeding off an edge is normal comics practice; vanishing entirely is not."""
        for index, core in enumerate(compiled):
            for actor in core.actors:
                assert actor.bounds.overlap_area(core.bounds) > 0, (
                    f"panel {index}: actor {actor.id} is entirely off-panel"
                )


class TestDeterminism:
    def test_recompiling_gives_byte_identical_core(self):
        library = default_library()
        for source in PANELS:
            first = compile_source(source, library=library).core.to_json()
            second = compile_source(source, library=library).core.to_json()
            assert first == second

    def test_recompiling_gives_byte_identical_svg(self):
        library = default_library()
        for source in PANELS:
            core = compile_source(source, library=library).core
            assert render(core) == render(compile_source(source, library=library).core)

    def test_core_survives_a_json_round_trip(self, compiled: list[PanelCore]):
        """Panel Core is a real writable format, not a private data structure, so it
        must reload exactly."""
        for core in compiled:
            assert PanelCore.from_json(core.to_json()) == core

    def test_negative_zero_is_normalised(self):
        """-0.0 and 0.0 are equal but format differently, which would produce phantom
        golden-file diffs."""
        assert fmt(-0.0) == "0"
        assert fmt(-0.001) == "0"


class TestEmitters:
    def test_svg_is_well_formed(self, compiled: list[PanelCore]):
        for core in compiled:
            ElementTree.fromstring(render(core))

    def test_debug_svg_is_well_formed(self, compiled: list[PanelCore]):
        for core in compiled:
            ElementTree.fromstring(render_debug(core))

    def test_dialogue_is_never_emitted_as_raw_text_by_default(self, compiled: list[PanelCore]):
        """Lettering goes out as glyph outlines so the file depends on no installed
        font and renders exactly what was measured."""
        core = compiled[1]
        assert "<text" not in render(core)
        assert "<text" in render(core, live_text=True)

    def test_live_text_escapes_markup(self):
        core = compile_source(
            'cast:\n  a: {reference: alice}\nscript:\n  - say: {by: a, text: "<b>&</b>"}\n'
        ).core
        rendered = render(core, live_text=True)
        assert "<b>" not in rendered
        assert "&lt;b&gt;" in rendered

    def test_svg_declares_the_panel_size(self):
        core = compile_source("panel: {size: [640, 480]}\ncast:\n  a: {reference: alice}\n").core
        rendered = render(core)
        assert 'width="640"' in rendered
        assert 'viewBox="0 0 640 480"' in rendered


class TestExample:
    def test_shipped_example_compiles(self):
        result = compile_file(EXAMPLES / "duel.panel.yaml")
        assert len(result.core.actors) == 2
        assert len(result.core.balloons) == 2

    def test_a_retreating_camera_is_reported(self):
        """Diagnostics are part of the result, not log noise, so tooling can surface
        that the requested framing was loosened."""
        result = compile_file(EXAMPLES / "duel.panel.yaml")
        assert any("retreated" in note for note in result.notes)


class TestGeometryHelpers:
    def test_circle_box_intersection_uses_nearest_point(self):
        box = BBox(0, 0, 10, 10)
        assert box.intersects_circle(Circle(12, 5, 3))
        assert not box.intersects_circle(Circle(14, 5, 3))

    def test_diagonal_near_miss_is_not_an_intersection(self):
        """A naive centre-distance test would wrongly report a hit here."""
        box = BBox(0, 0, 10, 10)
        assert not box.intersects_circle(Circle(13, 13, 4))
