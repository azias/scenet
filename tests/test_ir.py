"""IR validation: what the language accepts, and what it must reject.

These tests are mostly about rejection. A compiler for a precise language earns its
keep by refusing ambiguous input loudly rather than rendering something plausible and
wrong.
"""

import pytest
from pydantic import ValidationError

from scenet.ir import (
    AnchorX,
    CastMember,
    PanelIR,
    PanelSpec,
    PlacementZone,
    Predicate,
    Relation,
    SayEvent,
)


def cast(*names: str) -> dict[str, CastMember]:
    return {name: CastMember(reference=name) for name in names}


class TestPanelSpec:
    def test_rejects_non_positive_size(self):
        with pytest.raises(ValidationError, match="must be positive"):
            PanelSpec(size=(0.0, 100.0))

    def test_rejects_margin_that_consumes_the_panel(self):
        with pytest.raises(ValidationError, match="no usable panel area"):
            PanelSpec(size=(100.0, 100.0), margin=50.0)

    def test_exposes_width_and_height(self):
        spec = PanelSpec(size=(800.0, 600.0))
        assert (spec.width, spec.height) == (800.0, 600.0)


class TestStrictness:
    def test_unknown_key_is_rejected(self):
        """A silently ignored typo is the worst failure mode for a precise language."""
        with pytest.raises(ValidationError, match=r"camra|extra"):
            PanelIR.model_validate({"camra": {"shot": "close_up"}})

    def test_models_are_immutable(self):
        member = CastMember(reference="alice")
        with pytest.raises(ValidationError):
            member.reference = "bob"  # ty: ignore[invalid-assignment]


class TestReferenceResolution:
    def test_staging_naming_unknown_actor_is_rejected(self):
        with pytest.raises(ValidationError, match="unknown actor 'carol'"):
            PanelIR(
                cast=cast("alice"),
                staging=(Relation(subject="alice", predicate=Predicate.LEFT_OF, object="carol"),),
            )

    def test_script_spoken_by_unknown_actor_is_rejected(self):
        with pytest.raises(ValidationError, match="unknown actor 'ghost'"):
            PanelIR(cast=cast("alice"), script=(SayEvent(by="ghost", text="hello"),))

    def test_reflexive_relation_is_rejected(self):
        with pytest.raises(ValidationError, match="cannot relate"):
            Relation(subject="alice", predicate=Predicate.LEFT_OF, object="alice")


class TestOrdering:
    def test_direct_cycle_is_rejected(self):
        with pytest.raises(ValidationError, match="cyclic"):
            PanelIR(
                cast=cast("alice", "bob"),
                staging=(
                    Relation(subject="alice", predicate=Predicate.LEFT_OF, object="bob"),
                    Relation(subject="bob", predicate=Predicate.LEFT_OF, object="alice"),
                ),
            )

    def test_indirect_cycle_is_rejected(self):
        with pytest.raises(ValidationError, match="cyclic"):
            PanelIR(
                cast=cast("a", "b", "c"),
                staging=(
                    Relation(subject="a", predicate=Predicate.LEFT_OF, object="b"),
                    Relation(subject="b", predicate=Predicate.LEFT_OF, object="c"),
                    Relation(subject="c", predicate=Predicate.LEFT_OF, object="a"),
                ),
            )

    def test_chain_without_a_cycle_is_accepted(self):
        panel = PanelIR(
            cast=cast("a", "b", "c"),
            staging=(
                Relation(subject="a", predicate=Predicate.LEFT_OF, object="b"),
                Relation(subject="b", predicate=Predicate.LEFT_OF, object="c"),
            ),
        )
        assert panel.ordering_constraints() == (("a", "b"), ("b", "c"))

    def test_right_of_is_normalised_to_a_left_right_pair(self):
        """left_of and right_of are the same constraint written from either end."""
        panel = PanelIR(
            cast=cast("a", "b"),
            staging=(Relation(subject="a", predicate=Predicate.RIGHT_OF, object="b"),),
        )
        assert panel.ordering_constraints() == (("b", "a"),)

    def test_right_of_participates_in_cycle_detection(self):
        with pytest.raises(ValidationError, match="cyclic"):
            PanelIR(
                cast=cast("a", "b"),
                staging=(
                    Relation(subject="a", predicate=Predicate.LEFT_OF, object="b"),
                    Relation(subject="a", predicate=Predicate.RIGHT_OF, object="b"),
                ),
            )


class TestGroundGroups:
    def test_shared_ground_is_transitive(self):
        """'a with b' plus 'b with c' must put all three on one ground line without
        the author having to state 'a with c'."""
        panel = PanelIR(
            cast=cast("a", "b", "c"),
            staging=(
                Relation(subject="a", predicate=Predicate.GROUND_SHARED_WITH, object="b"),
                Relation(subject="b", predicate=Predicate.GROUND_SHARED_WITH, object="c"),
            ),
        )
        assert panel.ground_groups() == (frozenset({"a", "b", "c"}),)

    def test_unrelated_actors_form_no_group(self):
        panel = PanelIR(cast=cast("a", "b"))
        assert panel.ground_groups() == ()

    def test_separate_groups_stay_separate(self):
        panel = PanelIR(
            cast=cast("a", "b", "c", "d"),
            staging=(
                Relation(subject="a", predicate=Predicate.GROUND_SHARED_WITH, object="b"),
                Relation(subject="c", predicate=Predicate.GROUND_SHARED_WITH, object="d"),
            ),
        )
        assert set(panel.ground_groups()) == {frozenset({"a", "b"}), frozenset({"c", "d"})}


class TestGaze:
    def test_looking_at_is_collected(self):
        panel = PanelIR(
            cast=cast("alice", "bob"),
            staging=(Relation(subject="alice", predicate=Predicate.LOOKING_AT, object="bob"),),
        )
        assert panel.gaze_targets() == {"alice": "bob"}


class TestPlacementZone:
    @pytest.mark.parametrize(
        ("zone", "expected"),
        [
            (PlacementZone.TOP_LEFT, (0.25, 0.2)),
            (PlacementZone.MIDDLE_CENTRE, (0.5, 0.5)),
            (PlacementZone.BOTTOM_RIGHT, (0.75, 0.8)),
        ],
    )
    def test_fractions(self, zone: PlacementZone, expected: tuple[float, float]):
        assert zone.fractions == expected

    def test_every_zone_resolves(self):
        """Guards against a member whose name does not parse into two known halves."""
        for zone in PlacementZone:
            across, down = zone.fractions
            assert 0.0 < across < 1.0
            assert 0.0 < down < 1.0

    def test_balloon_hint_is_two_dimensional(self):
        """A regression guard: `prefer` was briefly typed as the horizontal-only
        AnchorX, which cannot express 'top_left' at all."""
        event = SayEvent(by="alice", text="hi", prefer=PlacementZone.TOP_LEFT)
        assert event.prefer is PlacementZone.TOP_LEFT
        assert PlacementZone.TOP_LEFT.value not in {member.value for member in AnchorX}
