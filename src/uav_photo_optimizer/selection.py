"""Near-nadir strip geometry and conservative, linear-time interval restoration."""

import math

from pyproj import Geod

from .config import Config
from .metadata import Photo

GEOD = Geod(ellps="WGS84")
EPS = 1e-9


def angle(a, b):
    return abs((a - b + 180) % 360 - 180)


def distance(a, b):
    bearing, _, meters = GEOD.inv(a.longitude, a.latitude, b.longitude, b.latitude)
    return bearing % 360, meters


def geometry_height(p, config):
    if config.height_mode == "gps_proxy_trial":
        return p.absolute_altitude
    if config.height_mode == "gps_minus_dsm_trial":
        if p.absolute_altitude is None or p.dsm_surface_height_m is None:
            return None
        return p.absolute_altitude - p.dsm_surface_height_m
    return p.agl_m


def prepare(photos, config):
    """Normalize configured angles and trial heights without fabricating AGL."""
    groups = {}
    for p in photos:
        profile = config.camera_profiles.get(p.model, {})
        if profile.get("angle_convention") == "autel_positive_down":
            if p.pitch is None and p.vendor_pitch is not None:
                p.pitch = -p.vendor_pitch
                p.angle_source = "AUTEL_XMP_POSITIVE_DOWN"
            if p.yaw is None and p.vendor_yaw is not None:
                p.yaw = p.vendor_yaw
        p.estimation_height_m = geometry_height(p, config)
        sources = {
            "gps_proxy_trial": "GPS_ALTITUDE_PROXY_NOT_AGL",
            "gps_minus_dsm_trial": "GPS_MINUS_DSM_VERTICAL_DATUM_UNCONFIRMED",
        }
        p.estimation_height_source = sources.get(config.height_mode, p.height_source)
        groups.setdefault((p.model, p.serial), []).append(p)
    if config.height_mode not in ("gps_proxy_trial", "gps_minus_dsm_trial"):
        return
    for group in groups.values():
        group.sort(key=lambda p: (p.timestamp is None, p.timestamp or 0, p.relative_path))
        for i, p in enumerate(group):
            h = geometry_height(p, config)
            stable = h is not None and h > 0 and p.timestamp is not None
            nearby = []
            # Fixed five-image window; don't connect unrelated flight times.
            for j in range(max(0, i - 2), min(len(group), i + 3)):
                q = group[j]
                if p.timestamp is None or q.timestamp is None or abs(q.timestamp - p.timestamp) > config.max_time_gap_seconds:
                    continue
                q_height = geometry_height(q, config)
                if q_height is None or q_height <= 0:
                    stable = False
                    continue
                nearby.append(q_height)
                if abs(j - i) == 1 and h is not None and abs(q_height - h) > config.gps_max_step_m:
                    stable = False
            if nearby and max(nearby) - min(nearby) > config.gps_max_window_range_m:
                stable = False
            p.gps_height_stable = stable

def eligibility(p: Photo, config: Config) -> str | None:
    scan_errors = {"EXIFTOOL_UNAVAILABLE", "UNSUPPORTED_PATH_NEWLINE", "METADATA_BATCH_FAILED", "EXIF_READ_FAILED"}
    if scan_errors.intersection(p.reasons):
        return next(reason for reason in p.reasons if reason in scan_errors)
    if config.require_dsm or p.dsm_status != "NOT_REQUESTED":
        if p.dsm_status == "ROUGH":
            return "TERRAIN_CHANGE_PROTECTION"
        if p.dsm_status != "GENTLE":
            return "DSM_DATA_UNAVAILABLE"
    if p.latitude is None or p.longitude is None or not -90 <= p.latitude <= 90 or not -180 <= p.longitude <= 180:
        return "GPS_INVALID"
    if p.timestamp is None:
        return "CAPTURE_TIME_INVALID"
    height = geometry_height(p, config)
    if height is None or height <= 0:
        return "HEIGHT_REFERENCE_UNCERTAIN"
    if config.height_mode in ("gps_proxy_trial", "gps_minus_dsm_trial") and p.gps_height_stable is not True:
        return "GPS_HEIGHT_CHANGE_PROTECTION"
    profile = config.camera_profiles.get(p.model)
    if not profile or (p.width, p.height) != (profile["image_width"], profile["image_height"]):
        return "CAMERA_PROFILE_MISSING_OR_SIZE_MISMATCH"
    if p.focal_mm is None or p.focal_mm <= 0:
        return "FOCAL_LENGTH_INVALID"
    if p.pitch is None or abs(p.pitch + 90) > config.max_nadir_deviation_deg:
        return "NADIR_GEOMETRY_UNCERTAIN"
    if p.yaw is None or p.orientation not in (None, 1):
        return "CAMERA_ORIENTATION_UNCERTAIN"
    return None


def footprint(p: Photo, config: Config):
    profile = config.camera_profiles[p.model]
    height = geometry_height(p, config)
    return (height * profile["sensor_height_mm"] / p.focal_mm,
            height * profile["sensor_width_mm"] / p.focal_mm)


def overlap(a: Photo, b: Photo, config: Config) -> float | None:
    """Conservative interval overlap normalized by larger length, not area coverage.

    Supports travel near either camera image axis (forward or sideways flight).
    Diagonal/oblique cases return unknown. Different lengths intersect explicitly.
    """
    if eligibility(a, config) or eligibility(b, config) or (a.model, a.serial, a.focal_mm) != (b.model, b.serial, b.focal_mm):
        return None
    ha, hb = geometry_height(a, config), geometry_height(b, config)
    if abs(ha - hb) / min(ha, hb) > config.max_height_change_ratio:
        return None
    if config.height_mode in ("gps_proxy_trial", "gps_minus_dsm_trial") and abs(ha - hb) > config.gps_max_step_m:
        return None
    if angle(a.yaw, b.yaw) > config.max_heading_change_deg:
        return None
    bearing, meters = distance(a, b)
    length_a, width_a = footprint(a, config)
    length_b, width_b = footprint(b, config)
    if meters < config.min_track_distance_m:
        # GPS direction is unstable while hovering. Use smaller footprint and
        # full distance on both axes, conservatively, rather than a noisy bearing.
        length_a = width_a = min(length_a, width_a)
        length_b = width_b = min(length_b, width_b)
        along = cross = meters
    else:
        axes = []
        for yaw in (a.yaw, b.yaw):
            offsets = (0, 90, 180, 270)
            offset = min(offsets, key=lambda offset: angle(bearing, yaw + offset))
            if angle(bearing, yaw + offset) > config.max_camera_track_angle_deg:
                return None
            axes.append(offset % 180)
        if axes[0] != axes[1]:
            return None
        if axes[0] == 90:
            length_a, width_a = width_a, length_a
            length_b, width_b = width_b, length_b
        theta = math.radians(bearing - a.yaw - axes[0])
        along = abs(meters * math.cos(theta))
        cross = abs(meters * math.sin(theta))
    if cross > config.max_cross_track_ratio * min(width_a, width_b) + EPS:
        return None
    intersection = max(0.0, min(length_a / 2, along + length_b / 2) - max(-length_a / 2, along - length_b / 2))
    return max(0.0, min(1.0, intersection / max(length_a, length_b)))


def segment(photos: list[Photo], config: Config) -> list[list[Photo]]:
    # Missing timestamps cannot be localized within a camera stream. Retain that
    # stream instead of accidentally bridging over unknown-time source images.
    bad_streams = {(p.model, p.serial) for p in photos if p.timestamp is None}
    groups = {}
    for p in photos:
        groups.setdefault((p.model or "", p.serial or ""), []).append(p)
    strips = []
    for group in groups.values():
        group.sort(key=lambda p: (p.timestamp is None, p.timestamp or 0, p.relative_path))
        current, last_bearing = [], None
        for p in group:
            issue = eligibility(p, config)
            if (p.model, p.serial) in bad_streams:
                issue = "STREAM_TIME_UNCERTAIN"
            if issue:
                if current:
                    strips.append(current)
                    current = []
                p.reasons = list(dict.fromkeys([*p.reasons, issue]))
                last_bearing = None
                continue
            boundary = None
            bearing = None
            if current:
                previous = current[-1]
                dt = p.timestamp - previous.timestamp
                bearing, meters = distance(previous, p)
                if dt <= 0 or dt > config.max_time_gap_seconds:
                    boundary = "TIME_BOUNDARY"
                elif meters / dt > config.max_speed_mps:
                    boundary = "GPS_JUMP_PROTECTION"
                elif last_bearing is not None and meters >= config.min_track_distance_m and angle(bearing, last_bearing) > config.max_heading_change_deg:
                    boundary = "TURN_PROTECTION"
                elif overlap(previous, p, config) is None:
                    boundary = "GEOMETRY_BOUNDARY"
                if boundary:
                    # Both sides of every boundary become strip endpoints.
                    previous.reasons.append(boundary)
                    strips.append(current)
                    current = []
                    last_bearing = None
            current.append(p)
            if bearing is not None and not boundary and meters >= config.min_track_distance_m:
                last_bearing = bearing
        if current:
            strips.append(current)
    for index, strip in enumerate(strips, 1):
        for p in strip:
            p.strip_id = index
    return strips


def reduce_strip(strip: list[Photo], config: Config):
    anchor = strip[0]
    anchor.decision = "KEEP"
    anchor.reasons.append("FIRST_PHOTO")
    pending = []
    for index, p in enumerate(strip[1:], 1):
        value = overlap(anchor, p, config)
        last = index == len(strip) - 1
        p.candidate_anchor_id = anchor.photo_id
        p.candidate_overlap = value
        if not last and value is not None and value > config.overlap_threshold + EPS:
            p.was_candidate = True
            pending.append(p)
            continue
        safe = value is not None and value + EPS >= config.min_retained_forward_overlap
        if not safe and pending:
            # Keep the last safe intermediate anchor instead of restoring an
            # entire dense run merely because the next sample crossed below
            # the configured floor. Both resulting links must be checked.
            bridge = pending[-1]
            head_value = overlap(anchor, bridge, config)
            tail_value = overlap(bridge, p, config)
            if (head_value is not None and tail_value is not None
                    and min(head_value, tail_value) + EPS >= config.min_retained_forward_overlap):
                for candidate in pending[:-1]:
                    candidate.decision = "SKIP"
                    candidate.reasons.append("EXCESSIVE_FORWARD_OVERLAP")
                bridge.decision = "KEEP"
                bridge.restored = True
                bridge.reasons.append("RETAINED_LINK_PROTECTION")
                pending.clear()
                anchor = bridge
                p.candidate_anchor_id = bridge.photo_id
                p.candidate_overlap = tail_value
                value, safe = tail_value, True
                if not last and tail_value > config.overlap_threshold + EPS:
                    p.was_candidate = True
                    pending.append(p)
                    continue
        for candidate in pending:
            candidate.decision = "SKIP" if safe else "KEEP"
            candidate.restored = not safe
            candidate.reasons.append("EXCESSIVE_FORWARD_OVERLAP" if safe else "CANDIDATE_RESTORED")
        pending.clear()
        p.decision = "KEEP"
        p.reasons.append("LAST_PHOTO" if last else "OVERLAP_WITHIN_THRESHOLD" if value is not None else "LOCAL_GEOMETRY_UNCERTAIN")
        anchor = p
    if len(strip) == 1:
        anchor.reasons.append("LAST_PHOTO")
    previous = None
    for p in strip:
        if p.decision == "SKIP":
            continue
        if previous:
            p.previous_retained_id = previous.photo_id
            p.retained_overlap = overlap(previous, p, config)
            p.retained_link_status = "UNKNOWN" if p.retained_overlap is None else "PASS" if p.retained_overlap + EPS >= config.min_retained_forward_overlap else "FAIL"
            if p.retained_link_status != "PASS":
                p.reasons.append("ORIGINAL_LINK_GAP_OR_UNCERTAINTY")
        previous = p


def select(photos: list[Photo], config: Config, force=False):
    prepare(photos, config)
    trigger_size = sum(p.size_bytes for p in photos) >= config.size_threshold_bytes
    trigger_count = len(photos) >= config.count_threshold
    triggered = config.enabled and (force or trigger_size or trigger_count)
    if not triggered:
        for p in photos:
            p.reasons.append("OPTIMIZER_DISABLED" if not config.enabled else "BELOW_TRIGGER_THRESHOLD")
        return {"trigger_by_size": trigger_size, "trigger_by_count": trigger_count, "forced": force, "optimization_triggered": False, "strip_count": 0}
    strips = segment(photos, config)
    for strip in strips:
        reduce_strip(strip, config)
    return {"trigger_by_size": trigger_size, "trigger_by_count": trigger_count, "forced": force, "optimization_triggered": True, "strip_count": len(strips)}
