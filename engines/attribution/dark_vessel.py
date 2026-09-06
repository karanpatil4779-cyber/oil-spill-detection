"""Dark-vessel / AIS-gap fusion.

Directly implements the problem-statement's "unattributable" requirement: a
vessel that is present in radar/SAR but silent on AIS cannot be matched to a
transponder track, so conventional AIS-only attribution would report "no
suspect". We treat a SAR-detected dark spot with no coincident AIS presence as
the *top* attribution signal for that location.

This module is pure: it takes suspects and SAR detections and returns the fused
suspect list. Sensor-vessel-edge arbitrage (vessel detected but AIS missing) is
a classic oil-source signal because most operational discharges are done by
vessels deliberately going dark.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# AIS must be silent within this many km of a SAR dark spot for the spot to be
# labelled "dark vessel"; a vessel merely 50 km away is not a co-location.
DARK_VESSEL_RADIUS_KM = 15.0
# Minimum AIS gap (hours) for fusion to trigger on the *presence* side.
MIN_AIS_GAP_HOURS = 4.0

_OUR_KM_PER_DEG_LON_AT = 111.0


def _haversine_km(lon1, lat1, lon2, lat2) -> float:
    """Simple planar km estimate over short baselines (deg*111 ~ km)."""
    return ((lon1 - lon2) ** 2 + (lat1 - lat2) ** 2) ** 0.5 * _OUR_KM_PER_DEG_LON_AT


def ais_gap_hours(suspect: Dict, window_hours: int) -> float:
    """Estimate of how many of the origin-window hours a vessel was silent.

    Uses the difference between the full window and the reported presence. A
    negative / zero result means AIS coverage spanned the window.
    """
    presence = float(suspect.get("presence_hours") or suspect.get("match_count") or 0.0)
    return max(0.0, float(window_hours or presence) - presence)


def fuse_dark_vessels(
    suspects: List[Dict],
    sar_detections: List[Dict],
    window_hours: int = 24,
    incident_id: Optional[str] = None,
) -> List[Dict]:
    """Return a fused suspect list.

    Two fusion paths are implemented:

    1. Every SAR dark spot with a georeferenced centroid is checked against the
       AIS suspect positions. A spot with no AIS vessel within
       ``DARK_VESSEL_RADIUS_KM`` becomes a "dark vessel" candidate ranked above
       all transponder-tracked suspects in this step (the ranker still applies
       its full factor model afterwards, so the final order stays evidence-based).

    2. Existing AIS suspects whose track covers less than the full origin window
       receive an ``ais_gap_hours`` annotation. These are not new candidates;
       they are flagged so the ranker can weigh AIS-gap duration as evidence.
    """
    fused = list(suspects)
    seen_dark = False

    for det in sar_detections or []:
        cg = det.get("centroid_geo") or det.get("bbox_geo")
        if not cg or not isinstance(cg, (list, tuple)) or len(cg) < 2:
            continue
        lon, lat = float(cg[0]), float(cg[1])
        # AIS position of all candidates in the fuse radius.
        co_located = False
        for s in fused:
            if not s.get("position_known"):
                continue
            if _haversine_km(lon, lat, s.get("avg_lon"), s.get("avg_lat")) <= DARK_VESSEL_RADIUS_KM:
                co_located = True
                break
        if co_located:
            continue

        # SAR dark spot with no matching AIS => dark-vessel signal.
        fused.append({
            "mmsi": 0,
            "vessel_id": f"dark_sar_{incident_id or 'incident'}",
            "vessel_name": "Dark vessel (SAR-only, no AIS)",
            "ship_type": "Unknown",
            "geartype": "Unknown",
            "cargo_type": "Unknown",
            "flag": "Unknown",
            "imo": None,
            "length": None,
            "match_count": 0,
            "presence_hours": 0.0,
            "last_seen": None,
            "avg_lat": lat,
            "avg_lon": lon,
            "position_known": True,
            "position_source": "sar_dark_spot",
            "positions": [{"lat": lat, "lon": lon}],
            "from_sar": True,
            "dark_vessel": True,
            "ais_gap_hours": float(window_hours or MIN_AIS_GAP_HOURS),
            "evidence": ("SAR dark spot with no co-located AIS track — "
                         "vessel may be transmitting disabled"),
        })
        seen_dark = True
        logger.info(f"Dark-vessel fusion: SAR @({lon:.3f},{lat:.3f}) has no matching AIS track")

    # Annotate AIS-gap hours for tracked suspects so the evidence reasons can use it.
    for s in fused:
        if s.get("from_sar"):
            continue
        gap = ais_gap_hours(s, window_hours)
        if gap > MIN_AIS_GAP_HOURS:
            s["ais_gap_hours"] = round(gap, 1)

    return fused


def is_dark_vessel(suspect: Dict) -> bool:
    return bool(suspect.get("dark_vessel"))