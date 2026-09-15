import tempfile
import unittest
import hashlib
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from uav_photo_optimizer.config import Config
from uav_photo_optimizer.geoid import apply_geoid
from uav_photo_optimizer.geometry import geometry_height
from uav_photo_optimizer.selection import select
from test_optimizer import config, photo


TAGS = {
    "MODEL_NAME": "fixture",
    "SOURCE_URL": "https://example.test/geoid.zip",
    "SOURCE_SHA256": "a" * 64,
    "TARGET_VERTICAL_DATUM": "TWVD2001",
    "OFFSET_CONVENTION": "ELLIPSOIDAL_HEIGHT_MINUS_ORTHOMETRIC_HEIGHT",
    "UNIT": "metre",
    "AREA_OR_POINT": "Point",
}


def write_grid(path, values=None, tags=None):
    values = np.asarray(values if values is not None else [[10, 20], [30, 40]], dtype="float32")
    # Sample points are at (120, 24), (121, 24), (120, 23), (121, 23).
    with rasterio.open(
        path, "w", driver="GTiff", width=2, height=2, count=1,
        dtype="float32", crs="EPSG:3824", transform=from_origin(119.5, 24.5, 1, 1),
        nodata=-9999,
    ) as ds:
        ds.write(values, 1)
        ds.update_tags(**(tags or TAGS))


def cfg_for_grid(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return config(
        height_mode="gps_geoid_dsm", require_dsm=True,
        dsm_vertical_datum="TWVD2001", geoid_sha256=digest,
    )


class GeoidTests(unittest.TestCase):
    def test_config_requires_explicit_twvd2001_datum(self):
        with self.assertRaises(ValueError):
            Config(height_mode="gps_geoid_dsm", require_dsm=True)
        with self.assertRaises(ValueError):
            Config(height_mode="gps_geoid_dsm", require_dsm=True, dsm_vertical_datum="EGM2008")
        with self.assertRaises(ValueError):
            Config(height_mode="gps_geoid_dsm", require_dsm=True, dsm_vertical_datum="TWVD2001")

    def test_bilinear_undulation_and_corrected_height(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "geoid.tif"
            write_grid(path)
            p = photo(0, agl=None)
            p.longitude, p.latitude, p.absolute_altitude = 120.25, 23.75, 150
            p.vendor_vertical_reference = "ellipsoidal"
            cfg = cfg_for_grid(path)
            info = apply_geoid([p], path, cfg)
            p.dsm_surface_height_m = 100

            self.assertEqual(p.geoid_status, "AVAILABLE")
            self.assertAlmostEqual(p.geoid_undulation_m, 17.5)
            self.assertAlmostEqual(geometry_height(p, cfg), 32.5)
            self.assertEqual(info["height_formula"], "H = h - N; AGL = H - DSM")
            self.assertEqual(info["target_vertical_datum"], "TWVD2001")
            self.assertEqual(len(info["sha256"]), 64)

    def test_missing_geoid_and_nonpositive_height_are_retained(self):
        cfg = config(height_mode="gps_geoid_dsm", require_dsm=True, dsm_vertical_datum="TWVD2001", geoid_sha256="a" * 64)
        items = [photo(i, i * 5, agl=None) for i in range(2)]
        for p in items:
            p.absolute_altitude = 120
            p.vendor_vertical_reference = "ellipsoidal"
            p.dsm_surface_height_m = 100
            p.dsm_status = "GENTLE"
        items[0].geoid_status = "OUTSIDE_OR_EDGE"
        items[1].geoid_status = "AVAILABLE"
        items[1].geoid_undulation_m = 25

        select(items, cfg, force=True)

        self.assertTrue(all(p.decision == "BYPASS_KEEP" for p in items))
        self.assertIn("GEOID_DATA_UNAVAILABLE", items[0].reasons)
        self.assertIn("HEIGHT_REFERENCE_UNCERTAIN", items[1].reasons)

    def test_unconfirmed_gps_vertical_reference_is_retained(self):
        cfg = config(height_mode="gps_geoid_dsm", require_dsm=True, dsm_vertical_datum="TWVD2001", geoid_sha256="a" * 64)
        p = photo(0, agl=None)
        p.absolute_altitude = 150
        p.dsm_surface_height_m = 100
        p.dsm_status = "GENTLE"
        p.geoid_undulation_m = 25
        p.geoid_status = "AVAILABLE"

        select([p], cfg, force=True)

        self.assertEqual(p.decision, "BYPASS_KEEP")
        self.assertIn("GPS_VERTICAL_REFERENCE_UNCONFIRMED", p.reasons)

    def test_rejects_wrong_datum_convention_units_and_pixel_semantics(self):
        for key, value in (
            ("TARGET_VERTICAL_DATUM", "EGM2008"),
            ("OFFSET_CONVENTION", "ORTHOMETRIC_HEIGHT_MINUS_ELLIPSOIDAL_HEIGHT"),
            ("UNIT", "foot"),
            ("AREA_OR_POINT", "Area"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "geoid.tif"
                tags = {**TAGS, key: value}
                write_grid(path, tags=tags)
                cfg = cfg_for_grid(path)
                with self.assertRaises(ValueError):
                    apply_geoid([photo(0)], path, cfg)

    def test_nodata_and_outside_fail_closed_per_photo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "geoid.tif"
            write_grid(path, [[10, -9999], [30, 40]])
            inside, outside = photo(0), photo(1)
            inside.longitude, inside.latitude = 120.5, 23.5
            outside.longitude, outside.latitude = 130, 30
            cfg = cfg_for_grid(path)

            apply_geoid([inside, outside], path, cfg)

            self.assertEqual(inside.geoid_status, "NO_DATA")
            self.assertEqual(outside.geoid_status, "OUTSIDE_OR_EDGE")

    def test_rejects_changed_grid_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "geoid.tif"
            write_grid(path)
            cfg = cfg_for_grid(path)
            with path.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaises(ValueError):
                apply_geoid([photo(0)], path, cfg)

    def test_converter_preserves_longitude_order_and_flips_latitude(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, output = root / "model.zip", root / "model.tif"
            height, width = 601, 481
            values = np.arange(height * width, dtype="<f4").reshape(height, width)
            header = struct.pack("<6f", 75600, 93600, 30, 428400, 442800, 30)
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("TWHyGEO2014.bin", header + values.tobytes())
            subprocess.run(
                [sys.executable, "scripts/convert_twhygeo2014.py", str(archive), str(output)],
                check=True,
            )
            with rasterio.open(output) as ds:
                converted = ds.read(1)
                self.assertEqual(converted[0, 0], values[-1, 0])
                self.assertEqual(converted[0, -1], values[-1, -1])
                self.assertEqual(converted[-1, 0], values[0, 0])


if __name__ == "__main__":
    unittest.main()
