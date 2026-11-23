import ipaddress
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.models.user import User
from app.models.api_token import ApiToken, ApiUsage, hash_key
from app.scans.services import SUPPORTED_TYPES
from app.extensions import db
from app import audit


admin_bp = Blueprint('admin', __name__)


def admin_required(fn):
    """Allows the request only for a logged-in admin. The admin is passed as `current_admin`."""
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        admin = db.session.get(User, int(get_jwt_identity()))
        if not admin or admin.role != 'admin':
            return jsonify({'error': 'Accès refusé'}), 403
        return fn(*args, current_admin=admin, **kwargs)
    return wrapper


###############################################################################################################################
# API tokens (web service access)

def _iso(value):
    return value.isoformat() if value else None


def _plain(value):
    """A value for the audit log: dates as text."""
    return value.isoformat() if isinstance(value, datetime) else value


def _token_json(t, now=None):
    now = now or datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = ApiUsage.query.filter(ApiUsage.token_id == t.id)
    return {
        'id': t.id,
        'name': t.name,
        'token_prefix': t.token_prefix,
        'is_active': t.is_active,
        'allowed_ips': t.ip_list,
        'allowed_types': t.type_list,
        'quota_hourly': t.quota_hourly,
        'quota_monthly': t.quota_monthly,
        'valid_from': _iso(t.valid_from),
        'valid_until': _iso(t.valid_until),
        'created_at': _iso(t.created_at),
        'last_used_at': _iso(t.last_used_at),
        'rotated_at': _iso(t.rotated_at),
        # while the previous key still works: until when (the application has until then to switch)
        'previous_key_valid_until': _iso(t.previous_valid_until) if t.previous_valid_until and t.previous_valid_until > now else None,
        'usage_hour': usage.filter(ApiUsage.created_at >= now - timedelta(hours=1)).count(),
        'usage_month': usage.filter(ApiUsage.created_at >= month_start).count(),
    }


def _parse_date(value):
    """ISO date/datetime -> naive UTC datetime (dates without a timezone are taken as UTC)."""
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_token_fields(body, partial=False):
    """Validates the token fields of a request body. Returns (values, error)."""
    values = {}

    if 'name' in body or not partial:
        name = str(body.get('name') or '').strip()
        if not name or len(name) > 100:
            return None, 'Le nom est obligatoire (100 caractères maximum)'
        values['name'] = name

    if 'is_active' in body:
        if not isinstance(body['is_active'], bool):
            return None, 'is_active doit être true ou false'
        values['is_active'] = body['is_active']

    if 'allowed_ips' in body:
        ips = body['allowed_ips'] or []
        if not isinstance(ips, list):
            return None, 'allowed_ips doit être une liste'
        ips = [str(ip).strip() for ip in ips if str(ip).strip()]
        for ip in ips:
            try:
                ipaddress.ip_network(ip, strict=False)
            except ValueError:
                return None, f'Adresse IP invalide : {ip}'
        values['allowed_ips'] = ', '.join(ips) or None

    if 'allowed_types' in body:
        types = body['allowed_types'] or []
        if not isinstance(types, list):
            return None, 'allowed_types doit être une liste'
        for t in types:
            if t not in SUPPORTED_TYPES:
                return None, f'Type de code-barres inconnu : {t}'
        values['allowed_types'] = ', '.join(types) or None

    for field in ('quota_hourly', 'quota_monthly'):
        if field in body:
            v = body[field]
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                return None, f'{field} doit être un entier positif ou vide (illimité)'
            values[field] = v

    for field in ('valid_from', 'valid_until'):
        if field in body:
            v = body[field]
            if v in (None, ''):
                values[field] = None
                continue
            try:
                values[field] = _parse_date(v)
            except ValueError:
                return None, f'{field} : date invalide'

    return values, None


@admin_bp.route('/supported-types', methods=['GET'])
@admin_required
def supported_types(current_admin):
    return jsonify(SUPPORTED_TYPES)


@admin_bp.route('/api-tokens', methods=['GET'])
@admin_required
def list_api_tokens(current_admin):
    now = datetime.utcnow()
    return jsonify([_token_json(t, now) for t in ApiToken.query.order_by(ApiToken.created_at.desc()).all()])


@admin_bp.route('/api-tokens', methods=['POST'])
@admin_required
def create_api_token(current_admin):
    values, error = _parse_token_fields(request.get_json(silent=True) or {})
    if error:
        return jsonify({'error': error}), 400
    if values.get('valid_from') and values.get('valid_until') and values['valid_until'] <= values['valid_from']:
        return jsonify({'error': 'La date de fin doit être après la date de début'}), 400

    raw_key = ApiToken.generate_key()
    token = ApiToken(token_hash=hash_key(raw_key), token_prefix=raw_key[:10], **values)
    db.session.add(token)
    db.session.commit()
    audit.record(audit.TOKEN_CREATE, actor=current_admin, target=token, details={k: _plain(v) for k, v in values.items() if k != 'name'})
    # The key is shown only now: only its hash is stored
    return jsonify({'token': _token_json(token), 'api_key': raw_key}), 201


@admin_bp.route('/api-tokens/<int:token_id>', methods=['PUT'])
@admin_required
def update_api_token(token_id, current_admin):
    token = db.session.get(ApiToken, token_id)
    if not token:
        return jsonify({'error': 'Clé introuvable'}), 404
    values, error = _parse_token_fields(request.get_json(silent=True) or {}, partial=True)
    if error:
        return jsonify({'error': error}), 400
    changes = {key: [_plain(getattr(token, key)), _plain(value)] for key, value in values.items() if getattr(token, key) != value}
    for key, value in values.items():
        setattr(token, key, value)
    if token.valid_from and token.valid_until and token.valid_until <= token.valid_from:
        db.session.rollback()
        return jsonify({'error': 'La date de fin doit être après la date de début'}), 400
    db.session.commit()
    audit.record(audit.TOKEN_UPDATE, actor=current_admin, target=token, details=changes or None)
    return jsonify(_token_json(token))


@admin_bp.route('/api-tokens/<int:token_id>', methods=['DELETE'])
@admin_required
def delete_api_token(token_id, current_admin):
    token = db.session.get(ApiToken, token_id)
    if not token:
        return jsonify({'error': 'Clé introuvable'}), 404
    snapshot = type('Deleted', (), {'id': token.id, 'name': token.name, 'token_hash': ''})()    # the row is about to disappear
    db.session.delete(token)  # its usage log is deleted too (cascade)
    db.session.commit()
    audit.record(audit.TOKEN_DELETE, actor=current_admin, target=snapshot)
    return jsonify({'message': 'Clé supprimée'})


MAX_GRACE_HOURS = 168       # one week


@admin_bp.route('/api-tokens/<int:token_id>/rotate', methods=['POST'])
@admin_required
def rotate_api_token(token_id, current_admin):
    """Gives the key a new secret. The old secret keeps working for `grace_hours` (0 = stops at once), so that the application that
    uses it can switch without an interruption. The restrictions and quotas of the key are unchanged. The new key is shown once."""
    token = db.session.get(ApiToken, token_id)
    if not token:
        return jsonify({'error': 'Clé introuvable'}), 404
    grace = (request.get_json(silent=True) or {}).get('grace_hours', 24)
    if isinstance(grace, bool) or not isinstance(grace, (int, float)) or not 0 <= grace <= MAX_GRACE_HOURS:
        return jsonify({'error': f'grace_hours doit être compris entre 0 et {MAX_GRACE_HOURS}'}), 400

    now = datetime.utcnow()
    raw_key = ApiToken.generate_key()
    token.previous_token_hash = token.token_hash if grace > 0 else None
    token.previous_valid_until = now + timedelta(hours=grace) if grace > 0 else None
    token.token_hash = hash_key(raw_key)
    token.token_prefix = raw_key[:10]
    token.rotated_at = now
    db.session.commit()
    audit.record(audit.TOKEN_ROTATE, actor=current_admin, target=token, details={'grace_hours': grace})
    return jsonify({'token': _token_json(token, now), 'api_key': raw_key})
