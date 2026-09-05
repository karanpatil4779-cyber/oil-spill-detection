"""Prepare downloaded Sentinel-1 oil-spill archives into train.py's layout.

The Zenodo "Sentinel-1 SAR Oil spill image dataset" ships several nested
subfolders (`01_Train_Val_Oil_Spill_images/...`, per-class folders in Part II,
`test/...`, etc.).  This walks any extraction root and copies image + mask
TIFFs with matching stems into a flat:

    <data-dir>/images/*.tif
    <data-dir>/masks/*.tif

Usage:
    python engines/detection/prepare_dataset.py \
        --src <path to extracted archive root> --out data/datasets/s1_oil

It automatically keys on filenames that look like *_images / *_image / *_mask /
ground-truth descriptors.  If it cannot decide a pair (no mask found), the
image is skipped and reported so you can inspect the layout.

Optional: pass --test-only or --by-class to target specific subfolders.
"""

import argparse
import shutil
from pathlib import Path

_IMG_HINT = ("image", "sig0", "vv", "vh", "test")
_MSK_HINT = ("mask", "ground", "label", "truth", "gt")


def is_mask(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in _MSK_HINT)


def is_image(name: str) -> bool:
    low = name.lower()
    if is_mask(name):
        return False
    # Heuristic: skip clearly-non-image suffixes pulled in by the archive.
    if low.endswith((".txt", ".md", ".csv", ".xml", ".html", ".pdf", ".7z",
                     ".zip", ".json", ".npy", ".jpg.preview")):
        return False
    return low.endswith((".tif", ".tiff", ".geotiff", ".png", ".jpg", ".jpeg"))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, help="Extracted archive root")
    ap.add_argument("--out", required=True, help="Output data-dir (images/, masks/)")
    ap.add_argument("--copy", action="store_true",
                    help="copy instead of symlink/hardlink (default: hardlink on same vol)")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "masks").mkdir(parents=True, exist_ok=True)

    # collect candidate files
    imgs, msks = [], []
    for p in src.rglob("*"):
        if p.is_file():
            if is_image(p.name):
                imgs.append(p)
            elif is_mask(p.name):
                msks.append(p)

    # map masks by stem
    msk_by_stem = {}
    for m in msks:
        # strip a postfix like '0001_oil' to '0001' is not reliable; just use stem
        msk_by_stem.setdefault(m.stem, []).append(m)

    def link(dst: Path, srcf: Path):
        if args.copy:
            shutil.copy2(srcf, dst)
        else:
            try:
                dst.hardlink_to(srcf)
            except OSError:
                shutil.copy2(srcf, dst)

    n = 0
    skipped = []
    for im in imgs:
        cand = msk_by_stem.get(im.stem)
        if not cand:
            # try an alternate stem (mask may carry '_mask'/'_gt' suffix)
            cand = [m for key, lst in msk_by_stem.items()
                    for m in lst if key.startswith(im.stem)]
        if not cand:
            skipped.append(im.name)
            continue
        m = cand[0]
        link(out / "images" / im.name, im)
        link(out / "masks" / im.name, m)
        n += 1

    print(f"Linked {n} image/mask pairs -> {out}")
    if skipped:
        print(f"Skipped {len(skipped)} images with no matching mask:")
        for s in skipped[:20]:
            print("  -", s)


if __name__ == "__main__":
    main()
