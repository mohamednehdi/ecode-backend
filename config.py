import os
from datetime import timedelta

from dotenv import load_dotenv

# Load variables from the .env file next to this script (never committed to git)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))


def _required(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required setting '{name}'. Copy .env.example to .env and fill it in.")
    return value


class Config:
    # Security
    SECRET_KEY = _required('SECRET_KEY')
    JWT_SECRET_KEY = _required('JWT_SECRET_KEY')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(os.environ.get('JWT_EXPIRES_MINUTES', 30)))

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'mysql+pymysql://root:@localhost/barcodedb')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Database connection pool: keep at least as many connections as server threads (WAITRESS_THREADS)
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': int(os.environ.get('DB_POOL_SIZE', 20)),
        'max_overflow': int(os.environ.get('DB_POOL_OVERFLOW', 10)),
        'pool_pre_ping': True,    # drops dead connections instead of failing the request
        'pool_recycle': 280,      # MySQL closes idle connections after a while
    }

    # Uploads: anything bigger is rejected by Flask with 413
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_UPLOAD_MB', 10)) * 1024 * 1024

    # PDF: pages are rendered to images at this resolution before decoding
    PDF_DPI = int(os.environ.get('PDF_DPI', 200))
    PDF_MAX_PAGES = int(os.environ.get('PDF_MAX_PAGES', 20))

    # Hostile files: a tiny file can describe a gigantic picture (a 165 KB PNG of 12000x12000 pixels made the server use
    # 1.2 GB; a 0.5 KB PDF can ask for a page of several gigabytes). The size is read from the header BEFORE decoding.
    MAX_IMAGE_PIXELS = int(os.environ.get('MAX_IMAGE_PIXELS', 50_000_000))          # one image: refused above this
    # One PDF: every page is rendered at the usual resolution, or smaller when the page is huge, so that the whole
    # document stays within this many pixels (and no single page above MAX_IMAGE_PIXELS)
    MAX_DOCUMENT_PIXELS = int(os.environ.get('MAX_DOCUMENT_PIXELS', 100_000_000))

    # Decoding: scans larger than this (longest side, pixels) are decoded at reduced size
    DECODE_MAX_SIDE = int(os.environ.get('DECODE_MAX_SIDE', 3000))
    # Extra clean-up attempts on a poor scan when the fast pass finds nothing: time budget per document (ms), 0 = off
    DECODE_FALLBACK_BUDGET_MS = int(os.environ.get('DECODE_FALLBACK_BUDGET_MS', 2000))

    # Regions (localisation, see docs/LOCALIZER_STUDY.md): when the quick read finds nothing, the codes are located
    # first and each region is decoded separately (cropped, straightened, enlarged).
    #   first = regions, then page-wide clean-up passes | last = the other way round | off = page-wide passes only
    DECODE_REGIONS = os.environ.get('DECODE_REGIONS', 'first')
    # 1 = locate and decode the regions of EVERY page, even after the quick read found a code: finds the other
    # codes of a page (+18 points on pages with several codes) for about +65 ms. The public page always does it;
    # the API does it when the request has ?thorough=1.
    DECODE_ALL_REGIONS = os.environ.get('DECODE_ALL_REGIONS', '0') == '1'
    # Regions that look like a code but could not be read are reported when the localiser is at least this sure
    UNREAD_MIN_SCORE = float(os.environ.get('UNREAD_MIN_SCORE', 0.9))

    # Login protection: after LOGIN_MAX_FAILURES failed attempts for an e-mail address (known or not: the answer does not reveal
    # which accounts exist) every attempt for that address is refused for LOGIN_LOCK_MINUTES. Per IP address, LOGIN_RATE_LIMIT
    # caps all attempts (checking a password costs CPU). The password-reset routes send e-mails: they are limited too.
    LOGIN_MAX_FAILURES = int(os.environ.get('LOGIN_MAX_FAILURES', 5))
    LOGIN_LOCK_MINUTES = int(os.environ.get('LOGIN_LOCK_MINUTES', 15))
    LOGIN_RATE_LIMIT = os.environ.get('LOGIN_RATE_LIMIT', '20 per minute')
    RESET_REQUEST_LIMIT = os.environ.get('RESET_REQUEST_LIMIT', '5 per hour')           # e-mails asked, per IP address
    RESET_EMAIL_LIMIT = os.environ.get('RESET_EMAIL_LIMIT', '3 per hour')               # e-mails asked, per account
    RESET_STEP_LIMIT = os.environ.get('RESET_STEP_LIMIT', '20 per hour')                # code check / new password, per IP

    # HTTPS: sent only on requests that arrived over HTTPS (behind a proxy: TRUSTED_PROXIES=1). 0 = never send it.
    HSTS_SECONDS = int(os.environ.get('HSTS_SECONDS', 31536000))

    # Free public upload page: limit per IP address (Flask-Limiter syntax)
    PUBLIC_RATE_LIMIT = os.environ.get('PUBLIC_RATE_LIMIT', '10 per minute;60 per hour')
    # Redis (optional): when set, API quotas and the public rate limit are counted there, so that several
    # workers / servers share the same counters. Empty = counted in the database / in memory (one server).
    REDIS_URL = os.environ.get('REDIS_URL', '')
    # Where the rate-limit counters live: memory:// (one process) or redis://host:6379 (several workers/servers)
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI') or REDIS_URL or 'memory://'

    # Number of reverse proxies (Nginx...) in front of the app. With 1, the client IP is read from the
    # X-Forwarded-For header set by the proxy. Keep 0 when the app is reachable directly: the header is forgeable.
    TRUSTED_PROXIES = int(os.environ.get('TRUSTED_PROXIES', 0))

    # Frontend allowed by CORS
    FRONTEND_ORIGIN = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:4200')

    # Email (password reset)
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')

    # Password reset
    RESET_CODE_TTL_MINUTES = 15
    RESET_TOKEN_TTL_MINUTES = 10
    RESET_MAX_ATTEMPTS = 5
    PASSWORD_MIN_LENGTH = 8
