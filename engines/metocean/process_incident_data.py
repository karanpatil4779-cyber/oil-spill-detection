import xarray as xr
import numpy as np
from pathlib import Path

NORTH, SOUTH, WEST, EAST = 23.8, 18.0, 68.0, 73.8


def _find_cmems_currents(raw_dir: Path, incident_id: str) -> Path | None:
    """Locate CMEMS currents NetCDF for this incident.

    CMEMS files live under data/raw/metocean/cmems/<incident_id>/ while the
    ERA5 files live under data/raw/metocean/era5/<incident_id>/extracted/.
    """
    metocean_root = raw_dir.parents[2]            # data/raw/metocean
    cmems_base = metocean_root / "cmems" / incident_id
    if cmems_base.exists():
        nc_files = list(cmems_base.glob("currents_*.nc"))
        if nc_files:
            return nc_files[0]

    for p in metocean_root.rglob("currents_*.nc"):
        if incident_id in str(p):
            return p
    return None


def _clean_ds(ds):
    """Drop non-numeric / auxiliary coordinates that netCDF4 cannot serialise
    and ensure all coordinate dtypes are netCDF4-safe."""
    for name in ("expver", "number"):
        if name in ds.coords:
            ds = ds.drop_vars(name)
    return ds


def _safe_write(ds, path):
    """Write a dataset to netCDF4, stripping any problematic coords."""
    ds = _clean_ds(ds)
    ds.to_netcdf(path, engine="netcdf4")


def _crop_dataset(ds, north, south, west, east):
    """Crop a dataset to a bounding box, handling both lat ordering conventions."""
    ds = _clean_ds(ds)
    cropped = ds.sel(
        latitude=slice(north, south),
        longitude=slice(west, east),
    )
    if cropped.sizes.get("latitude", 0) == 0:
        cropped = ds.sel(
            latitude=slice(south, north),
            longitude=slice(west, east),
        )
    return _clean_ds(cropped)


def process_metocean(incident_id):
    print(f"--- Processing Metocean for {incident_id} ---")
    raw_dir = Path(f"data/raw/metocean/era5/{incident_id}/extracted")
    proc_dir = Path(f"data/processed/metocean/{incident_id}")
    proc_dir.mkdir(parents=True, exist_ok=True)

    files = list(raw_dir.glob("*.nc"))
    if not files:
        print(f"No ERA5 files found for {incident_id}")
        return

    # ── 1. Wind / weather (instant operational file) ──────────────────────
    def is_wind_file(f):
        return "wave" not in f.name and "accum" not in f.name and (
            "instant" in f.name or "oper" in f.name or "era5" in f.name
        )

    weather_file = next((f for f in files if is_wind_file(f)), None)

    wind_ds = None
    if weather_file:
        ds = xr.open_dataset(weather_file, engine="netcdf4")
        cropped = _crop_dataset(ds, NORTH, SOUTH, WEST, EAST)

        u10 = cropped["u10"]
        v10 = cropped["v10"]
        wind_speed = np.sqrt(u10**2 + v10**2)
        wind_dir = (np.rad2deg(np.arctan2(u10, v10)) + 180) % 360

        wind_ds = xr.Dataset(
            {
                "u10": u10,
                "v10": v10,
                "wind_speed": wind_speed,
                "wind_direction": wind_dir,
            },
            coords=cropped.coords,
        )
        wind_ds = _clean_ds(wind_ds)
        if "sst" in cropped:
            wind_ds["sst"] = cropped["sst"]
        if "msl" in cropped:
            wind_ds["msl"] = cropped["msl"]

        _safe_write(wind_ds, proc_dir / "wind_fields.nc")
        print(f"  Saved wind fields (u10, v10, wind_speed, wind_direction) -> {proc_dir}/wind_fields.nc")
        ds.close()

    # ── 2. Wave data ──────────────────────────────────────────────────────
    wave_file = next((f for f in files if "wave" in f.name), None)
    if wave_file:
        ds_w = xr.open_dataset(wave_file, engine="netcdf4")
        cropped_w = _crop_dataset(ds_w, NORTH, SOUTH, WEST, EAST)
        _safe_write(cropped_w, proc_dir / "wave_fields.nc")
        print(f"  Saved wave fields -> {proc_dir}/wave_fields.nc")
        ds_w.close()

    # ── 3. Ocean currents (CMEMS) ─────────────────────────────────────────
    currents_ds = None
    cmems_path = _find_cmems_currents(raw_dir, incident_id)
    if cmems_path and cmems_path.exists():
        print(f"  Loading CMEMS currents from {cmems_path}")
        ds_c = xr.open_dataset(cmems_path, engine="netcdf4")
        cropped_c = _crop_dataset(ds_c, NORTH, SOUTH, WEST, EAST)

        # Take the surface layer only (depth ~0.49 m)
        if "depth" in cropped_c.dims:
            cropped_c = cropped_c.isel(depth=0).drop_vars("depth", errors="ignore")

        # Standardise the time coordinate to 'time' so it merges cleanly
        if "time" not in cropped_c.coords and "valid_time" in cropped_c.coords:
            cropped_c = cropped_c.rename({"valid_time": "time"})

        # Align currents to the ERA5 wind grid and time axis so the final
        # dataset shares a single set of lat/lon/time coordinates.
        if wind_ds is not None:
            wtime = wind_ds["time"] if "time" in wind_ds.coords else wind_ds["valid_time"]
            wind_ds = _clean_ds(wind_ds)

            # Interpolate currents onto the ERA5 lat/lon grid.
            cropped_c = cropped_c.interp(
                latitude=wind_ds["latitude"],
                longitude=wind_ds["longitude"],
                kwargs={"fill_value": None},
            )

            # Broadcast the daily-mean current across every ERA5 hour.
            # Reduce uo/vo to pure 2-D surface fields (taking the single
            # daily-mean time step), then rebuild with the wind timestamps so
            # both share the same 'time', 'latitude' and 'longitude' axes.
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
                cropped_c = xr.Dataset(
                    new_vars,
                    coords={
                        "time": wtime_vals,
                        "latitude": wind_ds["latitude"],
                        "longitude": wind_ds["longitude"],
                    },
                )

        # Save standalone currents file
        currents_ds = _clean_ds(cropped_c)
        _safe_write(currents_ds, proc_dir / "currents_fields.nc")
        print(f"  Saved currents fields (uo, vo) -> {proc_dir}/currents_fields.nc")
        ds_c.close()
    else:
        print(f"  No CMEMS currents found for {incident_id}")

    # ── 4. Merge into final_metocean.nc ───────────────────────────────────
    try:
        datasets = []
        if wind_ds is not None:
            datasets.append(wind_ds)
        else:
            wpath = proc_dir / "wind_fields.nc"
            if wpath.exists():
                datasets.append(xr.open_dataset(wpath, engine="netcdf4"))

        if currents_ds is not None:
            datasets.append(currents_ds)
        else:
            cpath = proc_dir / "currents_fields.nc"
            if cpath.exists():
                datasets.append(xr.open_dataset(cpath, engine="netcdf4"))

        wpath = proc_dir / "wave_fields.nc"
        if wpath.exists():
            datasets.append(xr.open_dataset(wpath, engine="netcdf4"))

        if not datasets:
            print("  Nothing to merge!")
            return

        # Unify the time coordinate name before merging
        for i, ds in enumerate(datasets):
            if "valid_time" in ds.coords and "time" not in ds.coords:
                datasets[i] = ds.rename({"valid_time": "time"})

        merged = xr.merge(datasets, join="outer")
        merged = _clean_ds(merged)
        _safe_write(merged, proc_dir / "final_metocean.nc")
        print(f"\n  [OK] final_metocean.nc variables: {list(merged.data_vars)}")
        print(f"  [OK] Dimensions: {dict(merged.sizes)}")

        critical = {"u10", "v10", "uo", "vo"}
        present = set(merged.data_vars)
        missing = critical - present
        if missing:
            print(f"  [WARN] Missing critical variables: {missing}")
        else:
            print(f"  [OK] All critical variables present: {critical}")

        for ds in datasets:
            ds.close()
    except Exception as e:
        print(f"  Merge failed: {e}")


if __name__ == "__main__":
    import sys
    incident = sys.argv[1] if len(sys.argv) > 1 else "mt_jipro_neftis"
    process_metocean(incident)
