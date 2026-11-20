"""Trains the scoring model of the barcode localiser (F3). Uses ONLY the two tuning datasets.

    python bench/train_localizer.py

Candidates found by app/scans/localizer.py are labelled with the true boxes: IoU >= 0.5 with a real code = positive,
IoU < 0.2 with every code = negative (in-between candidates are skipped). A logistic regression (plain NumPy,
Newton's method, L2 penalty) is fitted on 80 % of the PAGES and checked on the other 20 %, then refitted on all
pages and written to app/scans/localizer_model.json. The final datasets (bench/dataset, bench/documents) are never read.
"""
import csv
import json
import os
import sys
from collections import defaultdict

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.scans.localizer import FEATURES, candidate_regions   # noqa: E402
from eval_localizer import iou                                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDERS = [os.path.join(HERE, 'dataset_tuning'), os.path.join(HERE, 'documents_tuning')]
OUT = os.path.join(ROOT, 'app', 'scans', 'localizer_model.json')


def collect():
    rows = []                                                       # (page id, features, label)
    for folder in FOLDERS:
        pages = defaultdict(list)
        with open(os.path.join(folder, 'labels.csv'), encoding='utf-8') as f:
            for r in csv.DictReader(f):
                pages[r['file']].append(r)
        for name, truths in pages.items():
            boxes = [dict(zip('xywh', (int(t[k]) for k in 'xywh'))) for t in truths]
            gray = cv2.imread(os.path.join(folder, name), cv2.IMREAD_GRAYSCALE)
            for c in candidate_regions(gray):
                best = max(iou(tuple(b[k] for k in 'xywh'), (c['x'], c['y'], c['w'], c['h'])) for b in boxes)
                if best >= 0.5:
                    rows.append((folder + name, c['features'], 1))
                elif best < 0.2:
                    rows.append((folder + name, c['features'], 0))
    return rows


def fit(x, y, l2=1.0, steps=60):
    """Logistic regression by Newton's method; returns weights and bias (features already standardised)."""
    x1 = np.hstack([x, np.ones((len(x), 1))])
    w = np.zeros(x1.shape[1])
    penalty = np.eye(x1.shape[1]) * l2
    penalty[-1, -1] = 0                                              # the bias is not penalised
    for _ in range(steps):
        p = 1 / (1 + np.exp(-np.clip(x1 @ w, -30, 30)))
        grad = x1.T @ (p - y) + penalty @ w
        hess = (x1 * (p * (1 - p))[:, None]).T @ x1 + penalty + 1e-6 * np.eye(len(w))
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w[:-1], w[-1]


def auc(score, y):
    order = np.argsort(score)
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    pos = y == 1
    return (ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum())


def main():
    rows = collect()
    pages = sorted({r[0] for r in rows})
    rng = np.random.default_rng(0)
    held_out = set(rng.choice(pages, size=len(pages) // 5, replace=False))
    x = np.array([r[1] for r in rows])
    y = np.array([r[2] for r in rows])
    is_val = np.array([r[0] in held_out for r in rows])
    print(f'{len(rows)} labelled candidates ({int(y.sum())} real codes, {int((1 - y).sum())} false regions) from {len(pages)} pages')

    mean, std = x[~is_val].mean(axis=0), x[~is_val].std(axis=0) + 1e-9
    w, b = fit((x[~is_val] - mean) / std, y[~is_val])
    z = ((x[is_val] - mean) / std) @ w + b
    pred = z > 0
    tp, fp, fn = int((pred & (y[is_val] == 1)).sum()), int((pred & (y[is_val] == 0)).sum()), int((~pred & (y[is_val] == 1)).sum())
    print(f'held-out pages ({len(held_out)}): AUC {auc(z, y[is_val]):.3f} | at 0.5: precision {tp / max(tp + fp, 1):.3f} '
          f'recall {tp / max(tp + fn, 1):.3f} | {tp} real kept, {fp} false kept, {fn} real lost')

    mean, std = x.mean(axis=0), x.std(axis=0) + 1e-9               # final model: all tuning pages
    w, b = fit((x - mean) / std, y)
    json.dump({'features': list(FEATURES), 'mean': mean.tolist(), 'std': std.tolist(), 'weights': w.tolist(),
               'bias': float(b), 'threshold': 0.5,
               'trained_on': 'bench/dataset_tuning + bench/documents_tuning'}, open(OUT, 'w'), indent=1)
    print('weights (standardised features):')
    for name, value in sorted(zip(FEATURES, w), key=lambda t: -abs(t[1])):
        print(f'  {name:12s} {value:+.2f}')
    print('written', OUT)


if __name__ == '__main__':
    main()
