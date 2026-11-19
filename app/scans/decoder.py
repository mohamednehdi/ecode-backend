"""Barcode localisation and decoding (1D, QR, DataMatrix, ...), built on zxing-cpp.

Two stages, so that good scans are fast and poor scans still get read:

1. Fast pass: grayscale image, one decoder call (about 20-90 ms depending on the image size).
2. Only when the fast pass finds nothing: clean-up passes (inverted colours, contrast boost,
   binarisation, noise removal, 2x enlargement, 45 degree rotations), within a time budget.
   The first pass that finds codes ends the search.

Coordinates are always returned in the pixel space of the original image, whatever the pass.
"""
import math
import time

import cv2
import numpy as np
import zxingcpp
from flask import current_app

# Type names of our JSON / API  ->  zxing-cpp format name.
# The names of the older decoder (pyzbar) are kept so existing clients and API keys keep working.
_FORMATS = {
    'QRCODE': 'QRCode',            # also Micro QR and rMQR
    'DataMatrix': 'DataMatrix',
    'CODE128': 'Code128',
    'CODE39': 'Code39',
    'CODE93': 'Code93',
    'CODABAR': 'Codabar',
    'EAN13': 'EAN13',
    'EAN8': 'EAN8',
    'UPCA': 'UPCA',
    'UPCE': 'UPCE',
    'I25': 'ITF',
    'DATABAR': 'DataBar',
    'DATABAR_EXP': 'DataBarExp',
    'PDF417': 'PDF417',
    'Aztec': 'Aztec',
    'MaxiCode': 'MaxiCode',
}
_SYMBOLOGY_TO_TYPE = {zxing_name: our_name for our_name, zxing_name in _FORMATS.items()}

# Every barcode type the platform can return
SUPPORTED_TYPES = sorted(_FORMATS)


def _formats(allowed_types):
    """zxing-cpp formats to look for. None = all supported types, empty set = nothing."""
    names = SUPPORTED_TYPES if allowed_types is None else [t for t in SUPPORTED_TYPES if t in allowed_types]
    if not names:
        return None
    return zxingcpp.barcode_formats_from_str('|'.join(_FORMATS[n] for n in names))


# ---- geometry helpers: 3x3 matrices that map original pixels -> processed pixels ----

_IDENTITY = np.eye(3)


def _scale_matrix(factor):
    return np.array([[factor, 0, 0], [0, factor, 0], [0, 0, 1]], dtype=np.float64)


def _to_original(corners, matrix):
    """Maps points from the processed image back to the original image."""
    pts = np.array(corners, dtype=np.float64)
    if matrix is _IDENTITY:
        return pts
    pts = np.hstack([pts, np.ones((len(pts), 1))])
    return (pts @ np.linalg.inv(matrix).T)[:, :2]


def _rotated(gray, degrees):
    """Rotates the image (the canvas grows so nothing is cut). Returns (image, matrix original->rotated)."""
    h, w = gray.shape
    center = (w / 2, h / 2)
    m = cv2.getRotationMatrix2D(center, degrees, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    new_w, new_h = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += new_w / 2 - center[0]
    m[1, 2] += new_h / 2 - center[1]
    out = cv2.warpAffine(gray, m, (new_w, new_h), flags=cv2.INTER_LINEAR, borderValue=255)
    return out, np.vstack([m, [0, 0, 1]])


# ---- clean-up passes for poor quality scans: each returns (image, matrix, zxing options) ----

def _clahe(gray):
    return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)


def _pass_inverted(gray):
    # zxing-cpp's own try_invert only covers 2D codes: invert the pixels so white-on-black 1D codes work too
    return cv2.bitwise_not(gray), _IDENTITY, dict(try_invert=False)


def _pass_contrast(gray):
    return _clahe(gray), _IDENTITY, dict(try_invert=False)


def _pass_binarize(gray):
    block = max(15, (min(gray.shape) // 20) | 1)  # odd window, about 5% of the image
    out = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 10)
    return out, _IDENTITY, dict(try_invert=True)


def _pass_denoise(gray):
    return _clahe(cv2.medianBlur(gray, 3)), _IDENTITY, dict(try_invert=False)


def _pass_enlarge(gray):
    if max(gray.shape) > 2200:  # already large: enlarging would be slow and use a lot of memory
        return None
    out = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return _clahe(out), _scale_matrix(2), dict(try_invert=True)


def _pass_rotate(degrees):
    def run(gray):
        out, matrix = _rotated(gray, degrees)
        return out, matrix, dict(try_invert=False)
    return run


_FALLBACK_PASSES = (
    _pass_inverted, _pass_contrast, _pass_binarize, _pass_denoise,
    _pass_rotate(45), _pass_rotate(-45), _pass_enlarge,  # enlarging is the slowest pass: last
)


# ---- public functions ----

def _read(image, formats, matrix, width, height, page_number, **options):
    """One zxing-cpp call; converts its results to our JSON format, in original image coordinates."""
    results = []
    for r in zxingcpp.read_barcodes(image, formats=formats, **options):
        p = r.position
        pts = _to_original([(q.x, q.y) for q in (p.top_left, p.top_right, p.bottom_right, p.bottom_left)], matrix)
        x0 = max(0, int(math.floor(pts[:, 0].min())))
        y0 = max(0, int(math.floor(pts[:, 1].min())))
        x1 = min(width, int(math.ceil(pts[:, 0].max())))
        y1 = min(height, int(math.ceil(pts[:, 1].max())))
        results.append({
            'page': page_number,
            'type': _SYMBOLOGY_TO_TYPE.get(r.symbology.name, r.format.name),
            'data': r.bytes.decode('utf-8', errors='replace'),
            'coordinates': {'x': x0, 'y': y0, 'w': x1 - x0, 'h': y1 - y0},
        })
    return sorted(results, key=lambda c: (c['coordinates']['y'], c['coordinates']['x']))


def new_fallback_deadline():
    """Time limit (perf_counter value) for the clean-up passes of ONE document, shared by all its pages."""
    return time.perf_counter() + current_app.config['DECODE_FALLBACK_BUDGET_MS'] / 1000


def _is_duplicate(code, known):
    """Same type and data at about the same place: the same code found by two different passes."""
    c = code['coordinates']
    cx, cy = c['x'] + c['w'] / 2, c['y'] + c['h'] / 2
    for other in known:
        if other['type'] != code['type'] or other['data'] != code['data']:
            continue
        o = other['coordinates']
        reach = 0.75 * max(c['w'], c['h'], o['w'], o['h'])
        if abs(cx - (o['x'] + o['w'] / 2)) <= reach and abs(cy - (o['y'] + o['h'] / 2)) <= reach:
            return True
    return False


def find_codes(img, page_number=1, allowed_types=None, deadline=None):
    """Finds and decodes every barcode on one page (RGB or grayscale numpy array), without drawing.

    allowed_types: set of type names to look for (None = all).
    deadline: time limit of the clean-up passes (see new_fallback_deadline); share one between the pages of
              a document. None = a new budget just for this page.
    """
    formats = _formats(allowed_types)
    if formats is None:
        return []

    config = current_app.config
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape

    # Very large scans are decoded at a reduced size (coordinates are mapped back)
    matrix = _IDENTITY
    longest = max(height, width)
    max_side = config['DECODE_MAX_SIDE']
    if longest > max_side:
        factor = max_side / longest
        gray = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        matrix = _scale_matrix(factor)

    # 1. fast pass
    results = _read(gray, formats, matrix, width, height, page_number, try_invert=False)
    if results:
        return results

    # 2. clean-up passes for poor scans, within a time budget. A completely uniform page has nothing to find.
    if config['DECODE_FALLBACK_BUDGET_MS'] <= 0 or gray.std() < 3:
        return []
    if deadline is None:
        deadline = new_fallback_deadline()
    found = []
    for make_pass in _FALLBACK_PASSES:
        if time.perf_counter() >= deadline:
            break
        prepared = make_pass(gray)
        if prepared is None:
            continue
        image, pass_matrix, options = prepared
        for code in _read(image, formats, pass_matrix @ matrix, width, height, page_number, **options):
            if not _is_duplicate(code, found):
                found.append(code)
        if found:
            # Something was found: keep looking only a little longer for the codes the first pass missed
            deadline = min(deadline, time.perf_counter() + 0.5 * config['DECODE_FALLBACK_BUDGET_MS'] / 1000)
    return sorted(found, key=lambda c: (c['coordinates']['y'], c['coordinates']['x']))


def draw_boxes(img_rgb, results):
    """Draws a box around each code on an RGB image: red for 1D/QR, green for DataMatrix."""
    for result in results:
        c = result['coordinates']
        color = (0, 255, 0) if result['type'] == 'DataMatrix' else (255, 0, 0)
        cv2.rectangle(img_rgb, (c['x'], c['y']), (c['x'] + c['w'], c['y'] + c['h']), color, 2)
