from cuas.schemas.base import AzimuthDeg, Message, Probability, SimTime


class PicketAlert(Message):
    """A coarse early warning from one picket. ``loudness`` is relative, from 0 to 1."""

    picket_id: str
    t: SimTime
    bearing_deg: AzimuthDeg
    loudness: Probability
    engine_type_probs: dict[str, Probability]
