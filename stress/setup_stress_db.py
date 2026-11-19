"""Prepares an EMPTY SCRATCH database for the stress test, so the real database is never touched.

    python stress/setup_stress_db.py create     # creates database `barcode_stress`, its tables and a test API key
    python stress/setup_stress_db.py drop       # deletes the scratch database

It reuses the MySQL server of DATABASE_URL (from .env) and only changes the database name.
`create` prints the line to set before starting the server:   DATABASE_URL=...   (hidden password) and the API key.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

SCRATCH = 'barcode_stress'


def scratch_url():
    from config import Config
    return make_url(Config.SQLALCHEMY_DATABASE_URI).set(database=SCRATCH)


def server_engine():
    return create_engine(scratch_url()._replace(database=None))  # set(database=None) would keep the name


def create():
    with server_engine().begin() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {SCRATCH}'))
        conn.execute(text(f'CREATE DATABASE {SCRATCH} CHARACTER SET utf8mb4'))

    from app import create_app
    from app.extensions import db
    from app.models.api_token import ApiToken, hash_key
    from config import Config

    class StressConfig(Config):
        # Pinned to the scratch database (config.py would otherwise use the real DATABASE_URL)
        SQLALCHEMY_DATABASE_URI = scratch_url().render_as_string(hide_password=False)

    app = create_app(StressConfig)
    with app.app_context():
        assert db.engine.url.database == SCRATCH, 'refusing to touch a database other than the scratch one'
        db.create_all()
        key = ApiToken.generate_key()
        db.session.add(ApiToken(name='stress test', token_prefix=key[:10], token_hash=hash_key(key)))
        db.session.commit()
    print(f'scratch database "{SCRATCH}" created')
    print(f'API_KEY={key}')


def drop():
    with server_engine().begin() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {SCRATCH}'))
    print(f'scratch database "{SCRATCH}" deleted')


if __name__ == '__main__':
    {'create': create, 'drop': drop}[sys.argv[1]]()
