import base64
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.models.scan_history import ScanHistory
from .services import process_barcode_image
from ..models.user import User

scans_bp = Blueprint('scans', __name__)

@scans_bp.route('/upload', methods=['POST'])
@jwt_required()
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No selected file'}), 400

    try:
        user_id = get_jwt_identity()
        result = process_barcode_image(file, user_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@scans_bp.route('/history', methods=['GET'])
@jwt_required()
def get_history():
    user_id = get_jwt_identity()
    scans = ScanHistory.query.filter_by(user_id=user_id).order_by(ScanHistory.scan_time.desc()).all()
    
    return jsonify([{
        'id': scan.id,
        'type': scan.code_type,
        'data': scan.code_data,
        'time': scan.scan_time.isoformat(),
        'image': base64.b64encode(scan.image_data).decode('utf-8') if scan.image_data else None
    } for scan in scans])