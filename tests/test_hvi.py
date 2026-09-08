"""
Unit tests for Thermal LST Retrieval, SAR Urban Extraction, and Heat Vulnerability Index (HVI).
"""

import os
import sys
import unittest
import numpy as np

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from heatwatch813.thermal_engine import (
    compute_fractional_vegetation,
    compute_surface_emissivity,
    compute_lst_from_tirs,
    compute_uhi_anomaly,
    ThermalEngine,
    LAMBDA_TIRS_B10_UM,
    RHO_UM_K,
)
from heatwatch813.sar_urban import (
    to_decibels,
    to_linear,
    compute_sar_cross_ratio,
    filter_desert_sand,
    extract_urban_imperviousness,
)
from heatwatch813.hvi_model import (
    compute_hazard,
    compute_exposure,
    compute_sensitivity,
    compute_adaptation,
    compute_hvi,
    classify_hvi_tiers,
    HeatVulnerabilityIndexModel,
)


class TestThermalEngine(unittest.TestCase):
    """Test suite for physical LST retrieval and UHI anomalies."""

    def test_blackbody_lst_retrieval(self):
        """When emissivity is 1.0 (blackbody), LST should exactly equal T_B - 273.15."""
        tb_k = np.array([[300.0, 310.0], [320.0, 330.0]], dtype=np.float32)
        emissivity = np.ones_like(tb_k)

        lst_c = compute_lst_from_tirs(tb_k, emissivity)
        expected_c = tb_k - 273.15

        np.testing.assert_allclose(lst_c, expected_c, rtol=1e-4)

    def test_graybody_emissivity_correction(self):
        """When emissivity < 1.0, derived LST must be higher than uncorrected brightness temp."""
        tb_k = np.array([315.0], dtype=np.float32)
        emissivity = np.array([0.96], dtype=np.float32)

        lst_c = compute_lst_from_tirs(tb_k, emissivity)
        uncorrected_c = tb_k[0] - 273.15

        self.assertGreater(float(lst_c[0]), uncorrected_c)

    def test_fractional_vegetation_and_emissivity(self):
        """Verify Pv and emissivity calculation from NDVI."""
        ndvi = np.array([-0.2, 0.05, 0.35, 0.75], dtype=np.float32)
        pv = compute_fractional_vegetation(ndvi, ndvi_soil=0.05, ndvi_veg=0.70)

        # Pure soil at NDVI=0.05 -> Pv=0
        self.assertAlmostEqual(float(pv[1]), 0.0, places=4)
        # Dense veg at NDVI=0.75 -> Pv=1.0
        self.assertAlmostEqual(float(pv[3]), 1.0, places=4)

        emissivity = compute_surface_emissivity(ndvi, pv)
        self.assertTrue(np.all(emissivity >= 0.90))
        self.assertTrue(np.all(emissivity <= 1.0))

    def test_uhi_anomaly_calculation(self):
        """Verify UHI anomaly = LST - baseline."""
        lst = np.array([[30.0, 35.0], [38.0, 42.0]], dtype=np.float32)
        uhi, baseline = compute_uhi_anomaly(lst, rural_baseline_celsius=28.0)

        self.assertAlmostEqual(baseline, 28.0)
        np.testing.assert_allclose(uhi, lst - 28.0)


class TestSARUrbanExtraction(unittest.TestCase):
    """Test suite for SAR dual-polarization backscatter and sand discrimination."""

    def test_db_linear_conversions(self):
        """Verify round-trip conversion between linear and decibels."""
        linear_val = np.array([0.01, 0.1, 1.0], dtype=np.float32)
        db_val = to_decibels(linear_val)
        round_trip = to_linear(db_val)

        np.testing.assert_allclose(linear_val, round_trip, rtol=1e-5)

    def test_sand_filter(self):
        """Verify smooth sand produces specular reflection (< -18 dB) identified by filter."""
        vv_db = np.array([-24.0, -20.0, -10.0, -5.0], dtype=np.float32)
        sand_mask = filter_desert_sand(vv_db, sand_threshold_db=-18.0)

        self.assertTrue(sand_mask[0])
        self.assertTrue(sand_mask[1])
        self.assertFalse(sand_mask[2])
        self.assertFalse(sand_mask[3])

    def test_urban_imperviousness_extraction(self):
        """Verify vertical double-bounce backscatter is identified as built-up."""
        vv_db = np.array([-8.0, -22.0], dtype=np.float32)
        vh_db = np.array([-14.0, -28.0], dtype=np.float32)

        is_urban, isf = extract_urban_imperviousness(vv_db, vh_db)

        self.assertTrue(is_urban[0], "High backscatter should be classified as urban")
        self.assertFalse(is_urban[1], "Low backscatter should not be urban")
        self.assertGreater(isf[0], isf[1])


class TestHVIModel(unittest.TestCase):
    """Test suite for the Heat Vulnerability Index formulation and 5-tier classification."""

    def test_hvi_formula_bounds(self):
        """Ensure HVI output is strictly bounded in [0, 1]."""
        shape = (10, 10)
        h = np.random.uniform(0.0, 1.0, shape).astype(np.float32)
        e = np.random.uniform(0.0, 1.0, shape).astype(np.float32)
        s = np.random.uniform(0.0, 1.0, shape).astype(np.float32)
        a = np.random.uniform(0.0, 1.0, shape).astype(np.float32)

        hvi = compute_hvi(h, e, s, a)

        self.assertEqual(hvi.shape, shape)
        self.assertTrue(np.all(hvi >= 0.0))
        self.assertTrue(np.all(hvi <= 1.0))

    def test_adaptation_cooling_effect(self):
        """Higher adaptation (vegetation buffer) should decrease HVI."""
        h = np.array([[0.8]], dtype=np.float32)
        e = np.array([[0.8]], dtype=np.float32)
        s = np.array([[0.8]], dtype=np.float32)

        low_adapt = np.array([[0.1]], dtype=np.float32)
        high_adapt = np.array([[0.9]], dtype=np.float32)

        hvi_low = compute_hvi(h, e, s, low_adapt)
        hvi_high = compute_hvi(h, e, s, high_adapt)

        self.assertGreater(float(hvi_low[0, 0]), float(hvi_high[0, 0]))

    def test_tier_classification(self):
        """Verify 5-tier classification assigns all pixels to valid tiers 1-5."""
        test_hvi = np.array([0.1, 0.3, 0.5, 0.7, 0.9], dtype=np.float32)
        tier_map, stats = classify_hvi_tiers(test_hvi)

        self.assertEqual(list(tier_map), [1, 2, 3, 4, 5])
        self.assertEqual(len(stats), 5)


if __name__ == "__main__":
    unittest.main()
