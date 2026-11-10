from typing import Annotated

from pydantic import Field

from cuas.schemas.base import AzimuthDeg, Message, Probability, SimTime


class ClueEvidence(Message):
    """P(drone) from each clue. A clue is ``None`` when it is missing."""

    look: Probability | None = None
    move: Probability | None = None
    sound: Probability | None = None


class HeardBearing(Message):
    """A microphone bearing the classifier's bearing gate matched to a track."""

    t: SimTime
    azimuth_deg: AzimuthDeg
    sigma_deg: Annotated[float, Field(gt=0.0)]


class TrackClass(Message):
    track_id: str
    t: SimTime
    p_drone: Probability
    p_bird: Probability
    p_attack_drone: Probability
    evidence: ClueEvidence
    looks: dict[str, str] = Field(default_factory=dict)
    """The latest frame or sound window matched to this track from each camera and microphone,
    by ``station.sensor``: the opaque ``snapshot_ref`` of its bearing. Empty without recorded
    media."""
    heard: dict[str, HeardBearing] = Field(
        default_factory=dict, exclude_if=lambda heard: not heard
    )
    """The latest microphone bearing matched to this track, by ``station.acoustic``. Left out of
    the JSON when empty, so output without recorded media is unchanged."""
