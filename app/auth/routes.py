from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, jwt_required, decode_token

from ..models.user import User
from ..models.token import Token
from sqlalchemy import func

from .. import audit
from ..extensions import db, email_key, limiter
from ..models.audit_log import AuditLog
from .services import (
    send_email, generate_verification_code,
    generate_reset_token, read_reset_token, PURPOSE_VERIFY, PURPOSE_RESET,
)

auth_bp = Blueprint('auth', __name__)


def _json():
    return request.get_json(silent=True) or {}


def _password_error(password):
    min_len = current_app.config['PASSWORD_MIN_LENGTH']
    if not password or len(password) < min_len:
        return f'Le mot de passe doit contenir au moins {min_len} caractères'
    return None


###############################################################################################################################

def _failure_limit():
    cfg = current_app.config
    return f"{cfg['LOGIN_MAX_FAILURES']} per {cfg['LOGIN_LOCK_MINUTES']} minutes"


def _note_failure(email, user, reason):
    """Writes the failed attempt to the audit log, and a single "locked" entry when this attempt is the one that locks the address."""
    audit.record(audit.LOGIN_FAILURE, actor=user, actor_email=email, success=False, details={'reason': reason})
    cfg = current_app.config
    since = datetime.utcnow() - timedelta(minutes=cfg['LOGIN_LOCK_MINUTES'])
    failures = AuditLog.query.filter(AuditLog.action == audit.LOGIN_FAILURE, func.lower(AuditLog.actor_email) == email,
                                     AuditLog.created_at >= since).count()
    if failures == cfg['LOGIN_MAX_FAILURES']:
        audit.record(audit.LOGIN_LOCKED, actor=user, actor_email=email, success=False,
                     details={'failures': failures, 'locked_minutes': cfg['LOGIN_LOCK_MINUTES']})


@auth_bp.route('/login', methods=['POST'])
@limiter.limit(lambda: current_app.config['LOGIN_RATE_LIMIT'])                       # per IP address: every attempt
@limiter.limit(_failure_limit, key_func=email_key, deduct_when=lambda r: r.status_code in (401, 403))   # per e-mail: failures only
def login():
    data = _json()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    user = User.query.filter_by(email=email).first()
    if not user:
        User.burn_password_check(password)          # same time as a real account: the answer time does not reveal who exists
        _note_failure(email, None, 'unknown_account')
        return jsonify({'message': 'Invalid credentials'}), 401
    if not user.check_password(password):
        _note_failure(email, user, 'wrong_password')
        return jsonify({'message': 'Invalid credentials'}), 401

    # Only administrators have accounts: the public page and the web service need no login
    if user.role != 'admin':
        _note_failure(email, user, 'not_admin')
        return jsonify({'message': 'Accès réservé aux administrateurs'}), 403

    access_token = create_access_token(identity=str(user.id), additional_claims={'role': user.role})
    claims = decode_token(access_token)
    db.session.add(Token(
        user_id=user.id,
        token=access_token,
        jti=claims['jti'],
        expires_at=datetime.utcfromtimestamp(claims['exp']),
        ip_address=request.remote_addr,
    ))
    db.session.commit()
    audit.record(audit.LOGIN_SUCCESS, actor=user)
    return jsonify({'access_token': access_token, 'role': user.role}), 200

###############################################################################################################################

@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    # Deleting the session row revokes this JWT (see token_in_blocklist_loader in app/__init__.py)
    Token.query.filter_by(jti=get_jwt()['jti']).delete()
    db.session.commit()
    audit.record(audit.LOGOUT, actor=db.session.get(User, int(get_jwt_identity())))
    return jsonify({'message': 'Logged out successfully'}), 200

###############################################################################################################################

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({'message': 'User not found'}), 404

    return jsonify({
        'email': user.email,
        'firstname': user.firstname,
        'lastname': user.lastname,
        'role': user.role,
    })

##############################################################################################################################
# Password reset, 3 steps:
#   1. /request-password-reset  email -> code sent by email + "verify" token
#   2. /verify-code             verify token + code -> "reset" token (max 5 attempts)
#   3. /reset-password          reset token + new password (token is single use)
##############################################################################################################################

@auth_bp.route('/request-password-reset', methods=['POST'])
@limiter.limit(lambda: current_app.config['RESET_REQUEST_LIMIT'])                    # each call can send an e-mail
@limiter.limit(lambda: current_app.config['RESET_EMAIL_LIMIT'], key_func=email_key)
def request_reset_password():
    email = (_json().get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'Email requis'}), 400

    # Same answer whether or not the account exists, so this endpoint can't be used
    # to find out which emails are registered.
    response = {
        'message': 'Si un compte existe pour cette adresse, un code de vérification a été envoyé.',
        'token': generate_reset_token(email, PURPOSE_VERIFY),
    }

    user = User.query.filter_by(email=email).first()
    audit.record(audit.PASSWORD_RESET_REQUEST, actor=user, actor_email=email, details={'known_account': bool(user)})
    if user:
        code = generate_verification_code()
        user.set_verification_code(code, current_app.config['RESET_CODE_TTL_MINUTES'])
        db.session.commit()

        ttl = current_app.config['RESET_CODE_TTL_MINUTES']
        body = f"Votre code de vérification est : {code}\n\nCe code expire dans {ttl} minutes."
        if not send_email(email, 'Code de vérification', body):
            return jsonify({'error': "Impossible d'envoyer l'email, réessayez plus tard"}), 500

    return jsonify(response), 200

##############################################################################################################################

@auth_bp.route('/verify-code', methods=['POST'])
@limiter.limit(lambda: current_app.config['RESET_STEP_LIMIT'])
def verify_code():
    data = _json()
    cfg = current_app.config

    payload = read_reset_token(data.get('token'), PURPOSE_VERIFY, cfg['RESET_CODE_TTL_MINUTES'])
    if not payload:
        return jsonify({'error': 'Lien expiré, recommencez la procédure'}), 400

    user = User.query.filter_by(email=payload['email']).first()
    if not user or not user.has_pending_code():
        return jsonify({'error': 'Code invalide ou expiré'}), 400

    if user.check_verification_code(data.get('code')):
        user.clear_verification_code()
        db.session.commit()
        reset_token = generate_reset_token(user.email, PURPOSE_RESET, user.password)
        return jsonify({'message': 'Verification code is valid', 'reset_token': reset_token}), 200

    # Wrong code: count the attempt, burn the code after too many
    user.verification_attempts = (user.verification_attempts or 0) + 1
    remaining = cfg['RESET_MAX_ATTEMPTS'] - user.verification_attempts
    if remaining <= 0:
        user.clear_verification_code()
        db.session.commit()
        return jsonify({'error': 'Trop de tentatives, demandez un nouveau code', 'attempts_left': 0}), 429
    db.session.commit()
    return jsonify({'error': 'Code incorrect', 'attempts_left': remaining}), 400

##############################################################################################################################

@auth_bp.route('/reset-password', methods=['POST'])
@limiter.limit(lambda: current_app.config['RESET_STEP_LIMIT'])
def reset_password():
    data = _json()
    cfg = current_app.config

    payload = read_reset_token(data.get('token'), PURPOSE_RESET, cfg['RESET_TOKEN_TTL_MINUTES'])
    if not payload:
        return jsonify({'error': 'Lien expiré, recommencez la procédure'}), 400

    user = User.query.filter_by(email=payload['email']).first()
    # 'ph' must match the current password hash: a token that was already used is rejected
    if not user or payload.get('ph') != user.password[-12:]:
        return jsonify({'error': 'Lien expiré, recommencez la procédure'}), 400

    new_password = data.get('password') or ''
    error = _password_error(new_password)
    if error:
        return jsonify({'error': error}), 400

    user.set_password(new_password)
    # Log out every existing session of this user
    Token.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    audit.record(audit.PASSWORD_RESET_DONE, actor=user, details={'sessions_closed': True})
    return jsonify({'message': 'Password reset successfully'}), 200
