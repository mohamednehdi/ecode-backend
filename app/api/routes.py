"""Public web service for third-party applications. Authenticated only by an API key."""
import logging
import os
import time
from datetime import datetime, timedelta

from flask import Blueprint, current_app, request, jsonify

from ..extensions import db
from .openapi import build_spec
from ..models.api_token import ApiToken, ApiUsage, hash_key
from ..scans.services import (
    extract_document, is_pdf, InvalidImageError, InvalidPdfError, TooManyPagesError,
)

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__)

ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}


def _error(message, status):
    return jsonify({'error': message}), status


def _read_upload():
    """Returns (file bytes, None), or (None, error response) when the upload is not acceptable."""
    file = request.files.get('file')
    if not file or not file.filename:
        return None, _error('Aucun fichier reçu (champ multipart "file")', 400)
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None, _error('Format non supporté (PDF, PNG ou JPG uniquement)', 415)
    data = file.read()
    if (ext == '.pdf') != is_pdf(data):
        return None, _error('Le contenu du fichier ne correspond pas à son extension', 400)
    return data, None


def _log_usage(token, now, status, duration_ms, file_bytes, thorough, **outcome):
    """Writes the request log row (quota counting + statistics). A logging failure never fails the request."""
    try:
        db.session.add(ApiUsage(token_id=token.id, created_at=now, ip_address=request.remote_addr, status_code=status,
                                duration_ms=duration_ms, file_bytes=file_bytes, thorough=thorough, **outcome))
        # "last used" is informative only: refresh it at most once a minute to keep the write per request small
        if token.last_used_at is None or now - token.last_used_at > timedelta(seconds=60):
            token.last_used_at = now
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Could not write the request log for token %s', token.id)


@api_bp.route('/openapi.json', methods=['GET'])
def openapi():
    """The OpenAPI description of this service (shown by Swagger UI at /api/docs)."""
    return jsonify(build_spec(current_app.config))


@api_bp.route('/extract', methods=['POST'])
def extract():
    """POST a PDF/PNG/JPG as multipart field `file` with header `X-API-Key`. Returns the codes as JSON.

    Optional `?thorough=1`: also locate and decode the other codes of a page where one code was already read
    (slower). `unread_regions` lists regions that look like a code but could not be read."""
    raw_key = request.headers.get('X-API-Key', '').strip()
    if not raw_key:
        return _error('Clé API manquante (en-tête X-API-Key)', 401)

    token = ApiToken.query.filter_by(token_hash=hash_key(raw_key)).first()
    if not token:
        return _error('Clé API invalide', 401)

    now = datetime.utcnow()
    if not token.is_active:
        return _error('Clé API désactivée', 403)
    if token.valid_from and now < token.valid_from:
        return _error('Clé API pas encore valide', 403)
    if token.valid_until and now > token.valid_until:
        return _error('Clé API expirée', 403)
    if not token.ip_allowed(request.remote_addr):
        return _error('Adresse IP non autorisée pour cette clé', 403)

    # Quota: checked and counted in one atomic step (shared by every worker), given back if the file is refused
    quota = current_app.extensions['quota']
    quota_message, reservation = quota.reserve(token, now)
    if quota_message:
        return _error(quota_message, 429)

    data, upload_error = _read_upload()
    if upload_error:
        quota.release(reservation)
        return upload_error

    allowed_types = set(token.type_list) or None
    thorough = request.args.get('thorough', '').lower() in ('1', 'true', 'yes')
    outcome = {'codes_found': 0, 'pages': 0, 'file_type': 'pdf' if is_pdf(data) else 'image'}
    started = time.perf_counter()
    try:
        result = extract_document(data, allowed_types, thorough)
        outcome.update(codes_found=len(result['barcodes']), pages=result['page_count'])
        response = jsonify(result), 200
    except InvalidImageError:
        response = _error("Le fichier n'est pas une image valide", 400)
    except InvalidPdfError:
        response = _error('Le fichier PDF est invalide ou protégé par mot de passe', 400)
    except TooManyPagesError as e:
        response = _error(f'Le PDF contient trop de pages (max {e.max_pages})', 400)
    except Exception:
        logger.exception('API extraction failed for token %s', token.id)
        response = _error('Erreur interne lors du traitement du fichier', 500)

    # The request is logged whatever the outcome (a failing file counts against the quota too). One insert per request.
    _log_usage(token, now, response[1], int((time.perf_counter() - started) * 1000), len(data), thorough, **outcome)
    return response
