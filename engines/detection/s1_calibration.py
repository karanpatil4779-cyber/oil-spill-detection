"""Radiometric calibration for Sentinel-1 GRD SAFE measurement GeoTIFFs.

The raw ``measurement/*.tiff`` stores per-pixel amplitude (``DN``) without
georeferencing or radiometric scaling.  This module applies the standard
Sentinel-1 Level-1 calibration to produce sigma0 in dB:

    sigma0_db = 20*log10(DN) - 20*log10(A)

where ``A`` is the calibration factor ``sigmaNought`` interpolated (bilinear
across the ``calibrationVector`` grid) from ``annotation/calibration/*.xml``.

Oil-slick dark-spot detection should run on calibrated sigma0 dB so that an
absolute dark threshold (e.g. -14 dB) is physically meaningful.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import numpy as np


_CAL_VEC_RE = re.compile(
    r"<calibrationVector>\s*"
    r"<azimuthTime>.*?</azimuthTime>\s*"
    r"<line>(\d+)</line>\s*"
    r"<pixel[^>]*>\s*([\d\s]+?)\s*</pixel>\s*"
    r"<sigmaNought[^>]*>\s*([-\d.eE+\s]+?)\s*</sigmaNought>",
    re.S,
)


def find_calibration_xml(safe_dir: Path, band: str = "VV") -> Optional[Path]:
    safe_dir = Path(safe_dir)
    cal_dir = safe_dir / "annotation" / "calibration"
    if cal_dir.is_dir():
        for p in sorted(cal_dir.glob("*.xml")):
            if "noise" in p.name.lower():
                continue
            if band.lower() in p.name.lower():
                return p
        for p in sorted(cal_dir.glob("*.xml")):
            if "noise" not in p.name.lower():
                return p
    return None


def load_calibration(safe_dir: Path, band: str = "VV"):
    """Parse calibration vectors -> (lines, pixels_arrays, sigma0_arrays).

    Returns a list of dicts (one per calibration line) with keys:
      line  -> int pixel line in the measurement image
      pixel -> np.ndarray of pixel columns
      sig0  -> np.ndarray of sigmaNought values
    """
    xml = find_calibration_xml(safe_dir, band)
    if xml is None:
        return []
    text = Path(xml).read_text(encoding="utf-8")
    out = []
    for m in _CAL_VEC_RE.finditer(text):
        line = int(m.group(1))
        pixel = np.array([float(x) for x in m.group(2).split()])
        sig0 = np.array([float(x) for x in m.group(3).split()])
        out.append({"line": line, "pixel": pixel, "sig0": sig0})
    out.sort(key=lambda d: d["line"])
    return out


def calibrate_sigma0_db(
    dn: np.ndarray,
    row_offset: int,
    calib,
) -> np.ndarray:
    """Convert an amplitude DN window to calibrated sigma0 in dB.

    Args:
        dn: 2D amplitude image (a windowed subset of the measurement band).
        row_offset: image row in the *full* measurement image corresponding to
            row 0 of ``dn`` (so calibration line positions index correctly).
        calib: output of :func:`load_calibration`.

    Returns a float32 dB array, NaN where calibration is unavailable/edge.
    """
    dn = np.asarray(dn, dtype=np.float64)
    h, w = dn.shape
    db = np.full((h, w), np.nan, dtype=np.float32)

    if not calib:
        # No calibration -> fall back to relative amplitude dB (arbitrary offset)
        return (20.0 * np.log10(np.clip(dn, 1e-10, None))).astype(np.float32)

    cal_lines = np.array([c["line"] for c in calib])

    # For each measurement row, interpolate sigma0 (in log space) using the two
    # surrounding calibration lines, then interpolate across pixel columns.
    for r in range(h):
        row_abs = row_offset + r
        # find bracketing cal lines
        idx = np.searchsorted(cal_lines, row_abs, side="right") - 1
        idx = min(max(idx, 0), len(calib) - 2)
        c0 = calib[idx]
        c1 = calib[idx + 1]
        t = 0.0
        if c1["line"] != c0["line"]:
            t = (row_abs - c0["line"]) / (c1["line"] - c0["line"])

        # Interpolate log10(sigma0) as function of pixel for each cal line
        p = np.arange(w)
        a0 = np.interp(p, c0["pixel"], np.log10(np.clip(c0["sig0"], 1e-12, None)))
        a1 = np.interp(p, c1["pixel"], np.log10(np.clip(c1["sig0"], 1e-12, None)))
        lA = a0 * (1 - t) + a1 * t
        db[r, :] = 20.0 * np.log10(np.clip(dn[r, :], 1e-10, None)) - 20.0 * lA

    return db


def build_calibrated_db(
    safe_dir: Path,
    tiff_path: Path,
    c0: int,
    r0: int,
    c1: int,
    r1: int,
    band: str = "VV",
    downsample: int = 1,
):
    """Load a windowed measurement band and return calibrated sigma0 (dB).

    If ``downsample > 1`` the returned array is subsampled by that factor along
    both axes (simple box-mean of non-NaN pixels kept fast & memory safe).
    """
    import rasterio
    from rasterio.windows import Window

    calib = load_calibration(safe_dir, band)
    with rasterio.open(tiff_path) as src:
        data = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(np.float64)

    db = calibrate_sigma0_db(data, r0, calib)

    if downsample > 1:
        h = (db.shape[0] // downsample) * downsample
        w = (db.shape[1] // downsample) * downsample
        db = db[:h, :w].reshape(h // downsample, downsample, w // downsample, downsample)
        db = np.nanmean(db, axis=(1, 3))
    return db
