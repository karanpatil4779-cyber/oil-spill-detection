"""Download CMEMS ocean currents for a set of incidents (REAL data).

Uses the CMEMS_USERNAME / CMEMS_PASSWORD credentials from .env.
"""
import os
import sys
from pathlib import Path
import copernicusmarine
from dotenv import load_dotenv

load_dotenv()

PRODUCT = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
VARS = ["uo", "vo"]
LON = (68.0, 73.8)
LAT = (18.0, 23.8)

# incident_id -> (start_date, end_date) for the currents window
TARGETS = {
    "msc_chitra_khalijia3_mumbai_2010": ("2010-08-06", "2010-08-08"),
    "gal_constructor_mumbai_2021":     ("2021-05-16", "2021-05-18"),
}


def download(incident_id: str, start_date: str, end_date: str):
    out = Path("data/raw/metocean/cmems") / incident_id
    out.mkdir(parents=True, exist_ok=True)
    fname = f"currents_{start_date[:4]}_{start_date[5:7]}_{start_date[8:10]}_{end_date[8:10]}.nc"
    print(f"[{incident_id}] downloading {start_date} -> {end_date} ...", flush=True)
    copernicusmarine.subset(
        dataset_id=PRODUCT,
        variables=VARS,
        start_datetime=f"{start_date}T00:00:00",
        end_datetime=f"{end_date}T23:59:59",
        minimum_longitude=LON[0],
        maximum_longitude=LON[1],
        minimum_latitude=LAT[0],
        maximum_latitude=LAT[1],
        username=os.getenv("CMEMS_USERNAME"),
        password=os.getenv("CMEMS_PASSWORD"),
        output_directory=str(out),
        output_filename=fname,
    )
    print(f"[{incident_id}] DONE -> {out / fname}", flush=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which == "all":
        for inc, (s, e) in TARGETS.items():
            download(inc, s, e)
    else:
        s, e = TARGETS[which]
        download(which, s, e)
    print("ALL_DOWNLOADS_COMPLETE")
