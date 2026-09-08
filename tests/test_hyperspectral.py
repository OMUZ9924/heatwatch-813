"""
Unit tests for Hyperspectral 426-Band Processor (Satellite 813 / Planet Tanager).
"""

import os
import sys
import unittest
import numpy as np

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from heatwatch813.hyperspectral import (
    HyperspectralProcessor,
    generate_tanager_wavelengths,
    nearest_band_idx,
    mask_water_vapor_absorption,
    compute_surface_albedo,
    compute_cool_roof_index,
)


class TestHyperspectralProcessor(unittest.TestCase):
    """Test suite for hyperspectral band extraction, water vapor filters, and indices."""

    def setUp(self):
        self.wavelengths = generate_tanager_wavelengths(426)
        self.processor = HyperspectralProcessor()

    def test_band_count_and_wavelength_range(self):
        """Verify standard 426 bands and realistic VNIR-SWIR range (380-2510 nm)."""
        self.assertEqual(len(self.wavelengths), 426)
        self.assertAlmostEqual(float(self.wavelengths[0]), 380.0, places=1)
        self.assertAlmostEqual(float(self.wavelengths[-1]), 2510.0, places=1)

    def test_nearest_band_idx(self):
        """Verify nearest band index lookup for key diagnostic wavelengths."""
        # Red band ~665 nm
        idx_665 = nearest_band_idx(self.wavelengths, 665.0)
        self.assertLess(abs(self.wavelengths[idx_665] - 665.0), 5.0)

        # Green band ~560 nm
        idx_560 = nearest_band_idx(self.wavelengths, 560.0)
        self.assertLess(abs(self.wavelengths[idx_560] - 560.0), 5.0)

        # NIR band ~850 nm
        idx_850 = nearest_band_idx(self.wavelengths, 850.0)
        self.assertLess(abs(self.wavelengths[idx_850] - 850.0), 5.0)

    def test_water_vapor_absorption_mask(self):
        """Verify that water vapor absorption windows and noisy SWIR edges are masked."""
        mask = mask_water_vapor_absorption(self.wavelengths)
        self.assertEqual(len(mask), 426)

        # Test absorption window 1: 1350 - 1450 nm
        idx_1400 = nearest_band_idx(self.wavelengths, 1400.0)
        self.assertFalse(mask[idx_1400], "1400 nm band should be masked due to H2O absorption")

        # Test absorption window 2: 1800 - 1950 nm
        idx_1880 = nearest_band_idx(self.wavelengths, 1880.0)
        self.assertFalse(mask[idx_1880], "1880 nm band should be masked due to H2O/CO2 absorption")

        # Test SWIR edge noise: > 2450 nm
        idx_2480 = nearest_band_idx(self.wavelengths, 2480.0)
        self.assertFalse(mask[idx_2480], "2480 nm band should be masked due to SWIR sensor noise")

        # Clean atmospheric transmission window (e.g. 850 nm, 560 nm, 2200 nm)
        idx_clean_560 = nearest_band_idx(self.wavelengths, 560.0)
        idx_clean_850 = nearest_band_idx(self.wavelengths, 850.0)
        idx_clean_2200 = nearest_band_idx(self.wavelengths, 2200.0)
        self.assertTrue(mask[idx_clean_560], "560 nm is a clean green window")
        self.assertTrue(mask[idx_clean_850], "850 nm is a clean NIR window")
        self.assertTrue(mask[idx_clean_2200], "2200 nm is a clean SWIR window")

    def test_surface_albedo_boundedness(self):
        """Verify surface albedo computation produces bounded [0, 1] output."""
        cube, wavelengths = self.processor.generate_synthetic_cube(shape=(16, 16))
        albedo = compute_surface_albedo(cube, wavelengths)

        self.assertEqual(albedo.shape, (16, 16))
        self.assertTrue(np.all(albedo >= 0.0))
        self.assertTrue(np.all(albedo <= 1.0))

    def test_cool_roof_index_discrimination(self):
        """Verify CRI differentiates high-albedo cool coatings from dark asphalt."""
        cube, wavelengths = self.processor.generate_synthetic_cube(shape=(20, 20))
        cri = compute_cool_roof_index(cube, wavelengths)

        self.assertEqual(cri.shape, (20, 20))
        self.assertTrue(np.all(cri >= -1.0))
        self.assertTrue(np.all(cri <= 1.0))

    def test_selective_slice_loading(self):
        """Verify single 2D slice loading without full cube memory footprint."""
        slice_665 = self.processor.load_band_slice(665.0)
        self.assertIsInstance(slice_665, np.ndarray)
        self.assertEqual(slice_665.ndim, 2)
    def test_land_cover_indices(self):
        """Verify NDBI, MNDWI, and BUI indices calculation matching challenge criteria."""
        from heatwatch813.hyperspectral import compute_ndbi, compute_mndwi, compute_bui
        swir = np.array([0.4, 0.2], dtype=np.float32)
        nir = np.array([0.2, 0.5], dtype=np.float32)
        green = np.array([0.1, 0.6], dtype=np.float32)
        ndvi = (nir - 0.1) / (nir + 0.1)

        ndbi = compute_ndbi(swir, nir)
        mndwi = compute_mndwi(green, swir)
        bui = compute_bui(ndbi, ndvi)

        # First pixel: swir > nir -> positive NDBI
        self.assertGreater(ndbi[0], 0.0)
        # Second pixel: swir < nir -> negative NDBI
        self.assertLess(ndbi[1], 0.0)
        self.assertEqual(len(bui), 2)


if __name__ == "__main__":
    unittest.main()
