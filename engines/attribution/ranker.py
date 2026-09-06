import numpy as np
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Vessel-type tiers used for "irrelevant traffic" filtering (PS directive).
# Tankers/oil carriers are the most credible source profile; fishing craft,
# ferries and passenger vessels are deprioritised unless their behaviour or a
# repeat-offence history argues otherwise.
TYPE_TIERS = {
    "oil": 1.0, "tanker": 1.0, "crude": 1.0, "fuel": 0.9, "bunker": 0.9,
    "lng": 0.8, "lpg": 0.8, "chemical": 0.8, "hazmat": 0.8, "petrochemical": 0.8,
    "bitumen": 0.85,
    "cargo": 0.5, "container": 0.5, "bulk": 0.45, "general": 0.45,
    "reefer": 0.4, "vehicle": 0.4,
    "supply": 0.3, "anchor": 0.25, "tug": 0.25,
    "fishing": 0.1, "trawler": 0.1, "purse": 0.1, "longline": 0.1,
    "ferry": 0.1, "passenger": 0.15, "cruise": 0.2,
}
TYPE_TIER_LABELS = {
    "oil": "oil tanker", "tanker": "oil tanker", "crude": "crude carrier",
    "cargo": "cargo/container", "container": "cargo/container",
    "bulk": "bulk carrier",
    "fishing": "fishing", "trawler": "fishing", "ferry": "ferry/passenger",
    "passenger": "ferry/passenger", "cruise": "passenger",
}

# Cargo types that carry oil / hazardous liquid cargo
OIL_CARGO_KEYWORDS = {"oil", "tanker", "crude", "fuel", "bunker", "petrochemical",
                       "bitumen", "lng", "lpg", "chemical", "hazmat"}
CARGO_KEYWORDS = {"cargo", "container", "bulk", "general", "reefer"}
FISHING_KEYWORDS = {"fishing", "trawler", "purse", "longline"}
LOW_TIER_KEYWORDS = {"ferry", "passenger", "tug", "pilot", "pleasure", "leisure", "sailing", "search"}

DEFAULT_WEIGHTS = {
    "proximity": 0.30,
    "duration": 0.18,
    "cargo": 0.22,
    "behaviour": 0.15,
    "vessel_type": 0.10,
    "repeat": 0.05,
}


class AttributionRanker:
    """Ranks potential source vessels based on multi-factor evidence scoring.

    Factors (weights sum to 1.0):
      - proximity    : closeness of the vessel's track mean to the origin centroid
      - duration     : how long the vessel was present in the origin window
      - cargo        : whether the vessel plausibly carries oil / hazardous cargo
      - behaviour    : behavioural anomaly (loitering / station-keeping), which
                       biases strongly toward a stationary discharge source
      - vessel_type  : relevance of the vessel's type to an oil source profile
                       (tanker/cargo upweighted; fishing/ferry deprioritised)
      - repeat       : repeat-offender history in the region (AIS gaps / prior
                       attribution) — only scored when real history is supplied

    Every suspect is returned with a ``reasons`` list so the ranking is
    explainable: each reason states which factor relied on what observation.
    """

    def __init__(self, weights: Dict[str, float] = None):
        self.weights = weights or dict(DEFAULT_WEIGHTS)

    def _calculate_distance(self, p1: List[float], p2: List[float]) -> float:
        """Haversine-like distance in degrees (sufficient for small areas)."""
        return np.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def _vessel_type(self, suspect: Dict) -> str:
        """Normalised vessel type string from registry fields."""
        combined = " ".join(str(suspect.get(k, "") or "") for k in
                            ("cargo_type", "ship_type", "geartype")).lower()
        for kw in ("fishing", "trawler", "purse", "longline"):
            if kw in combined:
                return "fishing"
        for kw in ("ferry", "passenger", "cruise"):
            if kw in combined:
                return "ferry/passenger"
        for kw in OIL_CARGO_KEYWORDS:
            if kw in combined:
                return "oil"
        for kw in CARGO_KEYWORDS:
            if kw in combined:
                return "cargo"
        return "unknown"

    def _vessel_type_score(self, suspect: Dict) -> float:
        """Relevance of the vessel type to an oil-source profile (0..1)."""
        vt = self._vessel_type(suspect)
        return TYPE_TIERS.get(vt, TYPE_TIERS.get("unknown", 0.3)) if vt != "unknown" \
            else 0.3

    def _cargo_score(self, suspect: Dict) -> float:
        """Score based on vessel type and cargo relevance to oil spills."""
        combined = ""
        for key in ("cargo_type", "ship_type", "geartype"):
            if suspect.get(key):
                combined += f" {str(suspect[key]).lower()}"
        combined = combined.strip()

        for kw in OIL_CARGO_KEYWORDS:
            if kw in combined:
                return 1.0
        for kw in CARGO_KEYWORDS:
            if kw in combined:
                return 0.3
        for kw in FISHING_KEYWORDS:
            if kw in combined:
                return 0.1
        return 0.0

    def _suspect_evidence(self, suspect: Dict, dist, proximity_score, duration_score,
                          cargo_score, behaviour_score, type_score, repeat_info,
                          window_hours) -> List[str]:
        """Human-readable reasons explaining this suspect's ranking."""
        reasons = []
        vt = self._vessel_type(suspect)
        presence = float(suspect.get("presence_hours") or suspect.get("match_count") or 0.0)
        if suspect.get("dark_vessel") or suspect.get("from_sar"):
            reasons.append("SAR dark spot with no co-located AIS track — primary "
                           "unattributable source signal (AIS may be disabled)")
        if dist is not None:
            reasons.append(f"{dist:.3f} deg from probable origin (proximity {proximity_score:.2f})")
            reasons.append("track passes through the origin-window overlap region")
        else:
            reasons.append("no reported position, so proximity could not be scored")
        reasons.append(f"present {presence:.0f}h of the {window_hours}h origin window")
        gap = max(0.0, window_hours - presence)
        if gap >= 1.0:
            reasons.append(f"AIS gap of {gap:.0f}h within the origin window (presence does not cover the full window)")
        if cargo_score >= 1.0:
            reasons.append("carries oil/hazardous cargo compatible with a discharge source")
        elif cargo_score >= 0.3:
            reasons.append("general cargo profile; can carry fuel but not a primary oil carrier")
        elif cargo_score <= 0.1:
            reasons.append(f"low-cargo-relevance type ({vt})")
        if behaviour_score >= 0.6:
            reasons.append(f"strong behavioural anomaly ({suspect.get('evidence', 'signal')})")
        elif behaviour_score >= 0.3:
            reasons.append("moderate behavioural anomaly (partial linger near origin)")
        else:
            reasons.append("no behavioural anomaly; a transit-only profile")
        tier_note = TYPE_TIER_LABELS.get(vt, vt)
        if type_score >= 0.8:
            reasons.append(f"vessel type {tier_note} strongly matches an oil-source profile")
        elif type_score <= 0.15:
            reasons.append(f"vessel type {tier_note} is deprioritised (irrelevant traffic)")
        if repeat_info is not None:
            if repeat_info.get("count", 0) > 0:
                reasons.append(
                    f"repeat offender: involved in {repeat_info['count']} prior "
                    f"attribution{'s' if repeat_info['count'] > 1 else ''} in this region")
            else:
                reasons.append("no prior attribution history in this region")
        return reasons

    def rank_vessels(
        self,
        suspects: List[Dict],
        origin_centroid: List[float],
        cargo_data: Dict[int, str] = None,
        history: Optional[Dict[int, Dict]] = None,
        window_hours: int = 24,
    ) -> List[Dict]:
        """Assigns a score to each suspect and ranks them.

        Args:
            suspects: List of vessel dicts from AIS / GFW.
            origin_centroid: [lon, lat] of the probability centroid.
            cargo_data: Map of MMSI -> Cargo Type (legacy fallback).
            history: Map of MMSI -> {"count": int, "incidents": [case_number]}
                     from real prior-attribution records (repeat-offender profile).
            window_hours: Length of the origin window used to quantify AIS gaps.
        """
        ranked_list = []

        for suspect in suspects:
            reasons = []

            avg_lon = suspect.get("avg_lon")
            avg_lat = suspect.get("avg_lat")
            position_known = (
                suspect.get("position_known", avg_lon is not None and avg_lat is not None)
                and avg_lon is not None and avg_lat is not None
            )
            unscoreable = []
            if position_known:
                dist = self._calculate_distance([avg_lon, avg_lat], origin_centroid)
                proximity_score = 1.0 / (1.0 + dist * 100)
            else:
                dist = None
                proximity_score = 0.0
                unscoreable.append("proximity")

            duration_score = min((suspect.get("presence_hours") or
                                  suspect.get("match_count") or 0) / 50.0, 1.0)

            cargo_score = self._cargo_score(suspect)
            if cargo_score == 0.0 and cargo_data:
                mmsi = suspect.get("mmsi", 0)
                if mmsi in cargo_data:
                    ct = str(cargo_data[mmsi]).lower()
                    for kw in OIL_CARGO_KEYWORDS:
                        if kw in ct:
                            cargo_score = 1.0
                            break
                    if cargo_score == 0.0:
                        for kw in CARGO_KEYWORDS:
                            if kw in ct:
                                cargo_score = 0.3
                                break

            behaviour_score = float(suspect.get("anomaly_score", 0.0) or 0.0)
            type_score = self._vessel_type_score(suspect)

            # Feature 1: a SAR dark spot with no co-located AIS track is the
            # single strongest "unattributable" source signal. Treat it as a
            # maximal behavioural anomaly — the vessel may have disabled AIS.
            is_dark = bool(suspect.get("dark_vessel") or suspect.get("from_sar"))
            if is_dark:
                behaviour_score = max(behaviour_score, 0.95)
                suspect["evidence"] = (
                    suspect.get("evidence")
                    or "SAR dark spot with no co-located AIS track — AIS likely disabled")

            # Repeat-offender profile: real history passed in from the DB, or a
            # per-vessel prior supplied by the caller (e.g. SAR/AIS-gap fusion).
            repeat_info = None
            repeat_score = 0.0
            mmsi_key = suspect.get("mmsi")
            if isinstance(mmsi_key, int) and mmsi_key and history is not None:
                repeat_info = history.get(mmsi_key)
                if repeat_info:
                    repeat_score = min(1.0, repeat_info.get("count", 0) / 5.0)
                    suspect["repeat_offense_count"] = repeat_info.get("count", 0)
                    suspect["repeat_offense_incidents"] = repeat_info.get("incidents", [])
                else:
                    suspect["repeat_offense_count"] = 0

            reasons.extend(self._suspect_evidence(
                suspect, dist, proximity_score, duration_score, cargo_score,
                behaviour_score, type_score, repeat_info, window_hours))

            final_score = (
                proximity_score * self.weights["proximity"]
                + duration_score * self.weights["duration"]
                + cargo_score * self.weights["cargo"]
                + behaviour_score * self.weights.get("behaviour", 0.0)
                + type_score * self.weights.get("vessel_type", 0.0)
                + repeat_score * self.weights.get("repeat", 0.0)
            )

            ranked_list.append({
                **suspect,
                "attribution_score": round(float(final_score), 4),
                "factors": {
                    "proximity": round(float(proximity_score), 3),
                    "duration": round(float(duration_score), 3),
                    "cargo": round(float(cargo_score), 3),
                    "behaviour": round(float(behaviour_score), 3),
                    "vessel_type": round(float(type_score), 3),
                    "repeat": round(float(repeat_score), 3),
                },
                "factors_unscoreable": unscoreable,
                "distance_to_origin_deg": (round(float(dist), 5) if dist is not None else None),
                "reasons": reasons,
            })

        ranked_list.sort(
            key=lambda x: (bool(x.get("dark_vessel") or x.get("from_sar")),
                           x.get("attribution_score", 0.0)),
            reverse=True)

        for i, item in enumerate(ranked_list):
            # Feature 1: a SAR dark spot with no AIS match is the primary
            # "unattributable" signal and is ranked top by policy, with its
            # evidence-based score still shown for traceability.
            if item.get("dark_vessel") or item.get("from_sar"):
                item["top_signal"] = True
                if "SAR dark spot with no co-located AIS track" not in " ".join(item.get("reasons", [])):
                    item.setdefault("reasons", []).insert(
                        0, "ranked top signal: SAR dark spot with no matching AIS "
                           "(primary unattributable-vessel evidence)")
            tied = [o for o in ranked_list
                    if o is not item
                    and o["attribution_score"] == item["attribution_score"]]
            item["rank"] = i + 1
            item["rank_is_tied"] = bool(tied)
            item["tied_with_count"] = len(tied)
        return ranked_list