"""Writing to the audit log (docs/SECURITY_F9.md).

`record()` never raises: an audit failure must not break the action it describes, but it is logged loudly.
Secrets are filtered out of `details` as a second line of defence: nothing named like a password, key or token is stored.
"""
import json
import logging

from flask import has_request_context, request

from .extensions import db
from .models.audit_log import AuditLog

logger = logging.getLogger(__name__)

# Actions, so that a typo cannot create a new kind of entry silently
LOGIN_SUCCESS = 'login.success'
LOGIN_FAILURE = 'login.failure'
LOGIN_LOCKED = 'login.locked'
LOGOUT = 'logout'
TOKEN_CREATE = 'token.create'
TOKEN_UPDATE = 'token.update'
TOKEN_ROTATE = 'token.rotate'
TOKEN_DELETE = 'token.delete'
PASSWORD_RESET_REQUEST = 'password.reset_request'
PASSWORD_RESET_DONE = 'password.reset_done'
ADMIN_CLI = 'admin.cli'

ACTIONS = (LOGIN_SUCCESS, LOGIN_FAILURE, LOGIN_LOCKED, LOGOUT, TOKEN_CREATE, TOKEN_UPDATE, TOKEN_ROTATE, TOKEN_DELETE,
           PASSWORD_RESET_REQUEST, PASSWORD_RESET_DONE, ADMIN_CLI)

_SECRET_WORDS = ('password', 'secret', 'api_key', 'token_hash', 'jwt', 'authorization')


def _clean(details):
    """Drops any field that looks like a secret, whatever the caller passed."""
    if not isinstance(details, dict):
        return details
    return {k: ('[hidden]' if any(w in str(k).lower() for w in _SECRET_WORDS) else v) for k, v in details.items()}


def record(action, actor=None, actor_email=None, target=None, details=None, success=True):
    """Adds one row to the journal and commits it. `actor` is a User, `target` an ApiToken (or anything with id and name)."""
    try:
        entry = AuditLog(
            action=action,
            actor_id=getattr(actor, 'id', None),
            actor_email=(getattr(actor, 'email', None) or actor_email or None),
            target_type=('api_token' if target is not None and hasattr(target, 'token_hash') else ('user' if target is not None else None)),
            target_id=getattr(target, 'id', None),
            target_name=getattr(target, 'name', None) or getattr(target, 'email', None),
            details=json.dumps(_clean(details), ensure_ascii=False, default=str) if details else None,
            ip_address=request.remote_addr if has_request_context() else None,
            success=success,
        )
        if actor_email and not entry.actor_email:
            entry.actor_email = actor_email[:120]
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Could not write the audit log (%s)', action)
