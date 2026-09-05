"""Characterization engine: estimate oil spill volume and type from SAR detections.

Inputs:
  - A detected oil-slick polygon / dark-spot detection bbox (from the Detection stage)
  - Physical assumptions (film thickness ranges for different oil types)

Outputs:
  - Estimated slick area (km2)
  - Estimated oil volume (cubic meters / barrels / tonnes)
  - Most-likely oil type based on film-thickness signature

Reference film-thickness ranges (classic remote-sensing oil-slick values):
  Sheen         : 0.04 - 0.3  um   (silvery/grey, rainbow)
  Metallic      : 0.3  - 5.0  um   (visible metallic sheen)
  True oil color: 0.3  - 5.0  um   (dark/brown — thick emulsion)
  Continuous    : 1    - 10   um
  Emulsion      : 100  - 3000 um   (chocolate mousse)

The CFAR dark-spot detector cannot directly measure thickness from a single
intensity image, so we use the NOAA/Bonn Agreement rule-of-thumb:
  Default assumed mean film thickness = 1 um (micrometre) for a detected
  dark slick with no additional data. This is the standard approximation that
  NOAA uses for "true oil color" thickness on the water surface.
"""

import numpy as np
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Assumed mean oil film thickness per detection in micrometres (um).
# Default 1.0 um per NOAA "true oil color" rule of thumb.
DEFAULT_THICKNESS_UM = 1.0

# Common oil bulk densities in kg/m3
DENSITY_KG_M3 = {
    "crude_light": 850.0,
    "crude_heavy": 930.0,
    "fuel_oil": 950.0,
    "diesel": 850.0,
    "bunker": 980.0,
    "gasoline": 750.0,
}

BARRELS_PER_M3 = 6.28981


@dataclass
class CharacterizationResult:
    slick_count: int
    total_area_km2: float
    est_volume_m3: float
    est_volume_barrels: float
    est_volume_tonnes: float
    likely_oil_type: str
    per_slick: List[Dict] = field(default_factory=list)


def compute_pixel_area_m2(bbox_px, spatial_resolution_m: float = 40.0) -> float:
    """Approximate ground area (m2) of a pixel bbox.

    Sentinel-1 GRD IW mode ~10m resolution; a 512x512 patch at native
    resolution covers ~5x5 km. spatial_resolution_m defaults to 40 m to
    account for the multi-look / subsetting typical of our approach.
    """
    if len(bbox_px) < 4:
        return 0.0
    w = max(bbox_px[2] - bbox_px[0], 1)
    h = max(bbox_px[3] - bbox_px[1], 1)
    return w * h * (spatial_resolution_m ** 2)


def characterize_detections(
    detections: List[Dict],
    thickness_um: float = DEFAULT_THICKNESS_UM,
    oil_density: float = DENSITY_KG_M3["crude_heavy"],
    spatial_resolution_m: float = 40.0,
    likely_oil_type: str = "crude_oil",
) -> CharacterizationResult:
    """Convert SAR dark-spot detections into area/volume/type estimates.

    Args:
        detections: List of detection dicts, each with 'bbox_px' and optionally
            'area_px' and 'centroid_geo'.
        thickness_um: Assumed mean film thickness in micrometres.
        oil_density: Oil bulk density in kg/m3 for mass estimation.
        spatial_resolution_m: Ground resolution per pixel (m).
        likely_oil_type: Description of inferred oil type.

    Returns:
        CharacterizationResult with totals and per-slick estimates.
    """
    thickness_m = thickness_um * 1e-6
    per_slick = []
    total_area_m2 = 0.0
    total_volume_m3 = 0.0

    for det in detections:
        area_m2 = compute_pixel_area_m2(det.get("bbox_px", []), spatial_resolution_m)
        vol_m3 = area_m2 * thickness_m
        total_area_m2 += area_m2
        total_volume_m3 += vol_m3

        per_slick.append({
            "bbox_px": det.get("bbox_px"),
            "bbox_geo": det.get("bbox_geo"),
            "centroid_geo": det.get("centroid_geo"),
            "area_px": det.get("area_px"),
            "area_km2": round(area_m2 / 1e6, 6),
            "est_volume_m3": round(vol_m3, 3),
            "est_volume_barrels": round(vol_m3 * BARRELS_PER_M3, 2),
        })

    vol_m3 = total_volume_m3
    result = CharacterizationResult(
        slick_count=len(detections),
        total_area_km2=round(total_area_m2 / 1e6, 6),
        est_volume_m3=round(vol_m3, 3),
        est_volume_barrels=round(vol_m3 * BARRELS_PER_M3, 2),
        est_volume_tonnes=round(vol_m3 * oil_density, 3),
        likely_oil_type=likely_oil_type,
        per_slick=per_slick,
    )

    # Sanity heuristic — flag implausibly huge volumes (likely look-alike)
    if vol_m3 > 50000:
        result.likely_oil_type = (
            f"{likely_oil_type} (FLAG: implausibly large volume "
            f"{vol_m3:.0f} m3 — likely a look-alike dark patch)"
        )
    return result


if __name__ == "__main__":
    demo = [
        {"bbox_px": [10, 20, 110, 90], "area_px": 90 * 70, "centroid_geo": [72.80, 18.90]},
        {"bbox_px": [200, 150, 300, 260], "area_px": 100 * 110, "centroid_geo": [72.82, 18.92]},
    ]
    res = characterize_detections(demo)
    print(f"Slicks: {res.slick_count}")
    print(f"Total area: {res.total_area_km2} km2")
    print(f"Volume: {res.est_volume_m3} m3 / {res.est_volume_barrels} barrels / {res.est_volume_tonnes} t")
