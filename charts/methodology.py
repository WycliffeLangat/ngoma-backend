"""Canonical Ngoma Charts scoring and platform methodology.

There are deliberately two point systems:

* weekly/raw points (Top 100): ``101 - rank``; these build monthly rankings;
* public points (Top 50): ``51 - rank``; these power every public aggregate.

Platform database settings are descriptive metadata. They must never change
either formula.
"""

WEEKLY_CHART_LIMIT = 100
WEEKLY_POINTS_BASE = 101

PUBLIC_CHART_LIMIT = 50
PUBLIC_POINTS_BASE = 51

SINGLES_PLATFORMS = (
    "Apple Music",
    "Audiomack",
    "Boomplay",
    "Spotify",
    "YouTube",
    "Shazam",
)

ALBUMS_PLATFORMS = (
    "Apple Music",
    "Audiomack",
)

CERTIFICATION_THRESHOLDS = {
    "gold": 200,
    "platinum": 400,
    "diamond": 600,
}


def weekly_points(rank):
    """Return fixed Top 100 source points, or zero outside the chart."""
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        return 0
    return WEEKLY_POINTS_BASE - rank if 1 <= rank <= WEEKLY_CHART_LIMIT else 0


def public_points(rank):
    """Return fixed Top 50 public points, or zero outside the public chart."""
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        return 0
    return PUBLIC_POINTS_BASE - rank if 1 <= rank <= PUBLIC_CHART_LIMIT else 0


def platforms_for(chart_type):
    return ALBUMS_PLATFORMS if str(chart_type) == "albums" else SINGLES_PLATFORMS


def platform_max_for(chart_type):
    return len(platforms_for(chart_type))
