import json
import tempfile
import unittest
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from uav_photo_optimizer.cli import copy_selected, main
from uav_photo_optimizer.config import Config
from uav_photo_optimizer.metadata import Photo, apply_heights, discover, parse_time, scan
from uav_photo_optimizer.selection import GEOD, overlap, select


def config(**kwargs):
    return Config(camera_profiles={"TEST": {"sensor_width_mm": 40, "sensor_height_mm": 30, "image_width": 4000, "image_height": 3000}}, **kwargs)


def photo(index, north=0, east=0, agl=100):
    lon, lat, _ = GEOD.fwd(121, 24, 0, north)
    lon, lat, _ = GEOD.fwd(lon, lat, 90, east)
    return Photo(str(index), f"{index}.jpg", 10, 1, timestamp=index * 2,
                 latitude=lat, longitude=lon, agl_m=agl, height_source="synthetic fixture",
                 model="TEST", focal_mm=30, width=4000, height=3000, pitch=-90, yaw=0)


class SelectionTests(unittest.TestCase):
    def test_threshold_or_and_boundaries(self):
        for size, count, expected in [(2999, 9, False), (3000, 9, True), (1, 10, True)]:
            items = [photo(i) for i in range(count)]
            items[0].size_bytes = size
            for item in items[1:]:
                item.size_bytes = 0
            result = select(items, config(size_threshold_bytes=3000, count_threshold=10))
            self.assertEqual(result["optimization_triggered"], expected)

    def test_uniform_dense_strip_reduces_at_eighty(self):
        items = [photo(i, i * 5) for i in range(9)]
        select(items, config(), force=True)
        self.assertEqual([p.photo_id for p in items if p.decision != "SKIP"], ["0", "4", "8"])
        self.assertTrue(all(p.retained_link_status == "PASS" for p in items if p.previous_retained_id))

    def test_restore_original_discussion_example(self):
        items = [photo(i, position) for i, position in enumerate([0, 15, 35])]
        select(items, config(), force=True)
        self.assertEqual([p.decision for p in items], ["KEEP"] * 3)
        self.assertTrue(items[1].restored)
        self.assertAlmostEqual(items[2].retained_overlap, 0.8)

    def test_minimum_sixty_is_configurable(self):
        items = [photo(i, position) for i, position in enumerate([0, 15, 35])]
        select(items, config(min_retained_forward_overlap=0.6), force=True)
        self.assertEqual(items[1].decision, "SKIP")
        self.assertAlmostEqual(items[2].retained_overlap, 0.65)

    def test_missing_agl_never_uses_relative_altitude(self):
        items = [photo(i, i * 5, agl=None) for i in range(5)]
        for p in items:
            p.relative_altitude = 100
        select(items, config(), force=True)
        self.assertTrue(all(p.decision == "BYPASS_KEEP" for p in items))

    def test_height_change_is_unknown(self):
        self.assertIsNone(overlap(photo(0), photo(1, 5, agl=50), config()))

    def test_missing_time_retains_entire_camera_stream(self):
        items = [photo(i, i * 5) for i in range(9)]
        items[3].timestamp = None
        select(items, config(), force=True)
        self.assertTrue(all(p.decision == "BYPASS_KEEP" for p in items))

    def test_local_unknown_breaks_sequence(self):
        items = [photo(i, i * 5) for i in range(9)]
        items[4].agl_m = None
        select(items, config(), force=True)
        self.assertNotEqual(items[3].decision, "SKIP")
        self.assertEqual(items[4].decision, "BYPASS_KEEP")
        self.assertNotEqual(items[5].decision, "SKIP")
        self.assertNotEqual(items[3].strip_id, items[5].strip_id)

    def test_cross_track_and_oblique_rejected(self):
        self.assertIsNone(overlap(photo(0), photo(1, 15, east=30), config()))
        p = photo(1, 5)
        p.pitch = -45
        self.assertIsNone(overlap(photo(0), p, config()))

    def test_original_gap_stays_and_is_reported(self):
        items = [photo(0), photo(1, 40)]
        select(items, config(), force=True)
        self.assertEqual(items[1].retained_link_status, "FAIL")
        self.assertTrue(all(p.decision == "KEEP" for p in items))

    def test_turn_and_time_boundaries_protect_endpoints(self):
        for positions in ([0, 5, 10, 5, 0], [0, 5, 10, 15, 20]):
            items = [photo(i, pos) for i, pos in enumerate(positions)]
            if positions[-1] == 20:
                for item in items[3:]:
                    item.timestamp += 100
            select(items, config(), force=True)
            self.assertNotEqual(items[2].decision, "SKIP")
            self.assertNotEqual(items[3].decision, "SKIP")

    def test_variable_footprints_use_larger_denominator(self):
        value = overlap(photo(0), photo(1, 15, agl=105), config())
        self.assertAlmostEqual(value, (50 - (15 - 52.5)) / 105)

    def test_config_validation(self):
        for value in (float("nan"), float("inf"), -0.1, 1.1, True, "0.8"):
            with self.assertRaises(ValueError):
                Config(min_retained_forward_overlap=value)
        self.assertEqual(Config().min_retained_forward_overlap, 0.8)


class IOTests(unittest.TestCase):
    def test_exiftool_timeout_retains_original(self):
        items = [photo(0)]
        with patch("uav_photo_optimizer.metadata.shutil.which", return_value="exiftool"), patch("uav_photo_optimizer.metadata.subprocess.run", side_effect=subprocess.TimeoutExpired("exiftool", 10)):
            self.assertIsNone(scan(Path("/tmp"), items, config()))
        select(items, config(), force=True)
        self.assertEqual(items[0].decision, "BYPASS_KEEP")

    def test_exiftool_normalization_and_vendor_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            item = photo(0, agl=None)
            record = {"SourceFile": str(root / "0.jpg"), "Model": "XT701", "GPSLatitude": 24,
                      "GPSLongitude": 121, "DateTimeOriginal": "2026:07:31 09:48:58",
                      "AboveGroundAltitude": 258.2, "Pitch": 90, "Yaw": 154.26,
                      "VertCS": "ellipsoidal", "ImageWidth": 8000, "ImageHeight": 6000}
            replies = [subprocess.CompletedProcess([], 0, "13.55\n", ""),
                       subprocess.CompletedProcess([], 0, json.dumps([record]), "")]
            with patch("uav_photo_optimizer.metadata.shutil.which", return_value="exiftool"), patch("uav_photo_optimizer.metadata.subprocess.run", side_effect=replies):
                scan(root, [item], config())
            self.assertEqual(item.model, "XT701")
            self.assertEqual(item.vendor_above_ground_altitude, 258.2)
            self.assertIsNone(item.agl_m)
            self.assertIsNone(item.pitch)
            self.assertEqual(item.vendor_pitch, 90)

    def test_time_subseconds_and_offsets(self):
        self.assertEqual(parse_time("2026:01:01 00:00:01.125") - parse_time("2026:01:01 00:00:00"), 1.125)
        self.assertEqual(parse_time("2026:01:01 08:00:00+08:00"), parse_time("2026:01:01 00:00:00+00:00"))
        self.assertIsNone(parse_time("garbage"))

    def test_no_exiftool_fallback(self):
        items = [photo(0)]
        with patch("uav_photo_optimizer.metadata.shutil.which", return_value=None):
            self.assertIsNone(scan(Path("/tmp"), items, config()))
        select(items, config(), force=True)
        self.assertEqual(items[0].decision, "BYPASS_KEEP")

    def test_copy_preserves_paths_and_detects_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "input"
            for sub in ("a", "b"):
                (root / sub).mkdir(parents=True)
                (root / sub / "same.jpg").write_bytes(sub.encode())
            photos, _ = discover(root.resolve())
            output = Path(directory) / "out"
            records = copy_selected(root.resolve(), output, photos)
            self.assertEqual(len(records), 2)
            self.assertEqual((output / "selected/a/same.jpg").read_bytes(), b"a")
            (root / "a/same.jpg").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                copy_selected(root.resolve(), Path(directory) / "other", photos)

    def test_height_csv_requires_unique_valid_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "heights.csv"
            path.write_text("relative_path,agl_m,source\n0.jpg,100,survey\n", encoding="utf-8")
            items = [photo(0, agl=None)]
            apply_heights(items, path)
            self.assertEqual(items[0].agl_m, 100)
            path.write_text("relative_path,agl_m,source\n0.jpg,-1,survey\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                apply_heights(items, path)

    def test_cli_end_to_end_without_metadata_keeps_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "input"
            root.mkdir()
            (root / "one.jpg").write_bytes(b"test bytes")
            output = Path(directory) / "output"
            with patch("uav_photo_optimizer.metadata.shutil.which", return_value=None):
                result = main([str(root), "--output", str(output), "--force", "--copy"])
            self.assertEqual(result, 0)
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["selected_photo_count"], 1)
            self.assertEqual(summary["side_overlap_status"], "NOT_EVALUATED")
            self.assertIn("cross_strip_evaluated_link_count", summary)
            self.assertEqual((output / "selected/one.jpg").read_bytes(), b"test bytes")
            self.assertEqual(main([str(root), "--output", str(output)]), 2)
            self.assertEqual(main([str(root), "--output", str(root / "nested")]), 2)


if __name__ == "__main__":
    unittest.main()
