#!/usr/bin/env python3
"""Convert QPS's published TWHyGEO2014 LLDLLD binary archive to GeoTIFF."""

import argparse
import hashlib
import io
import struct
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


SOURCE_URL = "https://qpssoftware.scrollhelp.site/geodeticui/download-pre-released-vertical-models"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    archive_bytes = args.archive.read_bytes()
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as bundle:
        raw = bundle.read("TWHyGEO2014.bin")
    lat_min_s, lat_max_s, lat_step_s, lon_min_s, lon_max_s, lon_step_s = struct.unpack("<6f", raw[:24])
    if (lat_min_s, lat_max_s, lat_step_s, lon_min_s, lon_max_s, lon_step_s) != (75600, 93600, 30, 428400, 442800, 30):
        raise ValueError("unexpected TWHyGEO2014 grid header")
    height = round((lat_max_s - lat_min_s) / lat_step_s) + 1
    width = round((lon_max_s - lon_min_s) / lon_step_s) + 1
    values = np.frombuffer(raw, dtype="<f4", offset=24)
    if values.size != width * height or not np.isfinite(values).all():
        raise ValueError("unexpected TWHyGEO2014 grid payload")
    values = values.reshape(height, width)[::-1].copy()
    step = lon_step_s / 3600
    west = lon_min_s / 3600 - step / 2
    north = lat_max_s / 3600 + step / 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"output already exists: {args.output}")
    with rasterio.open(
        args.output, "w", driver="GTiff", width=width, height=height, count=1,
        dtype="float32", crs="EPSG:3824", transform=from_origin(west, north, step, step),
        nodata=-9999, compress="deflate", predictor=3,
    ) as ds:
        ds.write(values, 1)
        ds.update_tags(
            AREA_OR_POINT="Point",
            MODEL_NAME="TWHyGEO2014 (QPS pre-release redistribution)",
            SOURCE_URL=SOURCE_URL,
            SOURCE_SHA256=archive_sha256,
            TARGET_VERTICAL_DATUM="TWVD2001",
            OFFSET_CONVENTION="ELLIPSOIDAL_HEIGHT_MINUS_ORTHOMETRIC_HEIGHT",
            UNIT="metre",
        )


if __name__ == "__main__":
    main()
