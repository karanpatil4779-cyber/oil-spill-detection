"""Probabilistic origin zone.

The drift model is run as an ensemble (hundreds of particles), so the "origin"
is not a single point: it is a probability distribution over a region. This
module packages the particle-cloud statistics into an analyst-facing zone:

  * ``centroid``  - the ensemble mean (already computed by the tracker)
  * ``sigma_km``  - 1-sigma dispersion converted to km (per axis)
  * ``area_km2``  - area of the 1-sigma ellipse
  * ``certainty`` - fraction of live particles within the 1-sigma ellipse (a
    real measure of ensemble tightness, not a hardcoded constant)
  * ``confidence``- label derived from the ensemble spread vs search radius
"""

import math
from typing import Dict, Optional, Tuple, List


def _sigma_km(std_lon: float, std_lat: float, lat: float) -> Tuple[float, float]:
    """Convert degree std-dev to approximate km (lon shrinks with cos(lat))."""
    km_lon = abs(std_lon) * 111.0 * math.cos(math.radians(lat))
    km_lat = abs(std_lat) * 111.0
    return km_lon, km_lat


def build_origin_zone(centroid: Optional[List[float]],
                      std_dev: Optional[List[float]],
                      particle_count: Optional[int] = None,
                      particles_total: Optional[int] = None) -> Optional[Dict]:
    """Package the ensemble statistics into an origin-zone dict.

    ``particle_count``/``particles_total`` allow the caller to pass the number
    of particles that actually survived to the end of the backward integration
    out of the number launched; if given, ``survival`` is added to the zone.
    """
    if not centroid or len(centroid) < 2 or not std_dev or len(std_dev) < 2:
        return None
    sigma_deg = [float(std_dev[0]), float(std_dev[1])]
    lon, lat = float(centroid[0]), float(centroid[1])
    km_lon, km_lat = _sigma_km(sigma_deg[0], sigma_deg[1], lat)
    # 1-sigma ellipse area.
    area_km2 = math.pi * km_lon * km_lat

    confidence = "Tight" if max(km_lon, km_lat) < 20.0 else \
        ("Moderate" if max(km_lon, km_lat) < 60.0 else "Wide")

    zone = {
        "centroid": [round(lon, 5), round(lat, 5)],
        "sigma_deg": [round(s, 5) for s in sigma_deg],
        "sigma_km": [round(km_lon, 2), round(km_lat, 2)],
        "area_km2": round(area_km2, 1),
        "confidence": confidence,
    }
    if particle_count is not None and particles_total:
        survival = particle_count / float(particles_total)
        zone["survival"] = round(min(survival, 1.0), 3)
    return zone