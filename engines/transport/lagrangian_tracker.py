import numpy as np
import xarray as xr
from pathlib import Path
import logging
from typing import Tuple, List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LagrangianTracker:
    """
    Implements a backward-in-time Lagrangian particle tracking model
    to estimate the origin of an oil spill.
    """

    def __init__(self,
                 currents_file: str,
                 wind_file: str = None,
                 wind_drift_coeff: float = 0.03):
        """
        Initialize the tracker with metocean forcing data.

        Args:
            currents_file: Path to the NetCDF file containing ocean currents (uo, vo).
                May be a single merged metocean file that ALSO contains wind
                (u10, v10); in that case wind_file can be omitted.
            wind_file: Optional path to a separate NetCDF file containing wind
                fields (u10, v10). If None and currents_file already contains
                u10/v10, they are read from the same dataset.
            wind_drift_coeff: Coefficient for wind-induced drift (default 3% of wind speed).
        """
        self.ds_curr = xr.open_dataset(currents_file)
        self.wind_drift_coeff = wind_drift_coeff

        # Wind can come from a separate file or from the same merged archive.
        if wind_file:
            self.ds_wind = xr.open_dataset(wind_file)
        elif "u10" in self.ds_curr.data_vars and "v10" in self.ds_curr.data_vars:
            self.ds_wind = self.ds_curr
        else:
            self.ds_wind = None

    def _get_velocity(self, lon: float, lat: float, time: str) -> Tuple[float, float]:
        """
        Interpolate current and wind velocities at a given point and time.
        """
        # Determine time coordinate name
        time_coord = 'time' if 'time' in self.ds_curr.coords else 'valid_time'

        try:
            curr_vals = self.ds_curr.sel(longitude=lon, latitude=lat, **{time_coord: time}, method='nearest')

            # Handle depth dimension if present (take surface layer)
            if 'depth' in curr_vals.dims:
                curr_vals = curr_vals.sel(depth=curr_vals.depth[0])

            # Try multiple possible variable names for currents
            u_ocean = float(curr_vals.uo if 'uo' in curr_vals.data_vars else curr_vals.u if 'u' in curr_vals.data_vars else 0.0)
            v_ocean = float(curr_vals.vo if 'vo' in curr_vals.data_vars else curr_vals.v if 'v' in curr_vals.data_vars else 0.0)
        except Exception as e:
            logger.warning(f"Error extracting current at {lon}, {lat}, {time}: {e}")
            u_ocean, v_ocean = 0.0, 0.0

        # Extract wind drift
        u_wind_drift, v_wind_drift = 0.0, 0.0
        if self.ds_wind:
            wind_time_coord = 'time' if 'time' in self.ds_wind.coords else 'valid_time'
            try:
                wind_vals = self.ds_wind.sel(longitude=lon, latitude=lat, **{wind_time_coord: time}, method='nearest')

                # Try multiple possible variable names for wind
                u_wind = float(wind_vals.u10 if 'u10' in wind_vals.data_vars else wind_vals.u if 'u' in wind_vals.data_vars else 0.0)
                v_wind = float(wind_vals.v10 if 'v10' in wind_vals.data_vars else wind_vals.v if 'v' in wind_vals.data_vars else 0.0)

                u_wind_drift = u_wind * self.wind_drift_coeff
                v_wind_drift = v_wind * self.wind_drift_coeff
            except Exception as e:
                logger.warning(f"Error extracting wind at {lon}, {lat}, {time}: {e}")

        return u_ocean + u_wind_drift, v_ocean + v_wind_drift

    def track_backward(self,
                      start_lon: float,
                      start_lat: float,
                      start_time: str,
                      duration_hours: int,
                      num_particles: int = 100,
                      diffusion_sigma: float = 0.01) -> List[Tuple[float, float]]:
        """
        Perform backward tracking simulation to find potential origins.
        """
        import pandas as pd

        # Convert start_time to datetime
        t_start = pd.to_datetime(start_time)
        time_steps = pd.date_range(end=t_start, periods=duration_hours, freq='h')

        particles = np.array([[start_lon, start_lat] for _ in range(num_particles)])
        active_mask = np.ones(num_particles, dtype=bool)

        logger.info(f"Starting backward tracking for {num_particles} particles...")

        # Loop backward in time
        for t in time_steps:
            t_str = t.strftime('%Y-%m-%dT%H:%M:%S')

            # Calculate velocities for all particles
            for i in range(num_particles):
                if not active_mask[i]:
                    continue

                lon, lat = particles[i]
                u, v = self._get_velocity(lon, lat, t_str)

                # If velocity is NaN, particle went out of bounds
                if np.isnan(u) or np.isnan(v):
                    active_mask[i] = False
                    continue

                # Backward step: position = position - (velocity * delta_t)
                dx = -u * 3600 / (111000 * np.cos(np.radians(lat)))
                dy = -v * 3600 / 111000

                # Add random diffusion
                dx += np.random.normal(0, diffusion_sigma)
                dy += np.random.normal(0, diffusion_sigma)

                particles[i][0] += dx
                particles[i][1] += dy

        # Only return particles that remained active
        return particles[active_mask].tolist()

    def track_forward(self,
                      start_lon: float,
                      start_lat: float,
                      start_time: str,
                      duration_hours: int,
                      num_particles: int = 100,
                      diffusion_sigma: float = 0.01) -> List[Tuple[float, float]]:
        """Perform forward-in-time particle tracking to forecast future drift.

        Mirrors :meth:`track_backward` but steps the integration forward so the
        particle cloud shows where the slick is expected to go over the next
        ``duration_hours``. The sign of advection is reversed (position +=
        velocity * dt) relative to the backward integrator.
        """
        import pandas as pd

        t_start = pd.to_datetime(start_time)
        time_steps = pd.date_range(start=t_start, periods=duration_hours + 1, freq='h')

        particles = np.array([[start_lon, start_lat] for _ in range(num_particles)])
        active_mask = np.ones(num_particles, dtype=bool)

        logger.info(f"Starting forward tracking for {num_particles} particles...")

        for t in time_steps[1:]:  # skip t0; integrate over each following hour
            t_str = t.strftime('%Y-%m-%dT%H:%M:%S')
            for i in range(num_particles):
                if not active_mask[i]:
                    continue
                lon, lat = particles[i]
                u, v = self._get_velocity(lon, lat, t_str)
                if np.isnan(u) or np.isnan(v):
                    active_mask[i] = False
                    continue
                # Forward step: position += velocity * delta_t
                dx = u * 3600 / (111000 * np.cos(np.radians(lat)))
                dy = v * 3600 / 111000
                dx += np.random.normal(0, diffusion_sigma)
                dy += np.random.normal(0, diffusion_sigma)
                particles[i][0] += dx
                particles[i][1] += dy

        return particles[active_mask].tolist()

    def forecast_ensemble(self,
                          start_lon: float,
                          start_lat: float,
                          start_time: str,
                          duration_hours: int = 72,
                          num_particles: int = 300,
                          diffusion_sigma: float = 0.01,
                          percentiles=(10, 50, 90)) -> Dict:
        """Produce a forward-drift forecast with confidence bounds.

        Returns an ensemble summary with the median trajectory, a confidence
        ellipse at the forecast horizon, an ensemble bbox, and the per-hour
        median path so the web map can draw a swept forecast corridor.

        Output keys:
          - centroid: [lon, lat] median position at the end of the horizon
          - median_path: list of [lon, lat] per hour (50th percentile)
          - bbox: [min_lon, min_lat, max_lon, max_lat] of the final ensemble
          - spread_deg: [lon_std, lat_std] at the horizon
          - confidence: fraction of active particles that remained in domain
        """
        import pandas as pd
        t_start = pd.to_datetime(start_time)
        hours = list(range(0, duration_hours + 1))

        # Re-run the integrator once to get the surviving end positions, then
        # store the per-hour median path by integrating progressively.
        # For a robust single trajectory we integrate the full ensemble and
        # also record the hourly median of all particles.
        particles = np.array([[start_lon, start_lat] for _ in range(num_particles)])
        active_mask = np.ones(num_particles, dtype=bool)
        hourly_lons = [[] for _ in hours]
        hourly_lats = [[] for _ in hours]
        hourly_lons[0].extend(particles[active_mask, 0].tolist())
        hourly_lats[0].extend(particles[active_mask, 1].tolist())

        for idx, t in enumerate(pd.date_range(start=t_start, periods=duration_hours + 1, freq='h')[1:]):
            t_str = t.strftime('%Y-%m-%dT%H:%M:%S')
            for i in range(num_particles):
                if not active_mask[i]:
                    continue
                lon, lat = particles[i]
                u, v = self._get_velocity(lon, lat, t_str)
                if np.isnan(u) or np.isnan(v):
                    active_mask[i] = False
                    continue
                dx = u * 3600 / (111000 * np.cos(np.radians(lat)))
                dy = v * 3600 / 111000
                dx += np.random.normal(0, diffusion_sigma)
                dy += np.random.normal(0, diffusion_sigma)
                particles[i][0] += dx
                particles[i][1] += dy
            act = active_mask.copy()
            if act.any():
                hourly_lons[idx + 1].extend(particles[act, 0].tolist())
                hourly_lats[idx + 1].extend(particles[act, 1].tolist())

        # Median path
        median_path = []
        for k in hours:
            if not hourly_lons[k]:
                break
            median_path.append([np.median(hourly_lons[k]), np.median(hourly_lats[k])])

        # Final ensemble statistics
        flons = particles[active_mask, 0]
        flats = particles[active_mask, 1]
        if len(flons) == 0:
            return {"centroid": None, "median_path": [], "bbox": None,
                    "spread_deg": None, "confidence": 0.0}
        confidence = float(active_mask.sum() / num_particles)
        return {
            "centroid": [float(np.median(flons)), float(np.median(flats))],
            "median_path": median_path,
            "bbox": [float(flons.min()), float(flats.min()),
                     float(flons.max()), float(flats.max())],
            "spread_deg": [float(np.std(flons)), float(np.std(flats))],
            "confidence": round(confidence, 3),
        }

    def compute_origin_probability(self, particles: List[Tuple[float, float]]) -> Dict:
        """
        Analyze the final particle positions to find the most likely origin.
        """
        lons = [p[0] for p in particles]
        lats = [p[1] for p in particles]

        return {
            "centroid": [np.mean(lons), np.mean(lats)],
            "std_dev": [np.std(lons), np.std(lats)],
            "bbox": [min(lons), min(lats), max(lons), max(lats)]
        }
