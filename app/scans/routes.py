"""Free public upload page: no account, limited per IP address."""
import logging
import os

from flask import Blueprint, current_app, jsonify, request

from ..extensions import limiter
from .services import process_document, is_pdf, InvalidImageError, InvalidPdfError, TooManyPagesError

logger = logging.getLogger(__name__)

public_bp = Blueprint('public', __name__)

ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}


@public_bp.route('/extract', methods=['POST'])
@limiter.limit(lambda: current_app.config['PUBLIC_RATE_LIMIT'])
def extract():
    """Upload a PDF/PNG/JPG (multipart field `file`); returns each page with boxes drawn and the codes found."""
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
        return jsonify({'error': 'Le contenu du fichier ne correspond pas à son extension'}), 400

    try:
        return jsonify(process_document(data))
    except InvalidImageError:
        return jsonify({'error': "Le fichier n'est pas une image valide"}), 400
    except InvalidPdfError:
        return jsonify({'error': 'Le fichier PDF est invalide ou protégé par mot de passe'}), 400
    except TooManyPagesError as e:
        return jsonify({'error': f'Le PDF contient trop de pages (max {e.max_pages})'}), 400
    except Exception:
        # Full details go to the server log, never to the client
        logger.exception('Barcode processing failed for %s', file.filename)
        return jsonify({'error': 'Erreur interne lors du traitement du fichier'}), 500
