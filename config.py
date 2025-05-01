# import os
# from datetime import timedelta

# class Config:
#     SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key'
#     SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://root:@localhost/barcodedb2'
#     SQLALCHEMY_TRACK_MODIFICATIONS = False
#     JWT_SECRET_KEY = 'jwt-secret-key'
#     JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
#     SMTP_SERVER = 'smtp.gmail.com'
#     SMTP_PORT = 587
#     SMTP_USERNAME = 'your-email@gmail.com'
#     SMTP_PASSWORD = 'your-password'


import os

class Config:
    SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://root:@localhost/barcodedb'
    SQLALCHEMY_BINDS = {
        'scans': 'sqlite:///scans.db'  # Optional: if you want separate DB for scans
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'your-secret-key'