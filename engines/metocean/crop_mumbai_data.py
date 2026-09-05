import xarray as xr
from pathlib import Path
import os

# Coordinates for the Mumbai Coast (North, West, South, East)
NORTH = 23.8
SOUTH = 18.0
WEST = 68.0
EAST = 73.8

INPUT_DIR = Path("data/raw/metocean/era5")
OUTPUT_DIR = Path("data/processed/metocean/mumbai")

def crop_file(file_path):
    print(f"Processing {file_path.name}...")
    ds = xr.open_dataset(file_path)
    
    # ERA5 latitudes are usually sorted from North to South (90 down to -90)
    # We slice from North (max) to South (min)
    cropped = ds.sel(
        latitude=slice(NORTH, SOUTH), 
        longitude=slice(WEST, EAST)
    )
    
    # If the slice is empty, it might be because coordinates are sorted differently
    if cropped.latitude.size == 0 or cropped.longitude.size == 0:
        print(f"  Warning: Standard slice empty for {file_path.name}, trying opposite order...")
        cropped = ds.sel(
            latitude=slice(SOUTH, NORTH), 
            longitude=slice(WEST, EAST)
        )

    output_path = OUTPUT_DIR / f"cropped_{file_path.name}"
    cropped.to_netcdf(output_path)
    print(f"  Saved to {output_path}")
    ds.close()

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = list(INPUT_DIR.glob("*.nc"))
    
    if not files:
        print("No input files found!")
        return

    for f in files:
        crop_file(f)
    print("\nAll files cropped successfully.")

if __name__ == "__main__":
    main()
