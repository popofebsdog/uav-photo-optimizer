"""Conservative retained-photo links between parallel flight strips."""

import math
from dataclasses import dataclass

from .geometry import angle, distance, footprint


@dataclass(frozen=True)
class StripFrame:
    strip_id: int
    bearing_deg: float
    image_axis_offset_deg: int


@dataclass(frozen=True)
class SidePair:
    side_overlap: float
    along_overlap: float
    cross_distance_m: float
    along_distance_m: float


def interval_overlap(size_a, size_b, separation):
    intersection = max(
        0.0,
        min(size_a / 2, separation + size_b / 2)
        - max(-size_a / 2, separation - size_b / 2),
    )
    return max(0.0, min(1.0, intersection / max(size_a, size_b)))


def axis_angle(a, b):
    return min(angle(a, b), angle(a, b + 180))


def strip_frame(strip, config):
    if not strip or strip[0].strip_id is None:
        return None
    track_bearing = None
    for previous, current in zip(strip, strip[1:]):
        bearing, meters = distance(previous, current)
        if meters >= config.min_track_distance_m:
            track_bearing = bearing
            break
    if track_bearing is None or strip[0].yaw is None:
        return None
    offsets = (0, 90, 180, 270)
    offset = min(offsets, key=lambda candidate: angle(track_bearing, strip[0].yaw + candidate))
    if angle(track_bearing, strip[0].yaw + offset) > config.max_camera_track_angle_deg:
        return None
    return StripFrame(strip[0].strip_id, track_bearing, offset % 180)


def frame_dimensions(photo, frame, config):
    along, cross = footprint(photo, config)
    return (cross, along) if frame.image_axis_offset_deg == 90 else (along, cross)


def side_pair(a, b, frame_a, frame_b, config):
    if frame_a is None or frame_b is None or frame_a.strip_id == frame_b.strip_id:
        return None
    if axis_angle(frame_a.bearing_deg, frame_b.bearing_deg) > config.max_heading_change_deg:
        return None
    if (a.model, a.serial, a.focal_mm) != (b.model, b.serial, b.focal_mm):
        return None
    if (a.timestamp is None or b.timestamp is None
            or abs(a.timestamp - b.timestamp) > config.cross_strip_max_time_gap_seconds):
        return None
    bearing, meters = distance(a, b)
    theta = math.radians(bearing - frame_a.bearing_deg)
    along_distance = abs(meters * math.cos(theta))
    cross_distance = abs(meters * math.sin(theta))
    if cross_distance < config.cross_strip_min_separation_m:
        return None
    along_a, cross_a = frame_dimensions(a, frame_a, config)
    along_b, cross_b = frame_dimensions(b, frame_b, config)
    return SidePair(
        interval_overlap(cross_a, cross_b, cross_distance),
        interval_overlap(along_a, along_b, along_distance),
        cross_distance,
        along_distance,
    )


def strip_envelope(strip, config):
    latitude = sum(photo.latitude for photo in strip) / len(strip)
    half_extent = max(math.hypot(*footprint(photo, config)) / 2 for photo in strip)
    # 100 km/degree deliberately over-expands the usual local conversion so
    # a prefilter cannot discard a plausible footprint link.
    latitude_pad = half_extent / 100_000
    longitude_pad = half_extent / (100_000 * max(0.01, abs(math.cos(math.radians(latitude)))))
    return (
        min(photo.latitude for photo in strip) - latitude_pad,
        max(photo.latitude for photo in strip) + latitude_pad,
        min(photo.longitude for photo in strip) - longitude_pad,
        max(photo.longitude for photo in strip) + longitude_pad,
    )


def envelopes_overlap(a, b):
    return a[0] <= b[1] and b[0] <= a[1] and a[2] <= b[3] and b[2] <= a[3]


def strip_pair_possible(strip_a, strip_b, frame_a, frame_b, envelope_a, envelope_b, config):
    if frame_a is None or frame_b is None:
        return False
    if axis_angle(frame_a.bearing_deg, frame_b.bearing_deg) > config.max_heading_change_deg:
        return False
    if (strip_a[0].model, strip_a[0].serial, strip_a[0].focal_mm) != (
            strip_b[0].model, strip_b[0].serial, strip_b[0].focal_mm):
        return False
    start_a, end_a = strip_a[0].timestamp, strip_a[-1].timestamp
    start_b, end_b = strip_b[0].timestamp, strip_b[-1].timestamp
    time_gap = max(0, max(start_a, start_b) - min(end_a, end_b))
    return time_gap <= config.cross_strip_max_time_gap_seconds and envelopes_overlap(envelope_a, envelope_b)


def protect_cross_strip(strips, config, all_photos=None):
    result = {
        "side_overlap_status": "NOT_EVALUATED",
        "cross_strip_evaluated_link_count": 0,
        "cross_strip_restored_photo_count": 0,
        "cross_strip_pass_photo_count": 0,
        "cross_strip_original_gap_count": 0,
        "cross_strip_unpaired_photo_count": 0,
        "cross_strip_not_evaluated_photo_count": 0,
        "cross_strip_reduction_subset_status": "NOT_APPLICABLE",
        "cross_strip_reduction_subset_retained_photo_count": 0,
    }
    if not config.cross_strip_enabled:
        return result

    strips = [strip for strip in strips if strip]
    frames = {strip[0].strip_id: strip_frame(strip, config) for strip in strips}
    envelopes = {strip[0].strip_id: strip_envelope(strip, config) for strip in strips}
    photos = [photo for strip in strips for photo in strip]
    universe = photos if all_photos is None else all_photos
    eligible_ids = {photo.photo_id for photo in photos}
    not_evaluated_count = sum(
        photo.decision != "SKIP" and photo.photo_id not in eligible_ids
        for photo in universe
    )
    result["cross_strip_not_evaluated_photo_count"] = not_evaluated_count
    if not photos:
        return result
    partners = {photo.photo_id: [] for photo in photos}
    for index, strip_a in enumerate(strips):
        frame_a = frames.get(strip_a[0].strip_id)
        for strip_b in strips[index + 1:]:
            frame_b = frames.get(strip_b[0].strip_id)
            if not strip_pair_possible(
                    strip_a, strip_b, frame_a, frame_b,
                    envelopes[strip_a[0].strip_id], envelopes[strip_b[0].strip_id], config):
                continue
            for a in strip_a:
                for b in strip_b:
                    pair = side_pair(a, b, frame_a, frame_b, config)
                    if pair is None or pair.side_overlap <= 0 or pair.along_overlap + 1e-9 < config.min_retained_forward_overlap:
                        continue
                    partners[a.photo_id].append((b, pair))
                    partners[b.photo_id].append((a, pair))

    # Original side gaps stay explicit. Restore only when forward reduction
    # removed every otherwise-valid partner of a retained photo.
    restored = set()
    changed = True
    while changed:
        changed = False
        for photo in photos:
            if photo.decision == "SKIP":
                continue
            valid = [item for item in partners[photo.photo_id]
                     if item[1].side_overlap + 1e-9 >= config.min_retained_side_overlap]
            if not valid or any(partner.decision != "SKIP" for partner, _ in valid):
                continue
            partner, _ = max(valid, key=lambda item: (item[1].side_overlap, item[1].along_overlap))
            partner.decision = "KEEP"
            partner.restored = True
            partner.cross_strip_restored = True
            partner.reasons.append("CROSS_STRIP_LINK_PROTECTION")
            restored.add(partner.photo_id)
            changed = True

    links = set()
    for photo in photos:
        if photo.decision == "SKIP":
            continue
        candidates = partners[photo.photo_id]
        valid = [(partner, pair) for partner, pair in candidates
                 if partner.decision != "SKIP"
                 and pair.side_overlap + 1e-9 >= config.min_retained_side_overlap]
        if valid:
            partner, pair = max(valid, key=lambda item: (item[1].side_overlap, item[1].along_overlap))
            photo.cross_strip_status = "PASS"
            photo.cross_strip_partner_id = partner.photo_id
            photo.side_overlap = pair.side_overlap
            photo.cross_strip_along_overlap = pair.along_overlap
            links.add(tuple(sorted((photo.photo_id, partner.photo_id))))
        elif candidates:
            photo.cross_strip_status = "ORIGINAL_GAP_OR_UNCERTAIN"
            photo.reasons.append("ORIGINAL_SIDE_GAP_OR_UNCERTAINTY")
        else:
            photo.cross_strip_status = "UNPAIRED_OR_UNCERTAIN"
            photo.reasons.append("CROSS_STRIP_PAIR_UNCERTAIN")

    retained = [photo for photo in photos if photo.decision != "SKIP"]
    pass_count = sum(photo.cross_strip_status == "PASS" for photo in retained)
    gap_count = sum(photo.cross_strip_status == "ORIGINAL_GAP_OR_UNCERTAIN" for photo in retained)
    unpaired_count = sum(photo.cross_strip_status == "UNPAIRED_OR_UNCERTAIN" for photo in retained)
    skipped_strip_ids = {photo.strip_id for photo in photos if photo.decision == "SKIP"}
    reduction_subset = [photo for photo in retained if photo.strip_id in skipped_strip_ids]
    reduction_subset_status = (
        "NOT_APPLICABLE" if not skipped_strip_ids
        else "PASS" if reduction_subset and all(photo.cross_strip_status == "PASS" for photo in reduction_subset)
        else "GAPS_OR_UNCERTAINTY"
    )
    result.update(
        side_overlap_status="PASS" if pass_count and not gap_count and not unpaired_count and not not_evaluated_count else "GAPS_OR_UNCERTAINTY",
        cross_strip_evaluated_link_count=len(links),
        cross_strip_restored_photo_count=len(restored),
        cross_strip_pass_photo_count=pass_count,
        cross_strip_original_gap_count=gap_count,
        cross_strip_unpaired_photo_count=unpaired_count,
        cross_strip_reduction_subset_status=reduction_subset_status,
        cross_strip_reduction_subset_retained_photo_count=len(reduction_subset),
    )
    return result
