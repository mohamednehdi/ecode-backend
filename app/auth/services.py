import logging
import secrets
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

logger = logging.getLogger(__name__)

# Two kinds of password-reset tokens. They are signed with SECRET_KEY (not the JWT key),
# so they can never be used as a login token.
PURPOSE_VERIFY = 'verify-code'      # given after the email is sent, lets you submit the code
PURPOSE_RESET = 'reset-password'    # given only after the right code, lets you set a new password
_SALT = 'password-reset'


def generate_verification_code():
    """6-digit code from a cryptographically secure source."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=_SALT)


def generate_reset_token(email, purpose, password_hash=None):
    payload = {'email': email, 'purpose': purpose}
    if password_hash:
        # Ties the token to the current password: once the password changes, the token is dead (single use)
        payload['ph'] = password_hash[-12:]
    return _serializer().dumps(payload)


def read_reset_token(token, purpose, max_age_minutes):
    """Returns the token payload, or None if it is invalid, expired or of the wrong kind."""
    if not token:
        return None
    try:
        payload = _serializer().loads(token, max_age=max_age_minutes * 60)
    except (BadSignature, SignatureExpired):
        return None
    if payload.get('purpose') != purpose:
        return None
    return payload


def send_email(to_email, subject, body):
    cfg = current_app.config
    if not cfg['SMTP_USERNAME'] or not cfg['SMTP_PASSWORD']:
        logger.error("SMTP_USERNAME / SMTP_PASSWORD are not set in .env; cannot send email")
        return False

    msg = MIMEMultipart()
    msg['From'] = cfg['SMTP_USERNAME']
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        with smtplib.SMTP(cfg['SMTP_SERVER'], cfg['SMTP_PORT'], timeout=15) as server:
            server.starttls()
            server.login(cfg['SMTP_USERNAME'], cfg['SMTP_PASSWORD'])
            server.sendmail(cfg['SMTP_USERNAME'], to_email, msg.as_string())
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False
