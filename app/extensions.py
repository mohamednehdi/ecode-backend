from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
migrate = Migrate()
bcrypt = Bcrypt()
jwt = JWTManager()
cors = CORS()
# No default limit: only the public upload route is limited. Storage comes from RATELIMIT_STORAGE_URI.
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def email_key():
    """Rate-limit key of a login or password-reset request: its e-mail address, known or not (same treatment, no enumeration)."""
    from flask import request
    body = request.get_json(silent=True)
    email = body.get('email') if isinstance(body, dict) else ''
    return 'email:' + str(email or '').strip().lower()[:120]
