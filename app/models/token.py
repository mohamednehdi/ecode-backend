from ..extensions import db
from datetime import datetime


class Token(db.Model):
    """One row per active login session. Deleting the row revokes the JWT."""
    __tablename__ = 'token'  # Explicit table name to match existing

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(512), unique=True, nullable=False)
    jti = db.Column(db.String(36), unique=True, nullable=True, index=True)  # JWT unique ID
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)

    def __repr__(self):
        return f'<Token {self.jti}>'
