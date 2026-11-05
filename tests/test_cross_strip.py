import unittest

from uav_photo_optimizer.coverage import StripFrame, protect_cross_strip, side_pair, strip_envelope, strip_frame
from uav_photo_optimizer.config import Config
from uav_photo_optimizer.selection import evaluate_retained_links, overlap, reduce_strip, select
from test_optimizer import config, photo


def make_strip(identifier, east, positions=(0, 10, 20)):
    items = [photo(f"{identifier}-{i}", north, east=east) for i, north in enumerate(positions)]
    for index, item in enumerate(items):
        item.timestamp = index * 2
        item.strip_id = identifier
        item.decision = "KEEP"
    return items


class CrossStripGeometryTests(unittest.TestCase):
    def test_unequal_interval_geometry_is_exactly_symmetric(self):
        from uav_photo_optimizer.geometry import interval_overlap
        # Unequal real-run dimensions exposed endpoint-dependent last-bit rounding.
        a, b, distance, nominal = 122.11329291699228, 157.77551328204075, 9.333213005002763, 161.4228998186973
        self.assertEqual(interval_overlap(a, b, distance, nominal), interval_overlap(b, a, distance, nominal))

    def test_pair_geometry_is_symmetric_for_different_strip_directions(self):
        a, b = photo(0), photo(1, 29, east=40)
        a.strip_id, b.strip_id, b.yaw = 1, 2, 14
        fa, fb = StripFrame(1, 0, 0), StripFrame(2, 14, 0)
        cfg = config(cross_strip_enabled=True, min_retained_forward_overlap=0.7)
        ab, ba = side_pair(a, b, fa, fb, cfg), side_pair(b, a, fb, fa, cfg)
        self.assertIsNotNone(ab)
        self.assertIsNotNone(ba)
        self.assertAlmostEqual(ab.side_overlap, ba.side_overlap, places=7)
        self.assertAlmostEqual(ab.along_overlap, ba.along_overlap, places=7)

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
    @staticmethod
    def variable_height_case():
        cfg = config(
            height_mode="gps_geoid_dsm", require_dsm=True,
            dsm_vertical_datum="TWVD2001", geoid_sha256="0" * 64,
            cross_strip_enabled=True, overlap_threshold=0.7,
            min_retained_forward_overlap=0.7, min_retained_side_overlap=0.7,
        )
        right = [photo(i, i * 5) for i in range(8)]
        left = [photo(20 + i, 10 + i * 5, east=10) for i in range(2)]
        for i, p in enumerate(right + left):
            p.agl_m = None
            p.absolute_altitude = (75 if i == 2 else 100) if i < 8 else 60
            p.dsm_status, p.dsm_surface_height_m = "GENTLE", 0
            p.geoid_status, p.geoid_undulation_m = "AVAILABLE", 0
            p.vendor_vertical_reference = "ellipsoidal"
        for i, p in enumerate(left):
            p.timestamp = 100 + i * 2
        return right, left, cfg

    def test_cross_restore_repairs_variable_height_forward_chain(self):
        right, left, cfg = self.variable_height_case()
        self.assertTrue(all(overlap(a, b, cfg) >= 0.7 for a, b in zip(right, right[1:])))
        result = select(right + left, cfg, force=True)
        self.assertEqual(result["cross_strip_restored_photo_count"], 1)
        self.assertTrue(right[2].cross_strip_restored)
        self.assertTrue(all(p.retained_link_status == "PASS" for p in right if p.previous_retained_id))
        self.assertFalse(any("ORIGINAL_LINK_GAP_OR_UNCERTAINTY" in p.reasons for p in right))

    def test_new_retained_gap_is_not_labelled_as_original(self):
        right, _, cfg = self.variable_height_case()
        for p in right:
            p.strip_id = 1
        reduce_strip(right, cfg)
        right[2].decision = "KEEP"
        evaluate_retained_links(right, cfg)
        self.assertEqual(right[6].retained_link_status, "FAIL")
        self.assertNotIn("ORIGINAL_LINK_GAP_OR_UNCERTAINTY", right[6].reasons)
        self.assertIn("RETAINED_LINK_GAP_OR_UNCERTAINTY", right[6].reasons)

    def test_protection_is_invariant_to_strip_processing_order(self):
        def run(reverse):
            left = make_strip(1, 0, positions=(0, 10, 20))
            right = make_strip(2, 40, positions=(29, 39, 49))
            # A nearly parallel strip with its camera aligned to its track.
            from uav_photo_optimizer.geometry import GEOD
            for i, p in enumerate(right):
                p.longitude, p.latitude, _ = GEOD.fwd(right[0].longitude, right[0].latitude, 14, i * 10)
                p.yaw = 14
            right[1].decision = "SKIP"
            cfg = config(cross_strip_enabled=True, min_retained_forward_overlap=0.7)
            strips = [left, right]
            result = protect_cross_strip(list(reversed(strips)) if reverse else strips, cfg)
            return result, [(p.photo_id, p.decision, p.cross_strip_status, p.cross_strip_partner_id) for p in left + right]
        self.assertEqual(run(False), run(True))

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
        self.assertEqual(right[1].decision, "SKIP")
        self.assertFalse(right[1].cross_strip_restored)
        self.assertEqual(result["cross_strip_reduction_subset_status"], "GAPS_OR_UNCERTAINTY")
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

    def test_unpaired_strip_keeps_safe_forward_reduction(self):
        isolated = make_strip(1, 0)
        isolated[1].decision = "SKIP"
        cfg = config(cross_strip_enabled=True, min_retained_side_overlap=0.7)

        result = protect_cross_strip([isolated], cfg)

        self.assertEqual(isolated[1].decision, "SKIP")
        self.assertFalse(isolated[1].cross_strip_restored)
        self.assertEqual(result["cross_strip_restored_photo_count"], 0)
        self.assertEqual(result["cross_strip_reduction_subset_status"], "GAPS_OR_UNCERTAINTY")


if __name__ == "__main__":
    unittest.main()
