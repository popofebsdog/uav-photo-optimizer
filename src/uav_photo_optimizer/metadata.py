"""Read only selected EXIF/XMP tags via bounded ExifTool batches."""

import csv
import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config

SUPPORTED = {".jpg", ".jpeg", ".tif", ".tiff", ".dng"}
TAGS = ["Model", "SerialNumber", "DateTimeOriginal", "SubSecDateTimeOriginal", "GPSLatitude", "GPSLongitude",
        "GPSAltitude", "RelativeAltitude", "GimbalPitchDegree", "GimbalYawDegree", "FocalLength",
        "ImageWidth", "ImageHeight", "ExifImageWidth", "ExifImageHeight", "Orientation",
        "XMP-Camera:AboveGroundAltitude", "XMP-Camera:Pitch", "XMP-Camera:Yaw", "XMP-Camera:VertCS"]


@dataclass
class Photo:
    photo_id: str
    relative_path: str
    size_bytes: int
    mtime_ns: int
    capture_time: str | None = None
    timestamp: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    absolute_altitude: float | None = None
    relative_altitude: float | None = None
    agl_m: float | None = None
    height_source: str | None = None
    model: str | None = None
    serial: str | None = None
    focal_mm: float | None = None
    width: int | None = None
    height: int | None = None
    pitch: float | None = None
    yaw: float | None = None
    orientation: int | None = None
    vendor_above_ground_altitude: float | None = None
    vendor_pitch: float | None = None
    vendor_yaw: float | None = None
    vendor_vertical_reference: str | None = None
    estimation_height_m: float | None = None
    estimation_height_source: str | None = None
    angle_source: str | None = None
    gps_height_stable: bool | None = None
    dsm_status: str = "NOT_REQUESTED"
    dsm_surface_height_m: float | None = None
    dsm_slope_deg: float | None = None
    dsm_relief_m: float | None = None
    geoid_status: str = "NOT_REQUESTED"
    geoid_undulation_m: float | None = None
    strip_id: int | None = None
    decision: str = "BYPASS_KEEP"
    reasons: list[str] = field(default_factory=list)
    was_candidate: bool = False
    restored: bool = False
    candidate_anchor_id: str | None = None
    candidate_overlap: float | None = None
    previous_retained_id: str | None = None
    retained_overlap: float | None = None
    retained_link_status: str = "NOT_EVALUATED"
    cross_strip_status: str = "NOT_EVALUATED"
    cross_strip_partner_id: str | None = None
    side_overlap: float | None = None
    cross_strip_along_overlap: float | None = None
    cross_strip_restored: bool = False


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def parse_time(value):
    if not isinstance(value, str) or len(value) < 19:
        return None
    try:
        parsed = datetime.fromisoformat(value[:10].replace(":", "-") + value[10:])
        # Naive timestamps use a fixed origin, never host timezone or DST.
        if parsed.tzinfo is None:
            return (parsed - datetime(1970, 1, 1)).total_seconds()
        return parsed.timestamp()
    except ValueError:
        return None


def discover(root: Path) -> tuple[list[Photo], int]:
    photos, ignored = [], 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink() or path.suffix.lower() not in SUPPORTED:
            ignored += 1
            continue
        # Do not follow directory symlinks pointing outside the selected input.
        if not path.resolve().is_relative_to(root):
            ignored += 1
            continue
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        identity = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
        photos.append(Photo(identity, relative, stat.st_size, stat.st_mtime_ns))
    return photos, ignored


def scan(root: Path, photos: list[Photo], config: Config) -> str | None:
    executable = shutil.which("exiftool")
    if not executable:
        for photo in photos:
            photo.reasons.append("EXIFTOOL_UNAVAILABLE")
        return None
    try:
        version = subprocess.run([executable, "-ver"], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        for photo in photos:
            photo.reasons.append("EXIFTOOL_UNAVAILABLE")
        return None
    for start in range(0, len(photos), config.metadata_batch_size):
        batch = photos[start:start + config.metadata_batch_size]
        safe = [p for p in batch if "\n" not in p.relative_path and "\r" not in p.relative_path]
        for photo in batch:
            if photo not in safe:
                photo.reasons.append("UNSUPPORTED_PATH_NEWLINE")
        if not safe:
            continue
        try:
            result = subprocess.run(
                [executable, "-json", "-n", *["-" + tag for tag in TAGS], "-@", "-"],
                input="".join(str(root / p.relative_path) + "\n" for p in safe),
                capture_output=True, text=True, timeout=config.metadata_timeout_seconds, check=False,
            )
            records = json.loads(result.stdout)
            if not isinstance(records, list):
                raise ValueError("ExifTool did not return a record list")
            by_path = {str(Path(r["SourceFile"]).resolve()): r for r in records if isinstance(r, dict) and "SourceFile" in r}
        except (subprocess.TimeoutExpired, OSError, ValueError, KeyError):
            for photo in safe:
                photo.reasons.append("METADATA_BATCH_FAILED")
            continue
        for photo in safe:
            record = by_path.get(str(root / photo.relative_path), {})
            if not record or record.get("Error"):
                photo.reasons.append("EXIF_READ_FAILED")
                continue
            photo.capture_time = record.get("SubSecDateTimeOriginal") or record.get("DateTimeOriginal")
            photo.timestamp = parse_time(photo.capture_time)
            for attr, tag in [("latitude", "GPSLatitude"), ("longitude", "GPSLongitude"),
                              ("absolute_altitude", "GPSAltitude"), ("relative_altitude", "RelativeAltitude"),
                              ("focal_mm", "FocalLength"), ("pitch", "GimbalPitchDegree"), ("yaw", "GimbalYawDegree")]:
                setattr(photo, attr, number(record.get(tag)))
            photo.model = record.get("Model")
            photo.serial = str(record["SerialNumber"]) if record.get("SerialNumber") else None
            photo.width = number(record.get("ExifImageWidth") or record.get("ImageWidth"))
            photo.height = number(record.get("ExifImageHeight") or record.get("ImageHeight"))
            photo.orientation = number(record.get("Orientation"))
            photo.vendor_above_ground_altitude = number(record.get("AboveGroundAltitude"))
            photo.vendor_pitch = number(record.get("Pitch"))
            photo.vendor_yaw = number(record.get("Yaw"))
            photo.vendor_vertical_reference = record.get("VertCS")


    return version


def apply_heights(photos: list[Photo], csv_path: Path | None):
    """Only explicit per-image AGL evidence. Never alias RelativeAltitude to AGL."""
    if csv_path is None:
        return
    known = {p.relative_path: p for p in photos}
    seen = set()
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"relative_path", "agl_m", "source"} <= set(reader.fieldnames or []):
            raise ValueError("height CSV requires relative_path,agl_m,source columns")
        for row in reader:
            name = row["relative_path"]
            height = number(row["agl_m"])
            if name not in known or name in seen or height is None or height <= 0 or not row["source"].strip():
                raise ValueError(f"invalid, duplicate or unknown height record: {name}")
            seen.add(name)
            known[name].agl_m = height
            known[name].height_source = row["source"].strip()
            # Optional normalized angles for non-DJI cameras. Their convention
            # must be supplied explicitly, never inferred from a vendor label.
            for column, attribute, low, high in [("pitch_deg", "pitch", -180, 180), ("yaw_deg", "yaw", -360, 360)]:
                if row.get(column):
                    value = number(row[column])
                    if value is None or not low <= value <= high:
                        raise ValueError(f"invalid {column}: {name}")
                    setattr(known[name], attribute, value)
