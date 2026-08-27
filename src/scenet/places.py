"""The place library: named settings, and what each expands into.

The thing an author wants to write is *where the scene is*, not a list of shapes. So
the headline surface is a named place:

    setting:
      place: docks

**The rule that keeps that honest**: a preset expands into a mass list the author could
have written themselves, and is never a second opaque format. A library for
convenience, not a parallel language. The expansion happens in the frontend, so by the
time anything downstream sees a backdrop there is exactly one representation of it --
the same treatment `alice left_of bob` gets on its way to a
:class:`Relation <scenet.ir.Relation>`.

**Free prose is deliberately not offered.** `setting: "a rainy street corner at
midnight"` needs language understanding, and `frontends/script_front.py` already
refuses to interpret prose on the grounds that guessing produces panels that are
confidently wrong. A named place is the honest middle: it reads like a description and
resolves deterministically.

Within a place, masses are listed **back to front**. Draw order comes from the plane, so
the listing order only decides ties within one plane -- but reading the list in the
order it will be painted is what makes a preset reviewable.
"""

from enum import StrEnum

from scenet.ir import Mass, MassKind, Plane, Spans

__all__ = ["PLACES", "Place"]


class Place(StrEnum):
    """A named setting, expanded into masses by the frontend.

    Ten to start with, chosen to span the distinctions that change how a backdrop is
    built rather than to be a catalogue: exterior and interior, built and natural, open
    and enclosed. `alley` is the one with a foreground mass, which is what makes it
    read as a place you are standing *in* rather than looking at.

    Example:
        >>> from scenet.places import PLACES, Place
        >>> [mass.kind.value for mass in PLACES[Place.SHORE]]
        ['sky', 'water', 'ground']
    """

    ALLEY = "alley"
    DESERT = "desert"
    DOCKS = "docks"
    FIELD = "field"
    FOREST = "forest"
    MOUNTAIN = "mountain"
    OFFICE = "office"
    ROOM = "room"
    SHORE = "shore"
    STREET = "street"


def _mass(kind: MassKind, plane: Plane, spans: Spans = Spans.FULL) -> Mass:
    """One mass, written positionally so a preset reads as a table."""
    return Mass(kind=kind, plane=plane, spans=spans)


#: What each place is made of. Every entry here is a plain mass list, and a test proves
#: it: whatever a preset produces, an author could have typed.
PLACES: dict[Place, tuple[Mass, ...]] = {
    Place.ALLEY: (
        # The walls make the slot of sky, rather than the sky being authored as a strip:
        # that is how an alley actually works, and a partial sky leaves bare paper in the
        # corners where nothing was asked to be. They stand at `near` so they tower.
        # The foreground wall is what makes this a place you are standing *in*.
        _mass(MassKind.SKY, Plane.FAR),
        _mass(MassKind.BUILDING, Plane.NEAR, Spans.LEFT),
        _mass(MassKind.BUILDING, Plane.NEAR, Spans.RIGHT),
        _mass(MassKind.GROUND, Plane.NEAR),
        _mass(MassKind.BUILDING, Plane.FOREGROUND, Spans.LEFT),
    ),
    Place.DESERT: (
        _mass(MassKind.SKY, Plane.FAR),
        _mass(MassKind.SOLID, Plane.FAR, Spans.RIGHT),
        _mass(MassKind.GROUND, Plane.MID),
        _mass(MassKind.GROUND, Plane.NEAR),
    ),
    Place.DOCKS: (
        _mass(MassKind.SKY, Plane.FAR),
        _mass(MassKind.BUILDING, Plane.FAR, Spans.LEFT),
        _mass(MassKind.WATER, Plane.MID),
        _mass(MassKind.STRUCTURAL, Plane.MID, Spans.RIGHT),
        _mass(MassKind.GROUND, Plane.NEAR),
    ),
    Place.FIELD: (
        # Open country: a treeline far off, and the ground doing the rest in bands. Put
        # the planting nearer and this becomes `forest`, which is the distinction the
        # two presets exist to make.
        _mass(MassKind.SKY, Plane.FAR),
        _mass(MassKind.PLANT, Plane.FAR),
        _mass(MassKind.GROUND, Plane.MID),
        _mass(MassKind.GROUND, Plane.NEAR),
    ),
    Place.FOREST: (
        # Canopy behind, and two stands of it close enough to crowd the frame.
        _mass(MassKind.SKY, Plane.FAR),
        _mass(MassKind.PLANT, Plane.FAR),
        _mass(MassKind.PLANT, Plane.NEAR, Spans.LEFT),
        _mass(MassKind.PLANT, Plane.NEAR, Spans.RIGHT),
        _mass(MassKind.GROUND, Plane.NEAR),
    ),
    Place.MOUNTAIN: (
        _mass(MassKind.SKY, Plane.FAR),
        _mass(MassKind.SOLID, Plane.FAR),
        _mass(MassKind.SOLID, Plane.MID, Spans.LEFT),
        _mass(MassKind.PLANT, Plane.MID, Spans.RIGHT),
        _mass(MassKind.GROUND, Plane.NEAR),
    ),
    Place.OFFICE: (
        _mass(MassKind.WALL, Plane.FAR),
        _mass(MassKind.WINDOW, Plane.FAR, Spans.CENTRE),
        # The ceiling sits at a nearer plane than the back wall because it *is* nearer,
        # and a shadowed band across the top is what tells an interior from an exterior
        # at a glance.
        _mass(MassKind.CEILING, Plane.MID),
        _mass(MassKind.FLOOR, Plane.NEAR),
        _mass(MassKind.FURNITURE, Plane.NEAR),
    ),
    Place.ROOM: (
        _mass(MassKind.WALL, Plane.FAR),
        _mass(MassKind.WINDOW, Plane.FAR, Spans.RIGHT),
        _mass(MassKind.CEILING, Plane.MID),
        _mass(MassKind.FLOOR, Plane.NEAR),
        _mass(MassKind.FURNITURE, Plane.NEAR, Spans.LEFT),
    ),
    Place.SHORE: (
        _mass(MassKind.SKY, Plane.FAR),
        _mass(MassKind.WATER, Plane.MID),
        _mass(MassKind.GROUND, Plane.NEAR),
    ),
    Place.STREET: (
        _mass(MassKind.SKY, Plane.FAR),
        _mass(MassKind.BUILDING, Plane.FAR),
        _mass(MassKind.BUILDING, Plane.MID, Spans.LEFT),
        _mass(MassKind.BUILDING, Plane.MID, Spans.RIGHT),
        _mass(MassKind.GROUND, Plane.NEAR),
    ),
}
