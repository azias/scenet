"""Balloon placement rules that are easy to get subtly wrong."""

import pytest

from scenet.geom import BBox, Circle, Point
from scenet.solve.balloons import _reading_order_allows, _stop_at_face, route_tail


class TestReadingOrder:
    """A balloon may never sit above *and* left of one that precedes it."""

    def test_below_is_allowed(self):
        first = BBox(100, 100, 80, 40)
        assert _reading_order_allows([first], BBox(0, 200, 80, 40))

    def test_right_of_is_allowed(self):
        first = BBox(100, 100, 80, 40)
        assert _reading_order_allows([first], BBox(200, 0, 80, 40))

    def test_above_and_left_is_refused(self):
        first = BBox(100, 100, 80, 40)
        assert not _reading_order_allows([first], BBox(0, 0, 80, 40))

    def test_nothing_placed_yet_allows_anything(self):
        assert _reading_order_allows([], BBox(0, 0, 80, 40))

    def test_checked_against_every_predecessor_not_just_the_last(self):
        # "Readable after" is not a transitive relation, which is the whole point of
        # this test. Balloon 1 is legal after balloon 0 because it is far to its right;
        # the candidate is legal after balloon 1 because it is below it -- and yet the
        # candidate sits above *and* left of balloon 0, so reading 0, 1, candidate takes
        # the page in the wrong order. Comparing only against the last one misses it.
        first = BBox(0, 300, 100, 60)
        second = BBox(400, 100, 100, 60)
        candidate = BBox(0, 200, 100, 60)

        assert _reading_order_allows([first], second), "second follows first legally"
        assert _reading_order_allows([second], candidate), "legal against the last alone"
        assert not _reading_order_allows([first, second], candidate), (
            "must be refused: it is above and left of the first balloon"
        )


class TestTailTermination:
    """A tail stops on the face outline, not at the mouth anchor buried inside it."""

    def test_tail_stops_on_the_outline(self):
        face = Circle(cx=100.0, cy=100.0, r=30.0)
        mouth = Point(100.0, 110.0)  # inside the head
        tip = _stop_at_face(Point(100.0, 300.0), mouth, face)

        distance = ((tip.x - face.cx) ** 2 + (tip.y - face.cy) ** 2) ** 0.5
        assert distance == pytest.approx(face.r, abs=1e-6)

    def test_a_mouth_outside_the_face_is_left_alone(self):
        face = Circle(cx=100.0, cy=100.0, r=10.0)
        mouth = Point(100.0, 200.0)
        assert _stop_at_face(Point(100.0, 300.0), mouth, face) == mouth

    def test_a_clear_run_produces_a_straight_tail(self):
        route = route_tail(BBox(0, 0, 60, 40), Point(200.0, 200.0), obstacles=[])
        assert not route.is_curved

    def test_an_obstructing_face_bends_the_tail(self):
        balloon = BBox(0, 0, 60, 40)
        mouth = Point(400.0, 400.0)
        blocker = Circle(cx=200.0, cy=200.0, r=40.0)
        assert route_tail(balloon, mouth, obstacles=[blocker]).is_curved
