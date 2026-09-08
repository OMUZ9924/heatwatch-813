"""
Heat Vulnerability Index (HVI) Model & Urban Policy Recommendation Engine.

Implements:
    HVI = Hazard * Exposure * Sensitivity * (1 - Adaptation)

Where:
- Hazard: Normalized Land Surface Temperature (LST) + UHI anomaly
- Exposure: Built-up density (Sentinel-1 SAR imperviousness) weighted by population density
- Sensitivity: Low surface albedo (Satellite 813 / Tanager hyperspectral) -> heat-retaining materials
- Adaptation: Vegetative cooling buffer (NDVI) & urban tree canopy

Includes 5-tier classification and quantitative urban resilience policy recommendations.
"""

from dataclasses import dataclass
import logging
from typing import Dict, List, Optional, Tuple, Union
import numpy as np

logger = logging.getLogger("heatwatch813.hvi_model")

# 5-Tier HVI Classification Thresholds
HVI_TIERS = {
    1: {"name": "Low", "range": (0.0, 0.2), "color": "#2ca02c"},       # Green
    2: {"name": "Moderate", "range": (0.2, 0.4), "color": "#bcbd22"},  # Yellow-Green
    3: {"name": "High", "range": (0.4, 0.6), "color": "#ff7f0e"},      # Orange
    4: {"name": "Severe", "range": (0.6, 0.8), "color": "#d62728"},    # Red
    5: {"name": "Critical Risk", "range": (0.8, 1.0), "color": "#7b1fa2"}, # Deep Purple
}


@dataclass
class HVIComponents:
    """Normalized components [0, 1] feeding the HVI formulation."""
    hazard: np.ndarray
    exposure: np.ndarray
    sensitivity: np.ndarray
    adaptation: np.ndarray


@dataclass
class HVIResult:
    """Comprehensive container for HVI modeling outputs."""
    hvi: np.ndarray
    components: HVIComponents
    tier_map: np.ndarray
    tier_statistics: Dict[str, Dict[str, float]]
    interventions: Dict[str, np.ndarray]
    metrics: Dict[str, float]


def normalize_layer(arr: np.ndarray, p_min: float = 2.0, p_max: float = 98.0) -> np.ndarray:
    """Normalizes an array to [0, 1] using percentile robust clipping."""
    valid = arr[np.isfinite(arr)]
    if len(valid) == 0:
        return np.zeros_like(arr, dtype=np.float32)

    v_min = float(np.percentile(valid, p_min))
    v_max = float(np.percentile(valid, p_max))

    if v_max <= v_min:
        return np.zeros_like(arr, dtype=np.float32)

    clipped = np.clip(arr, v_min, v_max)
    norm = (clipped - v_min) / (v_max - v_min)
    return norm.astype(np.float32)


def compute_hazard(
    lst_celsius: np.ndarray,
    uhi_anomaly: np.ndarray,
    lst_weight: float = 0.6,
    uhi_weight: float = 0.4,
) -> np.ndarray:
    """
    Computes Hazard score [0, 1] from physical thermal metrics:
        Hazard = lst_weight * norm(LST) + uhi_weight * norm(Delta_T_UHI)
    """
    norm_lst = normalize_layer(lst_celsius)
    norm_uhi = normalize_layer(uhi_anomaly)
    hazard = lst_weight * norm_lst + uhi_weight * norm_uhi
    return np.clip(hazard, 0.0, 1.0).astype(np.float32)


def compute_exposure(
    sar_imperviousness: np.ndarray,
    population_density: Optional[np.ndarray] = None,
    sar_weight: float = 0.5,
    pop_weight: float = 0.5,
) -> np.ndarray:
    """
    Computes Exposure score [0, 1] from built-up structures and population grid:
        Exposure = sar_weight * ISF + pop_weight * norm(Pop)
    """
    norm_sar = np.clip(sar_imperviousness, 0.0, 1.0)

    if population_density is None:
        # If population grid is absent, proxy exposure primarily through built-up morphology
        return norm_sar.astype(np.float32)

    norm_pop = normalize_layer(population_density)
    exposure = sar_weight * norm_sar + pop_weight * norm_pop
    return np.clip(exposure, 0.0, 1.0).astype(np.float32)


def compute_sensitivity(
    surface_albedo: np.ndarray,
    cool_roof_index: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Computes Sensitivity score [0, 1] based on hyperspectral material properties.
    Low-albedo, dark asphalt/roofs trap solar heat (High Sensitivity = 1 - Albedo).
    High-albedo cool roofs reflect solar irradiance (Low Sensitivity).
    """
    norm_albedo = normalize_layer(surface_albedo)
    sensitivity = 1.0 - norm_albedo

    if cool_roof_index is not None:
        # High CRI actively reduces thermal sensitivity
        norm_cri = normalize_layer(cool_roof_index)
        sensitivity = sensitivity * (1.0 - 0.3 * norm_cri)

    return np.clip(sensitivity, 0.0, 1.0).astype(np.float32)


def compute_adaptation(
    ndvi: np.ndarray,
    water_distance_proximity: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Computes Adaptation capacity [0, 1] from vegetative cooling and water buffering:
        Adaptation = clip(NDVI, 0, 1) (+ water buffer bonus if present)
    """
    # Healthy green vegetation (NDVI > 0) transpires and cools ambient air
    veg_adaptation = np.clip(ndvi, 0.0, 1.0)

    if water_distance_proximity is not None:
        water_bonus = normalize_layer(water_distance_proximity)
        adaptation = 0.7 * veg_adaptation + 0.3 * water_bonus
    else:
        adaptation = veg_adaptation

    return np.clip(adaptation, 0.0, 1.0).astype(np.float32)


def compute_hvi(
    hazard: np.ndarray,
    exposure: np.ndarray,
    sensitivity: np.ndarray,
    adaptation: np.ndarray,
) -> np.ndarray:
    """
    Core Heat Vulnerability Index formulation:
        HVI = Hazard * Exposure * Sensitivity * (1.0 - Adaptation)

    All inputs must be bounded in [0, 1]. Output is guaranteed bounded in [0, 1].
    """
    h = np.clip(hazard, 0.0, 1.0)
    e = np.clip(exposure, 0.0, 1.0)
    s = np.clip(sensitivity, 0.0, 1.0)
    a = np.clip(adaptation, 0.0, 1.0)

    # Multiplicative interaction
    hvi_raw = h * e * s * (1.0 - a)

    # Scale to full dynamic range using square root or normalization for clearer risk discrimination
    hvi = np.sqrt(np.clip(hvi_raw, 0.0, 1.0))
    return np.clip(hvi, 0.0, 1.0).astype(np.float32)


def classify_hvi_tiers(hvi: np.ndarray) -> Tuple[np.ndarray, Dict[str, Dict[str, float]]]:
    """
    Classifies continuous HVI into 5 discrete policy risk tiers:
    1: Low, 2: Moderate, 3: High, 4: Severe, 5: Critical Risk
    """
    tier_map = np.zeros_like(hvi, dtype=np.uint8)
    tier_stats = {}
    total_pixels = float(np.size(hvi))

    for tier_id, info in HVI_TIERS.items():
        low_val, high_val = info["range"]
        if tier_id == 5:
            mask = (hvi >= low_val) & (hvi <= high_val)
        else:
            mask = (hvi >= low_val) & (hvi < high_val)

        tier_map[mask] = tier_id
        pixel_count = int(np.sum(mask))
        pct = (pixel_count / total_pixels) * 100.0 if total_pixels > 0 else 0.0

        tier_stats[info["name"]] = {
            "tier_id": tier_id,
            "pixel_count": pixel_count,
            "percentage": round(pct, 2),
            "color": info["color"],
        }

    return tier_map, tier_stats


def generate_policy_interventions(
    hvi: np.ndarray,
    hazard: np.ndarray,
    exposure: np.ndarray,
    sensitivity: np.ndarray,
    adaptation: np.ndarray,
    pixel_area_km2: float = 0.0009,  # 30m x 30m = 900 m^2 = 0.0009 km^2
) -> Dict[str, np.ndarray]:
    """
    Produces actionable spatial urban planning recommendations:
    1. Cool Roof Retrofit Zones: High sensitivity (low albedo) + high hazard in built-up areas
    2. Urban Green Corridors: High hazard + low adaptation (vegetation deficit)
    3. Priority Shading & Heat Shelters: Severe/Critical risk (HVI >= 0.6) + high pedestrian exposure
    """
    # 1. Cool Roof Retrofit: Built-up, high hazard, high sensitivity
    cool_roof_mask = (exposure >= 0.4) & (hazard >= 0.5) & (sensitivity >= 0.5)

    # 2. Green Corridors: High hazard with low vegetative adaptation
    green_corridor_mask = (hazard >= 0.5) & (adaptation < 0.2) & (exposure >= 0.3)

    # 3. Priority Shading Structures: Severe or critical vulnerability with human exposure
    shading_mask = (hvi >= 0.6) & (exposure >= 0.6)

    return {
        "cool_roof_retrofit_zones": cool_roof_mask,
        "green_corridors_afforestation": green_corridor_mask,
        "priority_pedestrian_shading": shading_mask,
    }


class HeatVulnerabilityIndexModel:
    """Comprehensive pipeline class for executing the HeatWatch-813 HVI model."""

    def __init__(self, pixel_size_m: float = 30.0):
        self.pixel_size_m = pixel_size_m
        self.pixel_area_km2 = (pixel_size_m * pixel_size_m) / 1e6

    def evaluate(
        self,
        lst_celsius: np.ndarray,
        uhi_anomaly: np.ndarray,
        sar_imperviousness: np.ndarray,
        surface_albedo: np.ndarray,
        ndvi: np.ndarray,
        population_density: Optional[np.ndarray] = None,
        cool_roof_index: Optional[np.ndarray] = None,
    ) -> HVIResult:
        """
        Executes end-to-end HVI calculation, tier categorization, and policy generation.
        """
        # 1. Component calculations
        hazard = compute_hazard(lst_celsius, uhi_anomaly)
        exposure = compute_exposure(sar_imperviousness, population_density)
        sensitivity = compute_sensitivity(surface_albedo, cool_roof_index)
        adaptation = compute_adaptation(ndvi)

        components = HVIComponents(
            hazard=hazard,
            exposure=exposure,
            sensitivity=sensitivity,
            adaptation=adaptation,
        )

        # 2. HVI composite index
        hvi = compute_hvi(hazard, exposure, sensitivity, adaptation)

        # 3. 5-Tier categorization
        tier_map, tier_stats = classify_hvi_tiers(hvi)

        # 4. Urban Policy Interventions
        interventions = generate_policy_interventions(
            hvi, hazard, exposure, sensitivity, adaptation, self.pixel_area_km2
        )

        # 5. Key Performance Metrics
        critical_pixels = tier_stats.get("Critical Risk", {}).get("pixel_count", 0)
        severe_pixels = tier_stats.get("Severe", {}).get("pixel_count", 0)
        total_high_risk_area_km2 = (critical_pixels + severe_pixels) * self.pixel_area_km2

        metrics = {
            "mean_hvi": float(np.mean(hvi)),
            "max_hvi": float(np.max(hvi)),
            "p90_hvi": float(np.percentile(hvi, 90)),
            "critical_risk_area_km2": float(critical_pixels * self.pixel_area_km2),
            "total_high_risk_area_km2": float(total_high_risk_area_km2),
            "cool_roof_retrofit_area_km2": float(np.sum(interventions["cool_roof_retrofit_zones"]) * self.pixel_area_km2),
            "green_corridor_area_km2": float(np.sum(interventions["green_corridors_afforestation"]) * self.pixel_area_km2),
            "shading_priority_area_km2": float(np.sum(interventions["priority_pedestrian_shading"]) * self.pixel_area_km2),
        }

        return HVIResult(
            hvi=hvi,
            components=components,
            tier_map=tier_map,
            tier_statistics=tier_stats,
            interventions=interventions,
            metrics=metrics,
        )
