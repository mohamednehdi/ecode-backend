from ..extensions import db
from datetime import datetime

class Token(db.Model):
    __tablename__ = 'token'  # Explicit table name to match existing
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(512), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)

    def __repr__(self):
        return f'<Token {self.token}>'