"""Turns bench/results/results.csv into the tables and figures of the decoder study (F2).

    python bench/analyze.py

Writes bench/results/summary.md (markdown tables) and, in bench/figures/:
    heatmap_<TYPE>.png   success rate of every decoder under every condition (one figure per code type)
    overall.png          success rate per decoder, one panel per code type
    speed.png            median decoding time per decoder (log scale), one panel per code type
"""
import csv
import os
from collections import defaultdict

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, 'results')
FIGURES = os.path.join(HERE, 'figures')

# Chart chrome and the single-hue sequential ramp of the reference palette (light surface)
SURFACE, INK, INK2, MUTED, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#898781', '#e1e0d9'
RAMP = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']     # 100 .. 700
BAR = '#2a78d6'
RED = '#d03b3b'
plt.rcParams.update({'font.family': ['Segoe UI', 'DejaVu Sans'], 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
                     'text.color': INK, 'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2})

TYPE_TITLE = {'QRCODE': 'QR code', 'DataMatrix': 'DataMatrix', 'CODE128': 'Code 128', 'EAN13': 'EAN-13'}
DECODER_ORDER = ['eCode pipeline', 'zxing-cpp', 'pyzbar (ZBar)', 'pylibdmtx', 'OpenCV QRCodeDetector',
                 'OpenCV QRCodeDetectorAruco', 'OpenCV BarcodeDetector']
SHORT = {'OpenCV QRCodeDetector': 'OpenCV QR', 'OpenCV QRCodeDetectorAruco': 'OpenCV QR Aruco',
         'OpenCV BarcodeDetector': 'OpenCV Barcode', 'pyzbar (ZBar)': 'pyzbar'}


def short(name):
    return SHORT.get(name, name)


def load():
    with open(os.path.join(RESULTS, 'results.csv'), encoding='utf-8') as f:
        return list(csv.DictReader(f))


def pct(n, d):
    return 100.0 * n / d if d else float('nan')


def main():
    os.makedirs(FIGURES, exist_ok=True)
    rows = load()
    conditions = []
    for r in rows:
        if r['condition'] not in conditions:
            conditions.append(r['condition'])
    types = [t for t in TYPE_TITLE if any(r['type'] == t for r in rows)]
    decoders = [d for d in DECODER_ORDER if any(r['decoder'] == d for r in rows)]

    cell = defaultdict(lambda: {'ok': 0, 'wrong': 0, 'miss': 0, 'ms': []})      # (decoder, type, condition)
    total = defaultdict(lambda: {'ok': 0, 'wrong': 0, 'miss': 0, 'ms': []})     # (decoder, type)
    for r in rows:
        for key, bucket in (((r['decoder'], r['type'], r['condition']), cell), ((r['decoder'], r['type']), total)):
            bucket[key][r['status']] += 1
            bucket[key]['ms'].append(float(r['ms']))

    md = ['# Decoder comparison: results', '',
          f'{len(rows)} decoder runs. A read counts only if the returned text is exactly the known content.', '']

    # ---- overall table
    md += ['## Overall (all conditions together)', '',
           '| Code type | Decoder | Images | Read correctly | Misread | Nothing | Median ms | p95 ms |', '|---|---|---|---|---|---|---|---|']
    for t in types:
        for d in decoders:
            c = total.get((d, t))
            if not c:
                continue
            n = c['ok'] + c['wrong'] + c['miss']
            md.append(f"| {TYPE_TITLE[t]} | {d} | {n} | {pct(c['ok'], n):.1f} % | {pct(c['wrong'], n):.1f} % | "
                      f"{pct(c['miss'], n):.1f} % | {np.median(c['ms']):.1f} | {np.percentile(c['ms'], 95):.1f} |")
    md.append('')

    # ---- per type, per condition
    for t in types:
        ds = [d for d in decoders if (d, t) in total]
        md += [f'## {TYPE_TITLE[t]}: correct reads (%) per condition', '',
               '| Condition | ' + ' | '.join(short(d) for d in ds) + ' |', '|---|' + '---|' * len(ds)]
        for cond in conditions:
            vals = []
            for d in ds:
                c = cell[(d, t, cond)]
                vals.append(f"{pct(c['ok'], c['ok'] + c['wrong'] + c['miss']):.0f}")
            md.append(f'| {cond} | ' + ' | '.join(vals) + ' |')
        md.append('')

    # ---- misreads (a wrong text is worse than no text)
    wrong = [(d, t, total[(d, t)]['wrong']) for t in types for d in decoders if (d, t) in total and total[(d, t)]['wrong']]
    md += ['## Misreads (wrong content returned)', '']
    md += [f'- {d} on {TYPE_TITLE[t]}: {n}' for d, t, n in wrong] if wrong else ['None: no decoder returned a wrong content.']
    md.append('')
    with open(os.path.join(RESULTS, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    # ---- heatmaps
    cmap = LinearSegmentedColormap.from_list('blue', RAMP)
    for t in types:
        ds = [d for d in decoders if (d, t) in total]
        grid = np.array([[pct(cell[(d, t, c)]['ok'], sum(cell[(d, t, c)][k] for k in ('ok', 'wrong', 'miss'))) for d in ds]
                         for c in conditions])
        fig, ax = plt.subplots(figsize=(1.45 * len(ds) + 2.6, 0.34 * len(conditions) + 1.6))
        ax.imshow(grid, cmap=cmap, vmin=0, vmax=100, aspect='auto')
        ax.set_xticks(range(len(ds)), [short(d) for d in ds], fontsize=9)
        ax.xaxis.tick_top()
        ax.set_yticks(range(len(conditions)), conditions, fontsize=9)
        for i in range(grid.shape[0]):
            for j in range(grid.shape[1]):
                v = grid[i, j]
                ax.text(j, i, f'{v:.0f}', ha='center', va='center', fontsize=8.5, color='white' if v >= 55 else INK)
        ax.set_xticks(np.arange(-.5, len(ds)), minor=True)
        ax.set_yticks(np.arange(-.5, len(conditions)), minor=True)
        ax.grid(which='minor', color=SURFACE, linewidth=2)
        ax.tick_params(which='both', length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        fig.suptitle(f'{TYPE_TITLE[t]}: share of images read correctly (%)', x=0.02, ha='left', fontsize=12, fontweight='bold', y=0.995)
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        fig.savefig(os.path.join(FIGURES, f'heatmap_{t}.png'), dpi=160)
        plt.close(fig)

    # ---- small multiples helper (bars, one panel per type, same decoder order everywhere)
    def panels(filename, value, fmt, xlabel, xlim=None, log=False, title=''):
        fig, axes = plt.subplots(1, len(types), figsize=(3.9 * len(types), 3.6), sharey=False)
        for ax, t in zip(np.atleast_1d(axes), types):
            ds = [d for d in decoders if (d, t) in total][::-1]
            vals = [value(total[(d, t)]) for d in ds]
            ax.barh(range(len(ds)), vals, color=BAR, height=0.62)
            ax.set_yticks(range(len(ds)), [short(d) for d in ds], fontsize=8.5)
            ax.set_title(TYPE_TITLE[t], fontsize=10.5, loc='left', fontweight='bold')
            if log:
                ax.set_xscale('log')
            if xlim:
                ax.set_xlim(*xlim)
            for y, v in enumerate(vals):
                ax.text(v, y, ' ' + fmt(v), va='center', fontsize=8.5, color=INK)
            ax.set_xlabel(xlabel, fontsize=8.5)
            ax.grid(axis='x', color=GRID, linewidth=0.8)
            ax.set_axisbelow(True)
            for s in ('top', 'right', 'left'):
                ax.spines[s].set_visible(False)
            ax.spines['bottom'].set_color(GRID)
            ax.tick_params(length=0)
        fig.suptitle(title, x=0.01, ha='left', fontsize=12, fontweight='bold')
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        fig.savefig(os.path.join(FIGURES, filename), dpi=160)
        plt.close(fig)

    panels('overall.png', lambda c: pct(c['ok'], c['ok'] + c['wrong'] + c['miss']), lambda v: f'{v:.0f} %',
           'images read correctly (%)', xlim=(0, 118), title='Share of images read correctly, all 22 conditions together')
    panels('speed.png', lambda c: float(np.median(c['ms'])), lambda v: f'{v:.0f} ms' if v >= 10 else f'{v:.1f} ms',
           'median time per image (ms)', xlim=(0, 75), title='Median decoding time per image (800x600 page, one thread)')
    print('written:', os.path.join(RESULTS, 'summary.md'), 'and figures in', FIGURES)


if __name__ == '__main__':
    main()
