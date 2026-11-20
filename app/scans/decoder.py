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

from .localizer import find_regions

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


# ---- regions: decode each located code separately ----

REGION_TARGET_PX = 140        # a region is resized so that its smaller side is about this many pixels (x0.5 .. x4)
REGION_PADDING = 0.12         # quiet zone added around a region (share of its larger side, at least 8 px)


def _region_view(gray, box):
    """Cuts a located region out of the page, straightens it (long side horizontal) and resizes it.

    Returns (image, matrix) where matrix maps the pixels of `gray` to the pixels of the returned image."""
    p = np.asarray(box, dtype=np.float32)
    a, b = np.linalg.norm(p[1] - p[0]), np.linalg.norm(p[2] - p[1])
    corners = p if a >= b else np.roll(p, -1, axis=0)                  # corners[0]->[1] is the long side
    width, height = max(a, b), min(a, b)
    u = (corners[1] - corners[0]) / max(width, 1e-6)
    v = (corners[3] - corners[0]) / max(height, 1e-6)
    pad = max(8.0, REGION_PADDING * width)
    src = np.float32([corners[0] - pad * u - pad * v, corners[1] + pad * u - pad * v,
                      corners[2] + pad * u + pad * v, corners[3] - pad * u + pad * v])
    scale = float(np.clip(REGION_TARGET_PX / max(height, 1.0), 0.5, 4.0))
    out_w, out_h = int((width + 2 * pad) * scale), int((height + 2 * pad) * scale)
    dst = np.float32([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]])
    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(gray, matrix, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE), matrix


def _region_variants(view):
    """The same region prepared in a few ways, cheapest first (a region is small: each attempt takes ms)."""
    yield view, dict(try_invert=True)
    yield cv2.bitwise_not(view), dict(try_invert=False)         # white-on-black 1D codes
    yield _clahe(view), dict(try_invert=True)
    yield cv2.adaptiveThreshold(view, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8), dict(try_invert=True)
    yield _clahe(cv2.medianBlur(view, 3)), dict(try_invert=True)


def _covers(region, codes, factor):
    """True when a decoded code already lies in this region (code boxes are in original pixels, regions in `gray`)."""
    rx, ry, rw, rh = region['x'], region['y'], region['w'], region['h']
    for c in codes:
        cc = c['coordinates']
        cx, cy = (cc['x'] + cc['w'] / 2) * factor, (cc['y'] + cc['h'] / 2) * factor
        if rx <= cx <= rx + rw and ry <= cy <= ry + rh:
            return True
    return False


def _decode_regions(gray, regions, formats, matrix, width, height, page_number, found, deadline):
    """Decodes the regions that hold no decoded code yet. Returns (new codes, regions that stay unreadable)."""
    factor = matrix[0, 0]
    new, unread = [], []
    for region in regions:                                              # best first
        if _covers(region, found + new, factor):
            continue
        codes = []
        if time.perf_counter() < deadline:
            view, view_matrix = _region_view(gray, region['box'])
            for image, options in _region_variants(view):
                codes = _read(image, formats, view_matrix @ matrix, width, height, page_number, **options)
                if codes:
                    break
        if codes:
            new.extend(c for c in codes if not _is_duplicate(c, found + new))
        else:
            unread.append(region)
    return new, unread


def _unread_report(regions, matrix, width, height, page_number, minimum):
    """Unreadable regions in the JSON format: original pixels, only the ones the localiser is sure about."""
    report = []
    for r in regions:
        if r['score'] < minimum:
            continue
        pts = _to_original([tuple(q) for q in r['box']], matrix)
        x0, y0 = max(0, int(pts[:, 0].min())), max(0, int(pts[:, 1].min()))
        x1, y1 = min(width, int(math.ceil(pts[:, 0].max()))), min(height, int(math.ceil(pts[:, 1].max())))
        report.append({'page': page_number, 'coordinates': {'x': x0, 'y': y0, 'w': x1 - x0, 'h': y1 - y0},
                       'score': round(float(r['score']), 2)})
    return report


def find_page(img, page_number=1, allowed_types=None, deadline=None, all_regions=None):
    """Finds every barcode of one page (RGB or grayscale numpy array), without drawing.

    Returns (codes, unread): the decoded codes, and the regions that look like a code but could not be read.
    allowed_types: set of type names to look for (None = all).
    deadline: time limit of the extra attempts (see new_fallback_deadline); share one between the pages of
              a document. None = a new budget just for this page.
    all_regions: True = locate and decode the regions even when the quick read found codes (finds the other codes
              of the page, slower). None = the DECODE_ALL_REGIONS setting.
    """
    formats = _formats(allowed_types)
    if formats is None:
        return [], []

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

    # When are the extra attempts made? Only on a page with something to find, within the time budget,
    # and (regions) when nothing was read - or always, if DECODE_ALL_REGIONS asks to look for the other codes too.
    budget = config['DECODE_FALLBACK_BUDGET_MS'] > 0 and gray.std() >= 3
    strategy = config.get('DECODE_REGIONS', 'off') if budget else 'off'
    if all_regions is None:
        all_regions = config.get('DECODE_ALL_REGIONS', False)
    if all_regions and budget and strategy == 'off':
        strategy = 'first'                                       # asked for explicitly: regions even if the setting is off
    if results and not all_regions:
        strategy = 'off'
    if deadline is None:
        deadline = new_fallback_deadline()

    unread = []

    def with_regions(found):
        nonlocal unread
        regions = find_regions(gray)
        new, unread = _decode_regions(gray, regions, formats, matrix, width, height, page_number, found, deadline)
        return found + new

    # 2a. regions first: locate the codes, then decode each one separately (cropped, straightened, enlarged)
    if strategy == 'first':
        results = with_regions(results)

    # 2b. clean-up passes of the whole page for poor scans
    if not results and budget and config.get('DECODE_GLOBAL_PASSES', True):
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
        results = found

    # 2c. regions last (after the page-wide passes)
    if strategy == 'last':
        results = with_regions(results)

    results = sorted(results, key=lambda c: (c['coordinates']['y'], c['coordinates']['x']))
    report = _unread_report(unread, matrix, width, height, page_number, config.get('UNREAD_MIN_SCORE', 0.8))
    return results, report


def find_codes(img, page_number=1, allowed_types=None, deadline=None):
    """The decoded codes only (see find_page)."""
    return find_page(img, page_number, allowed_types, deadline)[0]


def draw_boxes(img_rgb, results, unread=()):
    """Draws a box around each code on an RGB image: red for 1D/QR, green for DataMatrix,
    orange for a region that looks like a code but could not be read."""
    for region in unread:
        c = region['coordinates']
        cv2.rectangle(img_rgb, (c['x'], c['y']), (c['x'] + c['w'], c['y'] + c['h']), (255, 140, 0), 2)
    for result in results:
        c = result['coordinates']
        color = (0, 255, 0) if result['type'] == 'DataMatrix' else (255, 0, 0)
        cv2.rectangle(img_rgb, (c['x'], c['y']), (c['x'] + c['w'], c['y'] + c['h']), color, 2)
