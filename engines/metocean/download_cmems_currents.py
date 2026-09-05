import os
import sys
import copernicusmarine
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

USERNAME = os.getenv("CMEMS_USERNAME")
PASSWORD = os.getenv("CMEMS_PASSWORD")

# Product: Global Ocean Physics Reanalysis
# Variable: uo (eastward velocity), vo (northward velocity)
PRODUCT = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
VARIABLES = ["uo", "vo"]

def main(year, month, day, output_dir):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    start_date = f"{year}-{month:02d}-{day:02d}T00:00:00"
    end_date = f"{year}-{month:02d}-{day:02d}T23:59:59"

    print(f"Downloading ocean currents for {start_date}...")

    try:
        copernicusmarine.subset(
            dataset_id=PRODUCT,
            variables=VARIABLES,
            start_datetime=start_date,
            end_datetime=end_date,
            minimum_longitude=68.0,
            maximum_longitude=73.8,
            minimum_latitude=18.0,
            maximum_latitude=23.8,
            username=USERNAME,
            password=PASSWORD,
            output_directory=str(output_path),
            output_filename=f"currents_{year}_{month:02d}_{day:02d}.nc"
        )
        print(f"Successfully downloaded currents to {output_path}")
    except Exception as e:
        print(f"Error downloading CMEMS data: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python download_cmems_currents.py <year> <month> <day> <output_dir>")
        sys.exit(1)

    main(int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
