import xarray as xr
import numpy as np
from pathlib import Path

INPUT_FILE = Path("data/processed/metocean/mumbai/cropped_data_stream-oper_stepType-instant.nc")
OUTPUT_FILE = Path("data/processed/metocean/mumbai/mumbai_wind_fields.nc")

def main():
    print(f"Loading cropped data from {INPUT_FILE}...")
    ds = xr.open_dataset(INPUT_FILE)
    
    u = ds['u10']
    v = ds['v10']
    
    # Calculate Wind Speed
    wind_speed = np.sqrt(u**2 + v**2)
    
    # Calculate Wind Direction (Meteorological: direction FROM which wind blows)
    # atan2(u, v) gives angle from North (v-axis)
    # We add 180 to get the "FROM" direction
    wind_dir = (np.rad2deg(np.arctan2(u, v)) + 180) % 360
    
    # Create a new dataset with the processed fields
    processed_ds = xr.Dataset(
        {
            "wind_speed": (["valid_time", "latitude", "longitude"], wind_speed.values),
            "wind_direction": (["valid_time", "latitude", "longitude"], wind_dir.values),
        },
        coords=ds.coords
    )
    
    # Copy other useful variables
    processed_ds['sst'] = ds['sst']
    processed_ds['msl'] = ds['msl']
    
    processed_ds.to_netcdf(OUTPUT_FILE)
    print(f"Processed wind fields saved to {OUTPUT_FILE}")
    ds.close()

if __name__ == "__main__":
    main()
