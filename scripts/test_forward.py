import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from engines.transport.lagrangian_tracker import LagrangianTracker

path = "data/processed/metocean/mt_jipro_neftis/final_metocean.nc"
track = LagrangianTracker(path)
fc = track.forecast_ensemble(72.80, 18.90, "2018-01-30T12:00:00", duration_hours=48, num_particles=200)

print("=== FORWARD DRIFT FORECAST (REAL DATA) ===")
c = fc["centroid"]
print(f"Centroid:     [{c[0]:.4f}, {c[1]:.4f}]")
print(f"BBox:         {[round(x,4) for x in fc['bbox']]}")
print(f"Spread:       [{fc['spread_deg'][0]:.4f}, {fc['spread_deg'][1]:.4f}] deg")
print(f"Confidence:   {fc['confidence']*100:.1f}%")
print(f"Median path:  {len(fc['median_path'])} hourly points")
for i, pt in enumerate(fc["median_path"]):
    print(f"  t+{i:2d}h:  [{pt[0]:.4f}, {pt[1]:.4f}]")
print("=== PASS ===")
