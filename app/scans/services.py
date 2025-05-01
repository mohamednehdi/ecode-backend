import cv2
import numpy as np
from pyzbar import pyzbar
from pylibdmtx.pylibdmtx import decode
from PIL import Image
import io
import base64
from datetime import datetime
from ..models.scan_history import ScanHistory
from ..extensions import db
def process_barcode_image(file, user_id):
    try:
        img = Image.open(io.BytesIO(file.read())).convert('RGB')
        img_np = np.array(img)
        
        # Process barcodes
        barcodes = pyzbar.decode(img_np)
        data_matrix_codes = decode(img_np)
        results = []
        
        # Draw rectangles and collect data
        for barcode in barcodes:
            (x, y, w, h) = barcode.rect
            cv2.rectangle(img_np, (x, y), (x + w, y + h), (0, 0, 255), 2)
            data = barcode.data.decode('utf-8')
            results.append({
                'type': barcode.type,
                'data': data,
                'coordinates': {'x': x, 'y': y, 'w': w, 'h': h}
            })
            save_scan(user_id, barcode.type, data, img)
        
        for code in data_matrix_codes:
            (x, y, w, h) = code.rect
            cv2.rectangle(img_np, (x, y), (x + w, y + h), (0, 255, 0), 2)
            data = code.data.decode('utf-8')
            results.append({
                'type': 'DataMatrix',
                'data': data,
                'coordinates': {'x': x, 'y': y, 'w': w, 'h': h}
            })
            save_scan(user_id, 'DataMatrix', data, img)
        
        # Convert processed image to base64
        _, buffer = cv2.imencode('.jpg', img_np)
        return {
            'image': base64.b64encode(buffer).decode('utf-8'),
            'barcodes': results
        }
        
    except Exception as e:
        raise e

def save_scan(user_id, code_type, code_data, image):
    """Save scan to database with image"""
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='JPEG')
    img_byte_arr = img_byte_arr.getvalue()
    
    scan = ScanHistory(
        user_id=user_id,
        code_type=code_type,
        code_data=code_data,
        image_data=img_byte_arr
    )
    db.session.add(scan)
    db.session.commit()