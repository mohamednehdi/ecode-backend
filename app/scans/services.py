import base64
import io

import cv2
import numpy as np
import pymupdf
from flask import current_app
from PIL import Image, UnidentifiedImageError

from .decoder import SUPPORTED_TYPES, draw_boxes, find_codes, new_fallback_deadline  # noqa: F401 (SUPPORTED_TYPES is re-exported)



class InvalidImageError(Exception):
    """The uploaded file is not a readable image."""


class InvalidPdfError(Exception):
    """The uploaded file is not a readable PDF."""


class TooManyPagesError(Exception):
    """The PDF has more pages than PDF_MAX_PAGES."""

    def __init__(self, max_pages):
        super().__init__(max_pages)
        self.max_pages = max_pages


def is_pdf(data):
    return data[:5] == b'%PDF-'


def _load_image(data, gray=False):
    """Image bytes -> numpy array. gray=True is faster and enough when no result image is drawn."""
    try:
        image = Image.open(io.BytesIO(data))
        if gray:
            image.draft('L', image.size)  # JPEG: decode only the luminance (faster); ignored by other formats
        return np.array(image.convert('L' if gray else 'RGB'))
    except (UnidentifiedImageError, OSError) as e:
        raise InvalidImageError() from e


def _render_pdf_pages(data, gray=False):
    """Renders every page of the PDF to a numpy array (RGB, or grayscale when gray=True: faster)."""
    dpi = current_app.config['PDF_DPI']
    max_pages = current_app.config['PDF_MAX_PAGES']
    try:
        doc = pymupdf.open(stream=data, filetype='pdf')
    except Exception as e:
        raise InvalidPdfError() from e

    with doc:
        if doc.needs_pass:
            raise InvalidPdfError()
        if doc.page_count == 0:
            raise InvalidPdfError()
        if doc.page_count > max_pages:
            raise TooManyPagesError(max_pages)

        pages = []
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY if gray else pymupdf.csRGB, alpha=False)
            shape = (pix.height, pix.width) if gray else (pix.height, pix.width, 3)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(shape)
            pages.append(img.copy())  # copy: the pixmap buffer is freed with the page
        return pages


def _decode_page(img_np, page_number, deadline=None):
    """Finds every barcode on one page, draws a box around each one and returns (results, jpeg bytes)."""
    results = find_codes(img_np, page_number, deadline=deadline)
    draw_boxes(img_np, results)

    # OpenCV encodes BGR: convert, otherwise red and blue are swapped in the result image
    _, buffer = cv2.imencode('.jpg', cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR))
    return results, buffer.tobytes()


def _load_pages(data, gray=False):
    """Returns (file_type, [arrays]) for an image or a PDF."""
    if is_pdf(data):
        return 'pdf', _render_pdf_pages(data, gray)
    return 'image', [_load_image(data, gray)]


def extract_document(data, allowed_types=None):
    """Web-service extraction: JSON only, no result images, nothing saved in the database."""
    file_type, images = _load_pages(data, gray=True)
    deadline = new_fallback_deadline()  # one clean-up time budget for the whole document
    barcodes = []
    for number, img_np in enumerate(images, start=1):
        barcodes.extend(find_codes(img_np, number, allowed_types, deadline))
    return {'file_type': file_type, 'page_count': len(images), 'barcodes': barcodes}


def process_document(data):
    """Decodes an image (PNG/JPG) or a PDF (every page) for the public web page.

    Returns {'file_type', 'page_count',
             'barcodes': [...all codes, each with its page...],
             'pages': [{'page', 'image' (base64 jpeg with boxes), 'barcodes'}, ...]}.
    Nothing is stored.
    """
    file_type, images = _load_pages(data)

    deadline = new_fallback_deadline()  # one clean-up time budget for the whole document
    pages = []
    all_results = []
    for number, img_np in enumerate(images, start=1):
        results, image_bytes = _decode_page(img_np, number, deadline)
        all_results.extend(results)
        pages.append({
            'page': number,
            'image': base64.b64encode(image_bytes).decode('utf-8'),
            'barcodes': results,
        })

    return {
        'file_type': file_type,
        'page_count': len(pages),
        'barcodes': all_results,
        'pages': pages,
    }
