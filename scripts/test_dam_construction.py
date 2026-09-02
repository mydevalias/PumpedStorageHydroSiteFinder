"""Tests for dam_construction.py.

Run from the scripts/ directory:
    cd scripts && ../.venv/bin/python -m unittest test_dam_construction -v
"""

import unittest

from dam_construction import estimate_concrete_volume_m3, GRAVITY_DAM_BASE_TO_HEIGHT_RATIO


class TestEstimateConcreteVolume(unittest.TestCase):
    def test_matches_hand_calc(self):
        # base_width = 0.75 * 100 = 75; cross_section = 0.5 * 75 * 100 = 3750 m^2;
        # volume = 3750 * 200 = 750,000 m^3.
        self.assertAlmostEqual(
            estimate_concrete_volume_m3(dam_height_m=100, dam_length_m=200), 750_000
        )

    def test_scales_with_length_linearly(self):
        v1 = estimate_concrete_volume_m3(dam_height_m=50, dam_length_m=100)
        v2 = estimate_concrete_volume_m3(dam_height_m=50, dam_length_m=200)
        self.assertAlmostEqual(v2, v1 * 2)

    def test_scales_with_height_squared(self):
        # Cross-section area is quadratic in height (both base_width and the triangle's
        # other dimension grow with height), so volume should scale with height^2 at a
        # fixed length.
        v1 = estimate_concrete_volume_m3(dam_height_m=50, dam_length_m=100)
        v2 = estimate_concrete_volume_m3(dam_height_m=100, dam_length_m=100)
        self.assertAlmostEqual(v2, v1 * 4)

    def test_zero_or_negative_height_or_length_is_zero(self):
        self.assertEqual(estimate_concrete_volume_m3(0, 200), 0.0)
        self.assertEqual(estimate_concrete_volume_m3(100, 0), 0.0)
        self.assertEqual(estimate_concrete_volume_m3(-5, 200), 0.0)
        self.assertEqual(estimate_concrete_volume_m3(100, -5), 0.0)

    def test_base_to_height_ratio_is_a_plausible_gravity_dam_figure(self):
        # Sanity bound on the constant itself, not a specific project — real concrete
        # gravity dams are commonly cited in the 0.7-0.8x height range for their base
        # width (standard dam-engineering rule of thumb).
        self.assertGreater(GRAVITY_DAM_BASE_TO_HEIGHT_RATIO, 0.5)
        self.assertLess(GRAVITY_DAM_BASE_TO_HEIGHT_RATIO, 1.0)


if __name__ == "__main__":
    unittest.main()
