import unittest

from uav_photo_optimizer.coverage import protect_cross_strip, side_pair, strip_envelope, strip_frame
from uav_photo_optimizer.config import Config
from uav_photo_optimizer.selection import select
from test_optimizer import config, photo


def make_strip(identifier, east, positions=(0, 10, 20)):
    items = [photo(f"{identifier}-{i}", north, east=east) for i, north in enumerate(positions)]
    for index, item in enumerate(items):
        item.timestamp = index * 2
        item.strip_id = identifier
        item.decision = "KEEP"
    return items


class CrossStripGeometryTests(unittest.TestCase):
    def test_spatial_prefilter_encloses_rotated_footprint_corners(self):
        item = photo(0)
        envelope = strip_envelope([item], config())
        latitude_radius_m = (envelope[1] - item.latitude) * 100_000
        self.assertGreaterEqual(latitude_radius_m, 83.333)

    def test_parallel_strips_measure_seventy_percent_side_overlap(self):
        left = make_strip(1, 0)
        right = make_strip(2, 40)
        cfg = config(cross_strip_enabled=True, min_retained_side_overlap=0.7)
        pair = side_pair(left[1], right[1], strip_frame(left, cfg), strip_frame(right, cfg), cfg)
        self.assertIsNotNone(pair)
        self.assertAlmostEqual(pair.side_overlap, 0.7, places=6)
        self.assertAlmostEqual(pair.along_overlap, 1.0, places=6)

    def test_collinear_fragments_are_not_cross_strips(self):
        first = make_strip(1, 0, positions=(0, 10, 20))
        second = make_strip(2, 0, positions=(30, 40, 50))
        cfg = config(cross_strip_enabled=True, cross_strip_min_separation_m=5)
        self.assertIsNone(side_pair(first[-1], second[0], strip_frame(first, cfg), strip_frame(second, cfg), cfg))


class CrossStripProtectionTests(unittest.TestCase):
    def test_no_eligible_strips_remains_not_evaluated(self):
        result = protect_cross_strip([], config(cross_strip_enabled=True))
        self.assertEqual(result["side_overlap_status"], "NOT_EVALUATED")

    def test_select_runs_cross_strip_pass(self):
        left = make_strip(1, 0, positions=(0, 5, 10))
        right = make_strip(2, 40, positions=(0, 5, 10))
        for i, item in enumerate(left):
            item.timestamp = i * 2
            item.strip_id = None
            item.decision = "BYPASS_KEEP"
        for i, item in enumerate(right):
            item.timestamp = 100 + i * 2
            item.strip_id = None
            item.decision = "BYPASS_KEEP"
        cfg = config(cross_strip_enabled=True, min_retained_side_overlap=0.7)

        result = select(left + right, cfg, force=True)

        self.assertEqual(result["side_overlap_status"], "PASS")
        self.assertGreater(result["cross_strip_evaluated_link_count"], 0)
        self.assertTrue(all(p.cross_strip_status == "PASS" for p in left + right if p.decision != "SKIP"))

    def test_repeated_mission_cannot_supply_side_coverage(self):
        left = make_strip(1, 0)
        right = make_strip(2, 40)
        for i, item in enumerate(left):
            item.timestamp = i * 2
        for i, item in enumerate(right):
            item.timestamp = 86_400 + i * 2
        right[1].decision = "SKIP"
        cfg = config(cross_strip_enabled=True, cross_strip_max_time_gap_seconds=1800)

        result = protect_cross_strip([left, right], cfg)

        self.assertNotEqual(result["side_overlap_status"], "PASS")
        self.assertEqual(right[1].decision, "KEEP")
        self.assertFalse(any(p.cross_strip_status == "PASS" for p in left + right))

    def test_bypass_retained_photo_prevents_global_pass(self):
        left = make_strip(1, 0, positions=(0, 5, 10))
        right = make_strip(2, 40, positions=(0, 5, 10))
        for i, item in enumerate(left):
            item.timestamp = i * 2
            item.strip_id = None
            item.decision = "BYPASS_KEEP"
        for i, item in enumerate(right):
            item.timestamp = 100 + i * 2
            item.strip_id = None
            item.decision = "BYPASS_KEEP"
        bypass = photo(99, north=200, agl=None)
        bypass.timestamp = 200
        cfg = config(cross_strip_enabled=True, cross_strip_max_time_gap_seconds=1800)

        result = select(left + right + [bypass], cfg, force=True)

        self.assertEqual(result["side_overlap_status"], "GAPS_OR_UNCERTAINTY")
        self.assertEqual(result["cross_strip_reduction_subset_status"], "PASS")
        self.assertEqual(result["cross_strip_not_evaluated_photo_count"], 1)
        self.assertEqual(bypass.cross_strip_status, "NOT_EVALUATED")

    def test_skipped_partner_is_restored_for_side_coverage(self):
        cfg = Config(
            cross_strip_enabled=True,
            min_retained_side_overlap=0.7,
            camera_profiles={"TEST": {"sensor_width_mm": 40, "sensor_height_mm": 9,
                                      "image_width": 4000, "image_height": 3000}},
        )
        left = make_strip(1, 0, positions=(0, 20, 40))
        right = make_strip(2, 40, positions=(0, 20, 40))
        right[1].decision = "SKIP"

        result = protect_cross_strip([left, right], cfg)

        self.assertEqual(right[1].decision, "KEEP")
        self.assertTrue(right[1].cross_strip_restored)
        self.assertIn("CROSS_STRIP_LINK_PROTECTION", right[1].reasons)
        self.assertEqual(result["cross_strip_original_gap_count"], 0)

    def test_original_side_gap_is_reported_without_fabricated_pass(self):
        left = make_strip(1, 0)
        right = make_strip(2, 50)
        cfg = config(cross_strip_enabled=True, min_retained_side_overlap=0.7)

        result = protect_cross_strip([left, right], cfg)

        self.assertGreater(result["cross_strip_original_gap_count"], 0)
        self.assertTrue(any(p.cross_strip_status == "ORIGINAL_GAP_OR_UNCERTAIN" for p in left))
        self.assertTrue(all(p.decision == "KEEP" for p in left + right))

    def test_unpaired_strip_restores_all_of_its_candidates(self):
        isolated = make_strip(1, 0)
        isolated[1].decision = "SKIP"
        cfg = config(cross_strip_enabled=True, min_retained_side_overlap=0.7)

        result = protect_cross_strip([isolated], cfg)

        self.assertEqual(isolated[1].decision, "KEEP")
        self.assertTrue(isolated[1].cross_strip_restored)
        self.assertIn("CROSS_STRIP_UNCERTAINTY_PROTECTION", isolated[1].reasons)
        self.assertEqual(result["cross_strip_restored_photo_count"], 1)


if __name__ == "__main__":
    unittest.main()
