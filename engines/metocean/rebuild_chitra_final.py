"""Rebuild the Mumbai/Chitra final_metocean.nc preserving u10/v10 and merging CMEMS currents.

The old merge (merge_incident_data.py) only produced wind_speed / wind_direction
and dropped the original u10 / v10 components, plus it lacked ocean currents.
This script rebuilds the merged archive from:
  1. Raw ERA5 operational wind file (u10, v10, sst, msl)  -- cropped to Mumbai bbox
  2. Raw CMEMS currents file (uo, vo)                     -- cropped, surface layer

The result is a single final_metocean.nc that the LagrangianTracker can use
with both wind and current forcing.
"""

import xarray as xr
import numpy as np
from pathlib import Path

NORTH, SOUTH, WEST, EAST = 23.8, 18.0, 68.0, 73.8

PROJECT = Path(__file__).resolve().parents[2]


def _clean_ds(ds):
    for name in ("expver", "number"):
        if name in ds.coords:
            ds = ds.drop_vars(name)
    return ds


def _crop(ds, north, south, west, east):
    ds = _clean_ds(ds)
    cropped = ds.sel(latitude=slice(north, south), longitude=slice(west, east))
    if cropped.sizes.get("latitude", 0) == 0:
        cropped = ds.sel(latitude=slice(south, north), longitude=slice(west, east))
    return _clean_ds(cropped)


def rebuild_chitra(incident_id="msc_chitra_khalijia3_mumbai_2010"):
    raw_era5 = PROJECT / "data" / "raw" / "metocean" / "era5"
    raw_cmems = PROJECT / "data" / "raw" / "metocean" / "cmems" / incident_id
    proc_dir = PROJECT / "data" / "processed" / "metocean" / "mumbai"
    proc_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Wind from ERA5 ────────────────────────────────────────────────
    # The raw oper file contains u10, v10, sst, msl at full global resolution.
    wind_src = raw_era5 / "data_stream-oper_stepType-instant.nc"
    if not wind_src.exists():
        print(f"[SKIP] ERA5 wind file not found: {wind_src}")
        return

    print(f"[1/3] Loading ERA5 wind from {wind_src.name} ...")
    ds_wind_raw = xr.open_dataset(wind_src)
    ds_wind = _crop(ds_wind_raw, NORTH, SOUTH, WEST, EAST)
    ds_wind_raw.close()

    # Keep u10, v10 plus derived fields
    u10 = ds_wind["u10"]
    v10 = ds_wind["v10"]
    wind_speed = np.sqrt(u10**2 + v10**2)
    wind_dir = (np.rad2deg(np.arctan2(u10, v10)) + 180) % 360

    wind_ds = xr.Dataset({
        "u10": u10,
        "v10": v10,
        "wind_speed": wind_speed,
        "wind_direction": wind_dir,
    }, coords=ds_wind.coords)

    if "sst" in ds_wind:
        wind_ds["sst"] = ds_wind["sst"]
    if "msl" in ds_wind:
        wind_ds["msl"] = ds_wind["msl"]

    # Rename valid_time -> time for consistency
    if "valid_time" in wind_ds.coords and "time" not in wind_ds.coords:
        wind_ds = wind_ds.rename({"valid_time": "time"})

    wind_ds = _clean_ds(wind_ds)
    print(f"  Wind: {list(wind_ds.data_vars)}, dims={dict(wind_ds.sizes)}")

    # ── 2. Wave from ERA5 ────────────────────────────────────────────────
    wave_src = raw_era5 / "data_stream-wave_stepType-instant.nc"
    wave_ds = None
    if wave_src.exists():
        print(f"[2/3] Loading ERA5 wave from {wave_src.name} ...")
        ds_wave_raw = xr.open_dataset(wave_src)
        wave_ds = _crop(ds_wave_raw, NORTH, SOUTH, WEST, EAST)
        ds_wave_raw.close()
        wave_ds = _clean_ds(wave_ds)
        if "valid_time" in wave_ds.coords and "time" not in wave_ds.coords:
            wave_ds = wave_ds.rename({"valid_time": "time"})
        print(f"  Wave: {list(wave_ds.data_vars)}")
    else:
        print("[2/3] No wave file found, skipping.")

    # ── 3. CMEMS currents ────────────────────────────────────────────────
    cmems_files = list(raw_cmems.glob("currents_*.nc"))
    currents_ds = None
    if cmems_files:
        cmems_path = cmems_files[0]
        print(f"[3/3] Loading CMEMS currents from {cmems_path.name} ...")
        ds_c = xr.open_dataset(cmems_path)
        cropped_c = _crop(ds_c, NORTH, SOUTH, WEST, EAST)
        ds_c.close()

        if "depth" in cropped_c.dims:
            cropped_c = cropped_c.isel(depth=0).drop_vars("depth", errors="ignore")

        if "time" not in cropped_c.coords and "valid_time" in cropped_c.coords:
            cropped_c = cropped_c.rename({"valid_time": "time"})

        # Interpolate currents onto wind grid and broadcast daily-mean across hours
        wtime = wind_ds["time"]
        cropped_c = cropped_c.interp(
            latitude=wind_ds["latitude"],
            longitude=wind_ds["longitude"],
            kwargs={"fill_value": None},
        )
        wtime_vals = np.asarray(wtime.values)
        n_w = wtime.size
        new_vars = {}
        for var in ("uo", "vo"):
            if var in cropped_c:
                arr2d = cropped_c[var].isel(time=0)
                data = np.broadcast_to(arr2d.values, (n_w,) + arr2d.shape)
                new_vars[var] = (("time", "latitude", "longitude"),
                                 np.asarray(data).copy())
        if new_vars:
            currents_ds = xr.Dataset(
                new_vars,
                coords={"time": wtime_vals, "latitude": wind_ds["latitude"],
                        "longitude": wind_ds["longitude"]},
            )
        else:
            currents_ds = cropped_c
        currents_ds = _clean_ds(currents_ds)
        print(f"  Currents: {list(currents_ds.data_vars)}")
    else:
        print("[3/3] No CMEMS currents found.")

    # ── 4. Merge everything ──────────────────────────────────────────────
    datasets = [wind_ds]
    if wave_ds is not None:
        datasets.append(wave_ds)
    if currents_ds is not None:
        datasets.append(currents_ds)

    merged = xr.merge(datasets, join="outer")
    merged = _clean_ds(merged)

    out_path = proc_dir / "final_metocean.nc"
    merged.to_netcdf(out_path, engine="netcdf4")
    print(f"\n[OK] Saved {out_path}")
    print(f"  Variables: {list(merged.data_vars)}")
    print(f"  Dimensions: {dict(merged.sizes)}")

    critical = {"u10", "v10", "uo", "vo"}
    present = set(merged.data_vars)
    missing = critical - present
    if missing:
        print(f"  [WARN] Missing: {missing}")
    else:
        print(f"  [OK] All critical variables present: {critical}")

    # Also save a wind-only file preserving u10/v10
    wind_only_path = proc_dir / "wind_fields.nc"
    wind_ds.to_netcdf(wind_only_path, engine="netcdf4")
    print(f"  Saved wind_fields.nc with u10, v10 preserved")

    for ds in datasets:
        ds.close()

    return merged


if __name__ == "__main__":
    rebuild_chitra()
