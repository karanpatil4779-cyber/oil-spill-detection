"""Run one full Sentinel-1 SAR download + dark-spot detection end-to-end.

Picks the smallest Sentinel-1 GRD product found over an incident, downloads it
from Copernicus Data Space (CDSE), extracts the measurement GeoTIFF, subsets a
window around the incident, downsamples to a tractable size, runs the
vectorised CFAR dark-spot detector and writes:
  - data/raw/sar/<incident>/detections.json
  - data/raw/sar/<incident>/scene.png            (dB amplitude overview)
  - data/raw/sar/<incident>/detections.png       (detections overlaid)

Usage:
  python engines/detection/run_sar_end_to_end.py <incident_id> [--band VV]
"""

import argparse
import json
import shutil
import zipfile
from pathlib import Path

import numpy as np

from engines.detection.sar_detector import SARDetector

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_unet(checkpoint: str | Path):
    """Load a trained U-Net checkpoint saved by engines/detection/train.py.

    Returns (model, config) with the model in eval mode on CPU so inference can
    run locally without a GPU.
    """
    import torch
    from engines.detection.train import UNet

    ckpt = torch.load(str(checkpoint), map_location="cpu")
    if isinstance(ckpt, dict) and "config" in ckpt and "model_state" in ckpt:
        cfg = ckpt["config"]
        model = UNet(
            in_channels=cfg.get("in_channels", 2),
            num_classes=cfg.get("num_classes", 1),
            base=cfg.get("base", 32),
        )
        model.load_state_dict(ckpt["model_state"])
    elif isinstance(ckpt, dict):
        # bare state_dict checkpoint
        model = UNet(in_channels=2, num_classes=1, base=32)
        model.load_state_dict(ckpt)
        cfg = {"in_channels": 2, "num_classes": 1, "base": 32}
    else:
        raise ValueError(f"Unrecognised checkpoint format: {checkpoint}")
    model.eval()
    return model, cfg


def to_db_channels(db: np.ndarray):
    """Turn a 2D dB array into the (H,W,2) VV/VH-normalised input U-Net expects.

    ``db`` holds sigma0 in dB (range roughly -40..0). The model normalises to
    [0,1] via (dB+40)/40, so we pass raw dB and let ``predict``'s tiling feed it.
    A single band is duplicated to (VV, VH) as the OT-dataset does.
    """
    img = np.asarray(db, dtype=np.float32)
    if img.ndim == 2:
        img = np.stack([img, img], axis=-1)
    return img


def run_unet_mask(model, cfg, db, device=None):
    """Run U-Net inference over a dB scene; returns probability map in [0,1]."""
    import torch
    from engines.detection.train import predict

    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    img = to_db_channels(db)
    patch = int(cfg.get("patch", 256))
    prob = predict(model, img, device=device, patch=patch)
    return prob

# incident_id -> (lon, lat, date_iso, name)
BENCHMARKS = {
    "mt_jipro_neftis_mumbai_2018": (72.80, 18.90, "2018-01-30", "MT Jipro Neftis"),
    "gal_constructor_mumbai_2021": (72.70, 19.80, "2021-05-29", "GAL Constructor"),
    "ennore_chennai_coastal_2017": (80.35, 13.28, "2017-03-10", "Ennore/Chennai"),
    "kandla_gulf_kutch_2023": (69.85, 22.78, "2023-02-15", "Kandla/Gulf of Kutch"),
}


def search_smallest_products(det, lon, lat, date, band, limit=10):
    """Return candidate products sorted by size ascending (all from the pass)."""
    # Day-of and +2 days after (slicks are usually visible a few days later).
    import datetime as _dt
    d = _dt.date.fromisoformat(date)
    prods = det.search_near_date_range(
        lon, lat, str(d - _dt.timedelta(days=1)), str(d + _dt.timedelta(days=3)),
        product_type="GRD", limit=limit,
    )
    for p in prods:
        p["size_mb"] = p.get("size_mb", 0)
    prods.sort(key=lambda p: p["size_mb"])
    return prods


def read_band_windowed(product_dir, lon, lat, band="VV", half_deg=0.4):
    """Read the chosen polarisation, subset a lon/lat window and downsample.

    If the measurement GeoTIFF carries a CRS (geocoded product), subset via
    rasterio window.  Otherwise fall back to the Sentinel-1 annotation
    geolocation grid (``s1_georef``) to map the incident lon/lat into pixel
    space before reading.

    Returns (downsampled_dB: np.ndarray, transform, crs, scale,
             geoloc: GeolocGrid or None).  ``transform`` may be an affine that
    only maps pixel->pixel (identity scale) when no CRS is present; callers
    should use ``geoloc`` to geo-register detections in that case.
    """
    import rasterio
    from rasterio.warp import transform_bounds

    p = Path(product_dir)
    tiffs = sorted(p.rglob("*.tiff")) or sorted(p.rglob("*.tif"))
    target = None
    for t in tiffs:
        if band.upper() in t.name.upper():
            target = t
            break
    if target is None and tiffs:
        target = tiffs[0]
    if target is None:
        raise FileNotFoundError(f"No GeoTIFF in {product_dir}")

    print(f"  reading band Geo {target.name}")
    geoloc = None
    data_is_dB = False
    with rasterio.open(target) as src:
        if src.crs is not None:
            left, bottom, right, top = transform_bounds(
                "EPSG:4326", src.crs, lon - half_deg, lat - half_deg,
                lon + half_deg, lat + half_deg,
            )
            win = rasterio.windows.from_bounds(
                left, bottom, right, top, transform=src.transform,
            )
            win = win.round_lengths().round_offsets()
            win = win.intersection(
                rasterio.windows.Window(0, 0, src.width, src.height)
            )
            if win.width <= 0 or win.height <= 0:
                raise ValueError("Incident window falls outside the product footprint")
            data = src.read(1, window=win).astype(float)
            win_transform = src.window_transform(win) * src.transform.scale(1, 1)
            crs = src.crs
        else:
            # Raw SAFE measurement: no embedded CRS. Use annotation grid.
            print("  no CRS in GeoTIFF -> using annotation geolocation grid")
            from engines.detection.s1_georef import run_safe_georef
            from engines.detection.s1_calibration import (
                load_calibration, calibrate_sigma0_db,
            )
            geoloc = run_safe_georef(Path(product_dir), band)
            c0, r0, c1, r1 = geoloc.lonlat_to_pixel_bounds(
                lon, lat, half_deg, src.width, src.height,
            )
            data = src.read(
                1, window=rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0),
            ).astype(float)
            # Apply radiometric calibration to get physical sigma0 (dB).
            calib = load_calibration(Path(product_dir), band)
            print(f"  calibration vectors: {len(calib)}")
            data = calibrate_sigma0_db(data, r0, calib)
            data_is_dB = True
            # Identity-ish transform with the window offset for later use.
            win_transform = rasterio.transform.Affine(1, 0, c0, 0, -1, r1)
            crs = "EPSG:4326"
            # Record pixel-space window origin for geo-registration.
            geoloc._window_origin = (c0, r0)

    # dB conversion (calibrated branch already returns dB values)
    if not data_is_dB:
        db = 10.0 * np.log10(np.clip(np.nan_to_num(data, nan=0.0), 1e-10, None))
    else:
        db = np.asarray(data, dtype=float)

    # Downsample so the largest dimension <= ~2000 px to keep CFAR fast.
    max_dim = 2000
    scale = 1
    if max(db.shape) > max_dim:
        scale = max(db.shape) // max_dim
        from scipy import ndimage
        db = ndimage.zoom(db, 1.0 / scale, order=1)
        win_transform = win_transform * win_transform.scale(scale, scale)
        # _window_origin is left as the FULL-image pixel origin (c0, r0);
        # the geo-registration step converts downsampled window coords back to
        # full-image coords via: full = origin + window_px * scale.
    return db, win_transform, crs, scale, geoloc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("incident_id", choices=list(BENCHMARKS))
    ap.add_argument("--band", default="VV")
    ap.add_argument("--product-index", type=int, default=0,
                    help="Index into size-sorted candidate list (default 0 = smallest)")
    ap.add_argument("--safedir", default=None,
                    help="Reuse an already-downloaded/extracted .SAFE dir (skip search+download)")
    ap.add_argument("--model", default=None,
                    help="Trained U-Net checkpoint (.pt from train.py). When set, "
                         "also runs neural oil-mask inference on the same dB scene "
                         "(CPU-only) and writes oil_mask.json + oil_mask.png.")
    ap.add_argument("--nn-threshold", type=float, default=0.5,
                    help="Probability threshold for neural oil mask (default 0.5)")
    args = ap.parse_args()

    lon, lat, date, name = BENCHMARKS[args.incident_id]

    out_dir = PROJECT_ROOT / "data" / "raw" / "sar" / args.incident_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.safedir:
        print(f"[1-2/5] Reusing pre-downloaded product: {args.safedir}")
        det = SARDetector.__new__(SARDetector)
        prod = {"name": Path(args.safedir).name, "start": date, "size_mb": 0}
        safe = Path(args.safedir)
        extracted = safe.parent
    else:
        det = SARDetector()

        print(f"[1/5] Search CDSE for GNSS GRD products over {name} ({date})")
        candidates = search_smallest_products(det, lon, lat, date, args.band)
        if not candidates:
            print("  No products found. Nothing to run.")
            return 1
        for i, c in enumerate(candidates[:8]):
            print(f"   [{i}] {c['name'][:55]} {c['size_mb']:.0f}MB {c['start'][:19]}")
        prod = candidates[args.product_index]
        print(f"  -> selected [{args.product_index}] {prod['name'][:55]} {prod['size_mb']:.0f}MB")

        print("[2/5] Download product (this may take several minutes for ~100MB-1GB)")
        dl_dir = det.download_product(prod["id"], output_dir=str(out_dir / "download"))
        print(f"  downloaded to {dl_dir}")

        extracted = Path(dl_dir)
        # Locate the .SAFE folder (may be renamed to a short id-based name)
        if any(x.is_dir() and x.name.endswith(".SAFE") for x in extracted.iterdir()):
            safe = next(x for x in extracted.iterdir() if x.is_dir() and x.name.endswith(".SAFE"))
        else:
            # Long-path-safe short name: the folder that holds annotation/measurement
            safe = next((x for x in extracted.iterdir()
                         if x.is_dir() and (x / "measurement").exists()), extracted)

    print("[3/5] Read + subset band around incident")
    db, tfm, crs, scale, geoloc = read_band_windowed(safe, lon, lat, args.band)
    print(f"  subset shape {db.shape}, min={db.min():.2f} dB max={db.max():.2f} dB")

    print("[4/5] Run CFAR dark-spot detection (vectorised)")
    detections = det.detect_dark_spots(db, threshold_db=-14.0, min_area_px=200)

    print("[5/5] Geo-register detections + write outputs")
    import rasterio.transform

    if geoloc is not None:
        # Use the annotation geolocation grid. bbox_px/centroid_px are in
        # downsampled-window pixel space; convert back to full-image col/row.
        ox, oy = geoloc._window_origin
        def to_lonlat(px_x, px_y):
            col = ox + (px_x + 0.5) * scale
            row = oy + (px_y + 0.5) * scale
            return geoloc.pixel_to_lonlat(col, row)
        for d in detections:
            bx0, by0, bx1, by1 = d["bbox_px"]
            lon0, lat0 = to_lonlat(bx0, by0)
            lon1, lat1 = to_lonlat(bx1, by1)
            d["bbox_geo"] = [round(lon0, 6), round(lat0, 6), round(lon1, 6), round(lat1, 6)]
            cx, cy = d["centroid_px"]
            clon, clat = to_lonlat(cx, cy)
            d["centroid_geo"] = [round(clon, 6), round(clat, 6)]
    else:
        for d in detections:
            bx0, by0, bx1, by1 = d["bbox_px"]
            lon0, lat1 = rasterio.transform.xy(tfm, by0, bx0)
            lon1, lat0 = rasterio.transform.xy(tfm, by1, bx1)
            d["bbox_geo"] = [round(lon0, 6), round(lat0, 6), round(lon1, 6), round(lat1, 6)]
            cx, cy = rasterio.transform.xy(tfm, d["centroid_px"][1], d["centroid_px"][0])
            d["centroid_geo"] = [round(cx, 6), round(cy, 6)]

    payload = {
        "incident_id": args.incident_id,
        "incident_name": name,
        "coords": [lon, lat],
        "product": {"name": prod["name"], "start": prod["start"], "size_mb": prod["size_mb"]},
        "band": args.band,
        "subset_shape": list(db.shape),
        "detections": detections,
    }
    with open(out_dir / "detections.json", "w") as f:
        json.dump(payload, f, indent=2)
    print(f"  {len(detections)} detections -> {out_dir / 'detections.json'}")

    # --- Optional neural (U-Net) oil-mask inference (local CPU) ---
    if args.model:
        print(f"[5b/5] Run trained U-Net oil-mask inference (CPU) -- {args.model}")
        model, cfg = load_unet(args.model)
        prob = run_unet_mask(model, cfg, db)
        mask = (prob >= args.nn_threshold).astype(np.uint8)
        print(f"  prob range [{prob.min():.3f}, {prob.max():.3f}] | "
              f"oil pixels above {args.nn_threshold}: {int(mask.sum())}")

        # Geo-register the probability map (and mask) to lon/lat so the web layer
        # can place oil on the map. Reuse the same pixel->lonlat logic as CFAR.
        import rasterio.transform
        from rasterio.transform import Affine

        hw = prob.shape  # (rows, cols) of the downsampled window

        def mask_px_to_lonlat(row, col):
            if geoloc is not None:
                ox, oy = geoloc._window_origin
                fcol = ox + (col + 0.5) * scale
                frow = oy + (row + 0.5) * scale
                return geoloc.pixel_to_lonlat(fcol, frow)
            lon, lat = rasterio.transform.xy(tfm, row, col)
            return lon, lat

        # Geo-bounds of a positive region (bounding box of all oil pixels).
        ys, xs = np.where(mask > 0)
        if ys.size:
            lons = np.empty(ys.size); lats = np.empty(ys.size)
            for k in range(ys.size):
                lons[k], lats[k] = mask_px_to_lonlat(int(ys[k]), int(xs[k]))
            reg = {
                "min_lon": round(float(lons.min()), 6),
                "max_lon": round(float(lons.max()), 6),
                "min_lat": round(float(lats.min()), 6),
                "max_lat": round(float(lats.max()), 6),
                "centroid_lon": round(float(lons.mean()), 6),
                "centroid_lat": round(float(lats.mean()), 6),
                "oil_pixels": int(mask.sum()),
                "threshold": args.nn_threshold,
            }
        else:
            reg = None

        # Downsample the probability map for a compact output fragment.
        max_dim = 512
        s = 1
        p_geo = prob
        if max(prob.shape) > max_dim:
            s = max(prob.shape) // max_dim
            from scipy import ndimage
            p_geo = ndimage.zoom(prob, 1.0 / s, order=1)
        prob_frag = [round(float(v), 4) for v in p_geo.flatten()]

        nn_payload = {
            "incident_id": args.incident_id,
            "checkpoint": str(args.model),
            "checkpoint_config": cfg,
            "threshold": args.nn_threshold,
            "prob_shape": list(prob.shape),
            "prob_downsample": s,
            "prob_flat": prob_frag,
            "bbox_geo": reg,
        }
        with open(out_dir / "oil_mask.json", "w") as f:
            json.dump(nn_payload, f, indent=2)
        print(f"  oil mask -> {out_dir / 'oil_mask.json'}")

        # Visualise NN mask overlaid on dB scene (matplotlib optional).
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(1, 2, figsize=(14, 6))
            ax[0].imshow(db, cmap="gray", vmin=-25, vmax=-5)
            ax[0].set_title("SAR dB amplitude (downsampled)")
            ax[1].imshow(db, cmap="gray", vmin=-25, vmax=-5)
            ax[1].imshow(np.ma.masked_where(mask == 0, mask), cmap="Reds",
                         alpha=0.6)
            ax[1].set_title(f"U-Net oil mask (p>={args.nn_threshold})")
            plt.tight_layout()
            plt.savefig(out_dir / "oil_mask.png", dpi=100)
            print(f"  figure -> {out_dir / 'oil_mask.png'}")
        except Exception as e:
            print(f"  (oil_mask figure skipped: {e})")

    # Visualisations (matplotlib optional)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        ax = axes[0].imshow(db, cmap="gray", vmin=-25, vmax=-5)
        axes[0].set_title("SAR dB amplitude (downsampled)")
        cbar = fig.colorbar(ax, ax=axes[0]); cbar.set_label("dB")
        axes[1].imshow(db, cmap="gray", vmin=-25, vmax=-5)
        for d in detections:
            bx0, by0, bx1, by1 = d["bbox_px"]
            from matplotlib.patches import Rectangle
            axes[1].add_patch(Rectangle((bx0, by0), bx1 - bx0, by1 - by0,
                                        fill=False, edgecolor="r", linewidth=1.5))
        axes[1].set_title(f"{len(detections)} dark-spot candidates")
        plt.tight_layout()
        plt.savefig(out_dir / "detections.png", dpi=100)
        print(f"  figure -> {out_dir / 'detections.png'}")
    except Exception as e:
        print(f"  (matplotlib figure skipped: {e})")

    print("DONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
