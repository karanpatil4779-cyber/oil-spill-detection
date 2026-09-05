"""Seed mock pipeline data for demo.

EVERYTHING THIS SCRIPT WRITES IS SYNTHETIC. No value here was produced by the
pipeline, and no vessel named here exists. The records are therefore stamped
with ``is_demo`` and a ``demo_notice`` inside ``pipeline_result``, which the UI
renders as a DEMO DATA badge. Do not remove those fields: without them a
fabricated tanker name sits in the same table, and renders in the same panel,
as a real Global Fishing Watch record.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.db.models import SessionLocal, Case, AuditLogEntry, User, init_db
import json

DEMO_NOTICE = (
    "Synthetic fixture data seeded by scripts/seed_demo_data.py. Vessel "
    "identities, positions, attribution scores and imagery-derived values are "
    "invented for interface demonstration and must not be cited as evidence."
)

init_db()
db = SessionLocal()

analyst = db.query(User).filter(User.email == "analyst@oilspill.gov").first()
if not analyst:
    print("No analyst user found")
    sys.exit(1)

case = db.query(Case).filter(Case.analyst_id == analyst.id).first()
if not case:
    print("No case found")
    sys.exit(1)

result = {
    "is_demo": True,
    "demo_notice": DEMO_NOTICE,
    "incident_id": case.case_number,
    "status": "completed",
    "origin_centroid": [72.75, 18.92],
    "origin_bbox": [72.65, 18.82, 72.85, 19.02],
    "detections": [],
    "characterization": {
        "slick_count": 2,
        "total_area_km2": 4.32,
        "est_volume_m3": 156.7,
        "est_volume_barrels": 986.0,
        "likely_oil_type": "Crude Oil / Heavy Fuel",
        "per_slick": [
            {"area_km2": 2.8, "est_volume_m3": 102.3, "est_volume_barrels": 643.8, "bbox_geo": [72.7, 18.88, 72.78, 18.95]},
            {"area_km2": 1.52, "est_volume_m3": 54.4, "est_volume_barrels": 342.2, "bbox_geo": [72.72, 18.90, 72.79, 18.97]}
        ]
    },
    "age": {
        "age_hours": 14.5,
        "age_min_hours": 10.0,
        "age_max_hours": 19.0,
        "confidence": 0.72,
        "stage_label": "Fresh-Sheen",
        "method": "SAR-contrast + wind-corrected",
        "mean_wind_ms": 5.8
    },
    "eo": {
        "confirmed": True,
        "ndhi_mean_water": 0.12,
        "anomaly_px": 342,
        "reason": "NDHI anomaly above threshold in SWIR bands"
    },
    "forecast": {
        "centroid": [72.78, 18.88],
        "bbox": [72.60, 18.70, 72.96, 19.06],
        "spread_deg": [0.18, 0.16],
        "confidence": 0.65,
        "median_path": [[72.75, 18.92], [72.76, 18.90], [72.78, 18.88], [72.80, 18.85], [72.82, 18.82]]
    },
    "suspects": [
        {
            "mmsi": 419000123,
            "vessel_name": "MT Raavi",
            "ship_type": "Oil Tanker",
            "cargo_type": "Crude Oil",
            "flag": "India",
            "attribution_score": 0.847,
            "match_count": 14,
            "last_seen": "2018-01-30T08:30:00",
            "avg_lon": 72.74,
            "avg_lat": 18.93,
            "anomaly_score": 0.71,
            "evidence": "Loitering in origin zone, 3.2h dwell",
            "factors": {"proximity": 0.92, "duration": 0.78, "cargo": 0.85, "behaviour": 0.71}
        },
        {
            "mmsi": 419000456,
            "vessel_name": "MV Pacific Star",
            "ship_type": "Bulk Carrier",
            "cargo_type": "Dry Bulk",
            "flag": "Panama",
            "attribution_score": 0.523,
            "match_count": 8,
            "last_seen": "2018-01-30T06:15:00",
            "avg_lon": 72.71,
            "avg_lat": 18.96,
            "anomaly_score": 0.35,
            "evidence": "Passing through, normal speed",
            "factors": {"proximity": 0.65, "duration": 0.42, "cargo": 0.30, "behaviour": 0.35}
        },
        {
            "mmsi": 419000789,
            "vessel_name": "INS Betwa",
            "ship_type": "Naval Vessel",
            "cargo_type": "N/A",
            "flag": "India",
            "attribution_score": 0.291,
            "match_count": 3,
            "last_seen": "2018-01-30T10:00:00",
            "avg_lon": 72.82,
            "avg_lat": 18.85,
            "anomaly_score": 0.12,
            "evidence": "No anomalous behaviour detected",
            "factors": {"proximity": 0.40, "duration": 0.15, "cargo": 0.10, "behaviour": 0.12}
        }
    ],
    "sar_available": True,
    "sar_requested": False,
    "sar_scenes_used": 0,
    "gfw_available": True,
    "gfw_requested": True,
    "origin_std_dev": [0.06, 0.055],
    "provider_status": {"sar": "not_requested", "gfw": "ok", "transport": "ok"},
    "warnings": ["Metocean ERA5 wind field shows variable directions - transport model uncertainty elevated"]
}

# Every suspect carries the marker too: vessel rows are frequently exported,
# screenshotted or pasted into a report on their own, away from the case header
# where the badge lives.
for _s in result["suspects"]:
    _s["is_demo"] = True
    _s["position_known"] = True
    _s["position_source"] = "synthetic_fixture"

# Compute the verdict with the same code path a real run uses, rather than
# hardcoding a confidence the pipeline would never emit. The previous value
# (0.72) was copied from age.confidence and was not a detection confidence.
from engines.assessment import summarize, stored_confidence
summarize(result)
_provider_status = {"sar": "not_requested", "gfw": "ok", "transport": "ok"}
result["provider_status"] = _provider_status

case.pipeline_result = result
case.overall_confidence = stored_confidence(result)
case.status = "pending_review"

db.add(AuditLogEntry(case_id=case.id, actor_id=analyst.id, action_type="case_created", detail={"location": "Mumbai Harbour"}))
db.add(AuditLogEntry(case_id=case.id, actor_id=analyst.id, action_type="pipeline_run", detail={"triggered": True}))
db.add(AuditLogEntry(case_id=case.id, actor_id=analyst.id, action_type="rank_override", detail={"vessel_id": "419000123", "new_rank": 1, "justification": "Highest proximity + dwell time match"}))
db.add(AuditLogEntry(case_id=case.id, actor_id=analyst.id, action_type="status_change", detail={"from": "in_progress", "to": "pending_review"}))

db.commit()
print(f"Case {case.case_number} updated with mock pipeline data")
print(f"Status: {case.status}, Confidence: {case.overall_confidence}")
print(f"Suspects: {len(result['suspects'])}")

# Also create a second case (in_progress, no pipeline yet)
case2 = Case(
    case_number="INC-2026-0003",
    analyst_id=analyst.id,
    status="in_progress",
    location_name="Chennai Coast",
    lon=80.35,
    lat=13.28,
    detection_date="2017-03-10",
    duration_hours=48,
)
db.add(case2)
db.commit()
print(f"Case {case2.case_number} created (no pipeline yet)")

db.close()
