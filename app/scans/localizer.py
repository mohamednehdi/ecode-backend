"""Barcode localisation: finds WHERE codes are on a page, without decoding them (F3).

Step 1 - candidates. A barcode is a patch where sharp black/white edges are packed almost everywhere; text and table
lines also have edges, but with gaps. In a small window the detector measures the FRACTION of pixels that are strong
edges, at three image scales (so small and large codes both land in the right range), keeps the dense areas that are
compact and large enough, and describes each one by a few numbers (density, shape, how aligned its edges are, how
much of it is dark...).

Step 2 - scoring. A tiny logistic regression (a dozen weights in localizer_model.json, trained on synthetic pages by
bench/train_localizer.py) turns those numbers into "probability that this is a barcode". Without the model file every
candidate is returned, ranked by density.

It never reads a code. The platform uses the regions to (1) show codes it could not read, (2) decode each region
separately (cropped, straightened, enlarged) and (3) know how many codes a page should contain.

Pure OpenCV + NumPy, no deep learning: fast, and every number can be explained.
"""
import json
import os

import cv2
import numpy as np

# --- parameters (tuned on bench/dataset_tuning and bench/documents_tuning, never on the final datasets) ---
SCALES = (1.0, 0.5)    # the page is searched at these sizes
WINDOW = 13                  # side (pixels, at each scale) of the window where edge density is measured
EDGE_HEIGHT = 45             # an edge is "strong" when the grey level jumps by at least this much
DENSITY = 0.42               # a window is code-like when at least this share of its pixels are strong edges
MAX_SIDE = 1200              # larger pages are searched on a reduced copy (boxes are mapped back)
MIN_SIDE = 28                # smallest region side, in pixels of the original image (real codes: >= ~30 px)
MIN_FILL = 0.62              # region area / area of its rotated rectangle (compactness)
MAX_ASPECT = 14.0            # longest side / shortest side
TRIM_LEVEL = 0.3             # trimming: edge columns/rows below this share of the code's own level are cut off
MIN_PROBABILITY = 0.5        # a candidate is kept when the model gives it at least this probability

FEATURES = ('density', 'density_p10', 'fill', 'log_short', 'log_long', 'log_aspect', 'coherence2', 'coherence4',
            'dark', 'scale_1', 'scale_half', 'scale_quarter')

_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'localizer_model.json')


def load_model(path=_MODEL_PATH):
    """The trained scoring model, or None when there is none (then every candidate is returned)."""
    try:
        with open(path, encoding='utf-8') as f:
            model = json.load(f)
    except (OSError, ValueError):
        return None
    return {'mean': np.array(model['mean']), 'std': np.array(model['std']), 'weights': np.array(model['weights']),
            'bias': float(model['bias']), 'threshold': float(model.get('threshold', MIN_PROBABILITY))}


MODEL = load_model()


def _strong_edges(gray):
    """Strong-edge map (1 = the grey level changes sharply here) and the gradient it comes from."""
    smooth = cv2.GaussianBlur(gray, (0, 0), 0.8)                                # noise is not structure
    even = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(smooth)   # low contrast, uneven lighting
    gx = cv2.Scharr(even, cv2.CV_16S, 1, 0)
    gy = cv2.Scharr(even, cv2.CV_16S, 0, 1)
    # ~ height of the grey-level step (8-bit saturating arithmetic: much faster than float images)
    magnitude = cv2.add(cv2.convertScaleAbs(gx, alpha=1 / 16.0), cv2.convertScaleAbs(gy, alpha=1 / 16.0))
    return (magnitude >= EDGE_HEIGHT).astype(np.uint8), gx, gy, magnitude


def _coherence(gx, gy, magnitude, ys, xs):
    """How aligned the edge directions are (0-1). coherence2: one direction (1D bars). coherence4: directions that are
    multiples of 90 degrees apart (bars, QR and DataMatrix squares at ANY tilt; also straight text strokes)."""
    step = max(1, len(xs) // 3000)                                              # a sample is enough, and 10x faster
    ys, xs = ys[::step], xs[::step]
    angle = np.arctan2(gy[ys, xs].astype(np.float32), gx[ys, xs].astype(np.float32))
    weight = magnitude[ys, xs]
    total = max(float(weight.sum()), 1e-6)
    return (abs(np.sum(weight * np.exp(2j * angle))) / total, abs(np.sum(weight * np.exp(4j * angle))) / total)


def _hull(points):
    """Convex hull of the edge points. Big regions are sampled first: the hull of 4000 points is as good as the hull
    of 40000 (within a pixel or two) and much faster."""
    return cv2.convexHull(np.ascontiguousarray(points[::max(1, len(points) // 4000)]))


def _longest_run(mask):
    """(start, end) of the longest run of True values."""
    best, start = (0, 0), None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return best


def _trim(points):
    """Cuts off what is attached to a code (a text row, a table line) but is much sparser than the code itself.

    In the region's own rotated frame, a code has about the same number of edge pixels in every column and row
    across its whole extent. The part of the region where that count falls below half of the central level is
    dropped. Returns the points that remain."""
    (cx, cy), (rw, rh), _ = rect = cv2.minAreaRect(_hull(points))
    corners = cv2.boxPoints(rect)
    axes = [corners[1] - corners[0], corners[2] - corners[1]]
    for axis in axes:
        norm = np.linalg.norm(axis)
        if norm < 1 or len(points) < 60:
            return points
        coordinate = (points - np.array([cx, cy])) @ (axis / norm)
        low = int(np.floor(coordinate.min()))
        counts = np.bincount((coordinate - low).astype(int))
        size = max(5, int(0.04 * len(counts)))
        smooth = np.convolve(counts, np.ones(size) / size, mode='same')
        centre = smooth[len(smooth) // 4: 3 * len(smooth) // 4]
        if centre.size == 0 or not (centre > 0).any():
            continue
        level = TRIM_LEVEL * np.median(centre[centre > 0])
        start, end = _longest_run(smooth >= level)
        if end - start < 5:
            continue
        keep = (coordinate - low >= start) & (coordinate - low < end)
        if keep.sum() >= 30:
            points = points[keep]
    return points


def candidate_regions(gray):
    """Every dense, compact area at every scale (before scoring), with its feature vector."""
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY)
    if cv2.meanStdDev(gray)[1][0, 0] < 3:                                        # blank page: nothing to find
        return []
    reduction = 1.0
    if max(gray.shape) > MAX_SIDE:                                               # e.g. an A4 scan at 200 dpi
        reduction = MAX_SIDE / max(gray.shape)
        gray = cv2.resize(gray, None, fx=reduction, fy=reduction, interpolation=cv2.INTER_AREA)
    found = []
    for scale in SCALES:
        img = gray if scale == 1.0 else cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        edges, gx, gy, magnitude = _strong_edges(img)
        density = cv2.boxFilter(edges.astype(np.float32), -1, (WINDOW, WINDOW))
        dense = (density >= DENSITY).astype(np.uint8)
        dense = cv2.morphologyEx(dense, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(dense, connectivity=8)
        for i in range(1, count):
            x0, y0, w0, h0, area = stats[i]
            if area < (MIN_SIDE * scale) ** 2 or min(w0, h0) < MIN_SIDE * scale:
                continue
            # Work on the component's own rectangle only (a full-image comparison per component is slow)
            inside = labels[y0:y0 + h0, x0:x0 + w0] == i
            ys, xs = np.nonzero(inside & (edges[y0:y0 + h0, x0:x0 + w0] > 0))   # the real edge pixels of this area
            if len(xs) < 30:
                continue
            points = _trim(np.column_stack([xs + x0, ys + y0]).astype(np.float32))
            if len(points) < 30:
                continue
            xs, ys = points[:, 0].astype(int) - x0, points[:, 1].astype(int) - y0
            hull = _hull(points)
            rect = cv2.minAreaRect(hull)
            (rw, rh) = rect[1]
            short, long_ = sorted((rw, rh))
            if short < MIN_SIDE * scale or long_ / max(short, 1) > MAX_ASPECT:
                continue
            fill = cv2.contourArea(hull) / max(rw * rh, 1)                      # 1 = a perfect rectangle
            if fill < MIN_FILL:
                continue
            area_density = density[y0:y0 + h0, x0:x0 + w0][inside]
            coherence2, coherence4 = _coherence(gx, gy, magnitude, ys + y0, xs + x0)
            patch = img[y0:y0 + h0, x0:x0 + w0][inside]
            level, _ = cv2.threshold(patch.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            dark = float((patch < level).mean())
            short_o, long_o = short / scale, long_ / scale                      # in original-image pixels
            box = cv2.boxPoints(rect) / (scale * reduction)                     # back to the caller's pixels
            x, y, w, h = cv2.boundingRect(box.astype(np.float32))
            found.append({
                'box': box, 'x': x, 'y': y, 'w': w, 'h': h, 'angle': float(rect[2]), 'scale': scale,
                'features': np.array([area_density.mean(), np.percentile(area_density, 10), fill,
                                      np.log(short_o), np.log(long_o), np.log(long_o / max(short_o, 1)),
                                      coherence2, coherence4, dark,
                                      scale == 1.0, scale == 0.5, scale == 0.25], dtype=np.float64),
            })
    return found


def probability(features, model):
    z = ((features - model['mean']) / model['std']) @ model['weights'] + model['bias']
    return float(1.0 / (1.0 + np.exp(-np.clip(z, -30, 30))))


def _iou(a, b):
    ix = max(0, min(a['x'] + a['w'], b['x'] + b['w']) - max(a['x'], b['x']))
    iy = max(0, min(a['y'] + a['h'], b['y'] + b['h']) - max(a['y'], b['y']))
    inter = ix * iy
    return inter / (a['w'] * a['h'] + b['w'] * b['h'] - inter) if inter else 0.0


def find_regions(gray, model=MODEL):
    """Returns the code regions of a grayscale (or RGB) page, most probable first.

    Each region: {'box': 4 corner points (x, y) in the original image, 'x','y','w','h': its bounding box,
                  'angle': rotation in degrees, 'score': probability (0-1) that it is a code}
    """
    candidates = candidate_regions(gray)
    for c in candidates:
        c['score'] = probability(c['features'], model) if model else float(c['features'][0] * c['features'][2])
    threshold = model['threshold'] if model else 0.0
    kept = []
    # The same code shows up at several scales: keep the best box of each group of overlapping boxes
    for c in sorted(candidates, key=lambda c: -c['score']):
        if c['score'] >= threshold and all(_iou(c, k) < 0.3 for k in kept):
            kept.append(c)
    for c in kept:
        del c['features']
    return kept
