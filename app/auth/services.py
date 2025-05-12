from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import random
import smtplib

from flask_jwt_extended import create_access_token, decode_token
from jwt import ExpiredSignatureError, DecodeError

from itsdangerous import URLSafeTimedSerializer
from ..models.user import User
from ..extensions import db,jwt


serializer = URLSafeTimedSerializer('your_secret_key')
SECRET_KEY = 'supersecretkey'
SMTP_SERVER = 'smtp.gmail.com'  # Replace with your SMTP server
SMTP_PORT = 587
SMTP_USERNAME = 'noreplyybarcode@gmail.com'  # Replace with your "no-reply" email
SMTP_PASSWORD = 'wntw dzkv kuhk lpkb'


def create_user(email, password):
    """Service layer for user creation"""
    if User.query.filter_by(email=email).first():
        return None, 'User already exists'
    
    user = User(email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user, None

def authenticate_user(email, password):
    """Service layer for user authentication"""
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return None, 'Invalid credentials'
    return user, None

def generate_verification_code():
    return str(random.randint(100000, 999999))  # Generate a 6-digit random number



def send_email(to_email, subject, body):
    msg = MIMEMultipart()
    msg['From'] = SMTP_USERNAME
    msg['To'] = to_email
    msg['Subject'] = subject
    msg['Reply-To'] = ''  # Set to a non-existent or no-reply address

    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(SMTP_USERNAME, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
    

def generate_token(email):
    payload = {
        'email': email,
        'exp': datetime.utcnow() + timedelta(minutes=25)  # Token expires in 15 minutes
    }
    return create_access_token(identity=email, expires_delta=timedelta(minutes=25))

def verify_token(token):
    try:
        decoded = decode_token(token)
        return decoded.get("sub")  # sub contains the identity (email)
    except ExpiredSignatureError:
        return None
    except DecodeError:
        return None 