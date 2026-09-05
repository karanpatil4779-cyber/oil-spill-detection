"""Tests for the newly-added pipeline enhancements:
  - oil spill age estimation (engines/aging/oil_age.py)
  - forward drift forecast (engines/transport/lagrangian_tracker.py::track_forward/forecast_ensemble)
  - behavioural anomaly & irrelevant-traffic filtering (engines/ais/behaviour.py)
  - behavioural factor in attribution (engines/attribution/ranker.py)
  - Echo/Sentinel-2 EO detection modules importable (engines/detection/eo_detector.py)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

# ---------------------------------------------------------------------------
# 1. Oil age estimation
# ---------------------------------------------------------------------------
from engines.aging.oil_age import estimate_oil_age, extract_mean_wind, OilAgeResult

def test_age_estimation():
    # Fresh, strong-contrast slick -> small age
    fresh = estimate_oil_age([{"mean_db": -20.0, "area_px": 50000}], mean_wind_ms=3.0)
    assert isinstance(fresh, OilAgeResult)
    assert fresh.age_hours < 24, f"fresh slick should be young, got {fresh.age_hours}"
    assert fresh.age_min_hours <= fresh.age_hours <= fresh.age_max_hours
    assert fresh.confidence > 0

    # Weathered, weak contrast -> larger age
    old = estimate_oil_age([{"mean_db": -5.0, "area_px": 300000}], mean_wind_ms=10.0)
    assert old.age_hours > fresh.age_hours, "weathered slick should be older"

    # Multi-pass bracket widens / anchors confidence
    brack = estimate_oil_age([{"mean_db": -12.0}], frames=2, multi_pass_hint=(10, 50))
    assert brack.frames_used == 2
    assert brack.age_hours >= 10, "multi-pass bracket should bound the lower age"
    print("[PASS] test_age_estimation")

def test_age_real_wind_extraction():
    # Real metocean file (present in the repo) should yield a wind value or None
    path = "data/processed/metocean/mt_jipro_neftis/final_metocean.nc"
    if os.path.exists(path):
        mw = extract_mean_wind(path, 72.80, 18.90, "2018-01-30T12:00:00", 24)
        print(f"  real mean wind: {mw}")
    print("[PASS] test_age_real_wind_extraction")

# ---------------------------------------------------------------------------
# 2. Forward drift forecast
# ---------------------------------------------------------------------------
from engines.transport.lagrangian_tracker import LagrangianTracker

def test_forward_forecast():
    path = "data/processed/metocean/mt_jipro_neftis/final_metocean.nc"
    track = LagrangianTracker(path)
    fc = track.forecast_ensemble(72.80, 18.90, "2018-01-30T12:00:00",
                                 duration_hours=12, num_particles=50)
    assert fc["centroid"] is not None, "forecast centroid should exist"
    assert len(fc["median_path"]) > 1, "should have a multi-point median path"
    assert fc["bbox"] is not None and len(fc["bbox"]) == 4
    assert 0.0 <= fc["confidence"] <= 1.0
    assert fc["spread_deg"] is not None
    print("[PASS] test_forward_forecast",
          f"centroid={np.round(fc['centroid'],3)} conf={fc['confidence']}")

# ---------------------------------------------------------------------------
# 3. Behavioural anomaly + irrelevant-traffic filtering
# ---------------------------------------------------------------------------
from engines.ais.behaviour import behavioural_anomaly, filter_and_enrich

def test_behaviour_and_filter():
    loiterer = {
        "vessel_name": "TANKER A", "mmsi": 1, "presence_hours": 40, "match_count": 40,
        "positions": [{"lon": 72.8, "lat": 18.9}, {"lon": 72.801, "lat": 18.901},
                      {"lon": 72.799, "lat": 18.899}],
        "avg_lon": 72.8, "avg_lat": 18.9, "ship_type": "Tanker", "cargo_type": "Oil",
    }
    transient = {
        "vessel_name": "CARGO B", "mmsi": 2, "presence_hours": 0.1, "match_count": 1,
        "positions": [{"lon": 72.9, "lat": 19.1}], "avg_lon": 72.9, "avg_lat": 19.1,
    }
    b1 = behavioural_anomaly(loiterer)
    b2 = behavioural_anomaly(transient)
    assert b1["transit_ok"] is True
    assert b1["anomaly_score"] >= 0.5, "loiterer should score as anomalous"
    assert b2["transit_ok"] is False, "transient vessel should be filtered"
    kept = filter_and_enrich([loiterer, transient])
    names = [k["vessel_name"] for k in kept]
    assert "CARGO B" not in names, "transient must be dropped"
    assert "TANKER A" in names, "loiterer must be kept"
    print("[PASS] test_behaviour_and_filter", names, "anomaly", b1["anomaly_score"])

# ---------------------------------------------------------------------------
# 4. Attribution behavioural factor
# ---------------------------------------------------------------------------
from engines.attribution.ranker import AttributionRanker

def test_ranker_behaviour_factor():
    ranker = AttributionRanker()
    origin = [72.8, 18.9]
    suspects = [
        {"vessel_name": "A", "mmsi": 1, "avg_lon": 72.8, "avg_lat": 18.9,
         "match_count": 40, "anomaly_score": 1.0, "cargo_type": "Oil Tanker"},
        {"vessel_name": "B", "mmsi": 2, "avg_lon": 72.8, "avg_lat": 18.9,
         "match_count": 40, "anomaly_score": 0.1, "cargo_type": "Oil Tanker"},
    ]
    ranked = ranker.rank_vessels(suspects, origin, {})
    fa = ranked[0]["factors"]["behaviour"]
    fb = ranked[1]["factors"]["behaviour"]
    assert fa >= fb, "higher-anomaly vessel should get higher behaviour factor"
    assert ranked[0]["vessel_name"] == "A"
    print("[PASS] test_ranker_behaviour_factor", "A behaviour", fa, "B behaviour", fb)

# ---------------------------------------------------------------------------
# 5. EO / Sentinel-2 module importable
# ---------------------------------------------------------------------------
def test_eo_module_import():
    import engines.detection.eo_detector as eo
    assert hasattr(eo, "EODetector")
    assert hasattr(eo, "NDHI_OIL_THRESHOLD")
    print("[PASS] test_eo_module_import")


if __name__ == "__main__":
    test_age_estimation()
    test_age_real_wind_extraction()
    test_forward_forecast()
    test_behaviour_and_filter()
    test_ranker_behaviour_factor()
    test_eo_module_import()
    print("\nALL ENHANCEMENT TESTS PASSED")
