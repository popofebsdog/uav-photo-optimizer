"""Shared geodesic and conservative nadir camera-footprint geometry."""

import math

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


def common_axis(a, b):
    """Midpoint of two near-parallel, undirected headings (modulo 180)."""
    a, b = sorted((a % 180, b % 180))
    return (a + ((b - a + 90) % 180 - 90) / 2) % 180


def frame_footprint(photo, bearing, config):
    """Return an inner rectangle and nominal dimensions in a shared frame.

    Uniformly scale until every corner fits within the yaw-rotated footprint.
    Nominal dimensions remain the denominator, so shrinking cannot inflate overlap.
    """
    offset = min((0, 90, 180, 270), key=lambda value: angle(bearing, photo.yaw + value))
    deviation = angle(bearing, photo.yaw + offset)
    if deviation > config.max_camera_track_angle_deg + EPS:
        return None
    along, cross = footprint(photo, config)
    if offset % 180 == 90:
        along, cross = cross, along
    theta = math.radians(deviation)
    scale = 1 / (math.cos(theta) + max(along / cross, cross / along) * math.sin(theta))
    return along * scale, cross * scale, along, cross


def frame_separation(a, b, bearing):
    # A canonical geodesic direction avoids endpoint-dependent azimuth rounding.
    first, second = sorted((a, b), key=lambda p: (p.longitude, p.latitude))
    heading, meters = distance(first, second)
    theta = math.radians(heading - bearing)
    return abs(meters * math.cos(theta)), abs(meters * math.sin(theta))


def interval_overlap(size_a, size_b, separation, denominator=None):
    size_a, size_b = sorted((size_a, size_b))
    intersection = max(
        0.0,
        min(size_a / 2, separation + size_b / 2)
        - max(-size_a / 2, separation - size_b / 2),
    )
    return max(0.0, min(1.0, intersection / (max(size_a, size_b) if denominator is None else denominator)))
