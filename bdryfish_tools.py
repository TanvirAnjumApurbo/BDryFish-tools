"""Reproduce the derived files of the BDryFish deposit from its full resolution images.

BDryFish: https://doi.org/10.57760/sciencedb.25907 (CC BY 4.0)

Unpack the deposit so that <root>/raw/, <root>/resized640/, <root>/metadata/,
<root>/splits/ and <root>/checksums/ sit together, then:

    python bdryfish_tools.py verify   <root>   check every file against the SHA-256 manifests
    python bdryfish_tools.py resize   <root> <out_dir> [--check]
                                               rebuild resized640/ from raw/
    python bdryfish_tools.py sessions <root> [--out sessions.csv]
                                               rebuild capture sessions and the recommended split
                                               from the EXIF of raw/, and compare them with
                                               metadata/images.csv

The resize recipe is the one used for the release: apply the EXIF orientation to
the pixels and set the tag to 1, scale the long side to 640 px with Lanczos
resampling (never enlarging), and save as JPEG at quality 95 with 4:4:4 chroma.
Byte identical output needs the same Pillow and libjpeg build; with a different
build the pixels agree to within JPEG rounding but the bytes can differ.
"""
import argparse
import collections
import csv
import datetime
import hashlib
import os
import random
import sys

from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None

LONG_SIDE, QUALITY = 640, 95
GAPS = (2, 5, 10, 30)          # seconds
GAP_PREF = (30, 10, 5, 2)      # coarsest first
MIN_GROUPS = 4
TEST_FRAC, VAL_FRAC, SEED = 0.25, 0.15, 1000


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 22), b''):
            h.update(block)
    return h.hexdigest()


def images(root, tree='raw'):
    """(class, view, filename) for every image, in capture order within class and view."""
    base = os.path.join(root, tree)
    out = []
    for cls in sorted(os.listdir(base)):
        for view in ('Bulk', 'Single'):
            d = os.path.join(base, cls, view)
            if os.path.isdir(d):
                out += [(cls, view, f) for f in sorted(os.listdir(d)) if f.lower().endswith('.jpg')]
    return out


# ---------------------------------------------------------------- verify
def cmd_verify(root):
    bad = total = 0
    for manifest in sorted(os.listdir(os.path.join(root, 'checksums'))):
        with open(os.path.join(root, 'checksums', manifest), encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                digest, rel = line.rstrip('\n').split('  ', 1)
                total += 1
                path = os.path.join(root, rel)
                if not os.path.exists(path) or sha256(path) != digest:
                    bad += 1
                    print('FAILED', rel)
    print('%d files checked, %d failed' % (total, bad))
    return 1 if bad else 0


# ---------------------------------------------------------------- resize
def resize_one(src, dst):
    im = Image.open(src)
    im = ImageOps.exif_transpose(im)          # rotation goes into the pixels
    ex = im.getexif()
    ex.get_ifd(0x8769)                        # keep the Exif IFD when re-serialising
    ex[274] = 1                               # the pixels are upright now
    im = im.convert('RGB')
    w, h = im.size
    s = LONG_SIDE / max(w, h)
    if s < 1:
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im.save(dst, 'JPEG', quality=QUALITY, subsampling=0, optimize=True, exif=ex.tobytes())


def cmd_resize(root, out, check):
    expected = {}
    if check:
        with open(os.path.join(root, 'checksums', 'sha256_resized640.txt'), encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    d, rel = line.rstrip('\n').split('  ', 1)
                    expected[rel] = d
    same = differ = 0
    for n, (cls, view, fn) in enumerate(images(root), 1):
        dst = os.path.join(out, 'resized640', cls, view, fn)
        resize_one(os.path.join(root, 'raw', cls, view, fn), dst)
        if check:
            if sha256(dst) == expected.get('resized640/%s/%s/%s' % (cls, view, fn)):
                same += 1
            else:
                differ += 1
        if n % 500 == 0:
            print('  %d images' % n, flush=True)
    if check:
        print('%d byte identical to the release, %d differ' % (same, differ))
    return 0


# ---------------------------------------------------------------- sessions
def exif_time(path):
    """(capture instant in seconds or None, device string) from EXIF."""
    ex = Image.open(path).getexif()
    ifd = ex.get_ifd(0x8769)
    dto = str(ifd.get(0x9003, '') or '').strip('\x00 ')
    sub = str(ifd.get(0x9291, '') or '').strip('\x00 ')
    make = str(ex.get(0x010F, '') or '')
    model = str(ex.get(0x0110, '') or '')
    dev = ' '.join(('%s %s' % (make, model)).replace('\x00', ' ').split()) or 'unknown'
    if not dto:
        return None, dev, '', ''
    d, t = dto.split(' ')
    y, mo, da = (int(x) for x in d.split(':'))
    hh, mi, ss = (int(x) for x in t.split(':'))
    ms = sub.ljust(3, '0')[:3]
    ms = int(ms) if ms.isdigit() else 0
    return datetime.datetime(y, mo, da, hh, mi, ss).timestamp() + ms / 1000.0, dev, dto, sub


def cmd_sessions(root, out):
    rows = []
    by_cell = collections.defaultdict(list)
    for cls, view, fn in images(root):
        t, dev, dto, sub = exif_time(os.path.join(root, 'raw', cls, view, fn))
        by_cell[(cls, view)].append((fn, t, dev))

    groups = {}
    for (cls, view), items in by_cell.items():
        for g in GAPS:
            prev_t = prev_dev = None
            bid = 0
            for fn, t, dev in items:
                if t is None or prev_t is None or dev != prev_dev or t - prev_t > g:
                    bid += 1
                prev_t, prev_dev = t, dev
                groups[(fn, g)] = '%s_%s_g%02ds_b%03d' % (cls, view, g, bid)

    split, chosen_gap = {}, {}
    for (cls, view), items in sorted(by_cell.items()):
        chosen = GAP_PREF[-1]
        for g in GAP_PREF:
            if len({groups[(fn, g)] for fn, _, _ in items}) >= MIN_GROUPS:
                chosen = g
                break
        ids = sorted({groups[(fn, chosen)] for fn, _, _ in items})
        random.Random('%s|%s|%d' % (cls, view, SEED)).shuffle(ids)
        n_te = max(1, round(TEST_FRAC * len(ids)))
        n_va = max(1, round(VAL_FRAC * (len(ids) - n_te)))
        lab = {g: 'test' if i < n_te else ('val' if i < n_te + n_va else 'train')
               for i, g in enumerate(ids)}
        for fn, _, _ in items:
            split[fn] = lab[groups[(fn, chosen)]]
            chosen_gap[fn] = chosen
        for fn, _, _ in items:
            rows.append({'image_id': fn, 'class': cls, 'view': view,
                         **{'group_%ds' % g: groups[(fn, g)] for g in GAPS},
                         'group_canonical': groups[(fn, chosen_gap[fn])],
                         'canonical_gap_s': str(chosen_gap[fn]),
                         'split_single': split[fn] if view == 'Single' else '',
                         'split_bulk': split[fn] if view == 'Bulk' else ''})

    if out:
        with open(out, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    ref_path = os.path.join(root, 'metadata', 'images.csv')
    if os.path.exists(ref_path):
        with open(ref_path, encoding='utf-8') as f:
            ref = {r['image_id']: r for r in csv.DictReader(f)}
        cols = [k for k in rows[0] if k not in ('image_id', 'class', 'view')]
        mismatch = sum(1 for r in rows for k in cols if ref[r['image_id']][k] != r[k])
        print('%d images; %d mismatching fields against metadata/images.csv' % (len(rows), mismatch))
        return 1 if mismatch else 0
    print('%d images' % len(rows))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    v = sub.add_parser('verify')
    v.add_argument('root')
    r = sub.add_parser('resize')
    r.add_argument('root')
    r.add_argument('out')
    r.add_argument('--check', action='store_true')
    s = sub.add_parser('sessions')
    s.add_argument('root')
    s.add_argument('--out')
    a = ap.parse_args()
    if a.cmd == 'verify':
        return cmd_verify(a.root)
    if a.cmd == 'resize':
        return cmd_resize(a.root, a.out, a.check)
    return cmd_sessions(a.root, a.out)


if __name__ == '__main__':
    sys.exit(main())
