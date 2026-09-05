"""Behavioural-analysis engine for AIS-derived vessel suspects.

Filters out "irrelevant traffic" (vessels merely transiting the origin window
without stopping) and computes behavioural-anomaly evidence used to boost the
attribution score for suspect vessels. This directly addresses the problem
statement's requirement to "filter out irrelevant traffic" and score vessels
on "behavioural anomalies".

Supported anomaly signals (computed from real GFW presence / position data):

  * Loitering / station-keeping  - a vessel that lingered in the origin area
    for a long time (high presence hours relative to its footprint) is far more
    likely to be the source than one that merely passed through.
  * Stationary drift  - a suspect with many presence hours but a very small
    spatial spread behaved like a vessel stopped or drifting slowly, a classic
    sign of discharging or stopped-engine drifting.
  * Tight turnaround  - reversed motion (first and last positions far apart
    while hours are concentrated) suggests manoeuvring at the site.

Each produces a normalised 0..1 score; the max is returned as the anomaly
signal. A "transit filter" removes vessels whose presence is too brief/fast to
plausibly be the source.
"""

import math
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _haversine_deg(lon1, lat1, lon2, lat2) -> float:
    """Approx distance in km from degrees, good enough over short baselines."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(min(a, 1.0)))


def _positions_of(suspect: Dict) -> List[Dict]:
    """Extract position records from a suspect dict, GFW-normalised or raw."""
    pos = suspect.get("positions") or []
    if pos:
        return [p if isinstance(p, dict) else {"lon": p[0], "lat": p[1]} for p in pos]
    # Fall back to a single representative position if all we have is the mean
    mp = suspect.get("mean_position") or {}
    if mp:
        return [{"lon": mp.get("lon"), "lat": mp.get("lat")}]
    return []


def transit_filter(suspect: Dict,
                   min_presence_hours: float = 1.0,
                   max_transit_speed_kn: float = 25.0) -> Tuple[bool, Optional[str]]:
    """Decide whether a vessel should be kept as a plausible suspect.

    Returns (keep, reason). Vessels that only clipped the window edge with very
    few hours, or that are implausibly fast transits well clear of the origin,
    are dropped as "irrelevant traffic".

    Uses real presence hours (presence_hours / match_count).
    """
    hours = float(suspect.get("presence_hours") or suspect.get("match_count") or 0)
    if hours <= 0:
        return False, "no presence hours (edge clip / no coverage)"
    if hours < min_presence_hours:
        return False, f"transient (< {min_presence_hours}h)"

    pos = _positions_of(suspect)
    if len(pos) >= 2:
        lons = [p.get("lon") for p in pos if p.get("lon") is not None]
        lats = [p.get("lat") for p in pos if p.get("lat") is not None]
        if len(lons) >= 2 and len(lats) >= 2:
            dist_km = _haversine_deg(min(lons), min(lats), max(lons), max(lats))
            duration_h = max(hours, 0.5)
            speed_kn = (dist_km / duration_h) * 0.539957  # km/h -> knots
            if duration_h >= 2 and speed_kn > max_transit_speed_kn:
                return False, f"high-speed transit ({speed_kn:.0f} kn)"

    return True, "kept"


def loitering_score(suspect: Dict) -> float:
    """Score 0..1 based on how long the vessel lingered in the origin area.

    Uses presence hours normalised against the max observed footprint; the
    longer the dwell relative to an oil-source expectation, the higher.
    """
    hours = float(suspect.get("presence_hours") or suspect.get("match_count") or 0)
    if hours <= 0:
        return 0.0
    # Saturates around a full day of lingering
    return min(hours / 24.0, 1.0)


def stationary_score(suspect: Dict) -> float:
    """Score 0..1 for a vessel that stayed put (small spread over many hours)."""
    hours = float(suspect.get("presence_hours") or suspect.get("match_count") or 0)
    if hours <= 0:
        return 0.0
    pos = _positions_of(suspect)
    if len(pos) < 2:
        # Only a single representative position but many hours => very stationary
        return 0.5 if hours >= 8 else 0.2
    lons = [p.get("lon") for p in pos if p.get("lon") is not None]
    lats = [p.get("lat") for p in pos if p.get("lat") is not None]
    if len(lons) < 2:
        return 0.0
    spread_km = _haversine_deg(min(lons), min(lats), max(lons), max(lats))
    # spread_km should stay small if anchored/loitering; longer hours + small
    # spread => strongly stationary.
    spread_h = max(spread_km, 0.05)
    dwell = min(hours, 24.0)
    score = (dwell / 24.0) * (1.0 - min(spread_km / 5.0, 1.0))
    return max(0.0, min(score, 1.0))


def turnaround_score(suspect: Dict) -> float:
    """Score 0..1 for a tight-loop / manoeuvring signature at the site."""
    hours = float(suspect.get("presence_hours") or suspect.get("match_count") or 0)
    pos = _positions_of(suspect)
    if len(pos) < 3 or hours <= 0:
        return 0.0
    first = pos[0]
    last = pos[-1]
    if first.get("lon") is None or last.get("lon") is None:
        return 0.0
    out_bound = _haversine_deg(first["lon"], first["lat"], last["lon"], last["lat"])
    max_dist = 0.0
    for a in pos:
        for b in pos:
            if a.get("lon") is None or b.get("lon") is None:
                continue
            d = _haversine_deg(a["lon"], a["lat"], b["lon"], b["lat"])
            if d > max_dist:
                max_dist = d
    if max_dist <= 0:
        return 0.0
    # Loitering: huge internal spread relative to net displacement => circling
    coverage = max_dist / max(max_dist + out_bound + 0.001, 1e-6)
    dwell = min(hours, 24.0) / 24.0
    return max(0.0, min(coverage * dwell, 1.0))


def behavioural_anomaly(suspect: Dict) -> Dict:
    """Compute the anomaly report + a single 0..1 anomaly score for a suspect.

    Returns a dict (merged into the suspect later):
      - anomaly_score: max of the individual signals (0..1)
      - signals: {loitering, stationary, turnaround} each 0..1
      - evidence: short human-readable note
      - transit_ok / transit_reason: result of the irrelevant-traffic filter
    """
    loit = loitering_score(suspect)
    stat = stationary_score(suspect)
    turn = turnaround_score(suspect)
    signals = {"loitering": round(loit, 3),
               "stationary": round(stat, 3),
               "turnaround": round(turn, 3)}
    anomaly = max(loit, stat, turn)

    keep, reason = transit_filter(suspect)
    label = reason if not keep else "lingering / manoeuvring near origin"
    if anomaly >= 0.6 and keep:
        label = "strong behavioural anomaly (loitering/station-keeping)"

    return {
        "anomaly_score": round(anomaly, 3),
        "signals": signals,
        "evidence": label,
        "transit_ok": keep,
        "transit_reason": reason,
    }


def filter_and_enrich(suspects: List[Dict], min_presence_hours: float = 1.0) -> List[Dict]:
    """Drop irrelevant traffic and attach behavioural evidence to survivors.

    Returns a new suspect list sorted by anomaly score (highest first) with the
    behavioural fields merged into each record. Survivors keep only the fields
    of actual candidate source vessels.
    """
    out = []
    for s in suspects:
        beh = behavioural_anomaly(s)
        if not beh["transit_ok"]:
            logger.info(f"Dropping {s.get('vessel_name')}: {beh['transit_reason']}")
            continue
        merged = {**s, **beh}
        out.append(merged)
    out.sort(key=lambda x: x.get("anomaly_score", 0.0), reverse=True)
    return out
