"""
Visualizer Module for HeatWatch-813.

Provides:
- Leafmap / Folium interactive split-screen dual-maps
- Publication-grade spectral reflectance plots for 426-band Tanager endmembers
- HVI component breakdowns and risk distribution plots
- Cloud-optimized GeoTIFF export utility
"""

import os
import logging
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import matplotlib.pyplot as plt

logger = logging.getLogger("heatwatch813.visualizer")


def create_split_map(
    left_layer_name: str,
    right_layer_name: str,
    center: Tuple[float, float] = (25.275, 55.375),
    zoom: int = 11,
    left_tile_url: Optional[str] = None,
    right_tile_url: Optional[str] = None,
):
    """
    Creates an interactive split-screen map slider using leafmap.folium.
    Enables side-by-side comparative inspection between:
    - Left: True Color / High-resolution optical baseline
    - Right: Land Surface Temperature (LST) or Heat Vulnerability Index (HVI)
    """
    try:
        import leafmap.foliumap as leafmap

        m = leafmap.Map(center=list(center), zoom=zoom)

        # Standard basemap comparison
        left_layer = left_tile_url if left_tile_url else "HYBRID"
        right_layer = right_tile_url if right_tile_url else "OpenStreetMap"

        m.split_map(
            left_layer=left_layer,
            right_layer=right_layer,
            left_label=left_layer_name,
            right_label=right_layer_name,
        )
        return m
    except Exception as e:
        logger.warning("Could not instantiate leafmap split-map (%s). Falling back to folium.", e)
        try:
            import folium
            m = folium.Map(location=list(center), zoom_start=zoom)
            folium.TileLayer("Esri.WorldImagery", name=left_layer_name).add_to(m)
            folium.TileLayer("OpenStreetMap", name=right_layer_name).add_to(m)
            folium.LayerControl().add_to(m)
            return m
        except Exception as ex:
            logger.error("Folium map creation failed (%s)", ex)
            return None


def plot_spectral_endmembers(
    wavelengths_nm: np.ndarray,
    endmembers: Dict[str, np.ndarray],
    water_vapor_windows: Optional[List[Tuple[float, float]]] = None,
    title: str = "Satellite 813 / Tanager 426-Band Hyperspectral Endmembers",
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Generates a publication-quality spectral reflectance curve plot (380 - 2500 nm).
    Highlights atmospheric water vapor absorption bands (1350-1450 nm & 1800-1950 nm)
    and SWIR noise edge (> 2450 nm).
    """
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)

    # Color palette matching remote sensing conventions
    palette = {
        "Cool Roof Coating": "#2ca02c",      # Emerald Green
        "Aged Asphalt": "#333333",           # Charcoal
        "Desert Quartz Sand": "#d4a373",     # Ochre/Sand
        "Urban Tree Canopy": "#06d6a0",      # Bright Cyan-Green
    }

    # Plot spectral curves
    for name, spectrum in endmembers.items():
        color = palette.get(name, "#1f77b4")
        lw = 2.4 if "Cool" in name or "Asphalt" in name else 1.8
        ax.plot(wavelengths_nm, spectrum, label=name, color=color, linewidth=lw, alpha=0.9)

    # Shade water vapor absorption zones
    if water_vapor_windows is None:
        water_vapor_windows = [(1350.0, 1450.0), (1800.0, 1950.0)]

    for i, (w_min, w_max) in enumerate(water_vapor_windows):
        label = "Atmospheric H₂O Absorption (Masked)" if i == 0 else None
        ax.axvspan(w_min, w_max, color="#e0e0e0", alpha=0.6, hatch="//", label=label)

    # Shade SWIR edge noise
    ax.axvspan(2450.0, 2520.0, color="#ffdddd", alpha=0.5, label="SWIR Sensor Noise Edge (>2450 nm)")

    ax.set_xlim(380.0, 2520.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_xlabel("Wavelength (nm)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Surface Reflectance (0 - 1.0)", fontsize=11, fontweight="bold")
    ax.set_title(title, fontsize=13, fontweight="bold", pad=12)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(loc="upper right", framealpha=0.9, fontsize=9)

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, bbox_inches="tight", dpi=300)

    return fig


def plot_hvi_summary(
    tier_statistics: Dict[str, Dict[str, float]],
    city_name: str = "Sharjah & Dubai (UAE)",
    save_path: Optional[str] = None,
) -> plt.Figure:
    """
    Generates an executive bar chart and pie distribution of HVI risk tiers.
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5), dpi=150)

    tiers = list(tier_statistics.keys())
    percentages = [tier_statistics[t]["percentage"] for t in tiers]
    colors = [tier_statistics[t]["color"] for t in tiers]

    # Bar chart
    bars = ax1.bar(tiers, percentages, color=colors, edgecolor="black", linewidth=0.8, alpha=0.85)
    for bar in bars:
        h = bar.get_height()
        ax1.annotate(
            f"{h:.1f}%",
            xy=(bar.get_x() + bar.get_width() / 2, h),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontweight="bold",
            fontsize=9,
        )
    ax1.set_ylabel("Coverage of Urban Area (%)", fontsize=10, fontweight="bold")
    ax1.set_title(f"HVI Risk Tier Distribution — {city_name}", fontsize=11, fontweight="bold")
    ax1.set_ylim(0, max(percentages) * 1.25 if max(percentages) > 0 else 100)
    ax1.grid(axis="y", linestyle="--", alpha=0.5)

    # Donut / Pie chart
    ax2.pie(
        percentages,
        labels=tiers,
        colors=colors,
        autopct="%1.1f%%",
        startangle=140,
        wedgeprops=dict(width=0.45, edgecolor="w"),
        textprops=dict(fontsize=8, fontweight="bold"),
    )
    ax2.set_title("Vulnerability Share", fontsize=11, fontweight="bold")

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, bbox_inches="tight", dpi=300)

    return fig


def export_geotiff(
    data: np.ndarray,
    output_path: str,
    bbox: Tuple[float, float, float, float],
    epsg: int = 4326,
    nodata: float = -9999.0,
) -> str:
    """
    Exports a 2D numpy raster array into a georeferenced GeoTIFF with CRS metadata.
    """
    import rasterio
    from rasterio.transform import from_bounds

    height, width = data.shape
    min_lon, min_lat, max_lon, max_lat = bbox

    transform = from_bounds(min_lon, min_lat, max_lon, max_lat, width, height)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": rasterio.float32,
        "crs": f"EPSG:{epsg}",
        "transform": transform,
        "nodata": nodata,
        "compress": "lzw",
    }

    clean_data = np.where(np.isfinite(data), data, nodata).astype(np.float32)

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(clean_data, 1)

    logger.info("Successfully exported GeoTIFF to %s", output_path)
    return output_path
