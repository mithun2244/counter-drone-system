from cuas.schemas.base import Message, Probability, SimTime


class ClueEvidence(Message):
    """P(drone) from each clue. A clue is ``None`` when it is missing."""

    look: Probability | None = None
    move: Probability | None = None
    sound: Probability | None = None


class TrackClass(Message):
    track_id: str
    t: SimTime
    p_drone: Probability
    p_bird: Probability
    p_attack_drone: Probability
    evidence: ClueEvidence
