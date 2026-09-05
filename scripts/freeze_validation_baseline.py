"""Freeze the transport-validation baseline.

Reruns the backward-Lagrangian origin-error computation for every benchmark
incident and persists the results to:
  - data/validation/origin_error_baseline.json
  - data/validation/origin_error_baseline.csv
with per-incident origin coordinates, errors, robustness notes and aggregate
(mean / median / RMSE) metrics.

Run from the project root:
    python -m scripts.freeze_validation_baseline   (or python scripts/freeze_validation_baseline.py)
"""
import csv
import json
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

# NOTE: this sandbox mis-resolves ABSOLUTE windows paths inside script-launched
# processes (Path.exists() wrongly returns False). Relative forward-slash paths
# resolve correctly, so we build every path relative to the CWD (= project root).
PROJECT = Path.cwd()

sys.path.insert(0, str(PROJECT))
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

BENCH = Path("data/benchmarks/incidents.json")
OUT_DIR = Path("data/validation")

INCIDENT_FILES = {
    "msc_chitra_khalijia3_mumbai_2010": "data/processed/meteocean/msc_chitra_khalijia3_mumbai_2010/final_metocean.nc",
    "mt_jipro_neftis_mumbai_2018": "data/processed/meteocean/mt_jipro_neftis/final_metocean.nc",
    "gal_constructor_mumbai_2021": "data/processed/meteocean/mumbai/final_metocean.nc",
    "ennore_chennai_coastal_2017": "data/processed/meteocean/ennore_chennai_coastal_2017/final_metocean.nc",
    "kandla_gulf_kutch_2023": "data/processed/meteocean/kandla_gulf_kutch_2023/final_metocean.nc",
}

# Frozen configuration for the baseline (explicit and reproducible).
DURATION_HOURS = 24
N_PARTICLES = 100
SEED = 42

# Triage classification from Phase-1 analysis (expected physical behavior, not
# pipeline bugs). Keyed by incident id.
TRIAGE = {
    "msc_chitra_khalijia3_mumbai_2010": {
        "verdict": "OK",
        "note": "Fresh, weakly-advected spill in moderate current; backtracking reconstructs source within ~17 km.",
    },
    "mt_jipro_neftis_mumbai_2018": {
        "verdict": "OK (reduced active set)",
        "note": "Only ~60/100 particles stay active (limited forcing footprint near Mumbai shelf); error is moderate.",
    },
    "gal_constructor_mumbai_2021": {
        "verdict": "EXPECTED LARGE",
        "note": "Vessel GROUNDED during Cyclone Tauktae (winds ~10 m/s); source not advecting with current, so backtracking a spreading sheen under cyclone wind inherently spreads the origin. Metocean file fixed to 2021-05-14..21.",
    },
    "ennore_chennai_coastal_2017": {
        "verdict": "OK (real advection)",
        "note": "Source sits in a strong northward coastal current (~0.5 m/s); 24 h backward advection legitimately moves the inferred origin ~48-53 km south. Robust across seeds.",
    },
    "kandla_gulf_kutch_2023": {
        "verdict": "OK",
        "note": "Best case; weak currents so backtracking nearly pins the source (~6 km).",
    },
}


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def file_time_range(path):
    if not path.exists():
        return None
    import xarray as xr

    ds = xr.open_dataset(path)
    tname = "time" if "time" in ds.coords else ("valid_time" if "valid_time" in ds.coords else None)
    if tname is None:
        ds.close()
        return None
    t = ds[tname]
    tr = (str(t.values.min()), str(t.values.max()))
    ds.close()
    return tr


def main():
    incidents = json.loads(BENCH.read_text(encoding="utf-8"))
    from engines.transport.lagrangian_tracker import LagrangianTracker

    results = []
    for inc in incidents:
        kid = inc["id"]
        lon_src, lat_src = inc["coordinates"]
        path = Path(INCIDENT_FILES[kid])
        row = {
            "incident": kid,
            "name": inc["incident_name"],
            "source_lon": lon_src,
            "source_lat": lat_src,
            "date": inc["date"],
            "status": "OK",
        }

        if not path.exists():
            row["status"] = "NO_FORCING"
            row["origin_error_km"] = None
            results.append(row)
            continue

        tr = file_time_range(path)
        covers = False
        if tr is not None:
            t0 = np.datetime64(inc["date"])
            covers = t0 >= np.datetime64(tr[0][:10]) and t0 <= np.datetime64(tr[1][:10])
        if not covers:
            row["status"] = "NO_FORCING (date mismatch)"
            row["origin_error_km"] = None
            results.append(row)
            continue

        try:
            np.random.seed(SEED)
            tracker = LagrangianTracker(str(path))
            parts = tracker.track_backward(
                lon_src, lat_src, f"{inc['date']}T00:00:00", DURATION_HOURS, num_particles=N_PARTICLES
            )
            origin = tracker.compute_origin_probability(parts)
            if not parts:
                row["status"] = "NO ACTIVE PARTICLES"
                row["origin_error_km"] = None
                results.append(row)
                continue
            cx, cy = origin["centroid"]
            row["n_active"] = len(parts)
            row["origin_lon"] = round(cx, 4)
            row["origin_lat"] = round(cy, 4)
            row["origin_error_km"] = round(haversine_km(lon_src, lat_src, cx, cy), 2)
            row["std_lon"] = round(origin["std_dev"][0], 4)
            row["std_lat"] = round(origin["std_dev"][1], 4)
        except Exception as e:  # noqa: BLE001
            row["status"] = f"ERROR: {type(e).__name__}: {e}"
            row["origin_error_km"] = None

        tri = TRIAGE.get(kid, {"verdict": "?", "note": ""})
        row["verdict"] = tri["verdict"]
        row["note"] = tri["note"]
        results.append(row)

    # Aggregate over incident rows that produced a numeric error.
    errs = np.array([r["origin_error_km"] for r in results if r["origin_error_km"] is not None], dtype=float)
    agg = {}
    if errs.size:
        agg = {
            "n": int(errs.size),
            "mean_km": round(float(errs.mean()), 2),
            "median_km": round(float(np.median(errs)), 2),
            "rmse_km": round(float(np.sqrt((errs**2).mean())), 2),
            "max_km": round(float(errs.max()), 2),
            "min_km": round(float(errs.min()), 2),
        }

    payload = {
        "description": "Transport backward-Lagrangian origin-error validation baseline.",
        "config": {
            "duration_hours": DURATION_HOURS,
            "num_particles": N_PARTICLES,
            "seed": SEED,
            "detection_time": "00:00 UTC of incident date",
        },
        "aggregate": agg,
        "incidents": results,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "origin_error_baseline.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    with open(OUT_DIR / "origin_error_baseline.csv", "w", newline="", encoding="utf-8") as f:
        keys = ["incident", "name", "date", "status", "verdict", "source_lon", "source_lat",
                "n_active", "origin_lon", "origin_lat", "origin_error_km", "std_lon", "std_lat", "note"]
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)

    print("=== Origin-error baseline (frozen) ===")
    print(f"{'incident':40s} {'status':26s} {'orig_err_km':>11s}")
    for r in results:
        print(f"{r['incident']:40s} {r['status']:26s} {str(r['origin_error_km']):>11s}")
    print("\nAggregate:", agg)
    print("Wrote:", OUT_DIR / "origin_error_baseline.json")
    print("Wrote:", OUT_DIR / "origin_error_baseline.csv")


if __name__ == "__main__":
    main()
