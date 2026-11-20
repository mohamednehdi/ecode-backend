"""Compares decoding strategies of app/scans/decoder.py on a dataset with known contents and known positions (F3b).

    python bench/eval_decode.py <folder> [--strategy "name"]        folder: bench/dataset_tuning, bench/documents_tuning,
                                                                    bench/dataset or bench/documents (final: score once)

For every true code: read correctly when its exact content is among the decoded texts of the page.
Misread = a decoded text that is not the content of any code of the page (worse than no answer).
Unread regions (regions that look like a code but were not read) are listed with their score; a reported region is
"useful" when it overlaps a true code that was NOT read (IoU >= 0.3), "false" when it overlaps no code.
"""
import csv
import os
import sys
import time
from collections import defaultdict

os.environ.setdefault('SECRET_KEY', 'bench')
os.environ.setdefault('JWT_SECRET_KEY', 'bench')
os.environ.setdefault('DATABASE_URL', 'sqlite://')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
from flask import Flask

from app.scans.decoder import find_page
from eval_localizer import iou

BASE = dict(DECODE_MAX_SIDE=3000, DECODE_FALLBACK_BUDGET_MS=2000, UNREAD_MIN_SCORE=0.0,
            DECODE_REGIONS='off', DECODE_ALL_REGIONS=False, DECODE_GLOBAL_PASSES=True)
STRATEGIES = {
    'baseline: page-wide passes only': dict(DECODE_REGIONS='off'),
    'regions first, then page-wide': dict(DECODE_REGIONS='first'),
    'page-wide first, then regions': dict(DECODE_REGIONS='last'),
    'regions only': dict(DECODE_REGIONS='first', DECODE_GLOBAL_PASSES=False),
    'regions always (all codes)': dict(DECODE_REGIONS='first', DECODE_ALL_REGIONS=True),
}


def load(folder):
    pages = defaultdict(list)
    with open(os.path.join(folder, 'labels.csv'), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            pages[r['file']].append(r)
    return pages


def run(folder, name, settings):
    pages = load(folder)
    app = Flask('bench')
    app.config.update(BASE, **settings)
    rows, times, misreads, unread_rows = [], [], 0, []
    with app.app_context():
        for fname, truths in pages.items():
            gray = cv2.imread(os.path.join(folder, fname), cv2.IMREAD_GRAYSCALE)
            t0 = time.perf_counter()
            codes, unread = find_page(gray, 1, None, None)
            times.append((time.perf_counter() - t0) * 1000)
            texts = [c['data'] for c in codes]
            known = {t['truth'] for t in truths}
            misreads += sum(1 for x in texts if x not in known)
            read_flags = []
            for t in truths:
                ok = t['truth'] in texts
                read_flags.append(ok)
                rows.append({'type': t['type'], 'group': t.get('condition') or t.get('kind'), 'damage': t.get('damage', '-'), 'ok': ok})
            for u in unread:
                c = u['coordinates']
                useful = any(not ok and iou(tuple(int(t[k]) for k in 'xywh'), (c['x'], c['y'], c['w'], c['h'])) >= 0.3
                             for t, ok in zip(truths, read_flags))
                unread_rows.append({'score': u['score'], 'useful': useful})
    return rows, times, misreads, unread_rows


def table(results, key, title):
    groups = sorted({r[key] for rows, *_ in results.values() for r in rows})
    names = list(results)
    print(f'\n{title}')
    print(f'{key:16s}' + ''.join(f'{n[:22]:>24s}' for n in names))
    for g in groups:
        cells = []
        for n in names:
            sel = [r['ok'] for r in results[n][0] if r[key] == g]
            cells.append(f'{100 * sum(sel) / len(sel):6.1f}% ({len(sel):3d})' if sel else '-')
        print(f'{g:16s}' + ''.join(f'{c:>24s}' for c in cells))


if __name__ == '__main__':
    if '--target' in sys.argv:                                   # tuning aid: size a region is brought to before decoding
        import app.scans.decoder as decoder_module
        decoder_module.REGION_TARGET_PX = int(sys.argv[sys.argv.index('--target') + 1])
    args = [a for a in sys.argv[1:] if not a.startswith('--') and not a.isdigit() and a != sys.argv[sys.argv.index('--strategy') + 1 if '--strategy' in sys.argv else 0]]
    folder = args[0]
    only = sys.argv[sys.argv.index('--strategy') + 1] if '--strategy' in sys.argv else None
    results = {}
    for name, settings in STRATEGIES.items():
        if only and only != name:
            continue
        results[name] = run(folder, name, settings)
    print(f'\n{"strategy":34s} {"codes read":>11s} {"misreads":>9s} {"mean ms":>8s} {"median":>7s} {"p95":>7s}')
    for name, (rows, times, misreads, unread) in results.items():
        print(f'{name:34s} {100 * sum(r["ok"] for r in rows) / len(rows):10.1f}% {misreads:9d} {np.mean(times):8.1f} '
              f'{np.median(times):7.1f} {np.percentile(times, 95):7.1f}')
    print('\nunread-region reports (regions that look like codes but were not read):')
    for name, (rows, times, misreads, unread) in results.items():
        if not unread:
            continue
        for floor in (0.5, 0.7, 0.8, 0.9, 0.95):
            sel = [u for u in unread if u['score'] >= floor]
            if sel:
                print(f'  {name:34s} score >= {floor:.2f}: {len(sel):4d} reported, {100 * sum(u["useful"] for u in sel) / len(sel):5.1f}% point at a real unread code')
    table(results, 'type', 'read rate by code type')
    table(results, 'group', 'read rate by condition / page kind')
    if any(r['damage'] != '-' for rows, *_ in results.values() for r in rows):
        for rows, *_ in results.values():
            for r in rows:
                r['damage1'] = r['damage'].split('+')[0]
        table(results, 'damage1', 'read rate by damage of the code (first damage)')
