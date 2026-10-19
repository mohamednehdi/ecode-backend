from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, jwt_required, decode_token

from ..models.user import User
from ..models.token import Token
from ..extensions import db
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

@auth_bp.route('/register', methods=['POST'])
def register():
    data = _json()
    firstname = (data.get('first_name') or '').strip()
    lastname = (data.get('last_name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or '@' not in email:
        return jsonify({'message': 'Adresse email invalide'}), 400
    error = _password_error(password)
    if error:
        return jsonify({'message': error}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'message': 'User already exists'}), 400

    user = User(email=email, firstname=firstname, lastname=lastname)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({'message': 'User registered successfully'}), 201

###############################################################################################################################

@auth_bp.route('/login', methods=['POST'])
def login():
    data = _json()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({'message': 'Invalid credentials'}), 401

    # Accounts must be approved by an admin first (admins are never blocked)
    if not user.is_active and user.role != 'admin':
        return jsonify({'message': 'Compte en attente de validation par un administrateur'}), 403

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
    return jsonify({'access_token': access_token, 'role': user.role}), 200

###############################################################################################################################

@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    # Deleting the session row revokes this JWT (see token_in_blocklist_loader in app/__init__.py)
    Token.query.filter_by(jti=get_jwt()['jti']).delete()
    db.session.commit()
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
    return jsonify({'message': 'Password reset successfully'}), 200
