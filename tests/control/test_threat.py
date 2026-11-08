"""Hand-calculated cases for the threat score (docs/design.md A8)."""

import pytest

from cuas.config import ApprovedFlight, SiteConfig, ThreatSettings, ZoneLabels
from cuas.control.classify import Classified
from cuas.control.threat import (
    Assessment,
    ThreatRanker,
    level_of,
    rank,
    time_to_impact,
    urgency,
)
from cuas.schemas import ClueEvidence, Track, TrackClass

SQUARE = ((-100.0, -100.0), (100.0, -100.0), (100.0, 100.0), (-100.0, 100.0))
LABELS = ZoneLabels(
    critical="Pitch and Stands",
    important="Stadium Grounds",
    perimeter="Event Perimeter",
)


@pytest.fixture
def settings(site: SiteConfig) -> ThreatSettings:
    return site.threat


@pytest.mark.parametrize(
    ("tti", "expected"),
    [(None, 0.1), (0.0, 1.0), (30.0, 1.0), (105.0, 0.6), (180.0, 0.2), (180.5, 0.1)],
)
def test_urgency_ramp(settings: ThreatSettings, tti, expected: float) -> None:
    assert urgency(tti, settings) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("position", "velocity", "expected"),
    [
        ((0.0, 0.0), (5.0, 0.0), 0.0),  # already inside
        ((-300.0, 0.0), (10.0, 0.0), 20.0),  # straight in
        ((-300.0, 0.0), (-10.0, 0.0), None),  # flying away
        ((-300.0, 150.0), (10.0, 0.0), None),  # passing beside
        ((-300.0, -300.0), (10.0, 10.0), 20.0),  # in through the corner
        ((-300.0, 0.0), (0.0, 0.0), None),  # going nowhere
    ],
)
def test_time_to_impact_geometry(position, velocity, expected) -> None:
    result = time_to_impact(position, velocity, SQUARE)
    assert result == (None if expected is None else pytest.approx(expected))


@pytest.mark.parametrize(
    ("score", "level"),
    [(0.6, "red"), (0.5999, "amber"), (0.3, "amber"), (0.2999, "info")],
)
def test_level_boundaries(settings: ThreatSettings, score: float, level: str) -> None:
    assert level_of(score, settings) == level


def classified(
    p_drone: float,
    position,
    velocity=(0.0, 0.0, 0.0),
    move_reason=None,
    track_id="trk-1",
) -> Classified:
    cov = tuple(tuple(1.0 if i == j else 0.0 for j in range(6)) for i in range(6))
    track = Track(
        track_id=track_id,
        t=0.0,
        position_enu_m=position,
        velocity_mps=velocity,
        covariance=cov,
        n_stations=3,
        status="confirmed",
    )
    track_class = TrackClass(
        track_id=track_id,
        t=0.0,
        p_drone=p_drone,
        p_bird=1.0 - p_drone,
        p_attack_drone=0.0,
        evidence=ClueEvidence(move=0.8 if move_reason else None),
    )
    return Classified(track, track_class, None, move_reason, False)


@pytest.fixture
def ranker(site: SiteConfig) -> ThreatRanker:
    return ThreatRanker(site.threat, site.zones, LABELS)


@pytest.mark.parametrize(
    ("p", "position", "velocity", "score", "level", "zone", "tti"),
    [
        # heading in: zone 1.0, urgency 1.0 -> 0.9 * (0.5 + 0.5)
        (0.9, (-300.0, 0.0, 80.0), (10.0, 0.0, 0.0), 0.9, "red", "critical", 20.0),
        # still, inside important: 0.9 * (0.5 * 0.6 + 0.5 * 0.1)
        (0.9, (200.0, 200.0, 80.0), (0.0, 0.0, 0.0), 0.315, "amber", "important", None),
        # 110 s out: urgency 1 - (80 / 150) * 0.8 = 0.5733; 0.5 * (0.5 + 0.2867)
        (
            0.5,
            (-1200.0, 0.0, 80.0),
            (10.0, 0.0, 0.0),
            0.39333,
            "amber",
            "critical",
            110.0,
        ),
        # outside every zone and going nowhere: 0.3 * (0 + 0.05)
        (0.3, (2000.0, 0.0, 80.0), (0.0, 0.0, 0.0), 0.015, "info", None, None),
    ],
)
def test_hand_calculated_scores(
    ranker: ThreatRanker, p, position, velocity, score, level, zone, tti
) -> None:
    result = ranker.assess(0.0, classified(p, position, velocity))
    assert result.score == pytest.approx(score, abs=1e-5)
    assert (result.level, result.zone) == (level, zone)
    assert result.time_to_impact_s == (None if tti is None else pytest.approx(tti))


def test_an_approved_flight_is_not_hostile(site: SiteConfig) -> None:
    corridor = ApprovedFlight(
        corridor_enu_m=((-400.0, -50.0), (0.0, -50.0), (0.0, 50.0), (-400.0, 50.0)),
        min_altitude_m=50.0,
        max_altitude_m=120.0,
        start_s=0.0,
        end_s=60.0,
    )
    ranker = ThreatRanker(
        site.threat.model_copy(update={"approved_flights": (corridor,)}),
        site.zones,
        LABELS,
    )
    heading_in = classified(0.9, (-300.0, 0.0, 80.0), (10.0, 0.0, 0.0))
    inside_window = ranker.assess(30.0, heading_in)
    assert (inside_window.score, inside_window.level) == (0.0, "info")
    assert "approved flight" in inside_window.reasons
    assert ranker.assess(90.0, heading_in).level == "red"  # the window has closed


def test_reasons_are_plain_words_with_the_zone_label(ranker: ThreatRanker) -> None:
    heading_in = ranker.assess(
        0.0,
        classified(0.9, (-300.0, 0.0, 80.0), (10.0, 0.0, 0.0), "fast straight flight"),
    )
    assert heading_in.reasons == (
        "fast straight flight",
        "heading to Pitch and Stands, 20 s",
    )
    hovering = ranker.assess(
        0.0, classified(0.9, (0.0, 50.0, 70.0), move_reason="hovering")
    )
    assert hovering.reasons == ("hovering", "inside Pitch and Stands")


def assessment(track_id: str, level: str, tti, score: float) -> Assessment:
    return Assessment(track_id, 0.0, score, level, "critical", tti, ())


def test_ranking_is_by_level_then_time_to_impact_not_score() -> None:
    """Urgency is 1.0 for every track within 30 s, so score alone would not order by impact."""
    ranked = rank(
        [
            assessment("trk-a", "red", 20.0, 0.99),
            assessment("trk-b", "red", 10.0, 0.90),
            assessment("trk-c", "amber", 5.0, 0.50),
            assessment("trk-d", "red", 15.0, 0.95),
            assessment("trk-e", "red", None, 0.97),
        ]
    )
    assert [a.track_id for a in ranked] == ["trk-b", "trk-d", "trk-a", "trk-e", "trk-c"]
