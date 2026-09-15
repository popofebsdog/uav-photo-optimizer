"""Local DSM terrain gate. No implicit conversion of unknown vertical datums."""

import hashlib
import math
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.windows import Window


def terrain_metrics(values, dx, dy):
    """Horn 3x3 central slope and full-window relief, in metres/degrees."""
    z = np.asarray(values, dtype=float)
    if z.shape != (3, 3) or not np.isfinite(z).all() or dx <= 0 or dy <= 0:
        raise ValueError("invalid terrain window")
    dzdx = ((z[0, 2] + 2*z[1, 2] + z[2, 2]) - (z[0, 0] + 2*z[1, 0] + z[2, 0])) / (8*dx)
    dzdy = ((z[2, 0] + 2*z[2, 1] + z[2, 2]) - (z[0, 0] + 2*z[0, 1] + z[0, 2])) / (8*dy)
    return math.degrees(math.atan(math.hypot(dzdx, dzdy))), float(z.max() - z.min())


def apply_dsm(photos, path: Path, config):
    path = path.resolve(strict=True)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    with rasterio.open(path) as ds:
        if ds.crs is None:
            raise ValueError("DSM has no horizontal CRS")
        crs = CRS.from_user_input(ds.crs)
        if not crs.is_projected or any(abs(axis.unit_conversion_factor - 1) > 1e-10 for axis in crs.axis_info[:2]):
            raise ValueError("DSM must use a projected CRS with metre units")
        if ds.transform.b != 0 or ds.transform.d != 0:
            raise ValueError("rotated DSM grids are not supported")
        dx, dy = abs(ds.transform.a), abs(ds.transform.e)
        if dx <= 0 or dy <= 0:
            raise ValueError("invalid DSM cell dimensions")
        if ds.scales[0] != 1 or ds.offsets[0] != 0:
            raise ValueError("DSM must contain unscaled height values in metres")
        transform = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        for p in photos:
            p.dsm_status = "NO_DATA"
            if p.latitude is None or p.longitude is None or not -90 <= p.latitude <= 90 or not -180 <= p.longitude <= 180:
                continue
            x, y = transform.transform(p.longitude, p.latitude)
            if not math.isfinite(x) or not math.isfinite(y):
                continue
            row, col = ds.index(x, y)
            if not (1 <= row < ds.height - 1 and 1 <= col < ds.width - 1):
                p.dsm_status = "OUTSIDE_OR_EDGE"
                continue
            values = ds.read(1, window=Window(col - 1, row - 1, 3, 3), masked=True)
            if np.ma.getmaskarray(values).any() or not np.isfinite(values.data).all():
                continue
            slope, relief = terrain_metrics(values.data, dx, dy)
            p.dsm_surface_height_m = float(values[1, 1])
            p.dsm_slope_deg = slope
            p.dsm_relief_m = relief
            p.dsm_status = "GENTLE" if slope <= config.terrain_max_slope_deg and relief <= config.terrain_max_relief_m else "ROUGH"
        uses_height_difference = config.height_mode in ("gps_minus_dsm_trial", "gps_geoid_dsm")
        corrected_height = config.height_mode == "gps_geoid_dsm"
        info = {
            "filename": path.name, "sha256": digest.hexdigest(), "size_bytes": before.st_size,
            "horizontal_crs_wkt": crs.to_wkt(), "resolution_m": [dx, dy],
            "width": ds.width, "height": ds.height, "nodata": ds.nodata,
            "declared_vertical_datum": config.dsm_vertical_datum,
            "vertical_datum_basis": "Explicit configuration declaration; the GeoTIFF itself has no encoded vertical CRS",
            "vertical_datum_status": "CONFIG_DECLARED_TWVD2001_MATCHES_GEOID_TARGET" if corrected_height else ("UNCONFIRMED_EXPERIMENTAL_SUBTRACTION" if uses_height_difference else "UNCONFIRMED_NOT_USED_FOR_AGL"),
            "usage": "LOCAL_TERRAIN_GATE_AND_TWVD2001_AGL_HEIGHT" if corrected_height else ("LOCAL_TERRAIN_GATE_AND_EXPERIMENTAL_GPS_MINUS_DSM_HEIGHT" if uses_height_difference else "LOCAL_TERRAIN_GATE_ONLY"),
            "height_formula": "GPSAltitude - geoid_undulation - DSM_center_elevation" if corrected_height else ("GPSAltitude - DSM_center_elevation" if uses_height_difference else None),
            "window_cells": [3, 3],
            "limitation": "Local neighborhood classification, not full footprint terrain projection or occlusion validation",
        }
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("DSM changed during analysis")
    return info
