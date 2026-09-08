"""
Sentinel-1 SAR Urban Footprint & Imperviousness Extractor.

Features:
- Dual-polarization C-band SAR processing (VV and VH channels)
- Decibel calibration and SAR Cross-Ratio (CR = VH / VV)
- Elimination of optical sand-urban confusion in hyper-arid environments (Sharjah, Dubai)
- Double-bounce urban corner reflector extraction vs specular sand scatter
- Built-up density and Impervious Surface Fraction (ISF) mapping
"""

import logging
from typing import Dict, Optional, Tuple, Union
import numpy as np

logger = logging.getLogger("heatwatch813.sar_urban")

# SAR Thresholds for Arid Urban vs Sand Discrimination (dB)
URBAN_VV_THRESHOLD_DB = -12.0      # Double-bounce from vertical concrete & metal buildings
URBAN_VH_THRESHOLD_DB = -18.0      # Depolarized multiple-bounce volume scattering
DESERT_SAND_VV_MAX_DB = -18.0      # Specular reflection away from antenna over smooth sand
MIN_CROSS_RATIO_LINEAR = 0.15      # Cross-polarization ratio threshold (VH / VV)


def to_decibels(linear_backscatter: np.ndarray, floor_val: float = 1e-6) -> np.ndarray:
    """Converts linear radar backscatter intensity to decibels (dB): 10 * log10(sigma0)."""
    safe_lin = np.maximum(linear_backscatter, floor_val)
    return 10.0 * np.log10(safe_lin)


def to_linear(db_backscatter: np.ndarray) -> np.ndarray:
    """Converts backscatter from decibels (dB) back to linear intensity: 10^(sigma0_dB / 10)."""
    return np.power(10.0, db_backscatter / 10.0)


def compute_sar_cross_ratio(
    sigma0_vv: np.ndarray,
    sigma0_vh: np.ndarray,
    in_decibels: bool = True,
) -> np.ndarray:
    """
    Computes SAR Cross-Polarization Ratio (CR).
    In linear terms: CR = sigma0_VH / sigma0_VV
    In decibels: CR_dB = sigma0_VH_dB - sigma0_VV_dB
    """
    if in_decibels:
        cr_db = sigma0_vh - sigma0_vv
        return cr_db
    else:
        safe_vv = np.maximum(sigma0_vv, 1e-6)
        return sigma0_vh / safe_vv


def filter_desert_sand(
    sigma0_vv_db: np.ndarray,
    sand_threshold_db: float = DESERT_SAND_VV_MAX_DB,
) -> np.ndarray:
    """
    Identifies smooth desert sand pixels based on microwave specular reflection.
    Radar microwaves incident on smooth desert sand reflect away from the sensor,
    yielding very low backscatter (sigma0_VV < -18 dB).

    Returns:
        sand_mask: Boolean array where True indicates desert sand / smooth flat terrain.
    """
    return sigma0_vv_db < sand_threshold_db


def extract_urban_imperviousness(
    sigma0_vv_db: np.ndarray,
    sigma0_vh_db: np.ndarray,
    vv_threshold_db: float = URBAN_VV_THRESHOLD_DB,
    vh_threshold_db: float = URBAN_VH_THRESHOLD_DB,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Extracts the urban built-up footprint and continuous Impervious Surface Fraction (ISF).

    Double-bounce geometry between vertical building walls and horizontal ground/asphalt
    generates strong radar backscatter in both co-pol (VV) and cross-pol (VH).

    Returns:
        (built_up_mask, impervious_surface_fraction)
    """
    # Binary urban footprint: strong co-pol and cross-pol returns
    is_urban = (sigma0_vv_db >= vv_threshold_db) & (sigma0_vh_db >= vh_threshold_db)

    # Continuous Impervious Surface Fraction (ISF) [0.0, 1.0]
    # Sigmoidal mapping scaled between rural baseline (-22 dB) and dense commercial high-rise (-5 dB)
    normalized_vv = np.clip((sigma0_vv_db - (-22.0)) / (-5.0 - (-22.0)), 0.0, 1.0)
    normalized_vh = np.clip((sigma0_vh_db - (-28.0)) / (-12.0 - (-28.0)), 0.0, 1.0)

    isf = 0.6 * normalized_vv + 0.4 * normalized_vh
    isf = np.clip(isf, 0.0, 1.0)

    return is_urban, isf.astype(np.float32)


class SARUrbanExtractor:
    """Class wrapper for Sentinel-1 C-SAR urban analytics."""

    def __init__(
        self,
        vv_threshold_db: float = URBAN_VV_THRESHOLD_DB,
        vh_threshold_db: float = URBAN_VH_THRESHOLD_DB,
    ):
        self.vv_threshold_db = vv_threshold_db
        self.vh_threshold_db = vh_threshold_db

    def process_sar_scene(
        self,
        vv_array: np.ndarray,
        vh_array: np.ndarray,
        is_linear: bool = False,
    ) -> Dict[str, Union[np.ndarray, float]]:
        """
        Executes complete SAR urban analysis:
        1. Ensures decibel scale
        2. Computes cross-polarization ratio
        3. Identifies sand vs built-up structures
        4. Calculates Impervious Surface Fraction (ISF)
        """
        if is_linear:
            vv_db = to_decibels(vv_array)
            vh_db = to_decibels(vh_array)
        else:
            vv_db = vv_array.astype(np.float32)
            vh_db = vh_array.astype(np.float32)

        cross_ratio_db = compute_sar_cross_ratio(vv_db, vh_db, in_decibels=True)
        sand_mask = filter_desert_sand(vv_db)
        urban_mask, isf = extract_urban_imperviousness(
            vv_db, vh_db, self.vv_threshold_db, self.vh_threshold_db
        )

        urban_coverage_pct = float(np.mean(urban_mask) * 100.0)
        mean_isf = float(np.mean(isf))

        return {
            "sigma0_vv_db": vv_db,
            "sigma0_vh_db": vh_db,
            "cross_ratio_db": cross_ratio_db,
            "sand_mask": sand_mask,
            "urban_mask": urban_mask,
            "impervious_surface_fraction": isf,
            "urban_coverage_percentage": urban_coverage_pct,
            "mean_isf": mean_isf,
        }
