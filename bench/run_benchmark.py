"""Runs every decoder on the dataset of bench/make_dataset.py and writes bench/results/results.csv (F2).

    python bench/run_benchmark.py

Rules, the same for everybody:
  - every decoder receives the same 8-bit grayscale array and is used with its default settings
    (no hand-tuned preprocessing), except "ecode pipeline", which is our own decoder with its clean-up passes;
  - a decoder is only run on the code types it claims to read (see SUPPORTS);
  - status "ok"    = one of the returned texts is exactly the known content
    status "wrong" = it returned something, but not the known content (a misread: the worst case for a user)
    status "miss"  = it returned nothing;
  - time = wall-clock time of the decode call only, one image at a time, one thread, after a short warm-up.
"""
import csv
import os
import sys
import time

os.environ.setdefault('SECRET_KEY', 'bench')
os.environ.setdefault('JWT_SECRET_KEY', 'bench')
os.environ.setdefault('DATABASE_URL', 'sqlite://')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cv2
import zxingcpp
from flask import Flask
from pyzbar import pyzbar
from pylibdmtx import pylibdmtx

from app.scans.decoder import find_codes

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(HERE, 'dataset')
RESULTS = os.path.join(HERE, 'results')
DMTX_TIMEOUT_MS = 2000      # pylibdmtx can search for seconds on an image without a code: capped, a timeout counts as "miss"

_qr = cv2.QRCodeDetector()
_qr_aruco = cv2.QRCodeDetectorAruco()
_cv_barcode = cv2.barcode.BarcodeDetector()


def zxing_plain(gray):
    return [r.text for r in zxingcpp.read_barcodes(gray)]


_app = Flask('bench')
_app.config.update(DECODE_MAX_SIDE=3000, DECODE_FALLBACK_BUDGET_MS=2000)


def ecode_pipeline(gray):
    return [c['data'] for c in find_codes(gray, 1)]


def pyzbar_decode(gray):
    return [d.data.decode('utf-8', 'replace') for d in pyzbar.decode(gray)]


def pylibdmtx_decode(gray):
    return [d.data.decode('utf-8', 'replace') for d in pylibdmtx.decode(gray, timeout=DMTX_TIMEOUT_MS)]


def opencv_qr(gray):
    text, _, _ = _qr.detectAndDecode(gray)
    return [text] if text else []


def opencv_qr_aruco(gray):
    text, _, _ = _qr_aruco.detectAndDecode(gray)
    return [text] if text else []


def opencv_barcode(gray):
    out = _cv_barcode.detectAndDecodeWithType(gray)
    ok, infos = out[0], out[1]
    if not ok or infos is None:
        return []
    return [t for t in infos if t]


# name -> (function, code types it can read)
DECODERS = {
    'zxing-cpp': (zxing_plain, {'QRCODE', 'DataMatrix', 'CODE128', 'EAN13'}),
    'eCode pipeline': (ecode_pipeline, {'QRCODE', 'DataMatrix', 'CODE128', 'EAN13'}),
    'pyzbar (ZBar)': (pyzbar_decode, {'QRCODE', 'CODE128', 'EAN13'}),
    'pylibdmtx': (pylibdmtx_decode, {'DataMatrix'}),
    'OpenCV QRCodeDetector': (opencv_qr, {'QRCODE'}),
    'OpenCV QRCodeDetectorAruco': (opencv_qr_aruco, {'QRCODE'}),
    'OpenCV BarcodeDetector': (opencv_barcode, {'EAN13'}),     # EAN/UPC only: no Code 128 support in this module
}


def main():
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(DATASET, 'labels.csv'), encoding='utf-8') as f:
        labels = list(csv.DictReader(f))
    images = {}
    ctx = _app.app_context()
    ctx.push()

    out = open(os.path.join(RESULTS, 'results.csv'), 'w', newline='', encoding='utf-8')
    writer = csv.writer(out)
    writer.writerow(['decoder', 'type', 'condition', 'file', 'status', 'ms'])

    for name, (decode, supported) in DECODERS.items():
        rows = [r for r in labels if r['type'] in supported]
        for r in rows[:3]:                                          # warm-up (libraries load lazily)
            gray = cv2.imread(os.path.join(DATASET, r['file']), cv2.IMREAD_GRAYSCALE)
            decode(gray)
        counts = {'ok': 0, 'wrong': 0, 'miss': 0}
        started = time.perf_counter()
        for r in rows:
            gray = images.get(r['file'])
            if gray is None:
                gray = cv2.imread(os.path.join(DATASET, r['file']), cv2.IMREAD_GRAYSCALE)
            t0 = time.perf_counter()
            try:
                texts = decode(gray)
            except Exception as exc:                                # a crash is a miss, but say so
                print(f'  {name} failed on {r["file"]}: {exc}')
                texts = []
            ms = (time.perf_counter() - t0) * 1000
            status = 'ok' if r['truth'] in texts else ('wrong' if texts else 'miss')
            counts[status] += 1
            writer.writerow([name, r['type'], r['condition'], r['file'], status, f'{ms:.2f}'])
        out.flush()
        print(f'{name:28s} {len(rows):4d} images  ok={counts["ok"]:4d} wrong={counts["wrong"]:3d} miss={counts["miss"]:4d}'
              f'  ({time.perf_counter() - started:5.1f} s)', flush=True)
    out.close()


if __name__ == '__main__':
    main()
