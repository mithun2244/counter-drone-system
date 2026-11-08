from cuas.schemas.base import AzimuthDeg, ElevationDeg, Message, SimTime


class ZoomTask(Message):
    """Where one zoom camera should point, issued at ``t``."""

    station_id: str
    t: SimTime
    camera_id: str
    track_id: str
    azimuth_deg: AzimuthDeg
    elevation_deg: ElevationDeg
