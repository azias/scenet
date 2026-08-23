"""Text measurement and line breaking.

Line breaking is judged on craft, not just correctness. A balloon that technically
holds its text but strands a single word on its own line reads as bad lettering, so
several tests below encode what a letterer would actually do.
"""

import pytest

from scenet.solve.text import (
    FontMetrics,
    balloon_size,
    candidate_measures,
    layout_text,
    load_metrics,
    wrap_to_width,
)


@pytest.fixture(scope="module")
def metrics() -> FontMetrics:
    return load_metrics()


class TestMetrics:
    def test_font_is_a_declared_dependency_not_a_system_lookup(self, metrics: FontMetrics):
        """Determinism requires a fixed font. 'Whatever this machine has installed' is
        the opposite of reproducible, so it ships as a dependency."""
        assert metrics.path.exists()
        assert metrics.path.suffix == ".ttf"

    def test_wider_characters_measure_wider(self, metrics: FontMetrics):
        assert metrics.advance("m") > metrics.advance("i")

    def test_measurement_scales_linearly_with_size(self, metrics: FontMetrics):
        assert metrics.measure("hello", 40) == pytest.approx(2 * metrics.measure("hello", 20))

    def test_unknown_characters_do_not_crash(self, metrics: FontMetrics):
        """A panel may contain anything; an unmapped glyph must measure, not explode."""
        assert metrics.measure("中文", 40) >= 0

    def test_metrics_are_cached(self):
        assert load_metrics() is load_metrics()


class TestWrapping:
    def test_text_fitting_the_measure_stays_on_one_line(self, metrics: FontMetrics):
        assert wrap_to_width("short", metrics, 40, 10_000) == ["short"]

    def test_wrapping_happens_at_spaces(self, metrics: FontMetrics):
        lines = wrap_to_width("one two three four", metrics, 40, metrics.measure("one two", 40))
        assert all(" " in line or len(line.split()) == 1 for line in lines)
        assert " ".join(lines) == "one two three four"

    def test_an_overlong_word_overflows_rather_than_breaking(self, metrics: FontMetrics):
        """Hyphenating mid-word in comic lettering looks like a mistake; the balloon
        widening to fit is the correct outcome."""
        assert wrap_to_width("antidisestablishmentarianism", metrics, 40, 10) == [
            "antidisestablishmentarianism"
        ]

    def test_empty_text_yields_no_lines(self, metrics: FontMetrics):
        assert wrap_to_width("   ", metrics, 40, 100) == []


class TestCandidateMeasures:
    def test_candidates_are_contiguous_word_runs(self, metrics: FontMetrics):
        """The measures worth trying are exactly the widths a line could have, and a
        line is always some run of adjacent words."""
        widths = candidate_measures(["a", "bb", "ccc"], metrics, 40)
        assert len(widths) == 6  # a, bb, ccc, "a bb", "bb ccc", "a bb ccc"
        assert widths == sorted(widths)

    def test_the_good_break_is_reachable(self, metrics: FontMetrics):
        """A regression guard. Dividing total width by line count -- the obvious
        shortcut -- never proposes the measure fitting 'You forgot your', so the good
        two-line break is unreachable and the search settles for a ragged three-line
        block."""
        words = ["You", "forgot", "your", "umbrella!"]
        widths = candidate_measures(words, metrics, 40)
        assert metrics.measure("your umbrella!", 40) in widths


class TestLineBreakingCraft:
    def test_a_short_phrase_is_never_split(self, metrics: FontMetrics):
        """Purely on aspect ratio, breaking 'I know.' scores marginally better than
        leaving it alone. No letterer would do that, hence the per-line penalty."""
        assert layout_text("I know.", font_size=40, metrics=metrics).lines == ("I know.",)

    def test_no_word_is_stranded_alone(self, metrics: FontMetrics):
        block = layout_text("You forgot your umbrella!", font_size=40, metrics=metrics)
        assert len(block.lines) == 2
        assert all(len(line.split()) >= 2 for line in block.lines)

    def test_long_text_wraps_into_a_balloon_shaped_block(self, metrics: FontMetrics):
        block = layout_text(
            "This is a considerably longer line of dialogue that must wrap to stay readable.",
            font_size=40,
            metrics=metrics,
        )
        assert len(block.lines) > 2
        balloon_width, balloon_height = balloon_size(block)
        assert 1.2 < balloon_width / balloon_height < 2.6

    @pytest.mark.parametrize(
        "text",
        [
            "Wait.",
            "I know.",
            "You forgot your umbrella!",
            "Get out of the way, right now, before it lands on you!",
        ],
    )
    def test_balloons_land_in_a_natural_aspect_range(self, metrics: FontMetrics, text: str):
        width, height = balloon_size(layout_text(text, font_size=40, metrics=metrics))
        assert 1.0 < width / height < 3.0, text

    def test_no_line_overflows_the_block_width(self, metrics: FontMetrics):
        block = layout_text(
            "The quick brown fox jumps over the lazy dog", font_size=40, metrics=metrics
        )
        for line in block.lines:
            assert metrics.measure(line, 40) <= block.width + 0.01

    def test_wrapping_preserves_the_text(self, metrics: FontMetrics):
        text = "Nothing may be silently dropped or duplicated by wrapping."
        block = layout_text(text, font_size=40, metrics=metrics)
        assert " ".join(block.lines) == text

    def test_empty_text_produces_an_empty_block(self, metrics: FontMetrics):
        block = layout_text("", font_size=40, metrics=metrics)
        assert block.lines == ()
        assert block.width == 0.0


class TestRaggedness:
    def test_equal_lines_are_not_ragged(self, metrics: FontMetrics):
        block = layout_text("aaaa aaaa", font_size=40, metrics=metrics)
        assert block.raggedness < 0.35

    def test_single_line_is_never_ragged(self, metrics: FontMetrics):
        assert layout_text("solo", font_size=40, metrics=metrics).raggedness == 0.0


class TestOutlines:
    def test_every_character_yields_an_advance(self, metrics: FontMetrics):
        outlines = metrics.glyph_outlines("Hi!")
        assert len(outlines) == 3
        assert all(advance > 0 for _path, advance in outlines)

    def test_outline_advances_sum_to_the_measured_width(self, metrics: FontMetrics):
        """The outlines and the measurement must agree exactly, or rendered lettering
        drifts away from the box that was sized for it."""
        text = "Hello, world!"
        total = sum(advance for _path, advance in metrics.glyph_outlines(text)) * 40
        assert total == pytest.approx(metrics.measure(text, 40))

    def test_visible_characters_have_path_data(self, metrics: FontMetrics):
        paths = [path for path, _ in metrics.glyph_outlines("Hi")]
        assert all(path.startswith("M") for path in paths)


class TestDeterminism:
    def test_layout_is_repeatable(self, metrics: FontMetrics):
        text = "The same input must always produce the same line breaking."
        first = layout_text(text, font_size=37.5, metrics=metrics)
        second = layout_text(text, font_size=37.5, metrics=metrics)
        assert first == second
