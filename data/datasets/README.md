# SAR oil-spill segmentation datasets

`engines/detection/train.py` consumes the layout below. This file documents the
public datasets you can use, where to get them, and how to prepare them.

## Expected layout (what train.py reads)

```
<data-dir>/
  images/    # 2-channel (VV, VH) sigma0-in-dB TIFF/GeoTIFF, 3+ bands allowed
    0001.tif
    0002.tif
    ...
  masks/     # single-band uint8 TIFF, same stem as the image
    0001.tif   # binary: 1 = oil, 0 = sea   OR   multi-class: 0..N-1
    0002.tif
    ...
```

- Image channels should be **sigma0 in decibels** (VV = ch0, VH = ch1). Any
  value below -40 dB is clipped; values above 0 dB are clipped to 0 by
  `train.py`'s normalisation ([-40, 0] -> [0,1]).
- If your source images are single-channel, `train.py` duplicates it into 2
  channels automatically. 2-channel VV+VH is strongly preferred.
- For multi-class datasets (oil, look-alike, ship, land, sea) run with
  `--classes 5`; class id 0 is treated as background.

---

## Option A (recommended for pixel segmentation): Zenodo Sentinel-1 sigma0

3 open-access parts with 2048x2048x2 (VV, VH) sigma0 dB images and matching
2048x2048 ground-truth binary masks. Total ~55 GB across all parts.

| Part | DOI | File(s) |
|------|-----|---------|
| I (train+val images & masks) | 10.5281/zenodo.8346860 | `01_Train_Val_Oil_Spill_images.7z` (~40.7 GB) + masks |
| II (val maps)               | 10.5281/zenodo.8253899 | images/masks |
| III (test)                  | 10.5281/zenodo.13761290 | `02_Test_images_and_ground_truth.7z` (~9.9 GB) |

Steps:

1. Open each DOI, request the download link for the `.7z`, download with your
   browser or `curl -L -o <file>.7z <url>`.
2. Extract each archive. `.7z` needs `7-Zip`:
   `7z x 01_Train_Val_Oil_Spill_images.7z -oPartI`
3. Copy the extracted image TIFFs into `data/datasets/s1_oil/images/` and the
   mask TIFFs into `data/datasets/s1_oil/masks/` (matching stems).

See `prepare_dataset.py` in this folder for a helper that copies/re-names the
variously nested Zenodo subfolders into the flat `images/`/`masks/` layout.

---

## Option B: DARTIS (Eastern Mediterranean 2019) — DLR

`DARTIS` (Dataset of oil slicks, look-alikes and other remarkable SAR
signatures) covers the Eastern Mediterranean 2019 with **3325 labelled oil
objects across 1365 image patches** plus 2290 look-alike patches.

- **Data:** https://doi.org/10.1594/PANGAEA.980773 (Yang & Singha, 2025)
- **Code / reading tools:** https://github.com/yi-jie-yang/dataset_DARTIS_2019
- Georeferenced Sentinel-1 patches + Pascal-VOC XML object masks.

Prepare: render each patch from its georaster and rasterise the VOC XML to a
class mask of `0/1` (or up to 5 classes with look-alike/ship/land/sea) and
place into `images/`/`masks/`. The DARTIS repo ships the helpers.

---

## Option C: 5-class "Oil Spill Detection Dataset" (MKLab / AUTH)

~1000 train + 110 test JPEG chips, 5 classes (oil, look-alike, ship, land,
sea). ~400 MB. Available under Terms of Use from CERETETH:
https://m4d.iti.gr/oil-spill-detection-dataset/

May be combined with Option A by mapping its class ids. Requires requesting
access from the maintainers.

---

## Option D: CSIRO Sentinel-1 chips (classification, not segmentation)

400x400 grayscale JPEGs, oil vs non-oil (1905 / 3725). Great for a
classifier/encoder pretraining but has **no pixel masks**:
https://data.csiro.au/collection/csiro:57430 (DOI 10.25919/4v55-dn16), also
mirrored on Kaggle.

---

## Recommended workflow

1. Download Option A (Zenodo) and prepare with `prepare_dataset.py`.
2. Train:
   ```
   python engines/detection/train.py --data-dir data/datasets/s1_oil \
       --epochs 60 --batch-size 16 --patch 256 --out engines/detection/models/s1_unet.pt
   ```
3. (Optional, for robustness to look-alikes) add DARTIS/MKLab 5-class patches
   and retrain with `--classes 5`.
