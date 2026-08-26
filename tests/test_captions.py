"""Caption boxes: placement, lettering and the typographic rules that go with them.

A caption is the panel speaking in its own voice, and it goes through the same
placement machinery as a balloon rather than a parallel one -- face avoidance, hull
occlusion and reading order are the same problem whichever kind of box is being
positioned.

Two of these tests guard rules that are easy to get subtly wrong. Quotation marks are
applied *before* measurement, because text the emitter adds afterwards would not fit
the box drawn for it. And the italic face is a real font file, not a skew: the tests
check the measured width, which is the only thing that proves the right face was used.
"""

import pytest

from scenet.core import PanelCore
from scenet.emit.debug_svg import render_debug
from scenet.emit.svg import render
from scenet.errors import BalloonPlacementError
from scenet.geom import BBox
from scenet.ir import CaptionKind
from scenet.pipeline import compile_source
from scenet.solve.balloons import (
    CAPTION_PADDING_FACTOR,
    CLOSING_QUOTE,
    OPENING_QUOTE,
    _caption_positions,
)
from scenet.solve.text import ITALIC_FONT_PATH, balloon_size, layout_text, load_metrics

PANEL = BBox(0.0, 0.0, 1000.0, 800.0)


def compile_panel(script: str, *, cast: str = "  alice: {reference: alice}\n") -> PanelCore:
    return compile_source(f"cast:\n{cast}script:\n{script}").core


class TestCandidatePositions:
    def test_every_candidate_fits_inside_the_panel(self):
        boxes = _caption_positions((240.0, 90.0), PANEL)
        outside = [box for box in boxes if not PANEL.contains(box)]
        assert outside == []

    def test_there_is_one_candidate_per_placement_zone(self):
        """Derived from PlacementZone rather than a hand-written list, so a new zone
        cannot leave captions unable to reach it."""
        assert len(_caption_positions((240.0, 90.0), PANEL)) == 9

    def test_the_corners_are_tucked_against_the_panel_edge(self):
        boxes = _caption_positions((240.0, 90.0), PANEL)
        assert min(box.x for box in boxes) < PANEL.width * 0.05
        assert max(box.right for box in boxes) > PANEL.width * 0.95

    def test_generation_is_deterministic(self):
        first = _caption_positions((240.0, 90.0), PANEL)
        second = _caption_positions((240.0, 90.0), PANEL)
        assert first == second


class TestPlacement:
    def test_a_caption_reaches_panel_core(self):
        core = compile_panel('  - caption: {text: "Midnight. The docks."}\n')
        assert len(core.captions) == 1
        assert core.captions[0].id == "c0"

    def test_it_never_covers_a_face(self):
        """The same hard rule balloons obey. A box over a face is never acceptable,
        whatever else it has going for it."""
        core = compile_panel("""  - caption: {text: "Midnight. The docks.", prefer: middle_center}
""")
        box = core.captions[0].box.as_bbox()
        faces = [actor.face_exclusion.as_circle() for actor in core.actors]
        assert not any(box.intersects_circle(face) for face in faces)

    def test_it_honours_the_preferred_zone(self):
        left = compile_panel('  - caption: {text: "Midnight.", prefer: top_left}\n')
        right = compile_panel('  - caption: {text: "Midnight.", prefer: top_right}\n')
        assert left.captions[0].box.x < right.captions[0].box.x

    def test_top_left_is_the_default(self):
        core = compile_panel('  - caption: {text: "Midnight. The docks."}\n')
        box = core.captions[0].box
        assert box.x < core.width / 2
        assert box.y < core.height / 2

    def test_two_captions_do_not_overlap(self):
        core = compile_panel("""  - caption: {text: "Midnight."}
  - caption: {text: "The docks."}
""")
        first, second = (caption.box.as_bbox() for caption in core.captions)
        assert first.overlap_area(second) == 0

    def test_a_panel_with_no_room_left_is_refused(self):
        """There are nine candidate positions and boxes may not overlap, so a panel
        can genuinely run out of room. Refusing is right: a caption dropped silently
        is a line of the script that never reaches the page."""
        crowd = "".join(f'  - caption: {{text: "Caption {index}"}}\n' for index in range(9))
        with pytest.raises(BalloonPlacementError, match="no legal position for caption"):
            compile_panel(crowd)


class TestReadingOrder:
    """A caption takes part in reading order like anything else that carries words."""

    def test_a_leading_caption_is_read_before_the_dialogue(self):
        core = compile_panel("""  - caption: {text: "Midnight. The docks."}
  - say: {by: alice, text: "You forgot your umbrella!"}
""")
        caption, balloon = core.captions[0], core.balloons[0]
        assert caption.order < balloon.order
        # Never above-and-left of its predecessor: the rule, stated the other way up.
        assert balloon.box.y >= caption.box.y or balloon.box.x >= caption.box.right

    def test_a_trailing_caption_is_read_after_the_dialogue(self):
        """The reason placement is one pass in script order rather than captions
        first: a caption written last must not constrain the balloons before it."""
        core = compile_panel("""  - say: {by: alice, text: "You forgot your umbrella!"}
  - caption: {text: "Later.", prefer: bottom_right}
""")
        caption, balloon = core.captions[0], core.balloons[0]
        assert balloon.order < caption.order
        assert caption.box.y >= balloon.box.y or caption.box.x >= balloon.box.right

    def test_order_counts_across_both_kinds_of_box(self):
        core = compile_panel("""  - say: {by: alice, text: "Hello."}
  - caption: {text: "Later."}
  - say: {by: alice, text: "Still here."}
""")
        assert [balloon.order for balloon in core.balloons] == [0, 2]
        assert [caption.order for caption in core.captions] == [1]


class TestQuotationMarks:
    """Blambot's rule for a run of spoken captions: open quotes on each, close only
    on the last. It is objective, so it is testable."""

    def test_a_lone_spoken_caption_is_opened_and_closed(self):
        core = compile_panel('  - caption: {text: "Get down!", kind: spoken}\n')
        text = " ".join(core.captions[0].lines)
        assert text.startswith(OPENING_QUOTE)
        assert text.endswith(CLOSING_QUOTE)

    def test_a_run_closes_only_on_the_last(self):
        core = compile_panel("""  - caption: {text: "Get down!", kind: spoken}
  - caption: {text: "All of you!", kind: spoken}
""")
        first, second = (" ".join(caption.lines) for caption in core.captions)
        assert first.startswith(OPENING_QUOTE)
        assert not first.endswith(CLOSING_QUOTE)
        assert second.startswith(OPENING_QUOTE)
        assert second.endswith(CLOSING_QUOTE)

    def test_dialogue_between_two_spoken_captions_breaks_the_run(self):
        core = compile_panel("""  - caption: {text: "Get down!", kind: spoken}
  - say: {by: alice, text: "What?"}
  - caption: {text: "All of you!", kind: spoken}
""")
        first, second = (" ".join(caption.lines) for caption in core.captions)
        assert first.endswith(CLOSING_QUOTE)
        assert second.endswith(CLOSING_QUOTE)

    @pytest.mark.parametrize(
        "kind", [CaptionKind.LOCALE, CaptionKind.MONOLOGUE, CaptionKind.EDITORIAL]
    )
    def test_the_other_kinds_are_left_alone(self, kind: CaptionKind):
        core = compile_panel(f'  - caption: {{text: "Midnight.", kind: {kind.value}}}\n')
        assert " ".join(core.captions[0].lines) == "Midnight."


class TestItalics:
    """The italic face is a real font file that already ships as a dependency, so the
    box is measured with the face it will be drawn in."""

    def test_the_two_faces_measure_differently(self):
        roman = layout_text("Midnight. The docks.", font_size=30.0, metrics=load_metrics())
        italic = layout_text(
            "Midnight. The docks.", font_size=30.0, metrics=load_metrics(str(ITALIC_FONT_PATH))
        )
        assert roman.width != italic.width

    def test_an_italic_caption_is_measured_with_the_italic_face(self):
        """The test that actually proves it: the box matches the italic measurement,
        so nothing downstream can be drawn in a face the solver did not measure."""
        core = compile_panel('  - caption: {text: "Midnight. The docks."}\n')
        caption = core.captions[0]
        block = layout_text(
            "Midnight. The docks.",
            font_size=caption.font_size,
            metrics=load_metrics(str(ITALIC_FONT_PATH)),
        )
        width, _height = balloon_size(block, CAPTION_PADDING_FACTOR)
        assert caption.box.width == pytest.approx(width, abs=0.01)

    @pytest.mark.parametrize(
        ("kind", "italic"),
        [("locale", True), ("monologue", True), ("editorial", True), ("spoken", False)],
    )
    def test_the_kind_decides_the_face(self, kind: str, italic: bool):
        core = compile_panel(f'  - caption: {{text: "Midnight.", kind: {kind}}}\n')
        assert core.captions[0].italic is italic


class TestOffPanelSpeaker:
    def test_a_spoken_caption_carries_its_speaker_through(self):
        core = compile_panel(
            '  - caption: {text: "Get down!", kind: spoken, by: doctor}\n',
        )
        assert core.captions[0].speaker == "doctor"

    def test_a_caption_without_one_carries_nothing(self):
        core = compile_panel('  - caption: {text: "Midnight."}\n')
        assert core.captions[0].speaker is None


class TestRendering:
    def test_the_box_reaches_the_svg(self):
        core = compile_panel('  - caption: {text: "Midnight. The docks."}\n')
        assert 'id="caption-c0"' in render(core)

    def test_the_text_is_left_aligned(self):
        """A convention rather than a rule, but the one letterers use -- and the
        opposite of what balloons do, which centre."""
        core = compile_panel('  - caption: {text: "Midnight. The docks. It was raining."}\n')
        caption = core.captions[0]
        markup = render(core, live_text=True)
        starts = [
            float(line.split('x="')[1].split('"')[0])
            for line in markup.splitlines()
            if "<text" in line
        ]
        assert len(set(starts)) == 1
        assert starts[0] == pytest.approx(caption.box.x + caption.font_size * 0.42, abs=0.5)

    def test_live_text_declares_the_italic_style(self):
        italic = compile_panel('  - caption: {text: "Midnight.", kind: locale}\n')
        roman = compile_panel('  - caption: {text: "Midnight.", kind: spoken}\n')
        assert 'font-style="italic"' in render(italic, live_text=True)
        assert 'font-style="italic"' not in render(roman, live_text=True)

    def test_outlined_lettering_uses_the_face_the_solver_measured(self):
        """The same box and the same lines, drawn in the other face, must produce
        different glyph outlines -- otherwise `italic` is decorative."""
        core = compile_panel('  - caption: {text: "Midnight. The docks."}\n')
        roman = core.model_copy(
            update={"captions": (core.captions[0].model_copy(update={"italic": False}),)}
        )
        assert render(core) != render(roman)

    def test_the_debug_layer_annotates_captions(self):
        core = compile_panel('  - caption: {text: "Midnight. The docks."}\n')
        assert "c0" in render_debug(core)


class TestDeterminism:
    def test_the_same_source_compiles_to_the_same_bytes(self):
        source = """  - caption: {text: "Midnight. The docks.", kind: locale}
  - say: {by: alice, text: "You forgot your umbrella!"}
  - caption: {text: "She had.", kind: editorial}
"""
        assert compile_panel(source).to_json() == compile_panel(source).to_json()

    def test_a_caption_survives_a_round_trip_through_json(self):
        core = compile_panel('  - caption: {text: "Midnight. The docks."}\n')
        assert PanelCore.from_json(core.to_json()) == core
