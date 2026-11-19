import base64
import io

import cv2
import numpy as np
import pymupdf
from flask import current_app
from PIL import Image, UnidentifiedImageError
from pylibdmtx.pylibdmtx import decode
from pyzbar import pyzbar

from ..extensions import db
from ..models.scan_history import ScanHistory


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


def _load_image(data):
    try:
        return np.array(Image.open(io.BytesIO(data)).convert('RGB'))
    except (UnidentifiedImageError, OSError) as e:
        raise InvalidImageError() from e


def _render_pdf_pages(data):
    """Renders every page of the PDF to an RGB numpy array."""
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
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            pages.append(img.copy())  # copy: the pixmap buffer is freed with the page
        return pages


def _decode_page(img_np, page_number):
    """Finds every barcode on one page, draws a box around each one and returns (results, jpeg bytes)."""
    barcodes = pyzbar.decode(img_np)
    data_matrix_codes = decode(img_np)
    results = []

    # Draw rectangles and collect data (image is RGB here)
    for barcode in barcodes:
        (x, y, w, h) = barcode.rect
        cv2.rectangle(img_np, (x, y), (x + w, y + h), (255, 0, 0), 2)  # red
        results.append({
            'page': page_number,
            'type': barcode.type,
            'data': barcode.data.decode('utf-8', errors='replace'),
            'coordinates': {'x': x, 'y': y, 'w': w, 'h': h}
        })

    for code in data_matrix_codes:
        (x, y, w, h) = code.rect
        # pylibdmtx measures y from the bottom of the image; convert to top-left origin
        top = img_np.shape[0] - y - h
        cv2.rectangle(img_np, (x, top), (x + w, top + h), (0, 255, 0), 2)  # green
        results.append({
            'page': page_number,
            'type': 'DataMatrix',
            'data': code.data.decode('utf-8', errors='replace'),
            'coordinates': {'x': x, 'y': top, 'w': w, 'h': h}
        })

    # OpenCV encodes BGR: convert, otherwise red and blue are swapped in the result image
    _, buffer = cv2.imencode('.jpg', cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR))
    return results, buffer.tobytes()


def process_document(data, user_id):
    """Decodes an image (PNG/JPG) or a PDF (every page).

    Returns {'barcodes': [...all codes, each with its page...],
             'pages': [{'page', 'image', 'barcodes'}, ...],
             'image': first page image (kept for older clients)}.
    """
    if is_pdf(data):
        images = _render_pdf_pages(data)
        file_type = 'pdf'
    else:
        images = [_load_image(data)]
        file_type = 'image'

    pages = []
    all_results = []
    for number, img_np in enumerate(images, start=1):
        results, image_bytes = _decode_page(img_np, number)
        for result in results:
            db.session.add(ScanHistory(
                user_id=user_id,
                code_type=result['type'],
                code_data=result['data'],
                page=number,
                image_data=image_bytes,
            ))
        all_results.extend(results)
        pages.append({
            'page': number,
            'image': base64.b64encode(image_bytes).decode('utf-8'),
            'barcodes': results,
        })
    db.session.commit()  # one commit for the whole document

    return {
        'file_type': file_type,
        'page_count': len(pages),
        'barcodes': all_results,
        'pages': pages,
        'image': pages[0]['image'],
    }
