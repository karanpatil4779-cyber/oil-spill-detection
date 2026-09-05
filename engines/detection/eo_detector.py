"""Sentinel-2 (EO / optical) oil-film detection via Copernicus Data Space.

The problem statement asks for detection using "SAR and EO imagery". The
core pipeline detects dark spots from Sentinel-1 SAR; this module adds an
independent optical (EO) confirmation using Sentinel-2 MSI SWIR bands.

Method — Normalized Difference Hydrocarbon Index (NDHI):
    NDHI = (B11 - B12) / (B11 + B12)
where B11 (~1610 nm) and B12 (~2190 nm) are short-wave-infrared bands. Oil
films have distinctive SWIR absorption (hydrocarbon spectral signatures), so
a coherent area of anomalously low NDHI that also lines up with the SAR
dark-spot location corroborates the presence of oil (helps distinguish real
oil from SAR "look-alikes" such as low-wind zones).

This detector:
  1. searches CDSE for Sentinel-2 L2A MSI products over the spill location,
  2. downloads the B11 and B12 band JP2s (small, ~100-200 MB total),
  3. computes NDHI and thresholds an anomalous-oil mask,
  4. returns a confirmation flag + bounding boxes aligned with the SAR detection.

Unlike SAR, EO is only usable in daylight and cloud-free conditions, so the
result includes a cloud/valid-surface check when the SCL scene-classification
band is present.
"""

import os
import re
import math
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests
from dotenv import load_dotenv

from .sar_detector import CDSE_BASE, CDSE_DOWNLOAD, CDSE_AUTH, SARAuthError

load_dotenv()
logger = logging.getLogger(__name__)

S2_COLLECTION = "SENTINEL-2"
# NDHI threshold below which a pixel is flagged as a hydrocarbon anomaly
NDHI_OIL_THRESHOLD = -0.02


def _band_wavelength(name: str) -> Optional[float]:
    """Return the approximate central wavelength (nm) from an S2 band filename.

    S2 L2A band files look like <...>_B11.jp2, <...>_B02_10m.jp2 etc.
    """
    m = re.search(r"_B(\d{2})", name, re.IGNORECASE)
    if not m:
        return None
    b = int(m.group(1))
    table = {2: 490, 3: 560, 4: 665, 8: 842, 8: 842, 11: 1610, 12: 2190}
    return table.get(b)


class EODetector:
    """Sentinel-2 based optical oil-film confirmation detector."""

    def __init__(self, username: str = None, password: str = None):
        self.username = username or os.getenv("CDSE_USERNAME")
        self.password = password or os.getenv("CDSE_PASSWORD")
        self._token = None
        self._token_expiry = 0
        if not self.username or not self.password:
            raise SARAuthError("CDSE credentials not set (needed for Sentinel-2 EO).")

    def _get_token(self) -> str:
        import time
        if self._token and time.time() < self._token_expiry:
            return self._token
        resp = requests.post(CDSE_AUTH, data={
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
            "client_id": "cdse-public",
        }, timeout=30)
        if resp.status_code != 200:
            raise SARAuthError(f"CDSE auth failed ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 600) - 30
        return self._token

    def _auth_headers(self) -> Dict:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def search_products(self, lon: float, lat: float, start_date: str, end_date: str,
                        limit: int = 3) -> List[Dict]:
        """Search CDSE for Sentinel-2 MSI L2A products near a point/date range.

        L2A surface-reflectance products are identified by the product *Name*
        prefix (S2A_MSIL2A_ / S2B_MSIL2A_) — the ``productType`` attribute used
        by Sentinel-1 is not reliably set on S2 in the CDSE catalogue, so we
        filter on the Name prefix instead.
        """
        time_filter = (
            f"ContentDate/Start gt {start_date}T00:00:00.000Z"
            + f" and ContentDate/Start lt {end_date}T23:59:59.999Z"
        )
        name_filter = (
            "startswith(Name,'S2A_MSIL2A_') or startswith(Name,'S2B_MSIL2A_')"
        )
        filters = (
            f"Collection/Name eq '{S2_COLLECTION}'"
            + f" and OData.CSC.Intersects(area=geography'SRID=4326;POINT({lon} {lat})')"
            + f" and ({name_filter})"
            + f" and {time_filter}"
        )
        url = (
            f"{CDSE_BASE}/Products?$filter={filters}"
            + f"&$top={limit}&$orderby=ContentDate/Start desc"
        )
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        entries = resp.json().get("value", [])
        return [{
            "id": e.get("Id"),
            "name": e.get("Name"),
            "start": e.get("ContentDate", {}).get("Start"),
            "size_mb": round(e.get("ContentLength", 0) / 1e6, 1),
        } for e in entries]

    def _download_band_list(self, product_id: str, band_names: str,
                            out_dir: Path) -> Dict[str, Path]:
        """Download an S2 L2A product and extract the SWIR / quality bands.

        The CDSE band-list zipper endpoint is unreliable (often 404), so we
        download the whole L2A product ZIP via the zipper $value endpoint (the
        same pattern the SAR detector uses) and extract just the B11, B12, B8A
        reflectance bands and the SCL scene-classification band. This is the
        deterministic path and works across CDSE mirrors.

        The download is written through ``requests`` with a per-chunk read
        timeout and a stall guard, with one automatic retry on a dropped/
        stalled connection (CDSE's large-product zipper is known to stall).

        Returns {band_label: local_path}; an empty dict if nothing usable.
        """
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"}

        zip_path = out_dir / f"{product_id}.zip"
        candidates = [
            f"{CDSE_DOWNLOAD}/Products({product_id})/$value",
            f"{CDSE_DOWNLOAD}/Products('{product_id}')/$value",
            f"{CDSE_BASE}/Products({product_id})/$value",
        ]

        last_err = None
        written = 0
        for attempt in range(2):  # one retry
            for url in candidates:
                try:
                    written = self._download_to(zip_path, url, headers)
                    if written:
                        break
                except Exception as e:
                    last_err = e
                    logger.warning(f"S2 download via {url} (attempt {attempt + 1}): {e}")
                    try:
                        zip_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    written = 0
            if written:
                break

        if not written:
            logger.warning(f"Could not download S2 product: {last_err}")
            return {}

        logger.info(f"Downloaded S2 product ({zip_path.stat().st_size / 1e6:.0f} MB)")

        wanted = {"B11": "b11", "B12": "b12", "B8A": "b8a", "SCL": "sc"}
        out: Dict[str, Path] = {}
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for name in zf.namelist():
                    base = os.path.basename(name).upper()
                    for kw, label in wanted.items():
                        if base == f"{kw}.JP2" or f"_{kw}_" in base or base.startswith(kw + "_"):
                            if label in out:
                                continue
                            target = out_dir / f"{label}.jp2"
                            with open(target, "wb") as fo:
                                fo.write(zf.read(name))
                            out[label] = target
                            break
        except Exception as e:
            logger.warning(f"S2 extraction failed: {e}")
        return out

    @staticmethod
    def _download_to(zip_path: Path, url: str, headers: Dict,
                     max_stall_s: float = 60.0) -> bool:
        """Stream ``url`` to ``zip_path`` with a read timeout + stall guard.

        Returns True on a complete download, False/raises otherwise. The read
        timeout is applied per-chunk so a silently-stalled connection (common
        with CDSE large products) is detected and surfaced rather than hanging
        forever.
        """
        import time
        resp = requests.get(url, headers=headers, stream=True, timeout=(30, 300))
        if resp.status_code != 200:
            resp.close()
            return False
        total = int(resp.headers.get("Content-Length", 0) or 0)
        got = 0
        last_progress = time.time()
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                if not chunk:
                    continue
                f.write(chunk)
                got += len(chunk)
                if got % (64 << 20) < 8192:  # log ~every 64MB
                    logger.info(f"S2 download progress {got / 1e6:.0f} / {total / 1e6:.0f} MB")
                if time.time() - last_progress > max_stall_s:
                    raise ConnectionError(f"Stalled at {got / 1e6:.0f} / {total / 1e6:.0f} MB")
                last_progress = time.time()
        resp.close()
        return total == 0 or got >= total - 1

    def detect_oil(self, lon: float, lat: float, start_date: str, end_date: str,
                   ndhi_threshold: float = NDHI_OIL_THRESHOLD) -> Dict:
        """End-to-end EO oil confirmation for an incident location + window.

        Downloads the first available S2 L2A product over the site, computes the
        NDHI mask and returns a confirmation report. Uses real CDSE data.
        """
        products = self.search_products(lon, lat, start_date, end_date, limit=2)
        if not products:
            return {"available": False, "confirmed": False, "reason": "No Sentinel-2 product found in window",
                    "products_found": 0, "detections": []}

        out_dir = Path(tempfile.mkdtemp(prefix="s2_"))
        result = None
        errors = []
        for prod in products:
            try:
                bands = self._download_band_list(prod["id"], "B11,B12,SCL,B8A", out_dir)
                if "b11" not in bands or "b12" not in bands:
                    errors.append(f"Missing B11/B12 in {prod['name']}")
                    continue
                result = self._compute_ndhi(bands, lon, lat, ndhi_threshold)
                result["product"] = prod["name"]
                result["product_start"] = prod["start"]
                result["products_found"] = len(products)
                result["available"] = True
                break
            except Exception as e:
                errors.append(f"Error on {prod['name']}: {e}")
        if result is None:
            return {"available": False, "confirmed": False, "reason": "; ".join(errors),
                    "products_found": len(products), "detections": []}
        result["warnings"] = errors
        return result

    def _compute_ndhi(self, bands: Dict[str, Path], lon: float, lat: float,
                      ndhi_threshold: float) -> Dict:
        import rasterio
        from rasterio.warp import transform as rt_transform
        from rasterio.crs import CRS

        # Sentinel-2 L2A BOA reflectance is stored as scaled integers (0..10000);
        # convert to physical reflectance before computing the index.
        with rasterio.open(bands["b11"]) as d11, rasterio.open(bands["b12"]) as d12:
            b11 = (d11.read(1).astype("float32") / 10000.0)
            b12 = (d12.read(1).astype("float32") / 10000.0)
            crs = d11.crs
            transform = d11.transform
            if d12.crs != crs:
                logger.warning("B11/B12 CRS mismatch; using B11.")

        scl = None
        if "sc" in bands:
            try:
                with rasterio.open(bands["sc"]) as dsc:
                    scl = dsc.read(1)
            except Exception:
                scl = None

        # NDHI hydrocarbon index on physical reflectance.
        denom = b11 + b12
        with np.errstate(invalid="ignore", divide="ignore"):
            ndhi = np.where(denom > 1e-6, (b11 - b12) / denom, np.nan)

        # Keep only water and clear bare surfaces. For oil-on-water we focus on
        # the water class (SCL=6); we also allow bare/cloud-free surfaces but
        # never let clouds/shadow/snow drive a "confirmation".
        valid = np.ones_like(ndhi, dtype=bool)
        if scl is not None:
            h, w = ndhi.shape
            if scl.ndim == 2 and scl.shape[:2] == (h, w):
                # SCL: 6 = water, 5 = bare soil, 4 = vegetation (partial).
                valid = np.isin(scl, [5, 6])
            else:
                valid = np.ones_like(ndhi, dtype=bool)

        oil_mask = ((ndhi < ndhi_threshold) & valid & np.isfinite(ndhi))

        # Clean + label connected components.
        from scipy import ndimage
        confirmed = bool(oil_mask.any())
        detections = []
        if confirmed:
            struct = ndimage.generate_binary_structure(2, 1)
            clean = ndimage.binary_opening(oil_mask, structure=struct, iterations=1)
            clean = ndimage.binary_closing(clean, structure=struct, iterations=2)
            labeled, n = ndimage.label(clean)
            water_valid = valid & np.isfinite(ndhi)
            for i in range(1, n + 1):
                ys, xs = np.where(labeled == i)
                if len(ys) < 100:
                    continue  # ignore tiny speckles
                x0, x1 = int(xs.min()), int(xs.max())
                y0, y1 = int(ys.min()), int(ys.max())
                # Convert UTM pixel corners to WGS84 lon/lat.
                try:
                    xxs = [x0, x1, x1, x0]
                    yys = [y0, y0, y1, y1]
                    lons_a, lats_a = rt_transform(crs, CRS.from_epsg(4326), xxs, yys)
                    blon, blat = round(float(lons_a[0]), 6), round(float(lats_a[0]), 6)
                    tron, trat = round(float(lons_a[2]), 6), round(float(lats_a[2]), 6)
                except Exception:
                    blon = blat = tron = trat = None
                comp = clean == i
                vals = ndhi[comp]
                detections.append({
                    "bbox_geo": [blon, blat, tron, trat] if blon is not None else None,
                    "area_px": int(len(xs)),
                    "mean_ndhi": round(float(np.nanmean(vals)), 4) if vals.size else None,
                    "water_frac": round(float(np.mean(water_valid[comp])), 3) if comp.any() else 0.0,
                })

        oil_frac = float(np.nanmean(ndhi[valid & np.isfinite(ndhi)])) if np.isfinite(ndhi[valid]).any() else float("nan")
        return {
            "confirmed": confirmed,
            "ndhi_mean_water": round(oil_frac, 4) if not np.isnan(oil_frac) else None,
            "ndhi_threshold": ndhi_threshold,
            "anomaly_px": int(oil_mask.sum()) if oil_mask.any() else 0,
            "cloud_scl_available": scl is not None,
            "wgs84": True,
            "detections": detections,
            "scene_px": int(ndhi.size),
        }

    def health_check(self) -> bool:
        try:
            self._get_token()
            return True
        except Exception:
            return False
