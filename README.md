# BDryFish tools

Scripts that reproduce the derived files of the **BDryFish** dataset from its full
resolution images, and check a download against the published checksums.

- Dataset: BDryFish, Science Data Bank, https://doi.org/10.57760/sciencedb.25907 (CC BY 4.0)
- Data article: T.A. Apurbo, K.F. Ahammed, M. Abdullah, M. Islam, M.H. Belali, *BDryFish: A Smartphone
  Image Dataset of Dried Fish (Shutki) Trade Categories from Bangladeshi Markets*, Data in Brief,
  article 113359 (2026), https://doi.org/10.1016/j.dib.2026.113359

## Install

```
python -m pip install -r requirements.txt
```

Pillow is pinned to the version used to build the release, so that `resize`
reproduces the published files byte for byte.

## Use

These scripts are also included in the deposit, in `BDryFish-v4/code/`.

Unpack the two image archives and the metadata archive of the deposit into one place.
They all unpack into `BDryFish-v4/`, so that `raw/`, `resized640/`, `metadata/`,
`splits/` and `checksums/` sit side by side.

```
python bdryfish_tools.py verify   BDryFish-v4              # every file against checksums/
python bdryfish_tools.py sessions BDryFish-v4              # sessions and split from raw/ EXIF
python bdryfish_tools.py resize   BDryFish-v4 out --check  # rebuild resized640/ from raw/
```

| Command | What it rebuilds | Checked against |
|---|---|---|
| `verify` | nothing; recomputes SHA-256 of every file | `checksums/*.txt` |
| `sessions` | capture sessions at 2, 5, 10 and 30 s, and the recommended split | `metadata/images.csv` |
| `resize` | `resized640/` from `raw/` | `checksums/sha256_resized640.txt` |

Tested on the release: `sessions` reproduces all 5,778 rows of `metadata/images.csv`
with no differences, and `resize` reproduced a stratified sample of 62 images (every
device and EXIF orientation) byte for byte.

## Definitions

**Resized copy.** Apply the EXIF orientation to the pixels and set the tag to 1; scale
the long side to 640 px with Lanczos resampling (never enlarging); save as JPEG,
quality 95, 4:4:4 chroma. No padding, cropping or augmentation.

**Capture session.** Within each class and presentation (Single or Bulk), images are
taken in capture order, and a new session starts when the time since the previous
frame exceeds the threshold, when the device changes, or when the capture time is
missing.

**Recommended split.** For each class and presentation, use the coarsest threshold
(30, 10, 5, then 2 s) that gives at least four sessions; shuffle the sessions with
`random.Random('<class>|<view>|1000')`; put `max(1, round(0.25 n))` sessions in test,
`max(1, round(0.15 (n - n_test)))` in validation and the rest in training.

## Licence

Code: MIT (see `LICENSE`). Data: CC BY 4.0, from the deposit above.
