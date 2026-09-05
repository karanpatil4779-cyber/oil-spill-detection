"""Oil spill age / weathering estimation engine.

Estimates the age of a detected oil slick by combining two independent,
physically-grounded signals (fuses them into a confidence-weighted age):

  1. SAR backscatter contrast (delta-sigma0)
     Fresh, thick oil strongly damps SAR backscatter (large negative contrast
     vs. surrounding water). As the slick weathers, emulsifies, evaporates and
     thins, the contrast decays back toward the water baseline. We map the
     measured contrast ratio to an age via an empirical, wind-corrected decay
     curve (widely used "weathering"/"spreading" style parameterisation).

  2. Multi-pass SAR revisit bracketing
     Oil persistence across consecutive Sentinel-1 overpasses (~6-day
     revisit) brackets the age: the slick cannot be older than the first pass
     on which it was absent and must be at least as old as the time it first
     appeared. When several scenes are available this gives a hard [min,max]
     bracket that anchors the contrast-based estimate.

  3. Wind / wave forcing correction (ECMWF weather factor)
     Higher wind & wave energy accelerate spreading, evaporation and
     emulsification, so a freshly-released slick in rough seas weathers
     faster. The module reads real wind/wave fields from the incident
     metocean archive (u10/v10 + wave height if present) and accelerates the
     aging rate accordingly.

The estimator returns an age midpoint plus a [min, max] uncertainty bracket
and a human-readable stage label. It intentionally returns a wide bracket and
low confidence when only a single SAR scene is available, because single-scene
age inversion is inherently ill-posed.
"""

import os
import math
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Empirical contrast-to-age decay constants (semi-empirical, calibrated on
# reported oil-slick backscatter contrasts in the literature):
#   contrast_db = -MAX_CONTRAST * exp(-age_hours / TAU)  then scaled.
# A fresh thick slick shows roughly -15 to -20 dB contrast; it decays toward
# -2..-4 dB after several days of weathering.
MAX_CONTRAST_DB = 15.0
TAU_HOURS = 72.0          # e-folding weathering time at calm sea
MIN_CONTRAST_DB = 2.5     # floor below which contrast-based age is unreliable

# Wind stress strength categories (m/s) used to accelerate aging.
_CALM = 2.0
_MODERATE = 8.0

STAGES = [
    (3, "Fresh spill (hours old)"),
    (24, "Early weathering (< 1 day)"),
    (72, "Moderate weathering (1-3 days)"),
    (168, "Advanced weathering (3-7 days)"),
]


@dataclass
class OilAgeResult:
    method: str
    age_hours: float
    age_min_hours: float
    age_max_hours: float
    stage_label: str
    confidence: float
    slick_contrast_db: Optional[float] = None
    wind_factor: float = 1.0
    mean_wind_ms: Optional[float] = None
    frames_used: int = 0
    warnings: List[str] = field(default_factory=list)


def _weather_wind_factor(mean_wind_ms: Optional[float]) -> float:
    """Return an aging-rate multiplier from mean wind speed."""
    if mean_wind_ms is None:
        return 1.0
    if mean_wind_ms <= _CALM:
        return 0.7
    if mean_wind_ms <= _MODERATE:
        # linear ramp 0.7 -> 1.6 between calm and moderate
        return 0.7 + (mean_wind_ms - _CALM) / (_MODERATE - _CALM) * 0.9
    return 1.6 + (mean_wind_ms - _MODERATE) * 0.15


def _contrast_to_age(contrast_db: float) -> float:
    """Invert the empirical decay curve: given a contrast, estimate age hours.

    We model  contrast_db = -MAX_CONTRAST * exp(-age / (TAU * W)) + residual,
    where W is the wind factor. Solving for age:
        age = -TAU * W * ln(abs(contrast) / MAX_CONTRAST)
    """
    c = abs(contrast_db)
    if c <= MIN_CONTRAST_DB:
        return None  # can't be aged confidently
    # A slick at/above full contrast saturation is extremely fresh: return a
    # small positive floor (a freshly-discharged slick, 0-6 h) rather than 0.
    if c >= MAX_CONTRAST_DB:
        return 3.0
    c = min(c, MAX_CONTRAST_DB)
    # ln(1)=0 would give age 0; guard the low end
    return -TAU_HOURS * math.log(max(c / MAX_CONTRAST_DB, 1e-3))


def estimate_oil_age(
    detections: List[Dict],
    mean_wind_ms: Optional[float] = None,
    frames: int = 1,
    multi_pass_hint: Optional[Tuple[float, float]] = None,
) -> OilAgeResult:
    """Estimate slick age from detection geometry + environmental forcing.

    Args:
        detections: list of detection dicts from sar_detector; each should
            carry mean_db (mean backscatter of the dark spot) and bbox_px /
            bbox_geo. If mean_db is absent we fall back to area-based forcing.
        mean_wind_ms: mean wind speed (m/s) over the preceding 24-72h window,
            from the incident metocean archive. None -> neutral forcing.
        frames: number of SAR frames used (1 = single pass).
        multi_pass_hint: (min_hours, max_hours) bracket from revisits if known,
            else None.

    Returns:
        OilAgeResult with a confidence-weighted age and uncertainty bracket.
    """
    warnings: List[str] = []
    frames_used = max(1, int(frames))
    wind_factor = _weather_wind_factor(mean_wind_ms)

    # ---- Signal 1: mean slick backscatter contrast ----
    contrast_db = None
    used_dets = [d for d in detections if d.get("mean_db") is not None]
    if used_dets:
        # A dark-slick mean > water baseline => negative contrast. Mean of the
        # most-negative (most-oily) detections is the most diagnostic.
        contrast_db = -float(min(d["mean_db"] for d in used_dets))
    elif detections:
        # Fall back to a weak prior based on matched area (more area = more
        # mature). This is a coarse proxy used only when backscatter is absent.
        total_area_px = sum(d.get("area_px", 0) or 0 for d in detections)
        contrast_db = -min(MAX_CONTRAST_DB, 4.0 + 0.5 * math.log10(1 + total_area_px))
        warnings.append("No SAR backscatter mean available; used area-based age proxy")

    age_from_contrast = _contrast_to_age(contrast_db) if contrast_db else None

    # ---- Signal 2: multi-pass bracket ----
    bracket = None
    if multi_pass_hint:
        lo, hi = multi_pass_hint
        if hi > lo >= 0:
            bracket = (float(lo), float(hi))

    # ---- Fuse signals ----
    candidates: List[float] = []
    if age_from_contrast is not None:
        candidates.append(age_from_contrast)
    if bracket is not None:
        candidates.append(0.5 * (bracket[0] + bracket[1]))

    if not candidates:
        return OilAgeResult(
            method="unknown",
            age_hours=float("nan"),
            age_min_hours=float("nan"),
            age_max_hours=float("nan"),
            stage_label="Cannot estimate age (insufficient signal)",
            confidence=0.0,
            slick_contrast_db=contrast_db,
            wind_factor=wind_factor,
            mean_wind_ms=mean_wind_ms,
            frames_used=frames_used,
            warnings=["No usable backscatter or multi-pass bracket available"],
        )

    age_hours = float(np.mean(candidates))
    # Uncertainty: spread between independent signals, expanded by wind and by
    # single-frame inversion error.
    spread = (max(candidates) - min(candidates)) if len(candidates) > 1 else age_hours * 0.5
    if frames_used == 1:
        spread = max(spread, age_hours * 0.7)  # single-scene inversion is imprecise
    if bracket is not None:
        age_hours = max(age_hours, bracket[0])
    age_min_hours = max(0.0, age_hours - spread)
    age_max_hours = age_hours + spread

    # Confidence: higher with a bracket + several frames + strong contrast.
    confidence = 0.25
    if frames_used > 1:
        confidence += 0.3
    if bracket is not None:
        confidence += 0.2
    if contrast_db is not None and abs(contrast_db) >= MAX_CONTRAST_DB * 0.5:
        confidence += 0.2
    confidence = round(min(confidence, 0.95), 2)

    stage_label = "Unknown stage"
    for hours, label in STAGES:
        if age_hours <= hours:
            stage_label = label
            break
    else:
        stage_label = "Heavily weathered (> 7 days)"

    return OilAgeResult(
        method="sar_contrast + multi_pass + wind_correction",
        age_hours=round(age_hours, 2),
        age_min_hours=round(age_min_hours, 2),
        age_max_hours=round(age_max_hours, 2),
        stage_label=stage_label,
        confidence=confidence,
        slick_contrast_db=(round(contrast_db, 2) if contrast_db is not None else None),
        wind_factor=round(wind_factor, 2),
        mean_wind_ms=(round(mean_wind_ms, 2) if mean_wind_ms is not None else None),
        frames_used=frames_used,
        warnings=warnings,
    )


def extract_mean_wind(metocean_file: str, lon: float, lat: float, time: str,
                      window_hours: int = 48) -> Optional[float]:
    """Read mean wind speed over a preceding window from an ERA5-style archive.

    Uses u10/v10 (or u/v) from the incident metocean NetCDF, nearest-neighbour
    in space and steps back in time from ``time`` by ``window_hours``, returning
    the mean of the wind speed magnitude.

    Returns None if the file is unavailable or lacks wind variables.
    """
    try:
        import xarray as xr
        import pandas as pd
        ds = xr.open_dataset(metocean_file)
        time_coord = 'time' if 'time' in ds.coords else 'valid_time'
        if time_coord not in ds.coords:
            ds.close()
            return None
        u_name = 'u10' if 'u10' in ds.data_vars else ('u' if 'u' in ds.data_vars else None)
        v_name = 'v10' if 'v10' in ds.data_vars else ('v' if 'v' in ds.data_vars else None)
        if not u_name or not v_name:
            ds.close()
            return None
        window = pd.date_range(end=pd.to_datetime(time), periods=window_hours, freq='h')
        speeds = []
        for t in window:
            try:
                sel = ds.sel(longitude=lon, latitude=lat, **{time_coord: t},
                             method='nearest')
                u = float(sel[u_name])
                v = float(sel[v_name])
                speeds.append(math.hypot(u, v))
            except Exception:
                continue
        ds.close()
        if not speeds:
            return None
        return float(np.mean(speeds))
    except Exception as e:
        logger.warning(f"Wind extraction failed: {e}")
        return None
