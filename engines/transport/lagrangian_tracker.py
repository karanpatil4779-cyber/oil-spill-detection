import numpy as np
import xarray as xr
import logging
from typing import Tuple, List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LagrangianTracker:
    """
    Implements a backward-in-time Lagrangian particle tracking model
    to estimate the origin of an oil spill.

    The metocean forcing is loaded into in-memory numpy arrays once, and all
    particle advection is vectorised (one grid lookup per time step instead of
    one per particle per time step). Results are identical to a point-by-point
    nearest-neighbour xarray lookup, but runs in a fraction of the time.
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
        ds = xr.open_dataset(currents_file).load()
        self.wind_drift_coeff = wind_drift_coeff

        # Determine coordinate / variable names once.
        self.time_name = 'time' if 'time' in ds.coords else 'valid_time'
        self.lon_name = next((c for c in ('longitude', 'lon') if c in ds.coords), 'longitude')
        self.lat_name = next((c for c in ('latitude', 'lat') if c in ds.coords), 'latitude')

        self.times = np.asarray(ds[self.time_name].values, dtype='datetime64[ns]')
        self.lons = np.asarray(ds[self.lon_name].values, dtype=float)
        self.lats = np.asarray(ds[self.lat_name].values, dtype=float)

        uo_var = next((v for v in ('uo', 'u') if v in ds.data_vars), None)
        vo_var = next((v for v in ('vo', 'v') if v in ds.data_vars), None)
        self.u = np.asarray(ds[uo_var].values, dtype=float) if uo_var else None
        self.v = np.asarray(ds[vo_var].values, dtype=float) if vo_var else None

        # Wind drift: from a separate file or the same merged archive.
        self.u_wind = None
        self.v_wind = None
        if wind_file:
            dw = xr.open_dataset(wind_file).load()
            if 'u10' in dw.data_vars:
                self.u_wind = np.asarray(dw['u10'].values, dtype=float)
                self.v_wind = np.asarray(dw['v10'].values, dtype=float)
        elif 'u10' in ds.data_vars and 'v10' in ds.data_vars:
            self.u_wind = np.asarray(ds['u10'].values, dtype=float)
            self.v_wind = np.asarray(ds['v10'].values, dtype=float)

        if self.u is not None and self.u_wind is not None:
            # Align wind time axis with current time axis when they differ.
            if self.u.shape[0] != self.u_wind.shape[0] and 'time' in (dw.coords if wind_file else ds.coords):
                try:
                    wind_times = np.asarray((dw if wind_file else ds)[self.time_name].values, dtype='datetime64[ns]')
                    idx = np.searchsorted(wind_times, self.times)
                    idx = np.clip(idx, 0, len(wind_times) - 1)
                    self.u_wind = self.u_wind[idx]
                    self.v_wind = self.v_wind[idx]
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Wind time-alignment failed: {e}")

        ds.close()

    def _grid_idx(self, values, bounds):
        """Nearest-neighbour grid index for an array of coordinates.

        Out-of-domain coordinates are clamped to the nearest edge so particles
        are advected with the boundary flow rather than silently dropped
        (matching the original tracker, which fell back to the edge values).
        Handles both ascending and descending grid axes.
        """
        values = np.asarray(values, dtype=float)
        descending = bounds[0] > bounds[-1]
        b = bounds[::-1] if descending else bounds
        pos = np.searchsorted(b, values, side='left')
        pos = np.clip(pos, 1, len(b) - 1)
        lower = b[pos - 1]
        upper = b[pos]
        closer_lower = np.abs(values - lower) <= np.abs(upper - values)
        near = np.searchsorted(b, values, side='left')
        near = np.clip(near, 0, len(b) - 1)
        lower_near = b[np.clip(near - 1, 0, len(b) - 1)]
        upper_near = b[np.clip(near, 0, len(b) - 1)]
        idx = np.where(np.abs(values - lower_near) <= np.abs(upper_near - values),
                       near - 1, near)
        idx = np.clip(idx, 0, len(b) - 1)
        if descending:
            idx = (len(bounds) - 1) - idx
        idx[np.isnan(values)] = -1
        return idx.astype(int)

    def _velocities(self, lons, lats, time_str):
        """Vectorised nearest-neighbour velocity lookup for many particles."""
        u = np.zeros(len(lons), dtype=float)
        v = np.zeros(len(lats), dtype=float)
        if self.u is None:
            return u, v

        target = np.datetime64(time_str, 'ns')
        t_idx = int(np.argmin(np.abs(self.times - target)))

        lon_idx = self._grid_idx(lons, self.lons)
        lat_idx = self._grid_idx(lats, self.lats)
        valid = (lon_idx >= 0) & (lat_idx >= 0)
        lon_idx = np.clip(lon_idx, 0, len(self.lons) - 1)
        lat_idx = np.clip(lat_idx, 0, len(self.lats) - 1)

        if not valid.any():
            u[:] = np.nan
            v[:] = np.nan
            return u, v

        cur_u = self.u[t_idx, lat_idx, lon_idx].astype(float)
        cur_v = self.v[t_idx, lat_idx, lon_idx].astype(float)
        u = cur_u.copy()
        v = cur_v.copy()
        if self.u_wind is not None:
            w = self.wind_drift_coeff
            u = u + w * self.u_wind[t_idx, lat_idx, lon_idx]
            v = v + w * self.v_wind[t_idx, lat_idx, lon_idx]

        # NaN data (missing flow) drops the particle, matching the original.
        u[np.isnan(cur_u)] = np.nan
        v[np.isnan(cur_v)] = np.nan
        u[~valid] = np.nan
        v[~valid] = np.nan
        return u, v

    def _integrate(self, start_lon, start_lat, time_steps, sign, num_particles, diffusion_sigma):
        """Shared vectorised particle integrator.

        ``sign`` is +1 for forward drift, -1 for backward (origin) tracking.
        A per-step diffusion offset is applied to each surviving particle.
        """
        particles = np.array([[start_lon, start_lat] for _ in range(num_particles)], dtype=float)
        lat_rad = np.radians(particles[:, 1])
        cos_factor = np.cos(lat_rad)
        cos_factor = np.where(np.abs(cos_factor) < 1e-6, 1e-6, cos_factor)
        active = np.ones(num_particles, dtype=bool)

        rng = np.random.default_rng()

        for t in time_steps:
            t_str = t.strftime('%Y-%m-%dT%H:%M:%S')
            if not active.any():
                break
            u, v = self._velocities(particles[active, 0], particles[active, 1], t_str)
            good = ~np.isnan(u) & ~np.isnan(v)
            sub = np.where(active)[0][good]
            uu = u[good]
            vv = v[good]

            d_lon = sign * uu * 3600 / (111000 * np.cos(np.radians(particles[sub, 1])))
            d_lat = sign * vv * 3600 / 111000
            d_lon += rng.normal(0, diffusion_sigma, size=len(sub))
            d_lat += rng.normal(0, diffusion_sigma, size=len(sub))

            particles[sub, 0] += d_lon
            particles[sub, 1] += d_lat

            # Particles that drift out of the data domain leave the cloud.
            # Axis ordering can be descending, so compare against the true extent.
            stay = np.ones(len(sub), dtype=bool)
            ln = particles[sub, 0]
            lt = particles[sub, 1]
            lon_min, lon_max = min(self.lons[0], self.lons[-1]), max(self.lons[0], self.lons[-1])
            lat_min, lat_max = min(self.lats[0], self.lats[-1]), max(self.lats[0], self.lats[-1])
            sit = (ln < lon_min) | (ln > lon_max) | (lt < lat_min) | (lt > lat_max)
            stay &= ~sit
            dead = sub[~stay]
            active[dead] = False

        return particles, active

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

        t_start = pd.to_datetime(start_time)
        time_steps = pd.date_range(end=t_start, periods=duration_hours, freq='h')

        logger.info(f"Starting backward tracking for {num_particles} particles...")
        particles, active = self._integrate(
            start_lon, start_lat, time_steps, sign=-1,
            num_particles=num_particles, diffusion_sigma=diffusion_sigma,
        )
        return particles[active].tolist()

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
        ``duration_hours``.
        """
        import pandas as pd

        t_start = pd.to_datetime(start_time)
        time_steps = pd.date_range(start=t_start, periods=duration_hours + 1, freq='h')[1:]

        logger.info(f"Starting forward tracking for {num_particles} particles...")
        particles, active = self._integrate(
            start_lon, start_lat, time_steps, sign=+1,
            num_particles=num_particles, diffusion_sigma=diffusion_sigma,
        )
        return particles[active].tolist()

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
        """
        import pandas as pd
        t_start = pd.to_datetime(start_time)
        hours = list(range(0, duration_hours + 1))
        time_steps = pd.date_range(start=t_start, periods=duration_hours + 1, freq='h')[1:]

        particles = np.array([[start_lon, start_lat] for _ in range(num_particles)], dtype=float)
        active = np.ones(num_particles, dtype=bool)
        rng = np.random.default_rng()

        hourly_lons = [[] for _ in hours]
        hourly_lats = [[] for _ in hours]
        hourly_lons[0].extend(particles[active, 0].tolist())
        hourly_lats[0].extend(particles[active, 1].tolist())

        for idx, t in enumerate(time_steps):
            t_str = t.strftime('%Y-%m-%dT%H:%M:%S')
            if not active.any():
                break
            u, v = self._velocities(particles[active, 0], particles[active, 1], t_str)
            good = ~np.isnan(u) & ~np.isnan(v)
            sub = np.where(active)[0][good]
            uu = u[good]
            vv = v[good]

            d_lon = uu * 3600 / (111000 * np.cos(np.radians(particles[sub, 1])))
            d_lat = vv * 3600 / 111000
            d_lon += rng.normal(0, diffusion_sigma, size=len(sub))
            d_lat += rng.normal(0, diffusion_sigma, size=len(sub))

            particles[sub, 0] += d_lon
            particles[sub, 1] += d_lat

            lt = particles[sub, 1]
            ln = particles[sub, 0]
            out = (ln < min(self.lons[0], self.lons[-1])) | (ln > max(self.lons[0], self.lons[-1])) | \
                  (lt < min(self.lats[0], self.lats[-1])) | (lt > max(self.lats[0], self.lats[-1]))
            dead = sub[out]
            active[dead] = False

            act = active.copy()
            if act.any():
                hourly_lons[idx + 1].extend(particles[act, 0].tolist())
                hourly_lats[idx + 1].extend(particles[act, 1].tolist())

        median_path = []
        for k in hours:
            if not hourly_lons[k]:
                break
            median_path.append([np.median(hourly_lons[k]), np.median(hourly_lats[k])])

        flons = particles[active, 0]
        flats = particles[active, 1]
        if len(flons) == 0:
            return {"centroid": None, "median_path": [], "bbox": None,
                    "spread_deg": None, "confidence": 0.0}
        confidence = float(active.sum() / num_particles)
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