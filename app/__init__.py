import logging

from flask import Flask, jsonify

from config import Config
import click

from .extensions import db, migrate, bcrypt, jwt, cors, limiter


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    if app.config['TRUSTED_PROXIES']:
        # Behind Nginx: request.remote_addr must be the real client, not the proxy (IP rules, rate limits)
        from werkzeug.middleware.proxy_fix import ProxyFix
        hops = app.config['TRUSTED_PROXIES']
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=0, x_port=0, x_prefix=0)

    from .quota import make_quota
    app.extensions['quota'] = make_quota(app.config)

    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    limiter.init_app(app)
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

    @app.errorhandler(429)
    def too_many_requests(e):
        return jsonify({'error': 'Trop de requêtes, réessayez dans quelques instants'}), 429

    @app.get('/health')
    def health():
        """Liveness probe for Docker / the load balancer (does not touch the database)."""
        return jsonify({'status': 'ok'})

    # Register blueprints
    from app.auth.routes import auth_bp
    from app.scans.routes import public_bp
    from app.admin.routes import admin_bp
    from app.api.routes import api_bp
    from app.admin.stats import stats_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(public_bp, url_prefix='/public')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(stats_bp, url_prefix='/admin/stats')
    app.register_blueprint(api_bp, url_prefix='/api/v1')

    # Interactive documentation of the web service (Swagger UI, files served from the package: works offline)
    from flask_swagger_ui import get_swaggerui_blueprint
    app.register_blueprint(get_swaggerui_blueprint(
        '/api/docs', '/api/v1/openapi.json',
        config={'app_name': 'eCode API', 'docExpansion': 'list', 'defaultModelsExpandDepth': 1,
                'persistAuthorization': True, 'displayRequestDuration': True}), url_prefix='/api/docs')

    @app.cli.command('init-db')
    def init_db():
        """Prepares the database: builds it on first start, upgrades it afterwards (used by Docker).

        The first migrations of this project never created the base tables (they were created from the
        models), so `db upgrade` cannot build an EMPTY database: it is created from the models and every
        migration is marked as applied. A database that already has tables is upgraded normally.
        """
        from flask_migrate import stamp, upgrade
        from sqlalchemy import inspect
        if inspect(db.engine).get_table_names():
            upgrade()
            click.echo('Base de données mise à jour')
        else:
            db.create_all()
            stamp()
            click.echo('Base de données créée')

    @app.cli.command('create-admin')
    @click.option('--email', prompt=True)
    @click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(email, password):
        """Creates an administrator (or resets the password of an existing one)."""
        from .models.user import User
        email = email.strip().lower()
        min_len = app.config['PASSWORD_MIN_LENGTH']
        if '@' not in email:
            raise click.ClickException('Adresse email invalide')
        if len(password) < min_len:
            raise click.ClickException(f'Le mot de passe doit contenir au moins {min_len} caractères')

        user = User.query.filter_by(email=email).first()
        created = user is None
        if created:
            user = User(email=email)
            db.session.add(user)
        user.role = 'admin'
        user.is_active = True
        user.set_password(password)
        db.session.commit()
        click.echo(f"Administrateur {'créé' if created else 'mis à jour'} : {email}")

    @app.cli.command('seed-demo-usage')
    @click.option('--days', default=30, show_default=True, type=int)
    @click.option('--per-day', default=300, show_default=True, type=int, help='Requests on a weekday, all demo keys together')
    def seed_demo_usage(days, per_day):
        """Creates invented traffic (3 "[DEMO]" keys + request-log rows) so the statistics dashboard has something to show."""
        from .demo_data import seed
        count = seed(days, per_day)
        click.echo(f'{count} lignes de démonstration créées (clés "[DEMO]", IP 203.0.113.x). Données INVENTÉES : '
                   'à retirer avec `flask --app run clear-demo-usage`.')

    @app.cli.command('clear-demo-usage')
    def clear_demo_usage():
        """Removes the demo keys and the demo request-log rows."""
        from .demo_data import clear
        rows, tokens = clear()
        click.echo(f'{rows} lignes et {tokens} clés de démonstration supprimées')

    @app.cli.command('purge-usage')
    @click.option('--keep-days', default=35, show_default=True, type=int,
                  help='Keep the request log of the last N days (monthly quotas need the current month)')
    def purge_usage(keep_days):
        """Deletes old rows of the API request log (api_usage), which grows with every request."""
        from datetime import datetime, timedelta
        from .models.api_token import ApiUsage
        limit = datetime.utcnow() - timedelta(days=keep_days)
        total = 0
        while True:  # small batches: no long table lock on a busy server
            ids = [r[0] for r in db.session.query(ApiUsage.id).filter(ApiUsage.created_at < limit).limit(5000)]
            if not ids:
                break
            db.session.query(ApiUsage).filter(ApiUsage.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()
            total += len(ids)
        click.echo(f'{total} lignes supprimées (plus anciennes que {keep_days} jours)')

    return app
