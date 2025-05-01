from ..extensions import db
from datetime import datetime

class ScanHistory(db.Model):
    __tablename__ = 'scan_history'  # New table
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))  # Links to existing user table
    code_type = db.Column(db.String(20))
    code_data = db.Column(db.Text)
    scan_time = db.Column(db.DateTime, default=datetime.utcnow)
    image_data = db.Column(db.LargeBinary)  # For storing scanned images

    def __repr__(self):
        return f'<Scan {self.code_type}: {self.code_data}>'