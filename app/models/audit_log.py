from datetime import datetime

from ..extensions import db


class AuditLog(db.Model):
    """Who did what, when, from where: the security journal of the back office (append only).

    No route modifies or deletes a row (only `flask purge-audit` removes old ones). The actor's e-mail is copied into the row
    so that the entry stays readable if the account is deleted. Passwords, API keys and tokens are NEVER written here."""
    __tablename__ = 'audit_log'
    __table_args__ = (db.Index('ix_audit_log_created', 'created_at'), db.Index('ix_audit_log_action', 'action', 'created_at'))

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)      # UTC
    actor_id = db.Column(db.Integer, nullable=True)                                  # not a foreign key: the log outlives accounts
    actor_email = db.Column(db.String(120), nullable=True)
    action = db.Column(db.String(40), nullable=False)       # login.success, login.failure, login.blocked, logout, token.create, ...
    target_type = db.Column(db.String(20), nullable=True)   # 'api_token', 'user'
    target_id = db.Column(db.Integer, nullable=True)
    target_name = db.Column(db.String(100), nullable=True)
    details = db.Column(db.Text, nullable=True)             # JSON: what changed (field -> [before, after])
    ip_address = db.Column(db.String(45), nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=True)
