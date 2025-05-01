from ..extensions import db
from datetime import datetime, timedelta
from flask_bcrypt import generate_password_hash, check_password_hash

class User(db.Model):
    __tablename__ = 'user'  # Explicit table name to match existing
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    verification_code = db.Column(db.String(6), nullable=True)
    verification_code_expiry = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(50), default="user")
    tokens = db.relationship('Token', backref='user', lazy=True)

    def set_password(self, password):
        self.password = generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def set_verification_code(self, code):
        self.verification_code = code
        self.verification_code_expiry = datetime.utcnow() + timedelta(minutes=5)

    def is_verification_code_valid(self, code):
        return self.verification_code == code and datetime.utcnow() < self.verification_code_expiry