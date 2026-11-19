import base64
import logging
import os

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.models.scan_history import ScanHistory
from .services import process_document, is_pdf, InvalidImageError, InvalidPdfError, TooManyPagesError

logger = logging.getLogger(__name__)

scans_bp = Blueprint('scans', __name__)

ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}


@scans_bp.route('/upload', methods=['POST'])
@jwt_required()
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No selected file'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': 'Format non supporté (PDF, PNG ou JPG uniquement)'}), 415

    data = file.read()
    # The content must match the extension: a renamed file is rejected
    if (ext == '.pdf') != is_pdf(data):
        return jsonify({'error': "Le contenu du fichier ne correspond pas à son extension"}), 400

    try:
        result = process_document(data, int(get_jwt_identity()))
        return jsonify(result)
    except InvalidImageError:
        return jsonify({'error': "Le fichier n'est pas une image valide"}), 400
    except InvalidPdfError:
        return jsonify({'error': "Le fichier PDF est invalide ou protégé par mot de passe"}), 400
    except TooManyPagesError as e:
        return jsonify({'error': f'Le PDF contient trop de pages (max {e.max_pages})'}), 400
    except Exception:
        # Full details go to the server log, never to the client
        logger.exception("Barcode processing failed for %s", file.filename)
        return jsonify({'error': 'Erreur interne lors du traitement du fichier'}), 500


@scans_bp.route('/history', methods=['GET'])
@jwt_required()
def get_history():
    user_id = int(get_jwt_identity())
    scans = ScanHistory.query.filter_by(user_id=user_id).order_by(ScanHistory.scan_time.desc()).all()

    return jsonify([{
        'id': scan.id,
        'type': scan.code_type,
        'data': scan.code_data,
        'page': scan.page,
        'time': scan.scan_time.isoformat(),
        'image': base64.b64encode(scan.image_data).decode('utf-8') if scan.image_data else None
    } for scan in scans])
