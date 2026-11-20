"""Builds realistic document pages with several barcodes among text, tables and logos (F3).

    python bench/make_documents.py [pages_per_kind]            (default 120)  -> bench/documents/
    python bench/make_documents.py [pages_per_kind] tuning     other seeds    -> bench/documents_tuning/

The single-code pages of make_dataset.py are the easy case for a localiser (a code on a blank page). Here a page
(800x1000) holds paragraphs of text, a table, a dark logo block, a grey photo-like patch and 1 to 3 codes of
random types. Each code may be degraded on its own (blurred, shrunk, tilted, white-on-black, low contrast), as on
a real label or a pasted scan. Two kinds of pages: "clean" and "scan" (noise + blur + uneven light + JPEG).

labels.csv has one row per code: file, kind, type, truth, x, y, w, h (bounding box of the code), what was done to it.
"""
import csv
import os
import sys

import cv2
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_dataset import TYPES, _content, _make_code    # noqa: E402

PAGE_W, PAGE_H = 800, 1000
WORDS = ['FACTURE', 'Total', 'TVA', '19%', 'Quantite', 'Reference', 'Date', 'Client', 'Article', 'Prix', 'unitaire',
         'Livraison', 'Commande', 'N°', '2026', 'Lot', 'Palette', 'Expedition', 'Poids', 'kg', 'Adresse', 'Tunis',
         'Progress', 'Engineering', 'Bon', 'de', 'retour', 'Designation', 'Montant', 'HT', 'TTC', '12.500', '340.00']
FONTS = [cv2.FONT_HERSHEY_SIMPLEX, cv2.FONT_HERSHEY_DUPLEX, cv2.FONT_HERSHEY_COMPLEX, cv2.FONT_HERSHEY_TRIPLEX]


# ----------------------------------------------------------------------------------------------- page background

def _text_block(page, rng, x, y, width, lines):
    font = FONTS[int(rng.integers(len(FONTS)))]
    scale = float(rng.uniform(0.45, 0.8))
    thick = int(rng.integers(1, 3))
    step = int(30 * scale + 12)
    for n in range(lines):
        text = ' '.join(rng.choice(WORDS, int(rng.integers(3, 9))))
        cv2.putText(page, text, (x, y + n * step), font, scale, (20, 20, 20), thick, cv2.LINE_AA)


def _table(page, rng, x, y, cols, rows, cell_w, cell_h):
    for c in range(cols + 1):
        cv2.line(page, (x + c * cell_w, y), (x + c * cell_w, y + rows * cell_h), (30, 30, 30), 1)
    for r in range(rows + 1):
        cv2.line(page, (x, y + r * cell_h), (x + cols * cell_w, y + r * cell_h), (30, 30, 30), 1)
    for r in range(rows):
        for c in range(cols):
            cv2.putText(page, str(rng.choice(WORDS)), (x + c * cell_w + 6, y + r * cell_h + cell_h - 9),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (20, 20, 20), 1, cv2.LINE_AA)


def _background(rng):
    page = np.full((PAGE_H, PAGE_W, 3), 255, np.uint8)
    cv2.rectangle(page, (30, 30), (PAGE_W - 30, 95), (40, 40, 40), -1)                       # logo / title bar
    cv2.putText(page, 'PROGRESS ENGINEERING', (50, 75), cv2.FONT_HERSHEY_DUPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    for _ in range(int(rng.integers(2, 4))):
        _text_block(page, rng, int(rng.integers(40, 300)), int(rng.integers(130, 900)), 400, int(rng.integers(3, 8)))
    _table(page, rng, int(rng.integers(40, 120)), int(rng.integers(400, 640)), 4, int(rng.integers(3, 6)), 160, 34)
    px, py = int(rng.integers(400, 560)), int(rng.integers(120, 200))                            # grey photo-like patch
    ramp = np.linspace(80, 200, 160)[None, :, None] + rng.normal(0, 25, (110, 160, 1))
    page[py:py + 110, px:px + 160] = np.clip(np.repeat(ramp, 3, axis=2), 0, 255).astype(np.uint8)
    return page


# ----------------------------------------------------------------------------------------------- one code, with its own damage

def _prepare_code(kind, rng):
    """Returns (RGB code image with its own damage, truth, tight box (x, y, w, h) inside that image, damage names)."""
    text = _content(kind, rng)
    pil, truth = _make_code(kind, text)
    img = np.array(pil)
    if kind == 'DataMatrix':             # the generator draws 20 px modules: bring them to ~6 px, like the other codes
        img = cv2.resize(img, None, fx=0.3, fy=0.3, interpolation=cv2.INTER_NEAREST)
    mask = np.full(img.shape, 255, np.uint8)
    ys, xs = np.where(img.min(axis=2) < 128)
    mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1] = 0
    done = []

    choices = ['none', 'none', 'blur', 'small', 'tilt', 'inverted', 'lowcontrast']
    for what in rng.choice(choices, int(rng.integers(1, 3)), replace=False):
        if what == 'small':
            f = float(rng.uniform(0.6, 0.85))
            img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
            mask = cv2.resize(mask, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        elif what == 'tilt':
            deg = float(rng.uniform(-40, 40))
            h, w = img.shape[:2]
            m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
            c, s = abs(m[0, 0]), abs(m[0, 1])
            nw, nh = int(h * s + w * c), int(h * c + w * s)
            m[0, 2] += nw / 2 - w / 2
            m[1, 2] += nh / 2 - h / 2
            img = cv2.warpAffine(img, m, (nw, nh), borderValue=(255, 255, 255))
            mask = cv2.warpAffine(mask, m, (nw, nh), borderValue=(255, 255, 255))
        elif what == 'blur':
            img = cv2.GaussianBlur(img, (0, 0), float(rng.uniform(0.8, 1.4)))
        elif what == 'inverted':
            img = 255 - img
        elif what == 'lowcontrast':
            img = np.clip(128 + (img.astype(np.float32) - 128) * 0.4, 0, 255).astype(np.uint8)
        else:
            continue
        done.append(what)
    ys, xs = np.where(mask.min(axis=2) < 128)
    box = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    return img, truth, box, done or ['none']


def _place_codes(page, rng):
    """Pastes 1 to 3 codes without overlap. Returns one record per code."""
    placed, occupied = [], []
    for _ in range(int(rng.integers(1, 4))):
        kind = TYPES[int(rng.integers(len(TYPES)))]
        img, truth, (bx, by, bw, bh), done = _prepare_code(kind, rng)
        h, w = img.shape[:2]
        for _try in range(60):                                                        # find a free spot
            x = int(rng.integers(20, PAGE_W - w - 20))
            y = int(rng.integers(110, PAGE_H - h - 20))
            if all(x + w + 12 < ox or ox + ow + 12 < x or y + h + 12 < oy or oy + oh + 12 < y for ox, oy, ow, oh in occupied):
                break
        else:
            continue
        page[y:y + h, x:x + w] = img
        occupied.append((x, y, w, h))
        placed.append({'type': kind, 'truth': truth, 'x': x + bx, 'y': y + by, 'w': bw, 'h': bh, 'damage': '+'.join(done)})
    return placed


def _scan(page, rng):
    """Page-level scan quality: noise, blur, uneven lighting, JPEG (no geometry change: boxes stay valid)."""
    img = cv2.GaussianBlur(page, (0, 0), 0.8).astype(np.float32)
    img = img * np.linspace(0.65, 1.0, PAGE_W, dtype=np.float32)[None, :, None]
    img += rng.normal(0, 12, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    ok, enc = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 40])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)


def build(pages, out, offset):
    os.makedirs(out, exist_ok=True)
    rows = []
    for kind in ('clean', 'scan'):
        for i in range(pages):
            seed = offset + (0 if kind == 'clean' else 500_000) + i
            rng = np.random.default_rng(seed)
            page = _background(rng)
            codes = _place_codes(page, rng)
            if kind == 'scan':
                page = _scan(page, rng)
            fname = f'doc_{kind}_{i:03d}.png'
            Image.fromarray(page).save(os.path.join(out, fname))
            for c in codes:
                rows.append([fname, kind, c['type'], c['truth'], c['x'], c['y'], c['w'], c['h'], c['damage']])
    with open(os.path.join(out, 'labels.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['file', 'kind', 'type', 'truth', 'x', 'y', 'w', 'h', 'damage'])
        w.writerows(rows)
    print(f'{2 * pages} pages, {len(rows)} codes in {out}')


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    if 'tuning' in sys.argv[2:]:
        build(n, os.path.join(HERE, 'documents_tuning'), 7_000_000)
    else:
        build(n, os.path.join(HERE, 'documents'), 0)
