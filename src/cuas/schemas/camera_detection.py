from cuas.schemas.base import AzimuthDeg, Message, SimTime


class CameraDetection(Message):
    """A camera's first detection in the direction a picket heard a piston engine, noted by
    the dashboard's camera cue and written to the evidence chain by the evidence keeper.

    It records what a camera reported (its station, sensor and measured bearing), never where
    the target really was.
    """

    t: SimTime
    picket_id: str
    station_id: str
    sensor: str
    azimuth_deg: AzimuthDeg
    elevation_deg: float
