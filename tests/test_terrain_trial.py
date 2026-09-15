import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from uav_photo_optimizer.config import Config
from uav_photo_optimizer.selection import select, overlap
from uav_photo_optimizer.terrain import apply_dsm, terrain_metrics
from test_optimizer import config, photo


class TrialTests(unittest.TestCase):
    def test_sideways_flight_uses_long_sensor_dimension(self):
        a, b = photo(0), photo(1, east=20)
        # 40/30*100=133.333m width, hence 85% overlap for 20m motion.
        self.assertAlmostEqual(overlap(a, b, config()), 0.85, places=5)

    def test_hover_noise_does_not_break_sequence(self):
        items = [photo(i, 0.03*(i % 2), east=0.02*(i % 3)) for i in range(8)]
        select(items, config(), force=True)
        self.assertEqual(sum(p.decision == "SKIP" for p in items), 6)

    def test_gps_trial_stable_reduces_without_fabricating_agl(self):
        items = [photo(i, i * 5, agl=None) for i in range(9)]
        for p in items:
            p.absolute_altitude = 100
        select(items, config(height_mode="gps_proxy_trial"), force=True)
        self.assertEqual(sum(p.decision == "SKIP" for p in items), 6)
        self.assertTrue(all(p.agl_m is None for p in items))
        self.assertTrue(all(p.estimation_height_source == "GPS_ALTITUDE_PROXY_NOT_AGL" for p in items))

    def test_gps_changes_and_surrounding_photos_kept(self):
        items = [photo(i, i * 5, agl=None) for i in range(9)]
        for p, height in zip(items, [100, 100, 100, 110, 120, 130, 130, 130, 130]):
            p.absolute_altitude = height
        select(items, config(height_mode="gps_proxy_trial"), force=True)
        self.assertTrue(all(items[i].decision != "SKIP" for i in range(1, 7)))

    def test_gps_minus_dsm_trial_uses_difference_and_preserves_agl(self):
        items = [photo(i, i * 5, agl=None) for i in range(9)]
        for p in items:
            p.absolute_altitude = 180
            p.dsm_surface_height_m = 100
            p.dsm_status = "GENTLE"
        cfg = config(height_mode="gps_minus_dsm_trial", require_dsm=True)
        select(items, cfg, force=True)
        self.assertTrue(all(p.estimation_height_m == 80 for p in items))
        self.assertTrue(all(p.agl_m is None for p in items))
        self.assertTrue(all(p.estimation_height_source == "GPS_MINUS_DSM_VERTICAL_DATUM_UNCONFIRMED" for p in items))

    def test_gps_minus_dsm_height_change_uses_variable_footprints(self):
        a, b = photo(0, 0, agl=None), photo(1, 5, agl=None)
        for item, gps_height in ((a, 150), (b, 200)):
            item.absolute_altitude = gps_height
            item.dsm_surface_height_m = 100
            item.dsm_status = "GENTLE"
        cfg = config(height_mode="gps_minus_dsm_trial", require_dsm=True)

        select([a, b], cfg, force=True)

        self.assertEqual(a.strip_id, b.strip_id)
        self.assertNotIn("GPS_HEIGHT_CHANGE_PROTECTION", a.reasons + b.reasons)
        self.assertIsNotNone(overlap(a, b, cfg))

    def test_gps_minus_dsm_trial_requires_dsm(self):
        with self.assertRaises(ValueError):
            Config(height_mode="gps_minus_dsm_trial")

    def test_dsm_rough_and_missing_kept(self):
        for state in ("ROUGH", "NO_DATA", "OUTSIDE_OR_EDGE", "NOT_REQUESTED"):
            items = [photo(i, i * 5) for i in range(9)]
            for p in items:
                p.dsm_status = state
            select(items, config(require_dsm=True), force=True)
            self.assertTrue(all(p.decision == "BYPASS_KEEP" for p in items))

    def test_last_safe_candidate_restoration(self):
        items = [photo(i, distance) for i, distance in enumerate([0, 5, 10, 15, 21])]
        select(items, config(), force=True)
        self.assertEqual([p.photo_id for p in items if p.decision != "SKIP"], ["0", "3", "4"])
        self.assertTrue(items[3].restored)
        self.assertTrue(all(p.retained_link_status == "PASS" for p in items if p.previous_retained_id))

    def test_seventy_percent_selection(self):
        items = [photo(i, i * 5) for i in range(13)]
        select(items, config(overlap_threshold=0.7, min_retained_forward_overlap=0.7), force=True)
        self.assertEqual([p.photo_id for p in items if p.decision != "SKIP"], ["0", "6", "12"])

    def test_autel_normalization_is_explicit(self):
        items = [photo(0)]
        items[0].pitch = items[0].yaw = None
        items[0].vendor_pitch, items[0].vendor_yaw = 90, 0
        cfg = config()
        cfg.camera_profiles["TEST"]["angle_convention"] = "autel_positive_down"
        select(items, cfg, force=True)
        self.assertEqual(items[0].pitch, -90)
        self.assertEqual(items[0].yaw, 0)

    def test_trial_config_invalid_numbers(self):
        for values in ({"height_mode": "guess"}, {"gps_max_step_m": float("nan")}, {"terrain_max_slope_deg": -1}, {"require_dsm": 1}):
            with self.assertRaises(ValueError):
                Config(**values)


class DSMTests(unittest.TestCase):
    def test_flat_and_planar_slope(self):
        self.assertEqual(terrain_metrics(np.ones((3, 3)), 20, 20), (0, 0))
        z = np.array([[0, 20, 40]] * 3)
        slope, relief = terrain_metrics(z, 20, 20)
        self.assertAlmostEqual(slope, 45)
        self.assertEqual(relief, 40)

    def test_read_projected_grid_masks_and_edges(self):
        from pyproj import Transformer
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.tif"
            values = np.full((7, 7), 123, dtype="float32")
            values[1, 1] = -32767
            with rasterio.open(path, "w", driver="GTiff", width=7, height=7, count=1, dtype="float32", crs="EPSG:3857", transform=from_origin(0, 140, 20, 20), nodata=-32767) as ds:
                ds.write(values, 1)
            points = []
            convert = Transformer.from_crs(3857, 4326, always_xy=True)
            for i, (x, y) in enumerate([(90, 50), (30, 110), (10, 130), (1000, 1000)]):
                p = photo(i)
                p.longitude, p.latitude = convert.transform(x, y)
                points.append(p)
            info = apply_dsm(points, path, config())
            self.assertEqual(points[0].dsm_status, "GENTLE")
            self.assertEqual(points[0].dsm_surface_height_m, 123)
            self.assertEqual(points[0].agl_m, 100)  # Never overwritten by DSM subtraction.
            self.assertEqual(points[1].dsm_status, "NO_DATA")
            self.assertTrue(all(p.dsm_status == "OUTSIDE_OR_EDGE" for p in points[2:]))
            self.assertEqual(info["vertical_datum_status"], "UNCONFIRMED_NOT_USED_FOR_AGL")
            self.assertEqual(len(info["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
