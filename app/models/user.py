import secrets
from datetime import datetime, timedelta

from flask_bcrypt import generate_password_hash, check_password_hash

from ..extensions import db


class User(db.Model):
    __tablename__ = 'user'  # Explicit table name to match existing

    id = db.Column(db.Integer, primary_key=True)
    firstname = db.Column(db.String(100), nullable=True)
    lastname = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    verification_code = db.Column(db.String(6), nullable=True)
    verification_code_expiry = db.Column(db.DateTime, nullable=True)
    verification_attempts = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    is_active = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(50), default="user")

    # Deleting an admin also deletes their login sessions
    tokens = db.relationship('Token', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password = generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return check_password_hash(self.password, password)

    _dummy_hash = None

    @classmethod
    def burn_password_check(cls, password):
        """Checks the password against a throw-away hash of the same cost, so that "no such account" takes as long as "wrong password"."""
        if cls._dummy_hash is None:
            cls._dummy_hash = generate_password_hash('not-a-real-password').decode('utf-8')
        check_password_hash(cls._dummy_hash, password)

    def set_verification_code(self, code, ttl_minutes=15):
        self.verification_code = code
        self.verification_code_expiry = datetime.utcnow() + timedelta(minutes=ttl_minutes)
        self.verification_attempts = 0

    def clear_verification_code(self):
        self.verification_code = None
        self.verification_code_expiry = None
        self.verification_attempts = 0

    def has_pending_code(self):
        return bool(self.verification_code and self.verification_code_expiry
                    and datetime.utcnow() < self.verification_code_expiry)

    def check_verification_code(self, code):
        """Constant-time comparison so the code can't be guessed from response timing."""
        return self.has_pending_code() and secrets.compare_digest(self.verification_code, str(code or ''))
