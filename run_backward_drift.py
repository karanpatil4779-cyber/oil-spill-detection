"""Fast backward Lagrangian drift for GAL Constructor 2021 (within metocean domain)."""

import sys, time
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
import xarray as xr

METOCEAN = "data/processed/metocean/mumbai/final_metocean.nc"
# Incident grounding date May 17; data spans May 14-21 -> track 17 -> 14
LON, LAT = 72.7000, 19.8000
START_TIME = "2021-05-17T12:00:00"
DURATION_HOURS = 72
NUM_PARTICLES = 400

t0 = time.time()

# Load small grid fully into numpy
ds = xr.open_dataset(METOCEAN)
times = ds.time.values.astype("datetime64[h]").astype(np.int64) / 3600e9
lons = ds.longitude.values
lats = ds.latitude.values
uo = ds.uo.values          # (time, lat, lon)
vo = ds.vo.values
u10 = ds.u10.values
v10 = ds.v10.values
ds.close()

def velocity(lon, lat, timestamp):
    """Nearest-neighbour bilinear-free lookup on the small grid."""
    ti = np.argmin(np.abs(times - timestamp))
    li = np.argmin(np.abs(lons - lon))
    ai = np.argmin(np.abs(lats - lat))
    u = uo[ti, ai, li] + 0.03 * u10[ti, ai, li]
    v = vo[ti, ai, li] + 0.03 * v10[ti, ai, li]
    return u, v

t_start = pd.to_datetime(START_TIME).value / 1e9
# Unique hourly timestamps backward
time_hours = np.arange(0, DURATION_HOURS + 1)
ts_int = int(t_start)

particles = np.full((NUM_PARTICLES, 2), [LON, LAT], dtype=float)
active = np.ones(NUM_PARTICLES, dtype=bool)
rng = np.random.default_rng(42)

snap = [(1e18, [LON, LAT])]

for hour in range(1, DURATION_HOURS + 1):
    # current (going backward) simulation timestamp
    sim_t = ts_int - (hour - 1) * 3600
    lon = particles[:, 0]
    lat = particles[:, 1]
    for i in range(NUM_PARTICLES):
        if not active[i]:
            continue
        u, v = velocity(lon[i], lat[i], sim_t)
        if np.isnan(u) or np.isnan(v):
            active[i] = False
            continue
        dx = -u * 3600 / (111000 * np.cos(np.radians(lat[i]))) + rng.normal(0, 0.015)
        dy = -v * 3600 / 111000 + rng.normal(0, 0.015)
        particles[i, 0] += dx
        particles[i, 1] += dy
    if hour % 12 == 0 and active.any():
        snap.append((hour, [float(np.median(particles[active, 0])),
                            float(np.median(particles[active, 1]))]))

print(f"Active particles: {active.sum()} / {NUM_PARTICLES}  ({time.time()-t0:.1f}s)")

p = particles[active]
clon, clat = p[:, 0].mean(), p[:, 1].mean()
print(f"\n--- ORIGIN ESTIMATE ---")
print(f"Centroid : ({clon:.4f}, {clat:.4f})")
print(f"BBox     : [{p[:,0].min():.4f}, {p[:,1].min():.4f}, {p[:,0].max():.4f}, {p[:,1].max():.4f}]")
print(f"Std dev  : ({p[:,0].std():.4f}, {p[:,1].std():.4f})")
print(f"Lon spread: {p[:,0].max()-p[:,0].min():.4f} deg")
print(f"Lat spread: {p[:,1].max()-p[:,1].min():.4f} deg")

print(f"\n--- BACKWARD DRIFT PATH (every 12h) ---")
print(f"{'Back (h)':>8} {'Time UTC':<18} {'Lon':>10} {'Lat':>10}")
print("-" * 50)
for hour, pos in reversed(snap):
    if hour == 1e18:
        tt = ts_int
        hour = 0
    else:
        tt = ts_int - hour * 3600
    ts = pd.Timestamp(tt, unit="s").strftime("%Y-%m-%d %H:%M")
    print(f"{hour:>8} {ts:<18} {pos[0]:>10.4f} {pos[1]:>10.4f}")

print(f"\nTotal: {time.time()-t0:.1f}s")
