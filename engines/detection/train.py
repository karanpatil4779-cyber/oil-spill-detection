"""U-Net training for SAR oil-spill segmentation.

Replaces / complements the classical CFAR ``SARDetector`` with a learned
pixel-wise segmentation model.  Designed for 2-channel Sentinel-1 sigma0 dB
inputs (VV and VH) — the same georeferenced format the detection stage reads
through :mod:`engines.detection.s1_calibration` — and binary oil/not-oil masks.

Primary training source: the Zenodo "Sentinel-1 SAR Oil spill image dataset"
for train/validate/test deep learning models:

    Part I   train+val images & masks  https://zenodo.org/records/8346860
    Part II  val images & masks        https://zenodo.org/records/8253899
    Part III test images & masks       https://zenodo.org/records/13761290

Format: images are ``2048x2048x2`` TIFFs (channel 0 = VV sigma0 dB, channel 1 =
VH sigma0 dB); each has a matching ``2048x2048`` mask TIFF (1 = oil, 0 = sea).

Altternative / multi-class (oil, look-alike, ship, land, sea) DARTIS-derived
datasets are accepted in a second mode so a 2(3+)-channel image with a 0..N-1
label mask trains with CrossEntropyLoss instead of Dice/BCE.  See SECTIONS for
layout expectations.

Usage (binary, Zenodo layout):
    python engines/detection/train.py \
        --data-dir data/datasets/s1_oil \
        --epochs 60 --batch-size 16 --patch 256 --num-workers 0 \
        --out models/s1_unet.pt

Usage (multi-class / DARTIS 5-class):
    python engines/detection/train.py \
        --data-dir data/datasets/dartis --classes 5 \
        --epochs 60 --batch-size 16 --patch 256 --out models/s1_unet_5c.pt
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torch.optim as optim
    from torch.utils.data import DataLoader, Dataset
    from torch.utils.data.dataloader import default_collate
except ImportError as e:  # pragma: no cover - env guard
    raise SystemExit(f"torch is required but not installed: {e}")

try:
    import rasterio
except ImportError:
    rasterio = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ----------------------------------------------------------------------------
# Data layout helpers (documentation + validation)
# ----------------------------------------------------------------------------

PREPARED_LAYOUT = """Dataset directory layout (see also data/datasets/README):

Binary (Zenodo) layout:
    <data-dir>/
      images/           # 2048x2048x2 TIFF (VV, VH sigma0 dB)
        0001.tif
        ...
      masks/            # 2048x2048 uint8 TIFF (1 = oil, 0 = sea)
        0001.tif
        ...

Semantic -> binary (oil-vs-rest) layout (any 5-class dataset, e.g. DARTIS):
    <data-dir>/
      images/           # 2+ channel TIFF (VV, VH[, VV+VH variants])
      masks/            # single band label TIFF with class ids 0..N-1
        (class 0 ignored / considered background)

The training script discovers jpeg/jpg/png/tif/tiff/geotiff entries and picks
matching masks by stem name.
"""

# ----------------------------------------------------------------------------
# U-Net
# ----------------------------------------------------------------------------

class _DoubleConv(nn.Module):
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.seq = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.seq(x)


class UNet(nn.Module):
    """Standard encoder-decoder U-Net.

    Args:
        in_channels: number of input bands (2 for VV+VH).
        num_classes: output classes. 1 => binary sigmoid; >1 => softmax.
        base: channel multiplier for the first block (16-64 typical).
    """

    def __init__(self, in_channels: int = 2, num_classes: int = 1, base: int = 32):
        super().__init__()
        self.num_classes = num_classes
        # encoder
        self.e1 = _DoubleConv(in_channels, base)
        self.e2 = _DoubleConv(base, base * 2)
        self.e3 = _DoubleConv(base * 2, base * 4)
        self.e4 = _DoubleConv(base * 4, base * 8)
        # bottleneck
        self.b = _DoubleConv(base * 8, base * 16)
        # decoder
        self.d4 = _DoubleConv(base * 8 + base * 8, base * 8)
        self.d3 = _DoubleConv(base * 4 + base * 4, base * 4)
        self.d2 = _DoubleConv(base * 2 + base * 2, base * 2)
        self.d1 = _DoubleConv(base + base, base)
        self.pool = nn.MaxPool2d(2)
        self.up4 = nn.ConvTranspose2d(base * 16, base * 8, 2, stride=2)
        self.up3 = nn.ConvTranspose2d(base * 8, base * 4, 2, stride=2)
        self.up2 = nn.ConvTranspose2d(base * 4, base * 2, 2, stride=2)
        self.up1 = nn.ConvTranspose2d(base * 2, base, 2, stride=2)
        self.out = nn.Conv2d(base, num_classes, 1)

    def forward(self, x):
        x1 = self.e1(x)
        x2 = self.e2(self.pool(x1))
        x3 = self.e3(self.pool(x2))
        x4 = self.e4(self.pool(x3))
        xb = self.b(self.pool(x4))

        x = self.d4(torch.cat([self.up4(xb), x4], dim=1))
        x = self.d3(torch.cat([self.up3(x), x3], dim=1))
        x = self.d2(torch.cat([self.up2(x), x2], dim=1))
        x = self.d1(torch.cat([self.up1(x), x1], dim=1))
        return self.out(x)


# ----------------------------------------------------------------------------
# Dataset
# ----------------------------------------------------------------------------

_IM_EXT = (".tif", ".tiff", ".geotiff", ".jpg", ".jpeg", ".png")


def _read_tif(path: Path, out_dtype: np.dtype = np.float32) -> np.ndarray:
    """Read a raster as an ndarray; if it is a multiband VV/VH stack, return HWC."""
    if rasterio is not None:
        with rasterio.open(path) as src:
            data = src.read().astype(out_dtype)
        if data.ndim == 3 and data.shape[0] == 1:
            data = data[0]
        else:
            data = np.moveaxis(data, 0, -1)  # C,H,W -> H,W,C
        return data
    # last-resort numpy load (for plain npy/npz experimentation)
    return np.load(path).astype(out_dtype)


class OilDataset(Dataset):
    """Patched SAR-segmentation dataset.

    Expects ``<data-dir>/images`` and ``<data-dir>/masks``.  Each image triplet
    is either 2-channel (VV, VH) or 3+ channel.  Images are normalised to
    dB-range ``(-40, 0)`` (padded where a single channel exists).  Masks are
    read as class id (uint8).

    Random 256->patch crops during training; centre crop during evaluation.
    """

    def __init__(self, root: Path, patch: int = 256, train: bool = True,
                 num_classes: int = 1, transforms: bool = True):
        self.patch = patch
        self.train = train
        self.num_classes = num_classes
        self.transforms = transforms

        img_root, msk_root = root / "images", root / "masks"
        if not img_root.is_dir() or not msk_root.is_dir():
            raise FileNotFoundError(
                f"Expected {img_root} and {msk_root} directories to exist.\n"
                + PREPARED_LAYOUT
            )
        img_files = sorted(
            [p for p in img_root.iterdir() if p.suffix.lower() in _IM_EXT]
        )
        self.items = []
        for im in img_files:
            stem = im.stem
            cands = [
                p for p in msk_root.iterdir()
                if p.stem == stem and p.suffix.lower() in _IM_EXT
            ]
            if cands:
                self.items.append((im, cands[0]))
        if not self.items:
            raise RuntimeError(f"No image/mask pairs found under {root}")

    def __len__(self):
        return len(self.items)

    def _paired_read(self, img_path, msk_path):
        img = _read_tif(img_path).astype(np.float32)
        msk = _read_tif(msk_path, out_dtype=np.uint8)

        # normalise dB image(s) to [-40,0]; turn 2D single-channel into 2ch
        if img.ndim == 2:
            img = img[..., None]
            img = np.concatenate([img, img], axis=-1)  # duplicate to VV,VH
        img = np.clip((img + 40.0) / 40.0, 0.0, 1.0)  # -> [0,1]
        if img.ndim == 3 and img.shape[-1] == 2:
            img = img  # VV,VH
        elif img.ndim == 3:
            img = img[..., :2]
        if msk.ndim == 3:
            msk = msk[..., 0]
        msk = msk.astype(np.long)
        if self.num_classes == 1:
            msk = (msk > 0).astype(np.long)  # binary: any foreground = oil
        return img, msk

    def __getitem__(self, idx):
        img_path, msk_path = self.items[idx]
        img, msk = self._paired_read(img_path, msk_path)
        h, w = img.shape[:2]

        if self.train and self.transforms:
            ph = pw = self.patch
            y = random.randint(0, max(h - ph, 0))
            x = random.randint(0, max(w - pw, 0))
            img = img[y:y + ph, x:x + pw]
            msk = msk[y:y + ph, x:x + pw]
            if random.random() < 0.5:
                img, msk = img[:, ::-1], msk[:, ::-1]
            if random.random() < 0.5:
                img, msk = img[::-1], msk[::-1]
        else:
            # centre crop
            ph = pw = self.patch
            y = max((h - ph) // 2, 0); x = max((w - pw) // 2, 0)
            img = img[y:y + ph, x:x + pw]
            msk = msk[y:y + ph, x:x + pw]

        img = torch.from_numpy(np.ascontiguousarray(np.moveaxis(img, -1, 0)))
        msk = torch.from_numpy(np.ascontiguousarray(msk))
        return img, msk


# ----------------------------------------------------------------------------
# Losses & metrics
# ----------------------------------------------------------------------------

def dice_loss(pred, target, eps=1.0):
    """Soft Dice loss; pred expected already as probabilities (0..1)."""
    pred = pred.reshape(pred.size(0), -1)
    target = target.reshape(target.size(0), -1).float()
    inter = (pred * target).sum(1)
    denom = pred.sum(1) + target.sum(1) + eps
    return (1.0 - (2.0 * inter + eps) / denom).mean()


def bce_with_dice(pred_logit, target):
    target = target.float()
    bce = F.binary_cross_entropy_with_logits(pred_logit, target)
    dice = dice_loss(torch.sigmoid(pred_logit), target)
    return bce + dice


def iou_score(pred_bin, target_bin, eps=1.0):
    inter = (pred_bin & target_bin).sum().float()
    union = (pred_bin | target_bin).sum().float() + eps
    return (inter / union).item()


# ----------------------------------------------------------------------------
# Training loop
# ----------------------------------------------------------------------------

def train_one_epoch(model, loader, opt, device, num_classes):
    model.train()
    total_loss = 0.0
    t0 = time.time()
    for bi, (x, y) in enumerate(loader):
        x = x.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)
        opt.zero_grad()
        out = model(x)
        if num_classes == 1:
            loss = bce_with_dice(out, y.unsqueeze(1))
        else:
            loss = F.cross_entropy(out, y)
        loss.backward()
        opt.step()
        total_loss += loss.item() * x.size(0)
    return total_loss / max(len(loader.dataset), 1), time.time() - t0


@torch.no_grad()
def evaluate(model, loader, device, num_classes):
    model.eval()
    losses, ious = [], []
    for x, y in loader:
        x = x.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)
        out = model(x)
        if num_classes == 1:
            loss = bce_with_dice(out, y.unsqueeze(1))
            pred = (torch.sigmoid(out) > 0.5).squeeze(1).bool()
        else:
            loss = F.cross_entropy(out, y)
            pred = out.argmax(1)
            yb = (y > 0)  # binary oil-vs-rest of prediction
            pb = (pred > 0)
            ious.append(iou_score(pb, yb))
        losses.append(loss.item())
    mean_loss = float(np.mean(losses))
    mean_iou = float(np.mean(ious)) if ious else None
    return mean_loss, mean_iou


def run_train(args):
    device = torch.device(args.device if args.device else
                          ("cuda" if torch.cuda.is_available() else "cpu"))
    print(f"[train] device={device}")

    root = Path(args.data_dir)
    train_ds = OilDataset(root, patch=args.patch, train=True,
                          num_classes=args.classes)
    val_path = Path(args.val_dir) if args.val_dir else None
    if val_path is not None and val_path.is_dir():
        val_ds = OilDataset(val_path, patch=args.patch, train=False,
                            num_classes=args.classes)
    else:
        # hold out last 10%
        n = len(train_ds)
        split = int(n * 0.9)
        val_ds = OilDataset(root, patch=args.patch, train=False,
                            num_classes=args.classes)
        # best-effort: use a raw index split via torch Subset
        rng = random.Random(42)
        idx = list(range(n))
        rng.shuffle(idx)
        train_ds = torch.utils.data.Subset(train_ds, idx[:split])
        val_ds = torch.utils.data.Subset(val_ds, idx[split:])

    train_loader = DataLoader(train_ds, batch_size=args.batch_size,
                              shuffle=True, num_workers=args.num_workers,
                              pin_memory=(device.type == "cuda"))
    val_loader = DataLoader(val_ds, batch_size=args.batch_size,
                            shuffle=False, num_workers=args.num_workers,
                            pin_memory=(device.type == "cuda"))
    print(f"[train] train={len(train_ds)} val={len(val_ds)}")

    model = UNet(in_channels=2, num_classes=args.classes, base=args.base)
    model.to(device)
    opt = optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.wd)
    sched = optim.lr_scheduler.ReduceLROnPlateau(opt, mode="min", patience=6,
                                                 factor=0.5)

    best = float("inf")
    for epoch in range(1, args.epochs + 1):
        loss, dt = train_one_epoch(model, train_loader, opt, device, args.classes)
        val_loss, val_iou = evaluate(model, val_loader, device, args.classes)
        sched.step(val_loss)
        msg = (f"epoch {epoch:3d}/{args.epochs}  loss={loss:.4f}  "
               f"val_loss={val_loss:.4f}")
        if val_iou is not None:
            msg += f"  val_iou={val_iou:.4f}"
        msg += f"  ({dt:.1f}s)"
        print(msg)
        if val_loss < best:
            best = val_loss
            model.cpu()
            torch.save({
                "model_state": model.state_dict(),
                "config": {
                    "in_channels": 2, "num_classes": args.classes, "base": args.base,
                    "patch": args.patch,
                },
                "loss": best,
            }, args.out)
            model.to(device)
            print(f"    * saved {args.out} (val_loss={best:.4f})")

    print(f"[train] done. best val_loss={best:.4f} -> {args.out}")
    return 0


# ----------------------------------------------------------------------------
# Inference
# ----------------------------------------------------------------------------

@torch.no_grad()
def predict(model, img, device=None, patch=256):
    """Run a 2D dB image (H,W,2 or H,W) through the model; returns prob map.

    Image is tiled to a multiple of ``patch`` to keep memory flat, prediction
    merged, output resized to original HxW in [0,1] (binary model).
    """
    import torch.nn.functional as F
    device = device or torch.device("cpu")
    model.to(device).eval()
    img = np.asarray(img, dtype=np.float32)
    if img.ndim == 2:
        img = np.stack([img, img], axis=-1)
    h, w = img.shape[:2]
    ph = ((h + patch - 1) // patch) * patch
    pw = ((w + patch - 1) // patch) * patch
    img_t = torch.from_numpy(np.moveaxis(img, -1, 0)).to(device)
    if img_t.ndim == 2:
        img_t = img_t.unsqueeze(0)
    pad = F.pad(img_t, (0, pw - w, 0, ph - h), mode="constant", value=0.0)
    pad = pad.unsqueeze(0)  # -> (1, C, ph, pw)
    out = torch.zeros((1, 1, ph, pw), device=device)
    for y in range(0, ph, patch):
        for x in range(0, pw, patch):
            tile = pad[:, :, y:y + patch, x:x + patch]
            r = model(tile)
            if model.num_classes == 1:
                out[:, :, y:y + patch, x:x + patch] = torch.sigmoid(r)
            else:
                out[:, :, y:y + patch, x:x + patch] = (
                    torch.softmax(r, 1)[:, 0:1]
                )
    return out[0, 0, :h, :w].cpu().numpy()


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True,
                    help="Dataset root with images/ and masks/ (see PREPARED_LAYOUT)")
    ap.add_argument("--val-dir", default=None,
                    help="Optional separate validation root (default: 10-percent hold-out)")
    ap.add_argument("--classes", type=int, default=1,
                    help="num output classes (1=oil-vs-rest sigmoid, 5=DARTIS-style)")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--patch", type=int, default=256)
    ap.add_argument("--base", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--wd", type=float, default=1e-4)
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument("--device", default=None,
                    help="torch device, e.g. 'cpu'/'cuda' (default: auto)")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "engines" / "detection" /
                                          "models" / "s1_unet.pt"),
                    help="checkpoint output path (.pt)")
    args = ap.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    return run_train(args)


if __name__ == "__main__":
    raise SystemExit(main())
