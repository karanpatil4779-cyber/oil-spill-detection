import numpy as np
from typing import List, Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cargo types that carry oil / hazardous liquid cargo
OIL_CARGO_KEYWORDS = {"oil", "tanker", "crude", "fuel", "bunker", "petrochemical",
                       "bitumen", "lng", "lpg", "chemical", "hazmat"}
CARGO_KEYWORDS = {"cargo", "container", "bulk", "general", "reefer"}
FISHING_KEYWORDS = {"fishing", "trawler", "purse", "longline"}


class AttributionRanker:
    """Ranks potential source vessels based on multi-factor evidence scoring.

    Factors (weights sum to 1.0):
      - proximity    : closeness of the vessel's track mean to the origin centroid
      - duration     : how long the vessel was present in the origin window
      - cargo        : whether the vessel plausibly carries oil / hazardous cargo
      - behaviour    : behavioural anomaly (loitering / station-keeping), which
                       biases strongly toward a stationary discharge source
    """

    def __init__(self, weights: Dict[str, float] = None):
        self.weights = weights or {
            "proximity": 0.35,
            "duration": 0.2,
            "cargo": 0.3,
            "behaviour": 0.15,
        }

    def _calculate_distance(self, p1: List[float], p2: List[float]) -> float:
        """Haversine-like distance in degrees (sufficient for small areas)."""
        return np.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def _cargo_score(self, suspect: Dict) -> float:
        """Score based on vessel type and cargo relevance to oil spills.

        Uses both the cargo_data dict (MMSI -> type string) and any
        ship_type / cargo_type fields present in the suspect dict itself
        (populated by GFW registry lookups).
        """
        cargo_type = ""
        ship_type = ""
        geartype = ""

        if "cargo_type" in suspect:
            cargo_type = str(suspect["cargo_type"]).lower()
        if "ship_type" in suspect:
            ship_type = str(suspect["ship_type"]).lower()
        if "geartype" in suspect and suspect["geartype"]:
            geartype = str(suspect["geartype"]).lower()

        combined = f"{cargo_type} {ship_type} {geartype}"

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

    def rank_vessels(
        self,
        suspects: List[Dict],
        origin_centroid: List[float],
        cargo_data: Dict[int, str] = None,
    ) -> List[Dict]:
        """Assigns a score to each suspect and ranks them.

        Args:
            suspects: List of vessel dicts from AIS / GFW.
            origin_centroid: [lon, lat] of the probability centroid.
            cargo_data: Map of MMSI -> Cargo Type (legacy fallback).
        """
        ranked_list = []

        for suspect in suspects:
            # 1. Proximity Score (inverse distance)
            dist = self._calculate_distance(
                [suspect.get("avg_lon", 0), suspect.get("avg_lat", 0)],
                origin_centroid,
            )
            proximity_score = 1.0 / (1.0 + dist * 100)

            # 2. Duration Score (based on match count / track density)
            duration_score = min(suspect.get("match_count", 1) / 50.0, 1.0)

            # 3. Cargo Score — prefer GFW registry fields, fallback to cargo_data dict
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

            # 4. Behavioural anomaly score (loitering / station-keeping / turn)
            behaviour_score = float(suspect.get("anomaly_score", 0.0) or 0.0)

            final_score = (
                proximity_score * self.weights["proximity"]
                + duration_score * self.weights["duration"]
                + cargo_score * self.weights["cargo"]
                + behaviour_score * self.weights.get("behaviour", 0.0)
            )

            ranked_list.append({
                **suspect,
                "attribution_score": round(final_score, 4),
                "factors": {
                    "proximity": round(proximity_score, 3),
                    "duration": round(duration_score, 3),
                    "cargo": round(cargo_score, 3),
                    "behaviour": round(behaviour_score, 3),
                },
            })

        ranked_list.sort(key=lambda x: x["attribution_score"], reverse=True)
        return ranked_list
