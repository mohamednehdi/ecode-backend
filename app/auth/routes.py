from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from flask_cors import cross_origin
from flask_jwt_extended import create_access_token
from ..models.user import User
from ..models.token import Token
from ..extensions import db, bcrypt
from .services import send_email, generate_verification_code, generate_token,verify_token

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    if User.query.filter_by(email=email).first():
        return jsonify({'message': 'User already exists'}), 400

    user = User(email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({'message': 'User registered successfully'}), 201

###############################################################################################################################

@auth_bp.route('/login', methods=['POST', 'OPTIONS'])
@cross_origin(origins=["http://localhost:4200"], supports_credentials=True)
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        access_token = create_access_token(identity=str(user.id))
        expires_at = datetime.utcnow() + timedelta(minutes=30)  # Example expiration time
        ip_address = request.remote_addr
        new_token = Token(user_id=user.id, token=access_token, expires_at=expires_at, ip_address=ip_address)
        db.session.add(new_token)
        db.session.commit()
        return jsonify({'access_token': access_token,'role':user.role}), 200
        # return jsonify({'message':'user logged'}),200
    return jsonify({'message': 'Invalid credentials'}), 401

##############################################################################################################################

@auth_bp.route('/request-password-reset', methods=['POST'])
@cross_origin(origins=["http://localhost:4200"])
def request_reset_password():
    data = request.get_json()
    email = data.get('email')

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "Email not found"}), 404

    verification_code = generate_verification_code()
    user.set_verification_code(verification_code)
    db.session.commit()

    token = generate_token(email)

    subject = "Verification Code"
    body = f"Your verification code is: {verification_code}"

    if send_email(email, subject, body):
        return jsonify({"message": "Email sent successfully", "token": token}), 200
    else:
        return jsonify({"error": "Failed to send email"}), 500


##############################################################################################################################

@auth_bp.route('/verify-code', methods=['POST'])
@cross_origin(origins=["http://localhost:4200"], supports_credentials=True)
def verify_code():
    data = request.get_json()
    token = data.get('token')
    code = data.get('code')

    email = verify_token(token)
    if not email:
        return jsonify({"error": "Invalid or expired token"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "Email not found"}), 404

    if user.is_verification_code_valid(code):
        return jsonify({"message": "Verification code is valid"}), 200
    else:
        return jsonify({"error": "Invalid or expired verification code"}), 400
    
##############################################################################################################################

@auth_bp.route('/reset-password', methods=['POST'])
@cross_origin(origins=["http://localhost:4200"], supports_credentials=True)
def reset_password():
    data = request.get_json()
    token = data.get('token')
    new_password = data.get('password')

    email = verify_token(token)
    if not email:
        return jsonify({"error": "Invalid or expired token"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "Email not found"}), 404

    if user.verification_code and user.verification_code_expiry and datetime.utcnow() < user.verification_code_expiry:
        # The code is valid, reset the password
        user.set_password(new_password)
        user.verification_code = None  # Clear the verification code
        user.verification_code_expiry = None  # Clear the expiration time
        db.session.commit()
        return jsonify({"message": "Password reset successfully"}), 200
    else:
        return jsonify({"error": "No valid verification code found"}), 400