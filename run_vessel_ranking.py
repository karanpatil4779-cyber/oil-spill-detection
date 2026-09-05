"""Run vessel tracking + attribution ranking for the GAL Constructor 2021 incident."""

import sys
sys.path.insert(0, ".")

from engines.ais.gfw_client import GFWClient
from engines.ais.behaviour import filter_and_enrich
from engines.attribution.ranker import AttributionRanker

INCIDENT_COORDS = [72.7000, 19.8000]
START = "2021-05-15T00:00:00.000Z"
END = "2021-06-01T00:00:00.000Z"

margin = 0.15
BBOX = [
    INCIDENT_COORDS[0] - margin,
    INCIDENT_COORDS[1] - margin,
    INCIDENT_COORDS[0] + margin,
    INCIDENT_COORDS[1] + margin,
]

print(f"Incident : GAL Constructor, 2021-05-17")
print(f"Location : {INCIDENT_COORDS}")
print(f"BBox     : {BBOX}")
print(f"Window   : {START} -> {END}")
print()

# 1. Query GFW for vessels
print("--- Querying GFW AIS vessel presence ---")
gfw = GFWClient()
suspects = gfw.vessels_in_bbox_and_time(BBOX, [START, END])
print(f"Raw vessels found: {len(suspects)}")

# 2. Behavioural filter + enrichment
print("\n--- Behavioural analysis & filtering ---")
filtered = filter_and_enrich(suspects, min_presence_hours=1.0)
print(f"Vessels after transit filter: {len(filtered)}")

# 3. Attribution ranking
print("\n--- Attribution ranking ---")
ranker = AttributionRanker()
cargo = {}
for s in filtered:
    m = s.get("mmsi", 0)
    if m:
        cargo[m] = s.get("cargo_type", s.get("ship_type", "Unknown"))

ranked = ranker.rank_vessels(filtered, INCIDENT_COORDS, cargo)

print(f"\n{'Rank':<5} {'Vessel Name':<30} {'Score':>7} {'Prox':>6} {'Dur':>6} {'Cargo':>6} {'Behav':>6} {'Hours':>7} {'Type'}")
print("-" * 120)
for i, v in enumerate(ranked, 1):
    name = v.get("vessel_name", "Unknown")
    score = v["attribution_score"]
    prox = v["factors"]["proximity"]
    dur = v["factors"]["duration"]
    cargo_s = v["factors"]["cargo"]
    behav = v["factors"]["behaviour"]
    hours = v.get("presence_hours", 0)
    stype = v.get("ship_type", "?")
    anomaly = v.get("anomaly_score", 0)
    evidence = v.get("evidence", "")
    print(f"{i:<5} {name:<30} {score:>7.4f} {prox:>6.3f} {dur:>6.3f} {cargo_s:>6.3f} {behav:>6.3f} {hours:>7.1f} {stype}")
    if evidence:
        print(f"      Evidence: {evidence}")
