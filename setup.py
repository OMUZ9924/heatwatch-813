from setuptools import setup, find_packages

setup(
    name="heatwatch813",
    version="1.0.0",
    description="Autonomous Multi-Sensor GeoAI Engine for Urban Expansion & Extreme Heat Vulnerability Intelligence",
    author="Team T0033 (Arab Youth Space Hackathon: 813 Challenge)",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=[
        "numpy",
        "scipy",
        "pandas",
        "geopandas",
        "shapely",
        "rasterio",
        "xarray",
        "rioxarray",
        "h5py",
        "pystac-client",
        "planetary-computer",
        "leafmap",
        "streamlit",
        "matplotlib",
    ],
)
