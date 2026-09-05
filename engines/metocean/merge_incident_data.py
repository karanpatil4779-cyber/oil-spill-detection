import xarray as xr
from pathlib import Path

WIND_FILE = Path("data/processed/metocean/mumbai/mumbai_wind_fields.nc")
WAVE_FILE = Path("data/processed/metocean/mumbai/cropped_data_stream-wave_stepType-instant.nc")
FINAL_FILE = Path("data/processed/metocean/mumbai/mumbai_incident_metocean_final.nc")

def main():
    print("Merging wind and wave data...")
    ds_wind = xr.open_dataset(WIND_FILE)
    ds_wave = xr.open_dataset(WAVE_FILE)
    
    # Merge the datasets
    # We use combine_by_coords or simple merge
    merged = xr.merge([ds_wind, ds_wave])
    
    merged.to_netcdf(FINAL_FILE)
    print(f"Final merged incident data saved to {FINAL_FILE}")
    
    ds_wind.close()
    ds_wave.close()

if __name__ == "__main__":
    main()
