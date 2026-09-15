"""Strict local geoid-grid sampling for ellipsoidal-to-orthometric heights."""

import hashlib
import math
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS
from pyproj import Transformer
from rasterio.windows import Window


REQUIRED_TAGS = {
    "TARGET_VERTICAL_DATUM": "TWVD2001",
    "OFFSET_CONVENTION": "ELLIPSOIDAL_HEIGHT_MINUS_ORTHOMETRIC_HEIGHT",
    "UNIT": "metre",
    "AREA_OR_POINT": "Point",
}


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def apply_geoid(photos, path: Path, config):
    """Attach bilinearly interpolated N values; invalid samples remain unavailable."""
    path = path.resolve(strict=True)
    before = path.stat()
    digest = _sha256(path)
    if digest != config.geoid_sha256:
        raise ValueError("geoid grid SHA-256 does not match config")
    with rasterio.open(path) as ds:
        tags = ds.tags()
        if ds.count != 1 or ds.crs is None or CRS.from_user_input(ds.crs).to_epsg() != 3824:
            raise ValueError("geoid grid must be a single-band EPSG:3824 (TWD97) GeoTIFF")
        if ds.transform.b != 0 or ds.transform.d != 0 or ds.transform.a <= 0 or ds.transform.e >= 0:
            raise ValueError("geoid grid must be an unrotated north-up grid")
        if ds.scales[0] != 1 or ds.offsets[0] != 0:
            raise ValueError("geoid grid must contain unscaled offsets in metres")
        for key, expected in REQUIRED_TAGS.items():
            if tags.get(key) != expected:
                raise ValueError(f"geoid grid {key} must be {expected}")
        for key in ("MODEL_NAME", "SOURCE_URL", "SOURCE_SHA256"):
            if not tags.get(key):
                raise ValueError(f"geoid grid requires provenance tag {key}")
        if tags["TARGET_VERTICAL_DATUM"] != config.dsm_vertical_datum:
            raise ValueError("geoid target datum does not match declared DSM vertical datum")

        inverse = ~ds.transform
        to_grid = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
        for p in photos:
            p.geoid_status = "NO_DATA"
            if p.latitude is None or p.longitude is None or not -90 <= p.latitude <= 90 or not -180 <= p.longitude <= 180:
                continue
            x, y = to_grid.transform(p.longitude, p.latitude)
            col_corner, row_corner = inverse @ (x, y)
            col_center, row_center = col_corner - 0.5, row_corner - 0.5
            if not math.isfinite(col_center) or not math.isfinite(row_center):
                continue
            col0, row0 = math.floor(col_center), math.floor(row_center)
            if not (0 <= col0 < ds.width - 1 and 0 <= row0 < ds.height - 1):
                p.geoid_status = "OUTSIDE_OR_EDGE"
                continue
            values = ds.read(1, window=Window(col0, row0, 2, 2), masked=True)
            if np.ma.getmaskarray(values).any() or not np.isfinite(values.data).all():
                continue
            tx, ty = col_center - col0, row_center - row0
            top = values.data[0, 0] * (1 - tx) + values.data[0, 1] * tx
            bottom = values.data[1, 0] * (1 - tx) + values.data[1, 1] * tx
            p.geoid_undulation_m = float(top * (1 - ty) + bottom * ty)
            p.geoid_status = "AVAILABLE"

        info = {
            "filename": path.name,
            "sha256": digest,
            "size_bytes": before.st_size,
            "model_name": tags["MODEL_NAME"],
            "source_url": tags["SOURCE_URL"],
            "source_sha256": tags["SOURCE_SHA256"],
            "horizontal_crs": "EPSG:3824",
            "resolution_degrees": [ds.transform.a, abs(ds.transform.e)],
            "width": ds.width,
            "height": ds.height,
            "nodata": ds.nodata,
            "unit": tags["UNIT"],
            "offset_convention": tags["OFFSET_CONVENTION"],
            "target_vertical_datum": tags["TARGET_VERTICAL_DATUM"],
            "interpolation": "bilinear",
            "height_formula": "H = h - N; AGL = H - DSM",
        }
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("geoid grid changed during analysis")
    return info
