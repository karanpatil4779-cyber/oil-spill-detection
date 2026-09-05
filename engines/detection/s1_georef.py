"""Georeferencing helpers for Sentinel-1 GRD SAFE products.

Sentinel-1 Level-1 GRD measurement GeoTIFFs inside the .SAFE archive typically
carry no embedded CRS / geotransform (identity matrix).  The ground truth for
pixel <-> geographic mapping lives in the *annotation XML* ``geolocationGrid``
(one point per ~2010-line and ~1291-pixel step).  This module parses that grid
and exposes:
  - :func:`run_safe_georef`   -> build grid arrays of lon/lat over the image
  - :class:`GeolocGrid`       -> bilinear lon/lat <-> pixel (row,col) mapping

It is a lightweight replacement for SNAP/GDAL geocoding when the measurement
tiff carries no CRS (the common raw-SAFE case).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import numpy as np


# ── parsing ────────────────────────────────────────────────────────────────

_GRID_POINT_RE = re.compile(
    r"<geolocationGridPoint>\s*"
    r"<azimuthTime>.*?</azimuthTime>\s*"
    r"<slantRangeTime>.*?</slantRangeTime>\s*"
    r"<line>(\d+)</line>\s*"
    r"<pixel>(\d+)</pixel>\s*"
    r"<latitude>([-\d.eE+]+)</latitude>\s*"
    r"<longitude>([-\d.eE+]+)</longitude>",
    re.S,
)


def find_annotation_xml(safe_dir: Path, band: str = "VV") -> Path:
    """Locate the GIPP/annotation XML for the requested polarisation."""
    safe_dir = Path(safe_dir)
    annotation = safe_dir / "annotation"
    if annotation.is_dir():
        for p in sorted(annotation.glob("*.xml")):
            basename = p.name.lower()
            if band.lower() in basename:
                return p
        # fall back to any annotation xml
        xmls = sorted(annotation.glob("*.xml"))
        if xmls:
            return xmls[0]
    # recursive fallback
    for p in sorted(safe_dir.rglob("*.xml")):
        basename = p.name.lower()
        if band.lower() in basename:
            return p
    raise FileNotFoundError(f"No annotation XML found for band {band} in {safe_dir}")


def parse_geolocation_grid(annotation_xml: Path) -> "GeolocGrid":
    """Parse the geolocation grid from a Sentinel-1 annotation XML."""
    text = Path(annotation_xml).read_text(encoding="utf-8")
    matches = _GRID_POINT_RE.findall(text)
    if not matches:
        raise ValueError(f"No geolocationGridPoint entries in {annotation_xml}")

    rows = sorted({int(m[0]) for m in matches})
    cols = sorted({int(m[1]) for m in matches})

    row_index = {r: i for i, r in enumerate(rows)}
    col_index = {c: j for j, c in enumerate(cols)}

    nrow, ncol = len(rows), len(cols)
    lat = np.full((nrow, ncol), np.nan)
    lon = np.full((nrow, ncol), np.nan)
    for line_s, pix_s, lat_s, lon_s in matches:
        r = row_index[int(line_s)]
        c = col_index[int(pix_s)]
        lat[r, c] = float(lat_s)
        lon[r, c] = float(lon_s)

    return GeolocGrid(
        rows=np.array(rows, dtype=float),
        cols=np.array(cols, dtype=float),
        lat=lat,
        lon=lon,
    )


# ── mapping ────────────────────────────────────────────────────────────────

@dataclass
class GeolocGrid:
    """Discrete geolocation grid + bilinear interpolation helpers.

    Image pixel (column) maps to ScanSAR range; pixel (row) maps to azimuth.
    We use row ~ y, col ~ x (raster convention: row 0 at top).
    """

    rows: np.ndarray          # line (row) coordinates of the grid, ascending
    cols: np.ndarray          # pixel (col) coordinates of the grid, ascending
    lat: np.ndarray           # (nrow, ncol) latitude
    lon: np.ndarray           # (nrow, ncol) longitude

    # ── forward: pixel -> lon/lat ──────────────────────────────────────
    def pixel_to_lonlat(self, col: float, row: float) -> Tuple[float, float]:
        """Bilinear map a floating point (col,row) to (lon,lat)."""
        lat = self._interp(self.lat, row, col)
        lon = self._interp(self.lon, row, col)
        return float(lon), float(lat)

    def _interp(self, field: np.ndarray, row: float, col: float) -> float:
        r0 = np.searchsorted(self.rows, row, side="right") - 1
        c0 = np.searchsorted(self.cols, col, side="right") - 1
        nrow, ncol = field.shape
        r0 = min(max(r0, 0), nrow - 2)
        c0 = min(max(c0, 0), ncol - 2)
        r1, c1 = r0 + 1, c0 + 1

        w_r = (row - self.rows[r0]) / (self.rows[r1] - self.rows[r0])
        w_c = (col - self.cols[c0]) / (self.cols[c1] - self.cols[c0])

        top = field[r0, c0] * (1 - w_c) + field[r0, c1] * w_c
        bot = field[r1, c0] * (1 - w_c) + field[r1, c1] * w_c
        return top * (1 - w_r) + bot * w_r

    # ── inverse: lon/lat -> pixel (col,row) ────────────────────────────
    def lonlat_to_pixel(self, lon: float, lat: float) -> Tuple[float, float]:
        """Inverse-map (lon, lat) to fractional pixel (col,row).

        Implemented via Newton iteration on the forward grid (the S1 geolocation
        grid is smooth and small, so convergence is fast and stable).
        """
        col, row = self._guess(lon, lat)
        for _ in range(30):
            lo, la = self.pixel_to_lonlat(col, row)
            dlon, dlat = lo - lon, la - lat
            if max(abs(dlon), abs(dlat)) < 1e-7:
                break
            # finite-difference jacobian (dLon/dCol, dLon/dRow, dLat/dCol, dLat/dRow)
            e = 1e-3
            lo_e, la_e = self.pixel_to_lonlat(col + e, row)
            lo_er, la_er = self.pixel_to_lonlat(col, row + e)
            J = np.array([
                [(lo_e - lo) / e, (lo_er - lo) / e],
                [(la_e - la) / e, (la_er - la) / e],
            ])
            try:
                step = np.linalg.solve(J, np.array([dlon, dlat]))
            except np.linalg.LinAlgError:
                break
            col, row = col - step[0], row - step[1]
            if not (np.isfinite(col) and np.isfinite(row)):
                break
        return float(col), float(row)

    def _guess(self, lon: float, lat: float) -> Tuple[float, float]:
        """Coarse nearest-neighbour seed for the inverse mapping."""
        dist = (self.lat - lat) ** 2 + (self.lon - lon) ** 2
        idx = int(np.argmin(dist))
        r, c = np.unravel_index(idx, self.lat.shape)
        return float(self.cols[c]), float(self.rows[r])

    def lonlat_to_pixel_bounds(
        self,
        lon: float,
        lat: float,
        half_deg: float,
        width: int,
        height: int,
    ) -> Tuple[int, int, int, int]:
        """Return a clipped integer pixel window (col0, row0, col1, row1)."""
        c, r = self.lonlat_to_pixel(lon, lat)
        c0, r0 = self.lonlat_to_pixel(lon - half_deg, lat - half_deg)
        c1, r1 = self.lonlat_to_pixel(lon + half_deg, lat + half_deg)
        col0 = int(min(c, c0, c1))
        row0 = int(min(r, r0, r1))
        col1 = int(max(c, c0, c1))
        row1 = int(max(r, r0, r1))
        col0 = max(0, col0); row0 = max(0, row0)
        col1 = min(width - 1, col1 + 1); row1 = min(height - 1, row1 + 1)
        return col0, row0, col1, row1


def run_safe_georef(safe_dir: Path, band: str = "VV") -> GeolocGrid:
    """Convenience: find annotation XML and parse the geolocation grid."""
    xml = find_annotation_xml(safe_dir, band)
    return parse_geolocation_grid(xml)
