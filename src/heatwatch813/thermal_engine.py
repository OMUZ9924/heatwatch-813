"""
Thermal Engine for Physical Land Surface Temperature (LST) & UHI Anomaly Retrieval.

Implements:
- Single-channel radiative transfer LST retrieval (Artis & Carnahan formulation)
- Fractional Vegetation Cover (FVC / Pv) via NDVI threshold method (Sobrino et al.)
- Land Surface Emissivity (LSE, epsilon) calculation
- Urban Heat Island (UHI) anomaly computation against regional rural baselines
- Extreme heat anomaly classification
"""

import logging
from typing import Dict, Optional, Tuple, Union
import numpy as np

logger = logging.getLogger("heatwatch813.thermal_engine")

# Physical Constants for Landsat-8/9 TIRS Band 10
LAMBDA_TIRS_B10_UM = 10.895  # Effective center wavelength of TIRS Band 10 in micrometers
RHO_UM_K = 14380.0           # hc/sigma_B = Planck's constant * speed of light / Boltzmann constant (um*K)
KELVIN_OFFSET = 273.15       # 0 Celsius in Kelvin

# Standard Emissivity Threshold Parameters (Sobrino et al., 2004)
EMISSIVITY_VEG = 0.985       # Dense green canopy emissivity
EMISSIVITY_SOIL = 0.960      # Bare soil/mineral surface emissivity
EMISSIVITY_WATER = 0.992     # Open water body emissivity
CAVITY_TERM_C = 0.005        # Surface roughness geometric cavity factor


def compute_fractional_vegetation(
    ndvi: np.ndarray,
    ndvi_soil: float = 0.05,
    ndvi_veg: float = 0.70,
) -> np.ndarray:
    """
    Computes Fractional Vegetation Cover (Pv / FVC) from NDVI using the empirical threshold method.

    Pv = ((NDVI - NDVI_soil) / (NDVI_veg - NDVI_soil)) ** 2

    Args:
        ndvi: 2D array of NDVI values [-1.0, 1.0]
        ndvi_soil: NDVI threshold below which surface is pure bare soil
        ndvi_veg: NDVI threshold above which surface is fully vegetated

    Returns:
        pv: 2D array of fractional vegetation cover [0.0, 1.0]
    """
    denom = max(ndvi_veg - ndvi_soil, 1e-6)
    ratio = (ndvi - ndvi_soil) / denom
    ratio_clipped = np.clip(ratio, 0.0, 1.0)
    return np.square(ratio_clipped)


def compute_surface_emissivity(
    ndvi: np.ndarray,
    pv: Optional[np.ndarray] = None,
    ndvi_soil: float = 0.05,
    ndvi_veg: float = 0.70,
) -> np.ndarray:
    """
    Derives pixel-level Land Surface Emissivity (epsilon) from NDVI and vegetation fraction.

    For pixels where:
    - NDVI < ndvi_soil: Bare soil/built-up -> epsilon = EMISSIVITY_SOIL
    - NDVI > ndvi_veg: Dense vegetation -> epsilon = EMISSIVITY_VEG
    - ndvi_soil <= NDVI <= ndvi_veg: Mixed pixel -> epsilon = EMISSIVITY_VEG*Pv + EMISSIVITY_SOIL*(1-Pv) + C
    - NDVI < 0 (water bodies): -> epsilon = EMISSIVITY_WATER
    """
    if pv is None:
        pv = compute_fractional_vegetation(ndvi, ndvi_soil, ndvi_veg)

    # Base mixed pixel formula
    emissivity = EMISSIVITY_VEG * pv + EMISSIVITY_SOIL * (1.0 - pv) + CAVITY_TERM_C

    # Boundary conditions
    emissivity = np.where(ndvi < 0.0, EMISSIVITY_WATER, emissivity)
    emissivity = np.where((ndvi >= 0.0) & (ndvi < ndvi_soil), EMISSIVITY_SOIL, emissivity)
    emissivity = np.where(ndvi > ndvi_veg, EMISSIVITY_VEG, emissivity)

    return np.clip(emissivity, 0.90, 0.999)


def compute_lst_from_tirs(
    brightness_temp_k: np.ndarray,
    emissivity: np.ndarray,
    lambda_um: float = LAMBDA_TIRS_B10_UM,
    rho: float = RHO_UM_K,
) -> np.ndarray:
    """
    Retrieves physical Land Surface Temperature (LST) in degrees Celsius from Landsat TIRS Band 10
    Brightness Temperature using the single-channel Artis & Carnahan radiative transfer formulation:

        LST_C = (T_B / (1 + (lambda * T_B / rho) * ln(epsilon))) - 273.15

    Args:
        brightness_temp_k: At-sensor brightness temperature in Kelvin (270K - 340K)
        emissivity: Land surface emissivity [0.90, 1.0]
        lambda_um: Band 10 effective wavelength (10.895 um)
        rho: hc/sigma_B physical constant (14380 um*K)

    Returns:
        lst_celsius: Land Surface Temperature in degrees Celsius (°C)
    """
    # Guard against non-positive emissivity or brightness temp
    safe_eps = np.clip(emissivity, 0.85, 1.0)
    safe_tb = np.clip(brightness_temp_k, 200.0, 360.0)

    denominator = 1.0 + ((lambda_um * safe_tb) / rho) * np.log(safe_eps)
    lst_kelvin = safe_tb / denominator
    lst_celsius = lst_kelvin - KELVIN_OFFSET

    return lst_celsius.astype(np.float32)


def compute_uhi_anomaly(
    lst_celsius: np.ndarray,
    rural_baseline_celsius: Optional[float] = None,
    percentile_baseline: float = 15.0,
    urban_mask: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, float]:
    """
    Calculates the Urban Heat Island (UHI) temperature anomaly:

        Delta_T_UHI = LST_urban - LST_rural_baseline

    If rural_baseline_celsius is not provided, it is dynamically computed from
    the lower percentile of non-urban surrounding pixels or the entire scene.

    Returns:
        (uhi_anomaly_2d, baseline_value)
    """
    valid_lst = lst_celsius[np.isfinite(lst_celsius)]
    if len(valid_lst) == 0:
        return np.zeros_like(lst_celsius), 0.0

    if rural_baseline_celsius is None:
        if urban_mask is not None and np.any(~urban_mask & np.isfinite(lst_celsius)):
            # Rural area baseline from non-urban mask
            baseline = float(np.percentile(lst_celsius[~urban_mask & np.isfinite(lst_celsius)], percentile_baseline))
        else:
            baseline = float(np.percentile(valid_lst, percentile_baseline))
    else:
        baseline = float(rural_baseline_celsius)

    uhi_anomaly = lst_celsius - baseline
    return uhi_anomaly.astype(np.float32), baseline


class ThermalEngine:
    """High-level engine for processing thermal imagery, calculating LST and UHI analytics."""

    def __init__(self, lambda_um: float = LAMBDA_TIRS_B10_UM):
        self.lambda_um = lambda_um

    def process_scene(
        self,
        brightness_temp_k: np.ndarray,
        red_band: np.ndarray,
        nir_band: np.ndarray,
        urban_mask: Optional[np.ndarray] = None,
    ) -> Dict[str, Union[np.ndarray, float]]:
        """
        Executes end-to-end thermal pipeline:
        1. Computes NDVI
        2. Computes Fractional Vegetation Cover (Pv)
        3. Derives Surface Emissivity
        4. Calculates Physical LST in °C
        5. Computes UHI Anomaly and Hotspot Statistics
        """
        # Calculate NDVI
        denom = nir_band + red_band
        ndvi = np.where(denom != 0, (nir_band - red_band) / (denom + 1e-7), 0.0)
        ndvi = np.clip(ndvi, -1.0, 1.0)

        # Vegetation Cover & Emissivity
        pv = compute_fractional_vegetation(ndvi)
        emissivity = compute_surface_emissivity(ndvi, pv)

        # LST Retrieval
        lst_celsius = compute_lst_from_tirs(brightness_temp_k, emissivity, lambda_um=self.lambda_um)

        # UHI Anomaly
        uhi_anomaly, baseline = compute_uhi_anomaly(lst_celsius, urban_mask=urban_mask)

        # Summary Metrics
        valid_lst = lst_celsius[np.isfinite(lst_celsius)]
        peak_lst = float(np.max(valid_lst)) if len(valid_lst) > 0 else 0.0
        mean_lst = float(np.mean(valid_lst)) if len(valid_lst) > 0 else 0.0
        p95_lst = float(np.percentile(valid_lst, 95)) if len(valid_lst) > 0 else 0.0

        # Hotspot fraction: percentage of pixels with UHI anomaly > 3.0°C
        hotspot_pct = float(np.mean(uhi_anomaly > 3.0) * 100.0)

        return {
            "ndvi": ndvi,
            "fractional_vegetation": pv,
            "emissivity": emissivity,
            "lst_celsius": lst_celsius,
            "uhi_anomaly": uhi_anomaly,
            "rural_baseline_celsius": baseline,
            "peak_lst_celsius": peak_lst,
            "mean_lst_celsius": mean_lst,
            "p95_lst_celsius": p95_lst,
            "hotspot_percentage": hotspot_pct,
        }
