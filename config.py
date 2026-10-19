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

    # Uploads: anything bigger is rejected by Flask with 413
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_UPLOAD_MB', 10)) * 1024 * 1024

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
