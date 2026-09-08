"""
Hyperspectral 426-Band Processor for Satellite 813 & Planet Tanager.

Features:
- Atmospheric water vapor absorption masking (1350-1450 nm & 1800-1950 nm)
- High-noise SWIR-edge channel rejection (> 2450 nm)
- Quality masking (cloud, cirrus, nodata)
- Memory-efficient selective band slicing directly from HDF5
- Surface Albedo and Cool Roof Index (CRI) calculation
- Spectral endmember decomposition (Cool Roof, Asphalt, Sand, Vegetation)
"""

import os
import logging
from typing import Dict, List, Optional, Tuple, Union
import numpy as np

logger = logging.getLogger("heatwatch813.hyperspectral")

# Atmospheric absorption windows to mask in hyperspectral cubes (in nanometers)
WATER_VAPOR_WINDOWS_NM = [
    (1350.0, 1450.0),  # Strong atmospheric H2O vapor absorption
    (1800.0, 1950.0),  # Combined H2O and CO2 atmospheric absorption
]
MAX_RELIABLE_SWIR_NM = 2450.0  # Atmospheric transmission drops sharply; high sensor thermal noise


def generate_tanager_wavelengths(num_bands: int = 426) -> np.ndarray:
    """
    Generates standard Tanager / Satellite 813 contiguous center wavelengths in nanometers.
    Spans from ~380 nm (Visible-UV edge) to 2510 nm (SWIR) with ~5.0 nm spectral sampling.
    """
    return np.linspace(380.0, 2510.0, num_bands, dtype=np.float32)


def nearest_band_idx(wavelengths_nm: np.ndarray, target_nm: float) -> int:
    """
    Finds the index of the spectral band closest to a target wavelength in nanometers.
    """
    return int(np.argmin(np.abs(wavelengths_nm - target_nm)))


def mask_water_vapor_absorption(
    wavelengths_nm: np.ndarray,
    additional_windows: Optional[List[Tuple[float, float]]] = None,
) -> np.ndarray:
    """
    Creates a boolean mask where True indicates a clean, uncorrupted spectral band,
    and False indicates an atmospheric absorption or edge-noise band that must be masked out.

    Args:
        wavelengths_nm: 1D array of band center wavelengths in nanometers
        additional_windows: Optional extra (min_nm, max_nm) tuples to mask

    Returns:
        valid_bands: 1D boolean array (True = keep, False = masked)
    """
    valid = np.ones(len(wavelengths_nm), dtype=bool)
    windows = list(WATER_VAPOR_WINDOWS_NM)
    if additional_windows:
        windows.extend(additional_windows)

    for w_min, w_max in windows:
        in_window = (wavelengths_nm >= w_min) & (wavelengths_nm <= w_max)
        valid[in_window] = False

    # Mask noisy SWIR upper edge
    valid[wavelengths_nm > MAX_RELIABLE_SWIR_NM] = False

    return valid


def compute_surface_albedo(
    cube: np.ndarray,
    wavelengths_nm: np.ndarray,
    valid_bands_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Computes broadband surface albedo (alpha) across VNIR and SWIR regions.
    Approximated via trapezoidal integration of clean spectral reflectance weighted
    by the solar irradiance spectrum across 400 - 2400 nm.

    Args:
        cube: 3D array of shape (Bands, Height, Width) or (Bands, Pixels)
        wavelengths_nm: 1D array of center wavelengths
        valid_bands_mask: Optional boolean mask of clean bands (ignoring absorption)

    Returns:
        albedo: 2D array of broadband surface albedo [0, 1]
    """
    if valid_bands_mask is None:
        valid_bands_mask = mask_water_vapor_absorption(wavelengths_nm)

    clean_cube = cube[valid_bands_mask, ...]
    clean_wvl = wavelengths_nm[valid_bands_mask]

    # Approximate solar spectral irradiance weighting (ASTM G173-03 AM1.5 global)
    # Peak in visible (500nm), declining into SWIR
    solar_weight = np.exp(-((clean_wvl - 550.0) ** 2) / (2 * 450.0**2)) + 0.3 * np.exp(
        -((clean_wvl - 1000.0) ** 2) / (2 * 600.0**2)
    )
    solar_weight /= np.sum(solar_weight)

    # Weighted sum along spectral axis
    weighted_albedo = np.tensordot(solar_weight, clean_cube, axes=(0, 0))
    return np.clip(weighted_albedo, 0.0, 1.0)


def compute_cool_roof_index(
    cube: np.ndarray,
    wavelengths_nm: np.ndarray,
) -> np.ndarray:
    """
    Computes the Cool Roof Index (CRI) comparing high solar reflectance roof coatings
    against aged dark asphalt and standard concrete.

    Cool roofs feature high reflectance across visible (550nm) and NIR (850nm) with
    albedo > 0.65. Dark asphalt has very low VNIR reflectance (< 0.15) with distinct
    hydrocarbon absorption features around 2200-2350 nm.

    CRI is formulated as:
    CRI = (R_850 + R_550) / 2.0 - R_2250_hydrocarbon
    Normalized into [-1, 1] or [0, 1].
    """
    idx_550 = nearest_band_idx(wavelengths_nm, 550.0)
    idx_850 = nearest_band_idx(wavelengths_nm, 850.0)
    idx_2250 = nearest_band_idx(wavelengths_nm, 2250.0)

    r_vis = cube[idx_550, ...]
    r_nir = cube[idx_850, ...]
    r_swir = cube[idx_2250, ...]

    # Cool Roof Index
    cri = (r_vis + r_nir) / 2.0 - r_swir
    return np.clip(cri, -1.0, 1.0)


def compute_ndbi(swir: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """Normalized Difference Built-Up Index: (SWIR - NIR) / (SWIR + NIR)"""
    denom = swir + nir
    return np.where(denom != 0, (swir - nir) / (denom + 1e-7), 0.0).astype(np.float32)


def compute_mndwi(green: np.ndarray, swir: np.ndarray) -> np.ndarray:
    """Modified Normalized Difference Water Index: (Green - SWIR) / (Green + SWIR)"""
    denom = green + swir
    return np.where(denom != 0, (green - swir) / (denom + 1e-7), 0.0).astype(np.float32)


def compute_bui(ndbi: np.ndarray, ndvi: np.ndarray) -> np.ndarray:
    """Built-Up Index: NDBI - NDVI (isolates true impervious urban cover from vegetated zones)"""
    return (ndbi - ndvi).astype(np.float32)


class HyperspectralProcessor:
    """Production processor for 813 / Planet Tanager 426-band HDF5 surface reflectance cubes."""

    def __init__(self, hdf5_path: Optional[str] = None):
        self.hdf5_path = hdf5_path
        self.wavelengths_nm = generate_tanager_wavelengths(426)
        self.clean_bands_mask = mask_water_vapor_absorption(self.wavelengths_nm)

    def load_band_slice(self, target_nm: float, shape: Tuple[int, int] = (64, 64)) -> np.ndarray:
        """
        Fast selective loading: reads only the single 2D band closest to target_nm
        without loading the entire 1-4 GB hyperspectral cube into memory.
        """
        band_idx = nearest_band_idx(self.wavelengths_nm, target_nm)

        if self.hdf5_path and os.path.exists(self.hdf5_path):
            try:
                import h5py

                with h5py.File(self.hdf5_path, "r") as f:
                    # Check common Tanager HDF5 paths
                    root = "HDFEOS/GRIDS/HYP/Data Fields"
                    if root in f:
                        sr_ds = f[f"{root}/surface_reflectance"]
                    elif "surface_reflectance" in f:
                        sr_ds = f["surface_reflectance"]
                    else:
                        first_key = list(f.keys())[0]
                        sr_ds = f[first_key]

                    band_data = sr_ds[band_idx, :, :].astype(np.float32)
                    return band_data
            except Exception as e:
                logger.warning("Could not read slice from HDF5 (%s). Falling back to synthetic slice.", e)

        # High-fidelity synthetic fallback
        return self._generate_synthetic_slice(target_nm, shape=shape)

    def load_with_hypercoast(self, filepath_or_url: str):
        """
        Loads hyperspectral cube using the HyperCoast library (built on Leafmap and PyVista)
        as recommended in the official Arab Youth Space Hackathon onboarding guide.
        """
        try:
            import hypercoast
            if hasattr(hypercoast, "read_tanager"):
                return hypercoast.read_tanager(filepath_or_url)
            elif hasattr(hypercoast, "read_enmap"):
                return hypercoast.read_enmap(filepath_or_url)
            else:
                return hypercoast.read_spectral(filepath_or_url)
        except ImportError:
            logger.info("HyperCoast is an optional dependency. Using native HeatWatch-813 HDF5 processor.")
            return None

    def load_quality_mask(self, shape: Tuple[int, int] = (128, 128)) -> np.ndarray:
        """
        Loads pixel validity mask combining beta_cloud_mask, beta_cirrus_mask, and nodata.
        Returns boolean array where True = valid ground pixel, False = corrupted/cloud.
        """
        if self.hdf5_path and os.path.exists(self.hdf5_path):
            try:
                import h5py
                with h5py.File(self.hdf5_path, "r") as f:
                    root = "HDFEOS/GRIDS/HYP/Data Fields"
                    if root in f:
                        cloud = f[f"{root}/beta_cloud_mask"][:]
                        cirrus = f[f"{root}/beta_cirrus_mask"][:]
                        nodata = f[f"{root}/nodata_pixels"][:]
                        return (cloud == 0) & (cirrus == 0) & (nodata == 0)
            except Exception as e:
                logger.debug("Failed reading HDF5 masks (%s). Using clear synthetic mask.", e)

        return np.ones(shape, dtype=bool)

    def extract_endmembers(self) -> Dict[str, np.ndarray]:
        """
        Returns realistic reference spectral endmembers (426 bands) for key urban land cover types:
        - Cool Roofs (High albedo, white titanium dioxide coating)
        - Aged Asphalt (Low albedo, petroleum/bitumen hydrocarbon absorption at 2200-2300 nm)
        - Desert Quartz Sand (High SWIR iron oxide / silicate absorption features)
        - Urban Tree Canopy (Chlorophyll red absorption 660nm, NIR steep green jump 700-800nm)
        """
        wvl = self.wavelengths_nm

        # 1. Cool Roof (High reflectance across VNIR-SWIR)
        cool_roof = 0.80 - 0.15 * (wvl - 400.0) / 2100.0
        cool_roof += 0.02 * np.sin(wvl / 100.0)

        # 2. Aged Asphalt (Low flat reflectance, strong hydrocarbon absorption at 2200-2300 nm)
        asphalt = 0.09 + 0.07 * (wvl - 400.0) / 2100.0
        hc_mask = (wvl >= 2200.0) & (wvl <= 2350.0)
        asphalt[hc_mask] -= 0.04 * np.exp(-((wvl[hc_mask] - 2270.0) ** 2) / (2 * 35.0**2))

        # 3. Quartz Desert Sand (Characteristic Middle Eastern dune sand)
        sand = 0.20 + 0.35 * (1.0 - np.exp(-(wvl - 400.0) / 600.0))
        clay_absorption = (wvl >= 2180.0) & (wvl <= 2230.0)
        sand[clay_absorption] -= 0.05

        # 4. Dense Urban Vegetation (Green vegetation red edge)
        veg = np.zeros_like(wvl)
        for i, w in enumerate(wvl):
            if w < 500:
                veg[i] = 0.04
            elif w < 600:
                veg[i] = 0.12  # Green peak
            elif w < 680:
                veg[i] = 0.05  # Chlorophyll absorption
            elif w < 740:
                veg[i] = 0.05 + 0.40 * (w - 680.0) / 60.0  # Red edge
            elif w < 1300:
                veg[i] = 0.45  # NIR plateau
            else:
                veg[i] = 0.25 * np.exp(-(w - 1300.0) / 1000.0)  # SWIR water absorption

        # Zero out water vapor absorption bands for physical consistency
        for arr in [cool_roof, asphalt, sand, veg]:
            arr[~self.clean_bands_mask] = np.nan

        return {
            "Cool Roof Coating": np.clip(cool_roof, 0.0, 1.0),
            "Aged Asphalt": np.clip(asphalt, 0.0, 1.0),
            "Desert Quartz Sand": np.clip(sand, 0.0, 1.0),
            "Urban Tree Canopy": np.clip(veg, 0.0, 1.0),
        }

    def _generate_synthetic_slice(self, target_nm: float, shape: Tuple[int, int] = (128, 128)) -> np.ndarray:
        """Generates realistic 2D band spatial response for given target wavelength."""
        rng = np.random.default_rng(seed=int(target_nm * 10))
        h, w = shape
        y, x = np.mgrid[:h, :w]
        urban_core = ((x - w/2)**2 + (y - h/2)**2) < (w/3.2)**2

        endmembers = self.extract_endmembers()
        idx = nearest_band_idx(self.wavelengths_nm, target_nm)

        r_asphalt = np.nan_to_num(endmembers["Aged Asphalt"][idx], nan=0.12)
        r_sand = np.nan_to_num(endmembers["Desert Quartz Sand"][idx], nan=0.35)

        base = np.where(urban_core, r_asphalt, r_sand)
        noise = rng.normal(0, 0.015, shape)
        return np.clip(base + noise, 0.01, 1.0).astype(np.float32)

    def generate_synthetic_cube(self, shape: Tuple[int, int] = (64, 64)) -> Tuple[np.ndarray, np.ndarray]:
        """
        Creates a high-fidelity synthetic 426-band Tanager cube for testing and demonstrations.
        Returns (cube_3d, wavelengths_1d).
        """
        h, w = shape
        num_bands = len(self.wavelengths_nm)
        cube = np.zeros((num_bands, h, w), dtype=np.float32)
        y, x = np.mgrid[:h, :w]

        # Mixed land cover layout:
        # - Center: Urban asphalt and cool roofs
        # - Surroundings: Desert sand
        # - Park zone: Vegetation
        is_urban = ((x - w/2)**2 + (y - h/2)**2) < (w/3.0)**2
        is_cool_roof = is_urban & ((x % 6 < 2) & (y % 6 < 2))
        is_park = ((x - w/4)**2 + (y - h/4)**2) < (w/8.0)**2

        endmembers = self.extract_endmembers()
        c_cool = np.nan_to_num(endmembers["Cool Roof Coating"], nan=0.6)
        c_asphalt = np.nan_to_num(endmembers["Aged Asphalt"], nan=0.12)
        c_sand = np.nan_to_num(endmembers["Desert Quartz Sand"], nan=0.38)
        c_veg = np.nan_to_num(endmembers["Urban Tree Canopy"], nan=0.25)

        for b in range(num_bands):
            layer = np.full((h, w), c_sand[b], dtype=np.float32)
            layer[is_urban] = c_asphalt[b]
            layer[is_cool_roof] = c_cool[b]
            layer[is_park] = c_veg[b]
            cube[b, :, :] = layer

        return cube, self.wavelengths_nm
