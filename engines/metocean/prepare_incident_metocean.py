"""Prepare incident-scoped ERA5 + CMEMS data and rebuild each incident's own
final_metocean.nc so no incident shares another's forcing data.

This is the "download incident-specific data for all incidents in benchmarks"
step, ensuring each incident has its own self-contained metocean archive that
feeds the Lagrangian transport stage.
"""

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT = Path(__file__).resolve().parents[2]
BENCH = PROJECT / "data" / "benchmarks" / "incidents.json"

# ERA5 single-levels area: north, west, south, east
ERAS_AREA = [23.8, 66.0, 12.0, 81.0]

ERA5_VARS = [
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "mean_sea_level_pressure",
    "significant_height_of_combined_wind_waves_and_swell",
    "sea_surface_temperature",
]

CMEMS_PRODUCT = "cmems_mod_glo_phy_my_0.083deg_P1D-m"


def _incident_dates(inc):
    """Return (start, end) forcing window strings derived from incident date.

    The transport stage back-tracks particles for up to ~48h, so the forcing
    data must start at least one day BEFORE the incident and extend one day
    AFTER — otherwise particles immediately leave the data domain.
    """
    import datetime as dt
    date = datetime_from(inc["date"])
    start = date - dt.timedelta(days=1)
    end = date + dt.timedelta(days=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def datetime_from(yyyymmdd: str):
    import datetime as dt
    return dt.datetime.strptime(yyyymmdd, "%Y-%m-%d")


def _day_list(start_date: str, end_date: str):
    """List of YYYY-MM-DD strings over [start_date, end_date] inclusive."""
    import datetime as dt
    start = datetime_from(start_date)
    end = datetime_from(end_date)
    days = []
    cur = start
    while cur <= end:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += dt.timedelta(days=1)
    return days


def _download_era5_incident(inc, start_date=None, end_date=None, bbox=None, out_dir=None,
                            force=False):
    """Download ERA5 wind/wave for one incident into its own folder.

    If start_date/end_date/bbox are given they override the incident-derived
    window and the module-global ERAS_AREA respectively. bbox is
    [lat_south, lon_west, lat_north, lon_east]. force=True redownloads even if
    data is already present.
    """
    inc_id = inc["id"]
    start_date, end_date = start_date or _incident_dates(inc)[0], end_date or _incident_dates(inc)[1]
    out_dir = Path(out_dir) if out_dir else PROJECT / "data" / "raw" / "metocean" / "era5" / inc_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Already have data? skip (unless force or an explicit window is requested).
    if not force and any(out_dir.rglob("*.nc")):
        print(f"[SKIP] ERA5 already present for {out_dir.name}")
        return

    days = _day_list(start_date, end_date)
    years = sorted({d[:4] for d in days})
    months = sorted({d[5:7] for d in days})
    day_nums = sorted({d[8:10] for d in days})

    if not (PROJECT / ".cdsapirc").exists():
        print(f"[WARN] No .cdsapirc found for {inc_id} — ERA5 download skipped")
        return

    area = ERAS_AREA
    if bbox:
        lat_s, lon_w, lat_n, lon_e = bbox
        area = [lat_n, lon_w, lat_s, lon_e]

    import cdsapi
    os.environ.setdefault("CDSAPI_RC", str(PROJECT / ".cdsapirc"))
    client = cdsapi.Client()

    request = {
        "product_type": ["reanalysis"],
        "variable": ERA5_VARS,
        "year": years,
        "month": months,
        "day": day_nums,
        "time": ["00:00", "06:00", "12:00", "18:00"],
        "area": area,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    target = out_dir / f"era5_{inc_id}_{start_date}_{end_date}.nc"
    print(f"[ {inc_id}] downloading ERA5 -> {target.name} ({','.join(days)}) area={area}")
    client.retrieve("reanalysis-era5-single-levels", request, str(target))
    print(f"[ {inc_id}] ERA5 DONE")

    # CDS may return a zip of netcdf streams even with unarchived format in
    # newer cdsapi versions; extract in place so the rebuild step can read it.
    if zipfile.is_zipfile(target):
        import zipfile as _zf
        with _zf.ZipFile(target) as z:
            z.extractall(out_dir)
        target.unlink(missing_ok=True)
        print(f"[ {inc_id}] extracted ERA5 streams to {out_dir.name}/")


def _download_cmems_incident(inc, start_date=None, end_date=None, bbox=None, out_dir=None,
                             force=False):
    """Download CMEMS currents for one incident into its own folder."""
    inc_id = inc["id"]
    start_date, end_date = start_date or _incident_dates(inc)[0], end_date or _incident_dates(inc)[1]
    out_dir = Path(out_dir) if out_dir else PROJECT / "data" / "raw" / "metocean" / "cmems" / inc_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if not force and any(out_dir.glob("currents_*.nc")):
        print(f"[SKIP] CMEMS already present for {out_dir.name}")
        return

    if bbox:
        lat_s, lon_w, lat_n, lon_e = bbox
        min_lon, max_lon = lon_w, lon_e
        min_lat, max_lat = lat_s, lat_n
    else:
        min_lon, max_lon, min_lat, max_lat = 66.0, 81.0, 12.0, 23.8

    import copernicusmarine
    fname = f"currents_{start_date}_{end_date}.nc"
    print(f"[ {inc_id}] downloading CMEMS currents -> {fname} "
          f"({start_date}..{end_date}) lon[{min_lon},{max_lon}] lat[{min_lat},{max_lat}]")
    try:
        copernicusmarine.subset(
            dataset_id=CMEMS_PRODUCT,
            variables=["uo", "vo"],
            start_datetime=f"{start_date}T00:00:00",
            end_datetime=f"{end_date}T23:59:59",
            minimum_longitude=min_lon,
            maximum_longitude=max_lon,
            minimum_latitude=min_lat,
            maximum_latitude=max_lat,
            username=os.getenv("CMEMS_USERNAME"),
            password=os.getenv("CMEMS_PASSWORD"),
            output_directory=str(out_dir),
            output_filename=fname,
        )
        print(f"[ {inc_id}] CMEMS DONE -> {out_dir / fname}")
    except Exception as e:
        print(f"[ {inc_id}] CMEMS error: {e}")


def _fill_nan_nearest(arr2d):
    """Fill NaN cells in a 2D field with the nearest valid value.

    CMEMS GLORYS coastal cells are land-masked, so incident coordinates that
    fall on a masked cell would otherwise never see a current and the whole
    incident would drop out of the transport domain. Filling from the nearest
    open-water cell is a reasonable approximation for near-coast transport.
    """
    import numpy as _np
    from scipy import ndimage as _nd
    if not _np.isnan(arr2d).any():
        return arr2d
    if _np.isnan(arr2d).all():
        return _np.zeros_like(arr2d)
    mask = _np.isnan(arr2d)
    idx = _nd.distance_transform_edt(
        mask, return_distances=False, return_indices=True
    )
    return arr2d[tuple(idx)]


def _rebuild_incident(inc, raw_era5=None, raw_cmems=None, final=None):
    """Build incident-specific final_metocean.nc from its ERA5 + CMEMS."""
    import xarray as xr
    import numpy as np

    inc_id = inc["id"]
    raw_era5 = Path(raw_era5) if raw_era5 else PROJECT / "data" / "raw" / "metocean" / "era5" / inc_id
    raw_cmems = Path(raw_cmems) if raw_cmems else PROJECT / "data" / "raw" / "metocean" / "cmems" / inc_id
    if final is None:
        proc = PROJECT / "data" / "processed" / "metocean" / inc_id
        proc.mkdir(parents=True, exist_ok=True)
        final = proc / "final_metocean.nc"
    final = Path(final)
    final.parent.mkdir(parents=True, exist_ok=True)

    era5_nc = list(raw_era5.rglob("*.nc"))
    if not era5_nc:
        print(f"[SKIP] No ERA5 for {inc_id}")
        return

    try:
        # Prefer the atmospheric (operation) stream which carries u10/v10/sst/msl.
        oper = [p for p in era5_nc if "data_stream-oper" in p.name]
        ds = xr.open_dataset(oper[0] if oper else era5_nc[0])
        time_coord = "time" if "time" in ds.coords else "valid_time"
        u10 = ds["u10"]
        v10 = ds["v10"]
        speed = np.sqrt(u10**2 + v10**2)
        wdir = (np.rad2deg(np.arctan2(u10, v10)) + 180) % 360
        wind = xr.Dataset({"u10": u10, "v10": v10, "wind_speed": speed,
                           "wind_direction": wdir}, coords=ds.coords)
        for v in ("sst", "msl"):
            if v in ds:
                wind[v] = ds[v]
        if "valid_time" in wind.coords and "time" not in wind.coords:
            wind = wind.rename({"valid_time": "time"})
        ds.close()

        datasets = [wind]

        cmems_nc = list(raw_cmems.glob("currents_*.nc"))
        if cmems_nc:
            dsc = xr.open_dataset(cmems_nc[0])
            if "depth" in dsc.dims:
                dsc = dsc.isel(depth=0).drop_vars("depth", errors="ignore")
            if "valid_time" in dsc.coords and "time" not in dsc.coords:
                dsc = dsc.rename({"valid_time": "time"})
            # Normalise latitude to ascending order (xarray interp requires
            # strictly increasing coordinates; Copernicus/Mercator grids are
            # sometimes written pointing south-first).
            if "latitude" in dsc.coords and dsc.latitude.size > 1 and dsc.latitude[0] > dsc.latitude[-1]:
                dsc = dsc.isel(latitude=slice(None, None, -1))
            dsc = dsc.interp(latitude=wind["latitude"], longitude=wind["longitude"],
                             kwargs={"fill_value": None})
            n = wind.time.size
            new = {}
            for var in ("uo", "vo"):
                if var in dsc:
                    # CMEMS gives daily-mean currents; interpolate them in time
                    # across the ERA5 6-hourly grid so they vary through the window.
                    interp_t = dsc[var].interp(
                        **{dsc[var].time.dims[0]: wind["time"]}, kwargs={"fill_value": None}
                    ) if "time" in dsc[var].dims else dsc[var]
                    arr = interp_t.values
                    # Land-masked coastal cells become NaN; carry the nearest
                    # open-water value so near-coast incidents stay in-domain.
                    arr = np.stack([_fill_nan_nearest(arr[t]) for t in range(arr.shape[0])])
                    new[var] = (("time", "latitude", "longitude"), arr)
            if new:
                dsc = xr.Dataset(new, coords={"time": wind["time"].values,
                                              "latitude": wind["latitude"],
                                              "longitude": wind["longitude"]})
                datasets.append(dsc)
            dsc.close()

        merged = xr.merge(datasets, join="outer")
        for name in ("expver", "number"):
            if name in merged.coords:
                merged = merged.drop_vars(name)
        merged.to_netcdf(final, engine="netcdf4")
        print(f"[ {inc_id}] final_metocean.nc built: {list(merged.data_vars)}")
    except Exception as e:
        print(f"[ {inc_id}] rebuild error: {e}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Prepare incident-scoped ERA5 + CMEMS metocean forcing and rebuild "
                    "an incident's final_metocean.nc."
    )
    parser.add_argument("incident", nargs="?",
                        help="Incident id from data/benchmarks/incidents.json, or 'all'. "
                             "When given without explicit flags, the incident's own "
                             "date (plus/minus 1 day) and a default bbox are used.")
    parser.add_argument("--incident-id", dest="incident_id",
                        help="Incident id (alternative to positional). Must exist in incidents.json.")
    parser.add_argument("--start-date", help="YYYY-MM-DD forcing window start.")
    parser.add_argument("--end-date", help="YYYY-MM-DD forcing window end.")
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("LAT_S", "LON_W", "LAT_N", "LON_E"),
                        help="lat_south lon_west lat_north lon_east.")
    parser.add_argument("--output", help="Path for the rebuilt final_metocean.nc "
                        "(default: data/processed/meteocean/<incident_id>/final_metocean.nc).")
    parser.add_argument("--raw-base", default=None,
                        help="Inject base raw dir (used when --incident-id differs from the "
                             "downloaded folder name, e.g. 'gal_constructor_mumbai_2021' vs the "
                             "stored 'gal_constructor'). A subfolder is appended per source.")
    args = parser.parse_args()

    incidents = json.loads(BENCH.read_text(encoding="utf-8"))

    # Resolve the incident record, preferring the explicit --incident-id, then positional.
    target_id = args.incident_id or args.incident
    if target_id is None or target_id == "all":
        targets = incidents
    else:
        hit = [i for i in incidents if i["id"] == target_id]
        if not hit:
            parser.error(f"incident id '{target_id}' not found in {BENCH}. "
                         f"Available: {[i['id'] for i in incidents]}")
        targets = hit

    for inc in targets:
        inc_id = inc["id"]

        # Explicit window (--start-date given) => force fresh downloads so a
        # stale, narrower window left from an earlier run is not reused.
        force = args.start_date is not None

        # Download into the folder that actually matches the stored data.
        base = Path(args.raw_base) if args.raw_base else PROJECT / "data" / "raw" / "metocean"
        era5_dir = base / "era5" / inc_id
        cmems_dir = base / "cmems" / inc_id
        _download_era5_incident(inc, args.start_date, args.end_date, args.bbox, out_dir=era5_dir, force=force)
        _download_cmems_incident(inc, args.start_date, args.end_date, args.bbox, out_dir=cmems_dir, force=force)
        _rebuild_incident(inc, raw_era5=era5_dir, raw_cmems=cmems_dir, final=args.output)

    print("INCIDENT_METOCEAN_PREP_COMPLETE")


if __name__ == "__main__":
    main()
