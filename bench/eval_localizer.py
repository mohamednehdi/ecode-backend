"""Scores the barcode localiser (app/scans/localizer.py) against the true boxes of a dataset (F3).

    python bench/eval_localizer.py [folder]     (bench/dataset_tuning, bench/documents_tuning, bench/dataset, bench/documents)

A region is a correct detection when its bounding box overlaps the true box with IoU >= 0.5 (intersection over union).
  recall     share of images where the code was found
  precision  share of returned regions that are a real code (any other region is a false alarm)
"""
import csv
import os
import sys
import time
from collections import defaultdict

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.scans.localizer import find_regions   # noqa: E402  (pure OpenCV module: no Flask needed)

HERE = os.path.dirname(os.path.abspath(__file__))
IOU_MIN = 0.5


def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def evaluate(folder):
    """One row per true code (found or not) plus per-page counts of regions returned and regions that are real codes."""
    with open(os.path.join(folder, 'labels.csv'), encoding='utf-8') as f:
        labels = list(csv.DictReader(f))
    pages = defaultdict(list)
    for r in labels:
        pages[r['file']].append(r)
    codes, page_rows = [], []
    for fname, truths in pages.items():
        gray = cv2.imread(os.path.join(folder, fname), cv2.IMREAD_GRAYSCALE)
        t0 = time.perf_counter()
        regions = find_regions(gray)
        ms = (time.perf_counter() - t0) * 1000
        boxes = [tuple(int(t[k]) for k in 'xywh') for t in truths]
        grid = [[iou(b, (g['x'], g['y'], g['w'], g['h'])) for g in regions] for b in boxes]
        real = sum(1 for j in range(len(regions)) if any(grid[i][j] >= IOU_MIN for i in range(len(boxes))))
        first = truths[0]
        page_rows.append({'kind': first.get('kind', first.get('condition')), 'regions': len(regions), 'real': real,
                          'codes': len(truths), 'ms': ms})
        for i, t in enumerate(truths):
            codes.append({'type': t['type'], 'condition': t.get('condition', t.get('kind')), 'damage': t.get('damage', '-'),
                          'found': int(any(v >= IOU_MIN for v in grid[i])), 'best_iou': max(grid[i], default=0.0)})
    return codes, page_rows


def summarise(codes, by):
    groups = defaultdict(list)
    for r in codes:
        groups[r[by]].append(r)
    print(f'{by:14s} {"codes":>6s} {"recall":>7s} {"mean IoU":>9s}')
    for key, g in groups.items():
        print(f'{key:14s} {len(g):6d} {100 * sum(x["found"] for x in g) / len(g):6.1f}% {np.mean([x["best_iou"] for x in g]):9.2f}')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    folder = args[0] if args else os.path.join(HERE, 'dataset_tuning')
    codes, pages = evaluate(folder)
    summarise(codes, 'type')
    print()
    summarise(codes, 'condition')
    if any(c['damage'] != '-' for c in codes):
        print()
        summarise(codes, 'damage')
    print()
    n_regions = sum(p['regions'] for p in pages)
    n_real = sum(p['real'] for p in pages)
    print(f'ALL: {len(codes)} codes on {len(pages)} pages | recall {100 * sum(c["found"] for c in codes) / len(codes):.1f}% | '
          f'precision {100 * n_real / max(n_regions, 1):.1f}% ({n_regions - n_real} false regions, {n_regions / len(pages):.2f} regions/page '
          f'for {len(codes) / len(pages):.2f} codes/page) | median {np.median([p["ms"] for p in pages]):.1f} ms')
    by_kind = defaultdict(list)
    for p in pages:
        by_kind[p['kind']].append(p)
    for k, g in by_kind.items():
        print(f'  {k:14s} precision {100 * sum(p["real"] for p in g) / max(sum(p["regions"] for p in g), 1):5.1f}%  '
              f'false regions/page {(sum(p["regions"] - p["real"] for p in g)) / len(g):.2f}')
