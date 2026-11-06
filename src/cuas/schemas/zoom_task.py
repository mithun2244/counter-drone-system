from cuas.schemas.base import AzimuthDeg, ElevationDeg, Message


class ZoomTask(Message):
    station_id: str
    camera_id: str
    track_id: str
    azimuth_deg: AzimuthDeg
    elevation_deg: ElevationDeg
