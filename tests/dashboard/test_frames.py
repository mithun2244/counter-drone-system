"""The frame builder on hand-made messages, then on a recorded run."""

from itertools import pairwise

import pytest

from cuas.config import ScenarioMetadata, SiteConfig, ZoneLabels
from cuas.dashboard.contract import EvidenceHead
from cuas.dashboard.frames import FrameBuilder, compass, profiles, replay, site_map
from cuas.schemas import (
    ClueEvidence,
    CoverageStatus,
    EvidenceRecord,
    PicketAlert,
    RejectedMessage,
    SectorTrack,
    SensorStatus,
    ThreatAssessment,
    Track,
    TrackClass,
)

LABELS = ZoneLabels(critical="Pitch", important="Grounds", perimeter="Perimeter")


@pytest.fixture
def builder(site: SiteConfig) -> FrameBuilder:
    return FrameBuilder("run-1", site, LABELS)


def track(
    track_id: str, t: float, x: float = 0.0, status: str = "confirmed", n: int = 3
) -> Track:
    cov = tuple(tuple(1.0 if i == j else 0.0 for j in range(6)) for i in range(6))
    return Track(
        track_id=track_id,
        t=t,
        position_enu_m=(x, 500.0, 80.0),
        velocity_mps=(0.0, -10.0, 0.0),
        covariance=cov,
        n_stations=n,
        status=status,
    )


def threat(
    track_id: str, t: float, level: str, alert_id=None, tti=20.0
) -> ThreatAssessment:
    return ThreatAssessment(
        track_id=track_id,
        t=t,
        score=0.8,
        level=level,
        zone="critical",
        time_to_impact_s=tti,
        reasons=("seen hovering",),
        alert_id=alert_id,
    )


def classed(
    track_id: str, t: float, p_drone: float, p_attack: float = 0.0, looks=None
) -> TrackClass:
    return TrackClass(
        track_id=track_id,
        t=t,
        p_drone=p_drone,
        p_bird=1.0 - p_drone,
        p_attack_drone=p_attack,
        evidence=ClueEvidence(),
        looks=looks or {},
    )


def feed(builder: FrameBuilder, *messages) -> list:
    return [frame for m in messages for frame in builder.ingest(m)]


def test_a_frame_for_each_mark_simulated_time_passes(
    builder: FrameBuilder, site: SiteConfig
) -> None:
    period = site.dashboard.frame_period_s
    frames = feed(builder, *(track("trk-1", k * 0.2) for k in range(7)))  # 0.0 to 1.2 s
    assert [f.t for f in frames] == pytest.approx([0.0, period, 2 * period])
    assert builder.flush().t == pytest.approx(3 * period)


def test_time_passing_with_nothing_heard_still_gives_frames_once_each(
    builder: FrameBuilder, site: SiteConfig
) -> None:
    period = site.dashboard.frame_period_s
    quiet = builder.advance(1.0)
    assert [f.t for f in quiet] == pytest.approx([0.0, period, 2 * period])
    assert builder.advance(1.0) == []
    assert [f.t for f in feed(builder, track("trk-1", 1.4))] == [3 * period]


def test_cards_keep_the_published_ranking_and_a_new_batch_replaces_it(
    builder: FrameBuilder,
) -> None:
    feed(
        builder,
        track("trk-1", 0.0),
        track("trk-2", 0.0),
        track("trk-3", 0.0),
        threat("trk-2", 0.0, "red", "alert-2", tti=10.0),
        threat("trk-1", 0.0, "red", "alert-1", tti=30.0),
        threat("trk-3", 0.0, "info"),  # no alert: no card
    )
    assert [c.alert_id for c in builder.flush().alerts] == ["alert-2", "alert-1"]
    feed(
        builder,
        threat("trk-1", 0.4, "red", "alert-1", tti=5.0),
        threat("trk-2", 0.4, "amber", "alert-2"),
    )
    assert [c.alert_id for c in builder.flush().alerts] == ["alert-1", "alert-2"]


def test_a_card_stays_while_its_track_lives_and_goes_when_it_is_lost(
    builder: FrameBuilder,
) -> None:
    feed(builder, track("trk-1", 0.0), threat("trk-1", 0.0, "info", "alert-1"))
    assert [c.level for c in builder.flush().alerts] == ["info"]
    feed(builder, track("trk-1", 0.4, status="lost", n=0))
    frame = builder.flush()
    assert frame.alerts == [] and frame.tracks == []


def test_trails_keep_20_s_at_half_second_steps(
    builder: FrameBuilder, site: SiteConfig
) -> None:
    feed(
        builder, *(track("trk-1", k * 0.2, x=float(k)) for k in range(151))
    )  # 0 to 30 s
    trail = builder.flush().tracks[0].trail
    times = [p[0] for p in trail]
    assert min(times) >= 30.0 - site.dashboard.trail_s - 1e-6
    assert all(b - a >= site.dashboard.trail_step_s - 1e-6 for a, b in pairwise(times))


@pytest.mark.parametrize(
    ("p_drone", "p_attack", "key"),
    [(0.94, 0.62, "attack"), (0.94, 0.47, "drone"), (0.31, 0.0, "unclassified")],
)
def test_the_card_class_follows_the_classifier(
    builder: FrameBuilder, p_drone: float, p_attack: float, key: str
) -> None:
    feed(
        builder,
        track("trk-1", 0.0),
        classed("trk-1", 0.0, p_drone, p_attack),
        threat("trk-1", 0.0, "red", "alert-1"),
    )
    card = builder.flush().alerts[0]
    assert card.class_key == key
    assert card.confidence == (p_attack if key == "attack" else p_drone)


@pytest.mark.parametrize(
    ("tti", "approach"), [(0.0, "inside"), (12.0, "heading_to"), (None, "none")]
)
def test_approach_comes_from_time_to_impact(
    builder: FrameBuilder, tti, approach: str
) -> None:
    feed(
        builder, track("trk-1", 0.0), threat("trk-1", 0.0, "amber", "alert-1", tti=tti)
    )
    card = builder.flush().alerts[0]
    assert (card.approach, card.zone_label) == (approach, "Pitch")


def test_looks_become_clip_links_at_the_frame_the_model_saw(
    builder: FrameBuilder, site: SiteConfig
) -> None:
    looks = {"st1.rgb": "abcdef0123456789:7", "st2.zoom": "0123456789abcdef:0"}
    feed(
        builder,
        track("trk-1", 0.0),
        classed("trk-1", 0.0, 0.9, looks=looks),
        threat("trk-1", 0.0, "red", "alert-1"),
    )
    refs = builder.flush().alerts[0].looks
    assert [(r.source, r.clip_url) for r in refs] == [
        ("st1.rgb", "/api/clips/st1/abcdef0123456789"),
        ("st2.zoom", "/api/clips/st2/0123456789abcdef"),
    ]
    assert [r.at_s for r in refs] == pytest.approx(
        [7 * site.station_ai.look.period_s, 0.0]
    )


@pytest.mark.parametrize(
    ("bearing", "key"), [(0.0, "N"), (135.0, "SE"), (200.0, "S"), (350.0, "N")]
)
def test_compass_keys(bearing: float, key: str) -> None:
    assert compass(bearing) == key


def sector(t: float, status: str = "active") -> SectorTrack:
    return SectorTrack(
        sector_id="sec-1",
        t=t,
        sensor_id="pk4",
        origin_enu_m=(2121.3, -2121.3, 3.0),
        bearing_deg=315.0,
        half_width_deg=20.0,
        reports=1,
        status=status,
    )


def test_a_heard_sector_is_a_pre_alert_until_lost(builder: FrameBuilder) -> None:
    feed(builder, sector(1.0), sector(2.0))
    (pre,) = builder.flush().pre_alerts
    assert (pre.compass, pre.first_t, pre.last_t) == ("NW", 1.0, 2.0)
    feed(builder, sector(3.0, "lost"))
    assert builder.flush().pre_alerts == []


def test_pickets_flash_for_a_few_seconds(
    builder: FrameBuilder, site: SiteConfig
) -> None:
    heard = PicketAlert(
        picket_id="pk4", t=1.0, bearing_deg=315.0, loudness=0.5, engine_type_probs={}
    )
    feed(builder, heard, track("trk-1", 2.0))
    assert [p.picket_id for p in builder.flush().pickets_heard] == ["pk4"]
    feed(builder, track("trk-1", 1.0 + site.dashboard.picket_flash_s + 1.0))
    assert builder.flush().pickets_heard == []


def test_coverage_reach_follows_reported_camera_visibility(
    builder: FrameBuilder, site: SiteConfig
) -> None:
    feed(
        builder,
        SensorStatus(sensor_id="st2.rgb", ok=True, visibility_factor=0.5, t=0.0),
        CoverageStatus(t=0.0, coverage_pct=54.8, warning=True),
    )
    coverage = builder.flush().coverage
    full = site.sensors["rgb"].base_range_m["quadcopter"]
    assert coverage.reach_m == {"st1": full, "st2": full / 2, "st3": full}
    assert coverage.warning


def test_site_map_draws_outermost_zone_first_and_fits_the_pickets(
    site: SiteConfig,
) -> None:
    drawn = site_map(site, LABELS, site.dashboard.map_margin_fraction)
    assert [z.zone_id for z in drawn.zones] == ["perimeter", "important", "critical"]
    assert [z.label for z in drawn.zones] == ["Perimeter", "Grounds", "Pitch"]
    farthest = max(abs(c) for p in site.pickets for c in p.position_enu_m[:2])
    assert drawn.bounds.max_x > farthest and drawn.bounds.min_y < -farthest


def meta(scenario_id: str, venue: str, critical: str = "Pitch") -> ScenarioMetadata:
    labels = ZoneLabels(critical=critical, important="Grounds", perimeter="Perimeter")
    return ScenarioMetadata(
        id=scenario_id, title=f"{venue} {scenario_id}", venue=venue, zone_labels=labels
    )


def test_one_profile_per_venue_with_its_scenarios() -> None:
    found = profiles(
        [meta("s2", "Stadium"), meta("s1", "Plant"), meta("s3", "Stadium")]
    )
    assert [(p.profile_id, [s.scenario_id for s in p.scenarios]) for p in found] == [
        ("plant", ["s1"]),
        ("stadium", ["s2", "s3"]),
    ]
    with pytest.raises(ValueError):
        profiles([meta("s2", "Stadium"), meta("s3", "Stadium", critical="Other")])


async def test_a_recorded_run_replays_into_a_frame_per_mark(
    record_pipeline, site: SiteConfig
) -> None:
    _, ingested, controlled, _ = await record_pipeline("s2", seed=7)
    accepted = [m for m in ingested if not isinstance(m, RejectedMessage)]
    frames = replay(FrameBuilder("run-s2", site, LABELS), accepted, controlled)
    duration = 120.0
    assert len(frames) == round(duration / site.dashboard.frame_period_s) + 1
    assert any(f.alerts for f in frames)
    assert any(f.coverage is not None for f in frames)
    again = replay(FrameBuilder("run-s2", site, LABELS), accepted, controlled)
    assert [f.model_dump_json() for f in frames] == [f.model_dump_json() for f in again]


def record(seq: int, kind: str, label: str | None = None) -> EvidenceRecord:
    return EvidenceRecord(
        seq=seq,
        kind=kind,
        t=0.2,
        alert_id="alert-1",
        track_ids=("trk-1",),
        files=(),
        details={} if label is None else {"label": label},
        prev_hash=None if seq == 1 else f"{seq - 1}" * 64,
        record_hash=f"{seq}" * 64,
    )


def test_cards_show_the_latest_label_and_how_many_records_their_alert_has(
    builder: FrameBuilder,
) -> None:
    frames = feed(
        builder,
        track("trk-1", 0.0),
        threat("trk-1", 0.0, "red", "alert-1"),
        record(1, "alert"),
        record(2, "label", "confirm"),
        record(3, "label", "dismiss"),
        track("trk-1", 0.8),
    )
    assert frames[0].evidence_head is None
    card = frames[-1].alerts[0]
    assert (card.label, card.evidence_records) == ("dismiss", 3)
    assert frames[-1].evidence_head == EvidenceHead(seq=3, record_hash="3" * 64)


def test_the_latest_frame_again_shows_what_changed_since(
    builder: FrameBuilder,
) -> None:
    assert builder.again() is None
    (first,) = feed(
        builder,
        track("trk-1", 0.0),
        threat("trk-1", 0.0, "red", "alert-1"),
        track("trk-1", 0.2),
    )
    builder.ingest(record(1, "alert"))
    builder.ingest(record(2, "label", "confirm"))
    again = builder.again()
    assert again is not None and again.t == first.t == 0.0
    assert (first.alerts[0].label, again.alerts[0].label) == (None, "confirm")
    assert again.evidence_head == EvidenceHead(seq=2, record_hash="2" * 64)
