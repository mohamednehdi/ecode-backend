from ..models.user import User
from ..extensions import db

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