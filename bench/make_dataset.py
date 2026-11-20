"""Builds the labelled dataset of the decoder comparison study (F2).

    python bench/make_dataset.py [samples_per_cell]            (default 8)  -> bench/dataset/
    python bench/make_dataset.py [samples_per_cell] tuning     other seeds -> bench/dataset_tuning/ (for development)

Four code types x 22 conditions x N random contents. Every image is a page (800x600, white) holding ONE code
at a random position; the known content and the true position of the code (x, y, w, h of its bounding box in the
final image) are written to labels.csv, so a decoder is right only when it returns exactly that content and
a localiser is right when its box overlaps the true box. The random generator is seeded: the dataset is identical on every run.

Conditions: clean | blur (3) | gaussian noise (3) | JPEG compression (3) | low contrast (2) | rotation (4) |
perspective | small (2) | inverted | uneven lighting | "poor scan" (rotation + blur + noise + JPEG + low contrast).
Also writes bench/figures/dataset_examples.png (one code under every condition), used in the report.
"""
import csv
import io
import os
import sys

import barcode
import cv2
import numpy as np
import segno
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw
from pylibdmtx.pylibdmtx import encode as dmtx_encode

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'dataset')
FIGURES = os.path.join(HERE, 'figures')
PAGE_W, PAGE_H = 800, 600
TYPES = ['QRCODE', 'DataMatrix', 'CODE128', 'EAN13']
ALPHABET = np.array(list('ABCDEFGHJKLMNPQRSTUVWXYZ23456789'))


# ----------------------------------------------------------------------------------------------- base codes

def _content(kind, rng):
    if kind == 'EAN13':
        return ''.join(str(d) for d in rng.integers(0, 10, 12))          # 12 digits: the 13th is the check digit
    prefix = {'QRCODE': 'QR', 'DataMatrix': 'DM', 'CODE128': 'C128'}[kind]
    return prefix + '-' + ''.join(rng.choice(ALPHABET, 8))


def _make_code(kind, text):
    """Returns (RGB PIL image of the code with its quiet zone, exact content a decoder must return)."""
    if kind == 'QRCODE':
        buf = io.BytesIO()
        segno.make(text, error='m', micro=False).save(buf, kind='png', scale=4, border=4)
        return Image.open(buf).convert('RGB'), text
    if kind == 'DataMatrix':
        e = dmtx_encode(text.encode())
        img = Image.frombytes('RGB', (e.width, e.height), e.pixels)
        return img.resize((e.width * 4, e.height * 4), Image.NEAREST), text
    buf = io.BytesIO()
    options = dict(write_text=False, module_width=0.375, module_height=14, quiet_zone=6, dpi=200)   # ~3 px per module
    if kind == 'CODE128':
        code = barcode.get('code128', text, writer=ImageWriter())
    else:
        code = barcode.get('ean13', text, writer=ImageWriter())
        text = code.get_fullcode()                                       # with check digit
    code.write(buf, options)
    return Image.open(buf).convert('RGB'), text


def _page(kind, rng):
    text = _content(kind, rng)
    code, truth = _make_code(kind, text)
    page = Image.new('RGB', (PAGE_W, PAGE_H), 'white')
    x = int(rng.integers(60, max(61, PAGE_W - code.width - 60)))
    y = int(rng.integers(60, max(61, PAGE_H - code.height - 60)))
    page.paste(code, (x, y))
    # Position of the code itself (bars / modules, without the quiet zone), kept as a mask that follows the geometry
    ys, xs = np.where(np.array(code.convert('L')) < 128)
    mask = np.full((PAGE_H, PAGE_W, 3), 255, np.uint8)
    mask[y + ys.min():y + ys.max() + 1, x + xs.min():x + xs.max() + 1] = 0
    return np.array(page), truth, mask


# ----------------------------------------------------------------------------------------------- degradations

def blur(sigma):
    return lambda img, rng: cv2.GaussianBlur(img, (0, 0), sigma)


def noise(sigma):
    def run(img, rng):
        out = img.astype(np.float32) + rng.normal(0, sigma, img.shape).astype(np.float32)
        return np.clip(out, 0, 255).astype(np.uint8)
    return run


def jpeg(quality):
    def run(img, rng):
        ok, enc = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return cv2.imdecode(enc, cv2.IMREAD_COLOR)
    return run


def contrast(factor):
    return lambda img, rng: np.clip(128 + (img.astype(np.float32) - 128) * factor, 0, 255).astype(np.uint8)


def rotate(degrees):
    def run(img, rng):
        if degrees == 90:
            return np.ascontiguousarray(np.rot90(img))
        h, w = img.shape[:2]
        m = cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.0)
        cos, sin = abs(m[0, 0]), abs(m[0, 1])
        nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
        m[0, 2] += nw / 2 - w / 2
        m[1, 2] += nh / 2 - h / 2
        return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
    return run


def perspective(img, rng):
    h, w = img.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    jitter = rng.uniform(0.05, 0.11, 8) * np.array([w, h, w, h, w, h, w, h])
    dst = src + np.float32([[jitter[0], jitter[1]], [-jitter[2], jitter[3]],
                            [-jitter[4], -jitter[5]], [jitter[6], -jitter[7]]]) * np.float32([[1, 1], [1, 1], [0.4, 0.4], [0.4, 0.4]])
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=(255, 255, 255))


def small(scale):
    return lambda img, rng: cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def invert(img, rng):
    return 255 - img


def shading(img, rng):
    """Uneven lighting: the left side of the page is much darker than the right side."""
    ramp = np.linspace(0.35, 1.0, img.shape[1], dtype=np.float32)[None, :, None]
    return np.clip(img.astype(np.float32) * ramp, 0, 255).astype(np.uint8)


def chain(*steps):
    def run(img, rng):
        for step in steps:
            img = step(img, rng)
        return img
    return run


CONDITIONS = [
    ('clean', lambda img, rng: img),
    ('blur_1.0', blur(1.0)), ('blur_2.0', blur(2.0)), ('blur_3.0', blur(3.0)),
    ('noise_15', noise(15)), ('noise_30', noise(30)), ('noise_50', noise(50)),
    ('jpeg_30', jpeg(30)), ('jpeg_15', jpeg(15)), ('jpeg_8', jpeg(8)),
    ('contrast_0.5', contrast(0.5)), ('contrast_0.25', contrast(0.25)),
    ('rotate_10', rotate(10)), ('rotate_30', rotate(30)), ('rotate_45', rotate(45)), ('rotate_90', rotate(90)),
    ('perspective', perspective),
    ('small_0.5', small(0.5)), ('small_0.35', small(0.35)),
    ('inverted', invert),
    ('shading', shading),
    ('poor_scan', chain(rotate(5), blur(1.2), noise(15), contrast(0.7), jpeg(30))),
]


# Conditions that move the code: the true box is found by applying the same transform to the mask.
# The other conditions (blur, noise, JPEG, contrast, inversion, lighting) leave the code where it is.
GEOMETRY = {
    'rotate_10': rotate(10), 'rotate_30': rotate(30), 'rotate_45': rotate(45), 'rotate_90': rotate(90),
    'perspective': perspective, 'small_0.5': small(0.5), 'small_0.35': small(0.35), 'poor_scan': rotate(5),
}


def _true_box(mask, name, seed):
    moved = GEOMETRY[name](mask.copy(), np.random.default_rng(seed)) if name in GEOMETRY else mask
    ys, xs = np.where(moved.min(axis=2) < 128)
    return int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


# ----------------------------------------------------------------------------------------------- main

def build(samples, out=OUT, offset=0):
    os.makedirs(out, exist_ok=True)
    os.makedirs(FIGURES, exist_ok=True)
    rows = []
    for t, kind in enumerate(TYPES):
        for i in range(samples):
            # The same base page is used for every condition: differences between conditions come from the degradation only
            base, truth, mask = _page(kind, np.random.default_rng(offset + 1000 * t + i))
            for c, (name, degrade) in enumerate(CONDITIONS):
                seed = offset + 100000 + 1000 * t + 10 * i + c
                img = degrade(base.copy(), np.random.default_rng(seed))
                fname = f'{kind}_{name}_{i}.png'
                Image.fromarray(img).save(os.path.join(out, fname))
                x, y, w, h = _true_box(mask, name, seed)
                rows.append((fname, kind, name, truth, x, y, w, h))
    with open(os.path.join(out, 'labels.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['file', 'type', 'condition', 'truth', 'x', 'y', 'w', 'h'])
        w.writerows(rows)
    print(f'{len(rows)} images ({len(TYPES)} types x {len(CONDITIONS)} conditions x {samples}) in {out}')


def examples_figure(kind='QRCODE'):
    """One code under every condition, as a contact sheet for the report."""
    cell_w, cell_h, cols = 240, 180, 6
    rows_n = (len(CONDITIONS) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * cell_w, rows_n * (cell_h + 22)), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    for idx, (name, _) in enumerate(CONDITIONS):
        im = Image.open(os.path.join(OUT, f'{kind}_{name}_0.png')).convert('RGB')
        im.thumbnail((cell_w - 8, cell_h - 8))
        x, y = (idx % cols) * cell_w, (idx // cols) * (cell_h + 22)
        sheet.paste(im, (x + 4, y + 22))
        draw.text((x + 6, y + 5), name, fill=(20, 20, 20))
    path = os.path.join(FIGURES, 'dataset_examples.png')
    sheet.save(path)
    print('figure:', path)


if __name__ == '__main__':
    samples = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    if 'tuning' in sys.argv[2:]:
        # A second dataset with other seeds (other contents, other positions) used to develop and tune the
        # localiser and the decoder passes, so that the main dataset stays a fair final exam.
        build(samples, out=os.path.join(HERE, 'dataset_tuning'), offset=5_000_000)
    else:
        build(samples)
        examples_figure()
