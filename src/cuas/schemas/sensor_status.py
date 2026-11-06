from cuas.schemas.base import Message, Probability, SimTime


class SensorStatus(Message):
    """Health of one sensor. ``visibility_factor`` is the share of base range it can reach now."""

    sensor_id: str
    ok: bool
    visibility_factor: Probability
    t: SimTime
