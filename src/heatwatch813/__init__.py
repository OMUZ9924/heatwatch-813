"""
HeatWatch-813: Autonomous Multi-Sensor GeoAI Engine for Urban Expansion & Extreme Heat Vulnerability Intelligence.
Developed by Team T0033 for the Arab Youth Space Hackathon: 813 Challenge (UAE Space Agency & Space42).
"""

__version__ = "1.0.0"
__team__ = "T0033"
__authors__ = [
    "Fadwa Lahmek (Team Leader & Engineering Systems, Algeria)",
    "Alyazia Al Dhaheri (Urban Sustainability & Regional Policy Lead, UAE)",
    "Maamar Arbouz (Chief GeoAI & Space Systems Architect, Algeria)",
]

from .stac_loader import (
    STACClient,
    search_sentinel2,
    search_sentinel1,
    search_landsat,
    query_planet_tanager,
)
from .hyperspectral import (
    HyperspectralProcessor,
    generate_tanager_wavelengths,
    generate_satellite813_wavelengths,
    generate_enmap_wavelengths,
    mask_water_vapor_absorption,
    compute_surface_albedo,
    compute_cool_roof_index,
    compute_ndbi,
    compute_mndwi,
    compute_bui,
    nearest_band_idx,
)
from .thermal_engine import (
    ThermalEngine,
    compute_lst_from_tirs,
    compute_fractional_vegetation,
    compute_surface_emissivity,
    compute_uhi_anomaly,
)
from .sar_urban import (
    SARUrbanExtractor,
    compute_sar_cross_ratio,
    extract_urban_imperviousness,
    filter_desert_sand,
)
from .hvi_model import (
    HeatVulnerabilityIndexModel,
    HVIComponents,
    HVIResult,
    compute_hvi,
    classify_hvi_tiers,
    generate_policy_interventions,
)
from .visualizer import (
    create_split_map,
    plot_spectral_endmembers,
    plot_hvi_summary,
    export_geotiff,
)

__all__ = [
    "__version__",
    "__team__",
    "__authors__",
    "STACClient",
    "search_sentinel2",
    "search_sentinel1",
    "search_landsat",
    "query_planet_tanager",
    "HyperspectralProcessor",
    "generate_tanager_wavelengths",
    "generate_satellite813_wavelengths",
    "generate_enmap_wavelengths",
    "mask_water_vapor_absorption",
    "compute_surface_albedo",
    "compute_cool_roof_index",
    "compute_ndbi",
    "compute_mndwi",
    "compute_bui",
    "nearest_band_idx",
    "ThermalEngine",
    "compute_lst_from_tirs",
    "compute_fractional_vegetation",
    "compute_surface_emissivity",
    "compute_uhi_anomaly",
    "SARUrbanExtractor",
    "compute_sar_cross_ratio",
    "extract_urban_imperviousness",
    "filter_desert_sand",
    "HeatVulnerabilityIndexModel",
    "HVIComponents",
    "HVIResult",
    "compute_hvi",
    "classify_hvi_tiers",
    "generate_policy_interventions",
    "create_split_map",
    "plot_spectral_endmembers",
    "plot_hvi_summary",
    "export_geotiff",
]
