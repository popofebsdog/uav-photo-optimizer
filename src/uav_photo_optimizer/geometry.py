"""Shared geodesic and camera-footprint geometry."""

from pyproj import Geod

GEOD = Geod(ellps="WGS84")
EPS = 1e-9


def angle(a, b):
    return abs((a - b + 180) % 360 - 180)


def distance(a, b):
    bearing, _, meters = GEOD.inv(a.longitude, a.latitude, b.longitude, b.latitude)
    return bearing % 360, meters


def geometry_height(photo, config):
    if config.height_mode == "gps_proxy_trial":
        return photo.absolute_altitude
    if config.height_mode == "gps_minus_dsm_trial":
        if photo.absolute_altitude is None or photo.dsm_surface_height_m is None:
            return None
        return photo.absolute_altitude - photo.dsm_surface_height_m
    if config.height_mode == "gps_geoid_dsm":
        vertical_reference = (photo.vendor_vertical_reference or "").strip().lower()
        if (vertical_reference != "ellipsoidal" or photo.absolute_altitude is None
                or photo.geoid_undulation_m is None or photo.dsm_surface_height_m is None):
            return None
        return photo.absolute_altitude - photo.geoid_undulation_m - photo.dsm_surface_height_m
    return photo.agl_m


def footprint(photo, config):
    profile = config.camera_profiles[photo.model]
    height = geometry_height(photo, config)
    return (
        height * profile["sensor_height_mm"] / photo.focal_mm,
        height * profile["sensor_width_mm"] / photo.focal_mm,
    )
