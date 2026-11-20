import hashlib
import ipaddress
import secrets
from datetime import datetime

from ..extensions import db

KEY_PREFIX = 'ecode_'


def hash_key(raw_key):
    """Only the hash of an API key is stored: a database leak does not leak usable keys."""
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()


def _csv(value):
    return [item.strip() for item in (value or '').split(',') if item.strip()]


class ApiToken(db.Model):
    """Key given to a third-party application to call the extraction web service."""
    __tablename__ = 'api_token'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)                    # application / client name
    token_prefix = db.Column(db.String(16), nullable=False)             # first characters, to recognize a key
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    allowed_ips = db.Column(db.Text, nullable=True)                     # "1.2.3.4, 10.0.0.0/24"; empty = any IP
    allowed_types = db.Column(db.Text, nullable=True)                   # "QRCODE, DataMatrix"; empty = all types
    quota_hourly = db.Column(db.Integer, nullable=True)                 # requests per rolling hour; empty = unlimited
    quota_monthly = db.Column(db.Integer, nullable=True)                # requests per calendar month; empty = unlimited
    valid_from = db.Column(db.DateTime, nullable=True)
    valid_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)

    usages = db.relationship('ApiUsage', backref='api_token', lazy=True, cascade='all, delete-orphan')

    @classmethod
    def generate_key(cls):
        return KEY_PREFIX + secrets.token_urlsafe(32)

    @property
    def ip_list(self):
        return _csv(self.allowed_ips)

    @property
    def type_list(self):
        return _csv(self.allowed_types)

    def ip_allowed(self, ip):
        entries = self.ip_list
        if not entries:
            return True
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(address in ipaddress.ip_network(entry, strict=False) for entry in entries)

    def __repr__(self):
        return f'<ApiToken {self.name} {self.token_prefix}…>'


class ApiUsage(db.Model):
    """One row per accepted request (the file was valid and was processed, or failed while being processed).

    Quotas in database mode are computed by counting these rows; the admin statistics (docs/STATISTICS.md) read
    the outcome columns. Rows written before the statistics existed have NULL outcome columns."""
    __tablename__ = 'api_usage'
    __table_args__ = (db.Index('ix_api_usage_token_time', 'token_id', 'created_at'),
                      db.Index('ix_api_usage_created', 'created_at'))

    id = db.Column(db.Integer, primary_key=True)
    token_id = db.Column(db.Integer, db.ForeignKey('api_token.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)     # when the request arrived (UTC)
    ip_address = db.Column(db.String(45), nullable=True)
    # Outcome of the request
    status_code = db.Column(db.SmallInteger, nullable=True)          # HTTP status sent back: 200, 400, 500
    duration_ms = db.Column(db.Integer, nullable=True)               # processing time of the extraction
    codes_found = db.Column(db.Integer, nullable=True)
    pages = db.Column(db.SmallInteger, nullable=True)
    file_type = db.Column(db.String(8), nullable=True)               # 'image' or 'pdf'
    file_bytes = db.Column(db.Integer, nullable=True)
    thorough = db.Column(db.Boolean, nullable=True)                  # request made with ?thorough=1
