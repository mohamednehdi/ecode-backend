from flask import Flask
from flask_cors import CORS
from config import Config
from .extensions import db, migrate, bcrypt, jwt, cors

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Allow ALL routes for localhost:4200 during development
    CORS(app, resources={
        r"/*": {
            "origins": "http://localhost:4200",
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "supports_credentials": True
        }
    })    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    
    # Register blueprints
    from app.auth.routes import auth_bp
    from app.scans.routes import scans_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(scans_bp, url_prefix='/api')
    
    return app