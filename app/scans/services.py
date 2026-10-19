import base64
import io

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from pylibdmtx.pylibdmtx import decode
from pyzbar import pyzbar

from ..extensions import db
from ..models.scan_history import ScanHistory


class InvalidImageError(Exception):
    """The uploaded file is not a readable image."""


def process_barcode_image(file, user_id):
    try:
        img = Image.open(io.BytesIO(file.read())).convert('RGB')
    except (UnidentifiedImageError, OSError) as e:
        raise InvalidImageError() from e

    img_np = np.array(img)

    barcodes = pyzbar.decode(img_np)
    data_matrix_codes = decode(img_np)
    results = []

    # Draw rectangles and collect data (image is RGB here)
    for barcode in barcodes:
        (x, y, w, h) = barcode.rect
        cv2.rectangle(img_np, (x, y), (x + w, y + h), (255, 0, 0), 2)  # red
        results.append({
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
            'type': 'DataMatrix',
            'data': code.data.decode('utf-8', errors='replace'),
            'coordinates': {'x': x, 'y': top, 'w': w, 'h': h}
        })

    # OpenCV encodes BGR: convert, otherwise red and blue are swapped in the result image
    _, buffer = cv2.imencode('.jpg', cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR))
    image_bytes = buffer.tobytes()

    for result in results:
        db.session.add(ScanHistory(
            user_id=user_id,
            code_type=result['type'],
            code_data=result['data'],
            image_data=image_bytes,
        ))
    db.session.commit()  # one commit for all codes of this image

    return {
        'image': base64.b64encode(image_bytes).decode('utf-8'),
        'barcodes': results
    }
