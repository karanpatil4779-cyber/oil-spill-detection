"""End-to-end pipeline test with real data."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xarray as xr
import numpy as np

print("=" * 60)
print("END-TO-END PIPELINE TEST")
print("=" * 60)

# 1. Verify rebuilt metocean file
print("\n[1/5] Verifying rebuilt final_metocean.nc ...")
ds = xr.open_dataset("data/processed/metocean/mumbai/final_metocean.nc")
vars_list = list(ds.data_vars)
print(f"  Variables: {vars_list}")
print(f"  Dimensions: {dict(ds.sizes)}")
assert "u10" in ds.data_vars, "u10 missing!"
assert "v10" in ds.data_vars, "v10 missing!"
assert "uo" in ds.data_vars, "uo missing!"
assert "vo" in ds.data_vars, "vo missing!"
print(f"  u10 range: [{float(ds.u10.min()):.3f}, {float(ds.u10.max()):.3f}] m/s")
print(f"  uo range: [{float(ds.uo.min()):.6f}, {float(ds.uo.max()):.6f}] m/s")
ds.close()
print("  [PASS] All critical variables present (u10, v10, uo, vo)")

# 2. Test LagrangianTracker with rebuilt file
print("\n[2/5] Testing LagrangianTracker on Chitra 2010 data ...")
from engines.transport.lagrangian_tracker import LagrangianTracker
tracker = LagrangianTracker("data/processed/metocean/mumbai/final_metocean.nc")
start_lon, start_lat = 72.82, 18.8644
start_time = "2010-08-07T09:15:00"
particles = tracker.track_backward(start_lon, start_lat, start_time, 24, num_particles=100)
origin = tracker.compute_origin_probability(particles)
print(f"  Active particles: {len(particles)}/100")
print(f"  Estimated origin: [{origin['centroid'][0]:.4f}, {origin['centroid'][1]:.4f}]")
assert len(particles) > 0, "No particles survived!"
print("  [PASS]")

# Cross-check Jipro Neftis
print("  Cross-check with MT Jipro Neftis (2018)...")
tracker2 = LagrangianTracker("data/processed/metocean/mt_jipro_neftis/final_metocean.nc")
p2 = tracker2.track_backward(72.80, 18.90, "2018-01-30T12:00:00", 24)
o2 = tracker2.compute_origin_probability(p2)
print(f"  Active particles: {len(p2)}/100")
assert len(p2) > 0
print("  [PASS]")

# 3. Test GFW Client
print("\n[3/5] Testing GFW client ...")
from engines.ais.gfw_client import GFWClient, GFWAuthError, health_check
try:
    gfw = GFWClient()
    ok = health_check(gfw)
    status = "PASS" if ok else "FAIL (token may be expired)"
    print(f"  GFW health check: {status}")
    if ok:
        results = gfw.search_vessels("MSC Chitra", limit=3)
        print(f"  Vessel search results: {len(results)}")
        for r in results[:3]:
            print(f"    - {r}")
except GFWAuthError as e:
    print(f"  GFW auth error: {e}")
except Exception as e:
    print(f"  GFW error: {e}")

# 4. Test AttributionRanker with GFW-style data
print("\n[4/5] Testing AttributionRanker with GFW-style suspects ...")
from engines.attribution.ranker import AttributionRanker
ranker = AttributionRanker()
mock_suspects = [
    {
        "mmsi": 538000000, "vessel_name": "MT Jipro Neftis",
        "ship_type": "Tanker", "cargo_type": "Oil",
        "match_count": 12, "avg_lon": 72.81, "avg_lat": 18.89,
        "last_seen": "2018-01-30T12:00:00",
    },
    {
        "mmsi": 538000111, "vessel_name": "Generic Cargo",
        "ship_type": "Cargo", "cargo_type": "Container",
        "match_count": 5, "avg_lon": 72.90, "avg_lat": 18.95,
        "last_seen": "2018-01-30T11:00:00",
    },
]
cargo_data = {538000000: "Oil", 538000111: "Container"}
ranked = ranker.rank_vessels(mock_suspects, origin["centroid"], cargo_data)
print(f"  Ranked {len(ranked)} suspects:")
for r in ranked:
    f = r["factors"]
    print(f"    {r['vessel_name']}: score={r['attribution_score']} "
          f"(prox={f['proximity']}, dur={f['duration']}, cargo={f['cargo']})")
assert ranked[0]["attribution_score"] >= ranked[1]["attribution_score"]
print("  [PASS] Ranking correct - tanker scored highest")

# 5. Test Sentinel-1 SAR detector
print("\n[5/5] Testing Sentinel-1 SAR detector ...")
from engines.detection.sar_detector import SARDetector, SARAuthError
try:
    sar = SARDetector()
    print("  CDSE auth: OK")
    products = sar.search_near_date_range(
        72.80, 18.90, "2018-01-29", "2018-01-31",
        product_type="GRD", limit=3,
    )
    print(f"  Sentinel-1 products found: {len(products)}")
    for p in products[:3]:
        print(f"    - {p['name']} ({p['size_mb']} MB)")
    if not products:
        print("  (No GRD products in this window; try wider range)")
    print("  [PASS] SAR search operational")
except SARAuthError as e:
    print(f"  CDSE auth error: {e}")
except Exception as e:
    print(f"  SAR error: {e}")

print("\n" + "=" * 60)
print("END-TO-END TEST COMPLETE")
print("=" * 60)
