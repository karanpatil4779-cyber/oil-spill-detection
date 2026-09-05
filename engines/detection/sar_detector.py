"""Sentinel-1 SAR oil-spill detection via Copernicus Data Space (CDSE).

Searches for Sentinel-1 GRD/SLC products near an incident location,
downloads the best match, and applies a simple oil-detection pipeline:
  1. Read VV/VH polarisation from the SAFE manifest or GeoTIFF
  2. Apply CFAR-like thresholding (Constant False Alarm Rate)
  3. Morphological cleanup to isolate dark-spot candidates
  4. Return bounding boxes of detected oil slicks

Data source: Copernicus Data Space Ecosystem (CDSE) OData API.
Auth: CDSE_USERNAME / CDSE_PASSWORD from .env.

Limitations:
  - Sentinel-1 launched in 2014; no SAR imagery for pre-2014 incidents
    (e.g. MSC Chitra 2010).
  - GRD products are ground-range detected (no phase info); for full
    polarimetric analysis, SLC products are needed.
  - This is a first-order dark-spot detector; production systems use
    ML-based classifiers (U-Net, DeepLabV3+) for higher accuracy.
"""

import os
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CDSE_BASE = "https://catalogue.dataspace.copernicus.eu/odata/v1"
CDSE_DOWNLOAD = "https://zipper.dataspace.copernicus.eu/odata/v1"
CDSE_AUTH = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"


class SARAuthError(Exception):
    pass


def _default_cache_dir() -> Path:
    """Persistent cache root for Sentinel-1 products (skips re-downloads)."""
    env = os.getenv("SAR_CACHE_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "raw" / "sar_cache"


def _cached_extract_dir(cache_root: Path, product_id: str, short_name: str) -> Optional[Path]:
    """Return the already-extracted product dir if present (resume/cache)."""
    extracted = cache_root / product_id / short_name
    if extracted.is_dir() and (extracted / "manifest.safe").exists():
        return extracted
    return None


def _has_cached_zip(cache_root: Path, product_id: str) -> Optional[Path]:
    zip_path = cache_root / product_id / f"{product_id}.zip"
    if zip_path.exists() and zip_path.stat().st_size > 0:
        return zip_path
    return None


class SARDetector:
    """Sentinel-1 based oil-spill dark-spot detector."""

    def __init__(self, username: str = None, password: str = None):
        self.username = username or os.getenv("CDSE_USERNAME")
        self.password = password or os.getenv("CDSE_PASSWORD")
        self._token = None
        self._token_expiry = 0
        if not self.username or not self.password:
            raise SARAuthError(
                "CDSE_USERNAME / CDSE_PASSWORD not set in .env. "
                "Register at https://dataspace.copernicus.eu/ and add credentials."
            )

    # ── Auth ──────────────────────────────────────────────────────────────

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

    # ── Product search ───────────────────────────────────────────────────

    def search_products(
        self,
        lon: float,
        lat: float,
        date: str,
        collection: str = "SENTINEL-1",
        product_type: str = "GRD",
        max_cloud: int = 100,
        limit: int = 5,
    ) -> List[Dict]:
        """Search CDSE OData for Sentinel-1 products near a point/date.

        Args:
            lon, lat: Incident coordinates.
            date: ISO date (YYYY-MM-DD) of the incident.
            product_type: GRD (amplitude) or SLC (complex).
            max_cloud: Maximum cloud cover percentage (usually N/A for SAR).
            limit: Max results.
        """
        footprint = f"POINT({lon} {lat})"
        filter_parts = [
            f"Collection/Name eq '{collection}'",
            f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq '{product_type}')",
            f"OData.CSC.Intersects(area=geography'SRID=4326;POINT({lon} {lat})')",
        ]

        start_dt = f"{date}T00:00:00.000Z"
        end_dt = f"{date}T23:59:59.999Z"
        filter_parts.append(f"ContentDate/Start gt {start_dt}")
        filter_parts.append(f"ContentDate/Start lt {end_dt}")

        filters = " and ".join(filter_parts)
        url = (
            f"{CDSE_BASE}/Products?"
            f"$filter={filters}"
            f"&$top={limit}"
            f"&$orderby=ContentDate/Start desc"
        )

        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        entries = resp.json().get("value", [])
        results = []
        for e in entries:
            results.append({
                "id": e.get("Id"),
                "name": e.get("Name"),
                "start": e.get("ContentDate", {}).get("Start"),
                "end": e.get("ContentDate", {}).get("End"),
                "size_mb": round(e.get("ContentLength", 0) / 1e6, 1),
                "product_type": product_type,
            })
        logger.info(f"Found {len(results)} Sentinel-1 {product_type} products for {date}")
        return results

    def search_near_date_range(
        self,
        lon: float,
        lat: float,
        start_date: str,
        end_date: str,
        product_type: str = "GRD",
        limit: int = 5,
    ) -> List[Dict]:
        """Search over a date range (useful for finding passes within a window)."""
        footprint = f"POINT({lon} {lat})"
        filter_parts = [
            f"Collection/Name eq 'SENTINEL-1'",
            f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq '{product_type}')",
            f"OData.CSC.Intersects(area=geography'SRID=4326;POINT({lon} {lat})')",
            f"ContentDate/Start gt {start_date}T00:00:00.000Z",
            f"ContentDate/Start lt {end_date}T23:59:59.999Z",
        ]
        filters = " and ".join(filter_parts)
        url = (
            f"{CDSE_BASE}/Products?"
            f"$filter={filters}"
            f"&$top={limit}"
            f"&$orderby=ContentDate/Start desc"
        )
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        entries = resp.json().get("value", [])
        return [
            {
                "id": e.get("Id"),
                "name": e.get("Name"),
                "start": e.get("ContentDate", {}).get("Start"),
                "end": e.get("ContentDate", {}).get("End"),
                "size_mb": round(e.get("ContentLength", 0) / 1e6, 1),
            }
            for e in entries
        ]

    # ── Download ─────────────────────────────────────────────────────────

    def download_product(self, product_id: str, output_dir: str = None) -> Path:
        """Download a Sentinel-1 product ZIP via the CDSE zipper (SAS) service.

        Modern CDSE expects the product UUID in an unquoted OData key
        (``Products(<uuid>)/$value``). Some mirrors/locales still accept the
        quoted form, so we fall back across URL shapes. The streamed body is a
        ZIP of the whole .SAFE, which is extracted into ``output_dir``.

        Downloaded ZIPs and extracted .SAFE dirs are cached in
        ``SAR_CACHE_DIR`` (default ``data/raw/sar_cache``) so re-running a
        pipeline does not re-download the ~1.7 GB product (resume/cache layer;
        the retrieved bytes and scientific output are identical).
        """
        cache_root = _default_cache_dir()
        short_name = f"s1_{product_id[:8]}"
        cached_dir = _cached_extract_dir(cache_root, product_id, short_name)
        if cached_dir:
            logger.info(f"SAR cache hit (extracted): {cached_dir}")
            return cached_dir
        cached_zip = _has_cached_zip(cache_root, product_id)
        if cached_zip:
            logger.info(f"SAR cache hit (zip): {cached_zip}")

        output_dir = Path(output_dir or cache_root / product_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"}

        candidates = [
            f"{CDSE_DOWNLOAD}/Products({product_id})/$value",
            f"{CDSE_DOWNLOAD}/Products('{product_id}')/$value",
            f"{CDSE_DOWNLOAD}/Products({product_id})/PrimaryFiles",
            f"{CDSE_BASE}/Products({product_id})/$value",
        ]

        resp = None
        last_err = None
        if cached_zip:
            zip_path = cached_zip
        else:
            for url in candidates:
                try:
                    resp = requests.get(url, headers=headers, stream=True, timeout=(30, 600))
                except Exception as e:  # network failure -> try next URL shape
                    last_err = e
                    resp = None
                    continue
                if resp.status_code == 200:
                    break
                last_err = RuntimeError(
                    f"Download failed ({resp.status_code}) via {url}: {resp.text[:300]}"
                )
                resp.close()
                resp = None

            if resp is None:
                raise last_err or RuntimeError("No CDSE download URL responded successfully")

            if resp.status_code == 200 and resp.headers.get("Content-Length"):
                expected = int(resp.headers["Content-Length"])
                if cached_zip and cached_zip.stat().st_size == expected:
                    resp.close()
                    resp = None
            # (If a cached zip exists but is incomplete, re-download overwrites it.)

            if resp is not None:
                zip_path = output_dir / f"{product_id}.zip"
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(zip_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                resp.close()
                logger.info(f"Downloaded {zip_path.name} ({downloaded / 1e6:.1f} MB)")
                cached_zip = zip_path
            else:
                zip_path = cached_zip

        # Extract. Sentinel-1 .SAFE products have very long file/folder names
        # that exceed the Windows MAX_PATH limit when nested under a deep output
        # dir. To stay portable we shorten the top-level .SAFE folder of every
        # member to a short id-based name before writing it out.
        short_name = f"s1_{product_id[:8]}"
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.namelist()
            # First original top-level folder (e.g. S1A_...SAFE) length
            prefix = ""
            for m in members:
                head = m.split("/", 1)[0]
                if head:
                    prefix = head
                    break
            for m in members:
                rel = m
                if prefix and m.startswith(prefix):
                    rel = short_name + m[len(prefix):]
                if m.endswith("/"):
                    (output_dir / rel).mkdir(parents=True, exist_ok=True)
                    continue
                target = output_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(m) as fi, open(target, "wb") as fo:
                    fo.write(fi.read())
        extracted_dir = output_dir / short_name
        logger.info(f"Extracted {len(members)} members -> {extracted_dir}")
        return extracted_dir

    # ── Oil detection ────────────────────────────────────────────────────

    def detect_dark_spots(
        self,
        sar_data: np.ndarray,
        threshold_db: float = -15.0,
        min_area_px: int = 50,
        cfar_guard: int = 10,
        cfar_train: int = 20,
    ) -> List[Dict]:
        """Apply CFAR-like dark-spot detection on SAR amplitude/dB image.

        Args:
            sar_data: 2D numpy array of SAR backscatter in dB.
            threshold_db: Intensity threshold below which pixels are dark (dB).
            min_area_px: Minimum connected component area in pixels.
            cfar_guard: CFAR guard cell radius.
            cfar_train: CFAR training cell radius.
        """
        from scipy import ndimage

        h, w = sar_data.shape

        # Speckle suppression: SAR is inherently noisy, so a 3x3 median filter
        # (a cheap multi-look proxy) stabilises the local statistics before
        # thresholding. This dramatically reduces single-pixel false alarms.
        scaled = ndimage.median_filter(sar_data.astype(float), size=3)

        # Vectorised sliding-window statistics via uniform filters for a proper
        # CFAR-like adaptive background. The local background is estimated from
        # an ANNULUS that excludes the guard band and inner cells, so an
        # individual dark patch does not bias the background it is compared
        # against. This uses the difference of two uniform filters (outer minus
        # inner) for both the mean and the mean-square.
        outer_r = cfar_guard + cfar_train
        inner_r = cfar_guard
        inner_factor = (2 * inner_r + 1) / (2 * outer_r + 1)

        scaled_sq = scaled ** 2

        mu_outer = ndimage.uniform_filter(scaled, size=(2 * outer_r + 1, 2 * outer_r + 1), mode="nearest")
        mu_inner = ndimage.uniform_filter(scaled, size=(2 * inner_r + 1, 2 * inner_r + 1), mode="nearest")
        m2_outer = ndimage.uniform_filter(scaled_sq, size=(2 * outer_r + 1, 2 * outer_r + 1), mode="nearest")
        m2_inner = ndimage.uniform_filter(scaled_sq, size=(2 * inner_r + 1, 2 * inner_r + 1), mode="nearest")

        annulus_mean = (mu_outer - inner_factor * mu_inner) / (1.0 - inner_factor)
        annulus_m2 = (m2_outer - inner_factor * m2_inner) / (1.0 - inner_factor)
        annulus_var = np.clip(annulus_m2 - annulus_mean ** 2, 0.0, None)
        annulus_std = np.sqrt(annulus_var) + 1e-10

        # Primary gate: an absolute dark-spot threshold (genuinely dark pixels).
        # This robustly catches large slicks whose centre can saturate a local
        # adaptive background estimate.
        abs_dark = scaled < threshold_db

        # Secondary gate: dark relative to the local annulus background. This
        # catches weaker slicks and thin sheens that are darker than their
        # surroundings but not below a global floor.
        adaptive_thresh = annulus_mean - 2.5 * annulus_std
        adapt_dark = scaled < adaptive_thresh

        # Combined mask: any genuinely dark pixel, or any pixel darker than a
        # relaxed absolute floor that is also well below its local background.
        mask = abs_dark | (adapt_dark & (scaled < threshold_db + 5.0))

        # Edge exclusion: discard the frame where the annulus is clipped by the
        # image border and not representative of open water.
        if outer_r > 0:
            mask[:outer_r, :] = False
            mask[-outer_r:, :] = False
            mask[:, :outer_r] = False
            mask[:, -outer_r:] = False

        # Morphological cleanup: close to join fragmented slick pixels, then a
        # light opening to remove residual single-pixel speckle.
        if mask.any():
            struct = ndimage.generate_binary_structure(2, 1)
            mask = ndimage.binary_closing(mask, structure=struct, iterations=3)
            mask = ndimage.binary_opening(mask, structure=struct, iterations=1)

        # Label connected components
        labeled, n_features = ndimage.label(mask)
        detections = []
        for i in range(1, n_features + 1):
            component = labeled == i
            area = int(component.sum())
            if area < min_area_px:
                continue
            ys, xs = np.where(component)
            bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
            mean_val = float(sar_data[component].mean())
            detections.append({
                "bbox_px": bbox,
                "area_px": area,
                "mean_db": round(mean_val, 2),
                "centroid_px": [int(xs.mean()), int(ys.mean())],
            })

        detections.sort(key=lambda d: d["area_px"], reverse=True)
        logger.info(f"Dark-spot detection: {len(detections)} candidates above {min_area_px}px")
        return detections

    def detect_from_product(
        self,
        product_path: str,
        band: str = "VV",
    ) -> List[Dict]:
        """End-to-end: read a downloaded S1 product and detect dark spots.

        Expects a .tif or .data directory inside the extracted SAFE folder.
        """
        p = Path(product_path)
        tiffs = list(p.rglob("*.tif"))
        if not tiffs:
            tiffs = list(p.rglob("*.tiff"))

        target = None
        for t in tiffs:
            if band.upper() in t.name.upper():
                target = t
                break
        if target is None and tiffs:
            target = tiffs[0]

        if target is None:
            logger.warning(f"No GeoTIFF found in {product_path}")
            return []

        try:
            import rasterio
            with rasterio.open(target) as src:
                sar = src.read(1).astype(float)
                transform = src.transform
                crs = src.crs
        except ImportError:
            logger.warning("rasterio not available, using numpy load")
            sar = np.load(str(target)) if target.suffix == ".npy" else None
            if sar is None:
                return []
            transform, crs = None, None

        # Convert linear power to dB
        sar_db = 10 * np.log10(np.clip(sar, 1e-10, None))

        detections = self.detect_dark_spots(sar_db)

        # Convert pixel bbox to geo coords if transform available
        if transform is not None:
            import rasterio.transform
            for det in detections:
                bx0, by0, bx1, by1 = det["bbox_px"]
                lon0, lat1 = rasterio.transform.xy(transform, by0, bx0)
                lon1, lat0 = rasterio.transform.xy(transform, by1, bx1)
                det["bbox_geo"] = [round(lon0, 6), round(lat0, 6),
                                   round(lon1, 6), round(lat1, 6)]
                cx, cy = rasterio.transform.xy(transform, det["centroid_px"][1],
                                               det["centroid_px"][0])
                det["centroid_geo"] = [round(cx, 6), round(cy, 6)]

        return detections

    def health_check(self) -> bool:
        try:
            self._get_token()
            return True
        except Exception:
            return False
