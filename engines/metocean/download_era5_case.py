"""Download a small ERA5 metocean subset for an oil-spill incident replay."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import cdsapi


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CDSAPI_RC = PROJECT_ROOT / ".cdsapirc"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "metocean" / "era5"

PILOT_AREA_NWSE = [23.8, 68.0, 18.0, 73.8]  # north, west, south, east
DEFAULT_VARIABLES = [
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "mean_sea_level_pressure",
    "mean_wave_direction",
    "mean_wave_period",
    "sea_surface_temperature",
    "significant_height_of_combined_wind_waves_and_swell",
    "total_precipitation",
]

DEFAULT_TIMES = [
    "00:00",
    "01:00",
    "02:00",
    "03:00",
    "04:00",
    "05:00",
    "06:00",
    "07:00",
    "08:00",
    "09:00",
    "10:00",
    "11:00",
    "12:00",
    "13:00",
    "14:00",
    "15:00",
    "16:00",
    "17:00",
    "18:00",
    "19:00",
    "20:00",
    "21:00",
    "22:00",
    "23:00",
]


def _ensure_cds_config() -> None:
    os.environ.setdefault("CDSAPI_RC", str(DEFAULT_CDSAPI_RC))
    rc_path = Path(os.environ["CDSAPI_RC"])

    if not rc_path.exists():
        raise FileNotFoundError(f"CDS config not found: {rc_path}")

    content = rc_path.read_text(encoding="utf-8")
    if "<PERSONAL-ACCESS-TOKEN>" in content:
        raise ValueError(
            f"{rc_path} still contains the placeholder token. Replace it with your CDS personal access token."
        )


def build_request(year: str, month: str, days: list[str]) -> dict:
    return {
        "product_type": ["reanalysis"],
        "variable": DEFAULT_VARIABLES,
        "year": [year],
        "month": [month],
        "day": days,
        "time": DEFAULT_TIMES,
        "area": PILOT_AREA_NWSE,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download the ERA5 weather subset for the MSC Chitra Mumbai oil-spill replay."
    )
    parser.add_argument(
        "--days",
        nargs="+",
        default=["07", "08", "09", "10"],
        help="Month days to download, for example: --days 07 08",
    )
    parser.add_argument(
        "--year",
        default="2010",
        help="Incident year to download.",
    )
    parser.add_argument(
        "--month",
        default="08",
        help="Incident month to download.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for the downloaded NetCDF and request metadata.",
    )
    args = parser.parse_args()

    _ensure_cds_config()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = "reanalysis-era5-single-levels"
    request = build_request(args.year, args.month, args.days)
    target = output_dir / (
        f"era5_msc_chitra_{args.year}_{args.month}_{args.days[0]}_{args.days[-1]}"
        "_gujarat_mumbai.nc"
    )
    metadata_target = target.with_suffix(".request.json")

    metadata_target.write_text(
        json.dumps(
            {
                "incident_id": "msc_chitra_khalijia3_mumbai_2010",
                "dataset": dataset,
                "target": str(target),
                "request": request,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Downloading ERA5 subset to: {target}")
    print(f"Request metadata written to: {metadata_target}")
    client = cdsapi.Client()
    client.retrieve(dataset, request, str(target))


if __name__ == "__main__":
    main()
