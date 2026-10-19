import logging

from flask import Flask, jsonify

from config import Config
from .extensions import db, migrate, bcrypt, jwt, cors


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    cors.init_app(
        app,
        supports_credentials=True,
        origins=[app.config['FRONTEND_ORIGIN']],
        expose_headers=["Authorization", "Content-Type"],
    )

    # Every JWT must match a row in the `token` table; logout deletes the row,
    # which revokes the token immediately.
    from .models.token import Token

    @jwt.token_in_blocklist_loader
    def is_token_revoked(jwt_header, jwt_payload):
        return Token.query.filter_by(jti=jwt_payload['jti']).first() is None

    @jwt.revoked_token_loader
    def revoked_token_response(jwt_header, jwt_payload):
        return jsonify({'error': 'Session expirée, veuillez vous reconnecter'}), 401

    @jwt.expired_token_loader
    def expired_token_response(jwt_header, jwt_payload):
        return jsonify({'error': 'Session expirée, veuillez vous reconnecter'}), 401

    @app.errorhandler(413)
    def file_too_large(e):
        max_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
        return jsonify({'error': f'Fichier trop volumineux (max {max_mb} Mo)'}), 413

    # Register blueprints
    from app.auth.routes import auth_bp
    from app.scans.routes import scans_bp
    from app.admin.routes import admin_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(scans_bp, url_prefix='/scans')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    return app
