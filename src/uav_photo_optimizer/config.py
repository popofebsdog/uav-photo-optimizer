"""Validated, serializable configuration."""

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    enabled: bool = True
    height_mode: str = "strict_agl"
    gps_max_step_m: float = 2.0
    gps_max_window_range_m: float = 5.0
    require_dsm: bool = False
    dsm_vertical_datum: str | None = None
    geoid_sha256: str | None = None
    terrain_max_slope_deg: float = 10.0
    terrain_max_relief_m: float = 10.0
    cross_strip_enabled: bool = False
    min_retained_side_overlap: float = 0.7
    cross_strip_min_separation_m: float = 5.0
    cross_strip_max_time_gap_seconds: float = 1800.0
    size_threshold_bytes: int = 3_000_000_000  # Decimal GB, not GiB.
    count_threshold: int = 1000
    overlap_threshold: float = 0.8
    min_retained_forward_overlap: float = 0.8
    max_time_gap_seconds: float = 10.0
    max_speed_mps: float = 35.0
    max_heading_change_deg: float = 15.0
    max_nadir_deviation_deg: float = 10.0
    max_height_change_ratio: float = 0.1
    max_cross_track_ratio: float = 0.05
    max_camera_track_angle_deg: float = 10.0
    min_track_distance_m: float = 2.0
    metadata_timeout_seconds: int = 120
    metadata_batch_size: int = 100
    camera_profiles: dict = field(default_factory=dict)

    def __post_init__(self):
        modes = ("strict_agl", "gps_proxy_trial", "gps_minus_dsm_trial", "gps_geoid_dsm")
        if self.height_mode not in modes:
            raise ValueError(f"height_mode must be one of {', '.join(modes)}")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if type(self.require_dsm) is not bool:
            raise ValueError("require_dsm must be boolean")
        if type(self.cross_strip_enabled) is not bool:
            raise ValueError("cross_strip_enabled must be boolean")
        if self.height_mode in ("gps_minus_dsm_trial", "gps_geoid_dsm") and not self.require_dsm:
            raise ValueError(f"{self.height_mode} requires require_dsm=true")
        if self.dsm_vertical_datum is not None and (not isinstance(self.dsm_vertical_datum, str) or not self.dsm_vertical_datum.strip()):
            raise ValueError("dsm_vertical_datum must be a non-empty string or null")
        if self.height_mode == "gps_geoid_dsm" and self.dsm_vertical_datum != "TWVD2001":
            raise ValueError("gps_geoid_dsm requires dsm_vertical_datum=TWVD2001")
        if self.geoid_sha256 is not None and (
                not isinstance(self.geoid_sha256, str) or len(self.geoid_sha256) != 64
                or any(character not in "0123456789abcdef" for character in self.geoid_sha256)):
            raise ValueError("geoid_sha256 must be 64 lowercase hexadecimal characters or null")
        if self.height_mode == "gps_geoid_dsm" and self.geoid_sha256 is None:
            raise ValueError("gps_geoid_dsm requires a pinned geoid_sha256")
        for key in ("size_threshold_bytes", "count_threshold", "metadata_timeout_seconds", "metadata_batch_size"):
            value = getattr(self, key)
            if type(value) is not int or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        for key in ("overlap_threshold", "min_retained_forward_overlap", "min_retained_side_overlap", "max_height_change_ratio", "max_cross_track_ratio"):
            self._number(key, 0, 1)
        for key in ("max_heading_change_deg", "max_nadir_deviation_deg", "max_camera_track_angle_deg", "terrain_max_slope_deg"):
            self._number(key, 0, 45)
        for key in ("max_time_gap_seconds", "max_speed_mps", "gps_max_step_m", "gps_max_window_range_m", "terrain_max_relief_m", "min_track_distance_m", "cross_strip_min_separation_m", "cross_strip_max_time_gap_seconds"):
            self._number(key, 0.000001, float("inf"))
        if not isinstance(self.camera_profiles, dict):
            raise ValueError("camera_profiles must be an object keyed by exact camera model")
        for model, profile in self.camera_profiles.items():
            if not isinstance(model, str) or not isinstance(profile, dict):
                raise ValueError("invalid camera profile")
            if profile.get("angle_convention") not in (None, "autel_positive_down"):
                raise ValueError("unsupported camera angle convention")
            for key in ("sensor_width_mm", "sensor_height_mm", "image_width", "image_height"):
                value = profile.get(key)
                if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                    raise ValueError(f"camera profile {model}: invalid {key}")

    def _number(self, key, low, high):
        value = getattr(self, key)
        if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be a finite number in [{low}, {high}]")

    def snapshot(self):
        return asdict(self)


def load_config(path: Path | None) -> Config:
    if path is None:
        return Config()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    try:
        return Config(**data)
    except TypeError as error:
        raise ValueError(f"unknown or invalid config fields: {error}") from error
