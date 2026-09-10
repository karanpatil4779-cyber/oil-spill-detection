"""Cloud storage utility for satellite imagery.

Uploads SAR/Optical preview images to Cloudinary and returns public URLs.
Gracefully degrades if CLOUDINARY_* env vars are not set (images are
still saved locally, just not uploaded).
"""

import os
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Cloudinary is optional — if not configured, images are saved locally only.
_CLOUDINARY_AVAILABLE = None


def _is_cloudinary_configured() -> bool:
    global _CLOUDINARY_AVAILABLE
    if _CLOUDINARY_AVAILABLE is not None:
        return _CLOUDINARY_AVAILABLE
    name = os.getenv("CLOUDINARY_CLOUD_NAME")
    key = os.getenv("CLOUDINARY_API_KEY")
    secret = os.getenv("CLOUDINARY_API_SECRET")
    _CLOUDINARY_AVAILABLE = bool(name and key and secret)
    if not _CLOUDINARY_AVAILABLE:
        logger.info("Cloudinary not configured (CLOUDINARY_* env vars missing); "
                     "satellite images will be saved locally only")
    return _CLOUDINARY_AVAILABLE


def _get_cloudinary():
    """Lazy import and configure cloudinary."""
    import cloudinary
    import cloudinary.api
    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    )
    return cloudinary


def upload_image(
    image_bytes: bytes,
    folder: str,
    public_id: str,
    format: str = "png",
    caption: str = "",
    tags: list = None,
) -> dict:
    """Upload an image to Cloudinary and return metadata.

    Args:
        image_bytes: Raw image bytes (PNG/JPEG).
        folder: Cloudinary folder (e.g. "oilspill/INC-2026-0001").
        public_id: Unique filename without extension.
        format: Image format (png, jpeg).
        caption: Optional caption text.
        tags: Optional list of tags for organization.

    Returns:
        dict with keys: url, secure_url, public_id, width, height, format, bytes.
        If Cloudinary is not configured, returns local_path only.
    """
    result = {
        "url": None,
        "secure_url": None,
        "public_id": public_id,
        "caption": caption,
        "tags": tags or [],
        "local_only": True,
    }

    if _is_cloudinary_configured():
        try:
            cloudinary = _get_cloudinary()
            import cloudinary.uploader

            upload_result = cloudinary.uploader.upload(
                image_bytes,
                folder=folder,
                public_id=public_id,
                format=format,
                resource_type="image",
                tags=tags or [],
                transformation=[
                    {"width": 1200, "height": 800, "crop": "limit", "quality": "auto"},
                ],
            )
            result["url"] = upload_result.get("url")
            result["secure_url"] = upload_result.get("secure_url")
            result["public_id"] = upload_result.get("public_id")
            result["width"] = upload_result.get("width")
            result["height"] = upload_result.get("height")
            result["bytes"] = upload_result.get("bytes")
            result["format"] = upload_result.get("format")
            result["local_only"] = False
            logger.info(f"Uploaded satellite image to Cloudinary: {upload_result.get('secure_url')}")
            return result
        except Exception as e:
            logger.warning(f"Cloudinary upload failed: {e}; saving locally")

    # Fallback: save locally
    local_dir = Path("data") / "satellite_images" / folder
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"{public_id}.{format}"
    local_path.write_bytes(image_bytes)
    result["local_path"] = str(local_path)
    result["url"] = f"/data/satellite_images/{folder}/{public_id}.{format}"
    result["secure_url"] = result["url"]
    logger.info(f"Saved satellite image locally: {local_path}")
    return result


def save_sar_preview(
    sar_data_2d,
    incident_id: str,
    product_name: str = "",
    dpi: int = 100,
) -> dict:
    """Generate a SAR backscatter preview image from a 2D dB array and upload.

    Creates a false-colour SAR amplitude image with land/dark-spot overlay.

    Args:
        sar_data_2d: 2D numpy array of SAR backscatter in dB.
        incident_id: Case/incident identifier for folder organization.
        product_name: Sentinel-1 product name (for metadata).
        dpi: Image DPI for matplotlib rendering.

    Returns:
        dict with image metadata (url, secure_url, etc.)
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import io

        fig, ax = plt.subplots(1, 1, figsize=(10, 7), dpi=dpi)

        # Normalise dB range for display
        vmin, vmax = np.nanpercentile(sar_data_2d[sar_data_2d > -100], [2, 98])
        im = ax.imshow(sar_data_2d, cmap="gray", vmin=vmin, vmax=vmax, aspect="auto")
        ax.set_title(f"Sentinel-1 SAR Backscatter (VV dB)\n{product_name}", fontsize=11, color="white")
        ax.set_xlabel("Range (px)", fontsize=9, color="gray")
        ax.set_ylabel("Azimuth (px)", fontsize=9, color="gray")
        ax.tick_params(colors="gray", labelsize=8)

        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label("Backscatter (dB)", fontsize=9, color="gray")
        cbar.ax.tick_params(colors="gray", labelsize=8)

        fig.patch.set_facecolor("#0f172a")
        ax.set_facecolor("#0f172a")
        ax.title.set_color("white")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                    facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        buf.seek(0)

        public_id = f"sar_preview_{incident_id}"
        if product_name:
            # Truncate product name for cleaner Cloudinary IDs
            short = product_name.replace("_", "-")[:40]
            public_id = f"sar_{short}_{incident_id}"

        return upload_image(
            buf.read(),
            folder=f"oilspill/{incident_id}",
            public_id=public_id,
            caption=f"SAR backscatter — {product_name}",
            tags=["sar", "sentinel-1", incident_id],
        )
    except Exception as e:
        logger.warning(f"Failed to generate SAR preview: {e}")
        return {"url": None, "error": str(e)}


def save_eo_preview(
    ndhi_data_2d,
    incident_id: str,
    b11_data_2d=None,
    product_name: str = "",
    dpi: int = 100,
) -> dict:
    """Generate an EO/NDHI preview image and upload.

    Creates a side-by-side view: B11 SWIR reflectance + NDHI index with
    oil anomaly highlighting.

    Args:
        ndhi_data_2d: 2D numpy array of NDHI values.
        b11_data_2d: Optional 2D numpy array of B11 reflectance.
        incident_id: Case/incident identifier.
        product_name: Sentinel-2 product name.
        dpi: Image DPI.

    Returns:
        dict with image metadata.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import io

        has_b11 = b11_data_2d is not None
        ncols = 2 if has_b11 else 1
        fig, axes = plt.subplots(1, ncols, figsize=(6 * ncols, 5), dpi=dpi)
        if ncols == 1:
            axes = [axes]

        if has_b11:
            im0 = axes[0].imshow(b11_data_2d, cmap="viridis", aspect="auto")
            axes[0].set_title("Sentinel-2 B11 SWIR Reflectance", fontsize=10, color="white")
            fig.colorbar(im0, ax=axes[0], fraction=0.046, pad=0.04, label="Reflectance")

        im1 = axes[-1].imshow(ndhi_data_2d, cmap="RdYlGn", vmin=-0.3, vmax=0.3, aspect="auto")
        axes[-1].set_title("NDHI Hydrocarbon Index", fontsize=10, color="white")
        fig.colorbar(im1, ax=axes[-1], fraction=0.046, pad=0.04, label="NDHI")

        # Highlight oil anomalies (NDHI < threshold)
        oil_mask = ndhi_data_2d < -0.02
        if oil_mask.any():
            axes[-1].contour(oil_mask.astype(float), levels=[0.5], colors="red", linewidths=0.8)

        suptitle = f"Sentinel-2 EO Oil Confirmation — {product_name}" if product_name else "Sentinel-2 EO Oil Confirmation"
        fig.suptitle(suptitle, fontsize=11, color="white", y=1.02)

        for ax in axes:
            ax.set_facecolor("#0f172a")
            ax.tick_params(colors="gray", labelsize=8)

        fig.patch.set_facecolor("#0f172a")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                    facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        buf.seek(0)

        public_id = f"eo_ndhi_{incident_id}"
        if product_name:
            short = product_name.replace("_", "-")[:40]
            public_id = f"eo_{short}_{incident_id}"

        return upload_image(
            buf.read(),
            folder=f"oilspill/{incident_id}",
            public_id=public_id,
            caption=f"NDHI optical confirmation — {product_name}",
            tags=["eo", "sentinel-2", "ndhi", incident_id],
        )
    except Exception as e:
        logger.warning(f"Failed to generate EO preview: {e}")
        return {"url": None, "error": str(e)}
