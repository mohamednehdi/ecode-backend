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
