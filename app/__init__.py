from flask import Flask

from config import Config
from .extensions import db, migrate, bcrypt, jwt, cors



def create_app(config_class=Config):
    app = Flask(__name__)

    app.secret_key = 'supersecretkey'  # Replace with your actual secret key


    # app.config['SECRET_KEY'] = 'your_secret_key_here'
    # app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    # app.config['MAIL_PORT'] = 587
    # app.config['MAIL_USERNAME'] = 'noreplyybarcode@gmail.com'
    # app.config['MAIL_PASSWORD'] = 'nehdi.1965'
    # app.config['MAIL_USE_TLS'] = True
    # app.config['MAIL_USE_SSL'] = False  # Update SSL configuration as needed

    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    cors.init_app(app, supports_credentials=True, origins=["http://localhost:4200"],expose_headers=["Authorization", "Content-Type"])


    # Register blueprints
    from app.auth.routes import auth_bp
    from app.scans.routes import scans_bp
    from app.admin.routes import admin_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(scans_bp, url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    
        
    return app


