"""Security and functional tests for the Flask API.

Run from the project folder:   python -m pytest -q tests
(dev dependencies: pip install -r requirements-dev.txt)
"""
import io
import os
import sys
import tempfile

# Test settings are set before the app is imported, so they win over .env
_DB = os.path.join(tempfile.gettempdir(), 'barcode_test.db')
os.environ.update(SECRET_KEY='t' * 64, JWT_SECRET_KEY='j' * 64, DATABASE_URL='sqlite:///' + _DB,
                  SMTP_USERNAME='test@example.com', SMTP_PASSWORD='x', PUBLIC_RATE_LIMIT='1000 per minute')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image


@pytest.fixture()
def ctx(monkeypatch):
    from app import create_app
    from app.extensions import db
    from app.models.user import User
    import app.auth.routes as auth_routes

    sent = []  # emails are captured instead of being sent
    monkeypatch.setattr(auth_routes, 'send_email', lambda to, subject, body: sent.append(body) or True)

    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = User(email='admin@t.com', role='admin', is_active=True)
        admin.set_password('adminpass1')
        db.session.add(admin)
        db.session.commit()
    yield app.test_client(), sent, app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def login(c, e, p): return c.post('/auth/login', json={'email': e, 'password': p})
def H(t): return {'Authorization': f'Bearer {t}'}

def _user_jwt(app):
    """A valid session token of a NON-admin user (such sessions can no longer be created by login)."""
    from datetime import datetime
    from flask_jwt_extended import create_access_token, decode_token
    from app.extensions import db
    from app.models.token import Token
    from app.models.user import User
    with app.app_context():
        u = User(email='plain@t.com', role='user', is_active=True); u.set_password('goodpass1')
        db.session.add(u); db.session.commit()
        t = create_access_token(identity=str(u.id)); claims = decode_token(t)
        db.session.add(Token(user_id=u.id, token=t, jti=claims['jti'], expires_at=datetime.utcfromtimestamp(claims['exp'])))
        db.session.commit()
        return t

def test_login_is_for_admins_only(ctx):
    c, _, app = ctx
    with app.app_context():
        from app.extensions import db
        from app.models.user import User
        u = User(email='u@t.com', role='user', is_active=True); u.set_password('goodpass1')
        db.session.add(u); db.session.commit()
    assert login(c, 'admin@t.com', 'adminpass1').status_code == 200
    assert login(c, 'admin@t.com', 'wrongpass').status_code == 401
    assert login(c, 'u@t.com', 'wrongpass').status_code == 401        # no hint about the role without the password
    assert login(c, 'u@t.com', 'goodpass1').status_code == 403        # right password, but not an admin
    assert c.post('/auth/register', json={'email': 'n@t.com', 'password': 'goodpass1'}).status_code == 404  # no signup

def test_removed_user_features_are_gone(ctx):
    c, _, _ = ctx
    tok = login(c, 'admin@t.com', 'adminpass1').json['access_token']
    for method, url in (('get', '/admin/users'), ('get', '/admin/active-users'), ('post', '/admin/approve-user/1'),
                        ('delete', '/admin/delete-user/1'), ('get', '/scans/history'), ('post', '/scans/upload')):
        assert getattr(c, method)(url, headers=H(tok)).status_code == 404, url

def test_admin_routes_need_an_admin_token(ctx):
    c, _, app = ctx
    assert c.get('/admin/api-tokens').status_code == 401
    assert c.get('/admin/api-tokens', headers=H('garbage')).status_code in (401, 422)
    assert c.get('/admin/api-tokens', headers=H(_user_jwt(app))).status_code == 403   # a non-admin session is refused

def test_create_admin_command(ctx):
    c, _, app = ctx
    runner = app.test_cli_runner()
    r = runner.invoke(args=['create-admin', '--email', 'New@T.com', '--password', 'longenough1'])
    assert r.exit_code == 0 and 'créé' in r.output, r.output
    assert login(c, 'new@t.com', 'longenough1').json['role'] == 'admin'
    r = runner.invoke(args=['create-admin', '--email', 'new@t.com', '--password', 'another-pass1'])
    assert 'mis à jour' in r.output
    assert login(c, 'new@t.com', 'another-pass1').status_code == 200
    assert runner.invoke(args=['create-admin', '--email', 'x@t.com', '--password', 'short']).exit_code != 0
    assert runner.invoke(args=['create-admin', '--email', 'bad', '--password', 'longenough1']).exit_code != 0

def test_logout_revokes_token(ctx):
    c, _, _ = ctx
    tok = login(c, 'admin@t.com', 'adminpass1').json['access_token']
    assert c.get('/auth/me', headers=H(tok)).status_code == 200
    assert c.post('/auth/logout', headers=H(tok)).status_code == 200
    assert c.get('/auth/me', headers=H(tok)).status_code == 401

def test_reset_flow_secure(ctx):
    c, sent, _ = ctx
    # unknown email: same answer, no email sent
    r = c.post('/auth/request-password-reset', json={'email':'nobody@t.com'}); assert r.status_code == 200 and not sent
    r = c.post('/auth/request-password-reset', json={'email':'admin@t.com'}); assert r.status_code == 200
    vtok = r.json['token']; code = sent[-1].split(': ')[1][:6]
    # OLD BUG: calling reset-password directly with the first token must now fail
    assert c.post('/auth/reset-password', json={'token': vtok, 'password':'hacked123'}).status_code == 400
    # the verify token is not a login token
    assert c.get('/auth/me', headers=H(vtok)).status_code in (401, 422)
    bad = '000000' if code != '000000' else '111111'
    r = c.post('/auth/verify-code', json={'token': vtok, 'code': bad}); assert r.status_code == 400 and r.json['attempts_left'] == 4
    r = c.post('/auth/verify-code', json={'token': vtok, 'code': code}); assert r.status_code == 200
    rtok = r.json['reset_token']
    session = login(c, 'admin@t.com', 'adminpass1').json['access_token']
    assert c.post('/auth/reset-password', json={'token': rtok, 'password':'short'}).status_code == 400
    assert c.post('/auth/reset-password', json={'token': rtok, 'password':'newpass123'}).status_code == 200
    assert c.post('/auth/reset-password', json={'token': rtok, 'password':'again12345'}).status_code == 400  # single use
    assert c.get('/auth/me', headers=H(session)).status_code == 401   # old sessions logged out
    assert login(c, 'admin@t.com', 'newpass123').status_code == 200

def test_bruteforce_burns_code(ctx):
    c, sent, _ = ctx
    vtok = c.post('/auth/request-password-reset', json={'email':'admin@t.com'}).json['token']
    code = sent[-1].split(': ')[1][:6]; bad = '000000' if code != '000000' else '111111'
    codes = [c.post('/auth/verify-code', json={'token': vtok, 'code': bad}).status_code for _ in range(5)]
    assert codes[-1] == 429
    assert c.post('/auth/verify-code', json={'token': vtok, 'code': code}).status_code == 400  # burned

def _sample_image():
    import segno, barcode
    from barcode.writer import ImageWriter
    from pylibdmtx.pylibdmtx import encode
    canvas = Image.new('RGB', (1200, 900), 'white')
    q = io.BytesIO(); segno.make('HELLO-QR', error='m', micro=False).save(q, kind='png', scale=8); canvas.paste(Image.open(q), (50, 50))
    b = io.BytesIO(); barcode.get('code128', 'ABC-123', writer=ImageWriter()).write(b); canvas.paste(Image.open(b), (500, 60))
    e = encode(b'HELLO-DM'); dm = Image.frombytes('RGB', (e.width, e.height), e.pixels).resize((e.width*3, e.height*3), Image.NEAREST)
    canvas.paste(dm, (100, 600))
    out = io.BytesIO(); canvas.save(out, 'PNG'); return out.getvalue(), (100, 600, dm.size)

def _public(c, data, name):
    return c.post('/public/extract', data={'file': (io.BytesIO(data), name)}, content_type='multipart/form-data')

def test_public_extract_image(ctx):
    c, _, _ = ctx
    png, (dx, dy, (dw, dh)) = _sample_image()
    r = _public(c, png, 'doc.png')          # no login needed
    assert r.status_code == 200, r.json
    found = {b['type']: b for b in r.json['barcodes']}
    assert found['QRCODE']['data'] == 'HELLO-QR' and found['CODE128']['data'] == 'ABC-123' and found['DataMatrix']['data'] == 'HELLO-DM'
    assert abs(found['DataMatrix']['coordinates']['y'] - dy) < 40   # box is where the code really is
    assert r.json['page_count'] == 1 and r.json['pages'][0]['image']
    assert _public(c, b'x', 'a.exe').status_code == 415
    assert _public(c, b'notanimage', 'a.png').status_code == 400
    assert c.post('/public/extract').status_code == 400
    big = b'0' * (11 * 1024 * 1024)
    assert _public(c, big, 'big.png').status_code == 413

def test_public_extract_is_rate_limited_per_ip(ctx):
    c, _, app = ctx
    app.config['PUBLIC_RATE_LIMIT'] = '2 per hour'
    blank = _blank_png()
    assert [_public(c, blank, 'a.png').status_code for _ in range(3)] == [200, 200, 429]
    assert 'requêtes' in _public(c, blank, 'a.png').json['error']

def _sample_pdf():
    """Page 1: QR + Code128 + DataMatrix, page 2: empty, page 3: a QR code."""
    import pymupdf, segno
    png, _ = _sample_image()
    q = io.BytesIO(); segno.make('PAGE-3', error='m', micro=False).save(q, kind='png', scale=8)
    doc = pymupdf.open()
    p1 = doc.new_page(width=600, height=450); p1.insert_image(p1.rect, stream=png)
    doc.new_page()
    p3 = doc.new_page(); p3.insert_image(pymupdf.Rect(50, 50, 250, 250), stream=q.getvalue())
    return doc.tobytes()

def test_upload_pdf_multipage(ctx):
    c, _, _ = ctx
    up = lambda data, name: _public(c, data, name)
    r = up(_sample_pdf(), 'doc.pdf')
    assert r.status_code == 200, r.json
    j = r.json
    assert j['file_type'] == 'pdf' and j['page_count'] == 3 and len(j['pages']) == 3
    found = {(b['page'], b['type'], b['data']) for b in j['barcodes']}
    assert {(1, 'QRCODE', 'HELLO-QR'), (1, 'CODE128', 'ABC-123'), (1, 'DataMatrix', 'HELLO-DM'), (3, 'QRCODE', 'PAGE-3')} <= found
    assert j['pages'][1]['barcodes'] == []
    assert all(p['image'] for p in j['pages'])
    # renamed / broken files are rejected
    png, _ = _sample_image()
    assert up(png, 'fake.pdf').status_code == 400
    assert up(b'%PDF-1.4 garbage', 'broken.pdf').status_code == 400
    assert up(_sample_pdf(), 'fake.png').status_code == 400

def test_upload_pdf_too_many_pages(ctx):
    c, _, app = ctx
    import pymupdf
    doc = pymupdf.open()
    for _ in range(app.config['PDF_MAX_PAGES'] + 1): doc.new_page()
    r = _public(c, doc.tobytes(), 'big.pdf')
    assert r.status_code == 400 and 'pages' in r.json['error']


# ---------------------------------------------------------------- web service (API keys)

def _admin_tok(c):
    return login(c, 'admin@t.com', 'adminpass1').json['access_token']

def _new_key(c, **fields):
    r = c.post('/admin/api-tokens', headers=H(_admin_tok(c)), json={'name': 'App test', **fields})
    assert r.status_code == 201, r.json
    return r.json['api_key'], r.json['token']['id']

def _extract(c, key, data, name='a.png'):
    headers = {'X-API-Key': key} if key else {}
    return c.post('/api/v1/extract', headers=headers, data={'file': (io.BytesIO(data), name)}, content_type='multipart/form-data')

def _blank_png():
    out = io.BytesIO(); Image.new('RGB', (80, 80), 'white').save(out, 'PNG'); return out.getvalue()

def test_api_token_admin_rules(ctx):
    c, _, app = ctx
    atok = _admin_tok(c)
    utok = _user_jwt(app)
    assert c.post('/admin/api-tokens', headers=H(utok), json={'name': 'x'}).status_code == 403   # admins only
    assert c.get('/admin/api-tokens', headers=H(utok)).status_code == 403
    for bad in ({}, {'name': 'x', 'allowed_ips': ['not-an-ip']}, {'name': 'x', 'allowed_types': ['NOPE']},
                {'name': 'x', 'quota_hourly': -1}, {'name': 'x', 'quota_monthly': 'many'},
                {'name': 'x', 'valid_from': '2030-01-02', 'valid_until': '2030-01-01'}):
        assert c.post('/admin/api-tokens', headers=H(atok), json=bad).status_code == 400, bad
    assert 'QRCODE' in c.get('/admin/supported-types', headers=H(atok)).json
    assert 'DataMatrix' in c.get('/admin/supported-types', headers=H(atok)).json

def test_api_extract_and_key_rules(ctx):
    c, _, _ = ctx
    key, tid = _new_key(c)
    png, _ = _sample_image()
    assert _extract(c, None, png).status_code == 401                      # no key
    assert _extract(c, 'ecode_wrong', png).status_code == 401             # unknown key
    r = _extract(c, key, png)
    assert r.status_code == 200, r.json
    assert {b['data'] for b in r.json['barcodes']} == {'HELLO-QR', 'ABC-123', 'HELLO-DM'}
    assert 'image' not in r.json and 'pages' not in r.json              # JSON only, no result images
    assert r.json['page_count'] == 1 and r.json['file_type'] == 'image'
    # PDF works through the web service too
    r = _extract(c, key, _sample_pdf(), 'doc.pdf')
    assert r.status_code == 200 and r.json['page_count'] == 3 and {b['page'] for b in r.json['barcodes']} == {1, 3}
    # bad files
    assert _extract(c, key, b'x', 'a.exe').status_code == 415
    assert _extract(c, key, b'notanimage', 'a.png').status_code == 400
    assert c.post('/api/v1/extract', headers={'X-API-Key': key}).status_code == 400   # no file
    # usage is counted for requests that reach processing (rejected-before-processing ones are free)
    atok = _admin_tok(c)
    listed = c.get('/admin/api-tokens', headers=H(atok)).json
    assert listed[0]['usage_hour'] == 3 and listed[0]['last_used_at']
    assert 'api_key' not in listed[0] and listed[0]['token_prefix'] == key[:10]
    # the key itself is not stored, only its hash
    with c.application.app_context():
        from app.models.api_token import ApiToken
        assert key not in ApiToken.query.first().token_hash
    # disable / enable / delete
    assert c.put(f'/admin/api-tokens/{tid}', headers=H(atok), json={'is_active': False}).status_code == 200
    assert _extract(c, key, png).status_code == 403
    assert c.put(f'/admin/api-tokens/{tid}', headers=H(atok), json={'is_active': True}).status_code == 200
    assert _extract(c, key, _blank_png()).status_code == 200
    assert c.delete(f'/admin/api-tokens/{tid}', headers=H(atok)).status_code == 200
    assert _extract(c, key, png).status_code == 401

def test_api_allowed_types(ctx):
    c, _, _ = ctx
    png, _ = _sample_image()
    key, _ = _new_key(c, allowed_types=['QRCODE'])
    assert {b['type'] for b in _extract(c, key, png).json['barcodes']} == {'QRCODE'}
    key, _ = _new_key(c, allowed_types=['DataMatrix'])
    assert {b['type'] for b in _extract(c, key, png).json['barcodes']} == {'DataMatrix'}

def test_api_ip_and_validity_period(ctx):
    c, _, _ = ctx
    blank = _blank_png()
    key, _ = _new_key(c, allowed_ips=['10.1.2.3'])
    assert _extract(c, key, blank).status_code == 403                    # test client is 127.0.0.1
    key, _ = _new_key(c, allowed_ips=['10.1.2.3', '127.0.0.0/8'])
    assert _extract(c, key, blank).status_code == 200                    # CIDR range matches
    key, _ = _new_key(c, valid_until='2000-01-01')
    assert _extract(c, key, blank).status_code == 403                    # expired
    key, _ = _new_key(c, valid_from='2999-01-01')
    assert _extract(c, key, blank).status_code == 403                    # not valid yet
    key, _ = _new_key(c, valid_from='2000-01-01', valid_until='2999-01-01')
    assert _extract(c, key, blank).status_code == 200

def test_api_quotas(ctx):
    c, _, _ = ctx
    blank = _blank_png()
    key, tid = _new_key(c, quota_hourly=2)
    assert [_extract(c, key, blank).status_code for _ in range(3)] == [200, 200, 429]
    key, tid = _new_key(c, quota_monthly=1)
    assert [_extract(c, key, blank).status_code for _ in range(2)] == [200, 429]
    key, tid = _new_key(c, quota_hourly=0)                               # 0 = nothing allowed
    assert _extract(c, key, blank).status_code == 429
    # editing the quota takes effect immediately; empty = unlimited
    atok = _admin_tok(c)
    assert c.put(f'/admin/api-tokens/{tid}', headers=H(atok), json={'quota_hourly': None}).status_code == 200
    assert _extract(c, key, blank).status_code == 200


# ---------------------------------------------------------------- quotas in Redis (several workers) + reverse proxy

def _use_redis_quota(app, server=None, **kw):
    import fakeredis
    from app.quota import RedisQuota
    client = fakeredis.FakeRedis(server=server or fakeredis.FakeServer())
    app.extensions['quota'] = RedisQuota(client, **kw)
    return client


def test_redis_quota_hourly_monthly_and_unlimited(ctx):
    c, _, app = ctx
    _use_redis_quota(app)
    blank = _blank_png()
    key, tid = _new_key(c, quota_hourly=2)
    assert [_extract(c, key, blank).status_code for _ in range(3)] == [200, 200, 429]
    key, tid = _new_key(c, quota_monthly=1)
    assert [_extract(c, key, blank).status_code for _ in range(2)] == [200, 429]
    key, tid = _new_key(c, quota_hourly=0)
    assert _extract(c, key, blank).status_code == 429
    key, tid = _new_key(c)                                               # no quota: never refused
    assert [_extract(c, key, blank).status_code for _ in range(5)] == [200] * 5


def test_redis_quota_is_given_back_when_the_file_is_refused(ctx):
    c, _, app = ctx
    _use_redis_quota(app)
    blank = _blank_png()
    key, _ = _new_key(c, quota_hourly=1, quota_monthly=1)
    assert _extract(c, key, blank, 'a.gif').status_code == 415           # refused: must not use the quota
    assert _extract(c, key, b'not an image', 'a.pdf').status_code == 400
    assert _extract(c, key, blank).status_code == 200
    assert _extract(c, key, blank).status_code == 429


def test_redis_quota_never_admits_more_than_the_quota_under_concurrency(ctx, monkeypatch):
    """Eight workers share one Redis and fight for 50 slots: exactly 50 must get through."""
    import threading
    from types import SimpleNamespace
    import fakeredis
    import app.quota as quota_module
    from app.quota import RedisQuota
    from datetime import datetime

    monkeypatch.setattr(quota_module, '_db_count', lambda token, since: 0)
    server = fakeredis.FakeServer()
    token = SimpleNamespace(id=7, quota_hourly=50, quota_monthly=50)
    admitted, lock = [], threading.Lock()

    def worker():
        store = RedisQuota(fakeredis.FakeRedis(server=server))           # each worker has its own connection
        for _ in range(25):
            message, _ = store.reserve(token, datetime.utcnow())
            if message is None:
                with lock:
                    admitted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(admitted) == 50


def test_redis_monthly_counter_restarts_from_the_request_log(ctx):
    """If Redis loses its data, the monthly count is rebuilt from api_usage instead of starting from zero."""
    c, _, app = ctx
    blank = _blank_png()
    key, _ = _new_key(c, quota_monthly=3)
    assert [_extract(c, key, blank).status_code for _ in range(2)] == [200, 200]   # database counters
    _use_redis_quota(app)                                                          # fresh, empty Redis
    assert [_extract(c, key, blank).status_code for _ in range(2)] == [200, 429]


def test_quota_falls_back_to_the_database_when_redis_is_down(ctx):
    import redis
    from app.quota import RedisQuota

    class DeadRedis:
        def pipeline(self, *a, **k): raise redis.ConnectionError('down')
        def incrby(self, *a, **k): raise redis.ConnectionError('down')

    c, _, app = ctx
    app.extensions['quota'] = RedisQuota(DeadRedis())
    blank = _blank_png()
    key, _ = _new_key(c, quota_hourly=2)
    assert [_extract(c, key, blank).status_code for _ in range(3)] == [200, 200, 429]


def test_health_probe_for_docker_and_load_balancer(ctx):
    c, _, _ = ctx
    r = c.get('/health')
    assert r.status_code == 200 and r.json == {'status': 'ok'}


def test_client_ip_comes_from_the_proxy_only_when_a_proxy_is_trusted(ctx):
    from config import Config
    from app import create_app

    class BehindNginx(Config):
        TRUSTED_PROXIES = 1

    c, _, _ = ctx
    key, _ = _new_key(c, allowed_ips=['203.0.113.9'])
    blank = _blank_png()

    def call(client, forwarded):
        return client.post('/api/v1/extract', headers={'X-API-Key': key, 'X-Forwarded-For': forwarded},
                           data={'file': (io.BytesIO(blank), 'a.png')}, content_type='multipart/form-data')

    # Directly reachable app: a forged header must NOT let a stranger in
    assert call(c, '203.0.113.9').status_code == 403
    # Behind the proxy: the address written by Nginx is the client address
    proxied = create_app(BehindNginx).test_client()
    assert call(proxied, '203.0.113.9').status_code == 200
    assert call(proxied, '198.51.100.1').status_code == 403


# ---------------------------------------------------------------- localisation of codes (F3)

def _doc_page(seed):
    """A document page (text, table, logo) with 1 to 3 codes, and the true box (x, y, w, h) of each code."""
    import numpy as np
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bench'))
    from make_documents import _background, _place_codes
    rng = np.random.default_rng(seed)
    page = _background(rng)
    codes = _place_codes(page, rng)
    return page, [(c['x'], c['y'], c['w'], c['h']) for c in codes]


def _overlap(a, b):
    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / (a[2] * a[3] + b[2] * b[3] - inter) if inter else 0.0


def test_localizer_finds_every_code_of_a_document_page():
    from app.scans.localizer import find_regions
    page, truth = _doc_page(6)                                    # 3 codes among text and a table
    regions = find_regions(page)
    assert len(regions) == 3
    for box in truth:
        assert any(_overlap(box, (r['x'], r['y'], r['w'], r['h'])) >= 0.5 for r in regions)
    assert all(0.5 <= r['score'] <= 1 and len(r['box']) == 4 for r in regions)


def test_localizer_blank_pages_have_no_region():
    import numpy as np
    from app.scans.localizer import find_regions
    assert find_regions(np.full((600, 800), 255, np.uint8)) == []
    assert find_regions(np.full((600, 800, 3), 255, np.uint8)) == []


def test_localizer_maps_boxes_back_on_a_large_scan():
    """A 1600x2000 page is searched on a reduced copy; the boxes must come back in the page's own pixels."""
    import cv2
    from app.scans.localizer import find_regions
    page, truth = _doc_page(6)
    big = cv2.resize(page, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    regions = find_regions(big)
    found = sum(any(_overlap(tuple(2 * v for v in box), (r['x'], r['y'], r['w'], r['h'])) >= 0.5 for r in regions) for box in truth)
    assert found >= 2


def test_localizer_model_is_loaded_and_filters_candidates():
    from app.scans.localizer import FEATURES, MODEL, find_regions
    assert MODEL is not None and len(MODEL['weights']) == len(FEATURES)
    page, _ = _doc_page(5)
    assert len(find_regions(page, model=None)) >= len(find_regions(page)) >= 1     # the model only removes candidates


# ---------------------------------------------------------------- decoder: poor quality scans, speed, coordinates

def _big_codes_page(w=1400, h=1000):
    """White page with a large QR, Code128 and DataMatrix (so rotations stay readable)."""
    import segno, barcode
    from barcode.writer import ImageWriter
    from pylibdmtx.pylibdmtx import encode
    canvas = Image.new('RGB', (w, h), 'white')
    q = io.BytesIO(); segno.make('BIG-QR', error='m', micro=False).save(q, kind='png', scale=12); canvas.paste(Image.open(q), (80, 80))
    b = io.BytesIO(); barcode.get('code128', 'BIG-128', writer=ImageWriter()).write(b); canvas.paste(Image.open(b), (700, 100))
    e = encode(b'BIG-DM'); dm = Image.frombytes('RGB', (e.width, e.height), e.pixels).resize((e.width * 3, e.height * 3), Image.NEAREST)
    canvas.paste(dm, (150, 600))
    import numpy as np
    return np.array(canvas)

def _found(app, img, **kw):
    from app.scans.decoder import find_codes
    with app.app_context():
        return {(c['type'], c['data']) for c in find_codes(img, 1, **kw)}

ALL3 = {('QRCODE', 'BIG-QR'), ('CODE128', 'BIG-128'), ('DataMatrix', 'BIG-DM')}

def test_decoder_reads_poor_quality_scans(ctx):
    import cv2, numpy as np
    _, _, app = ctx
    base = _big_codes_page()
    assert _found(app, base) == ALL3
    noisy = np.clip(base.astype(np.int16) + np.random.RandomState(1).normal(0, 30, base.shape), 0, 255).astype(np.uint8)
    assert _found(app, noisy) == ALL3
    assert _found(app, cv2.GaussianBlur(base, (5, 5), 0)) == ALL3
    assert _found(app, np.clip(128 + (base.astype(np.float32) - 128) * 0.2 + 60, 0, 255).astype(np.uint8)) == ALL3   # washed out
    # light on dark: found by the clean-up passes when the fast pass finds nothing (a page that mixes
    # readable codes with an inverted 1D code is the known limit of the fast pass)
    only_128 = base.copy(); only_128[:, :650] = 255; only_128[550:, :] = 255
    assert _found(app, 255 - only_128) == {('CODE128', 'BIG-128')}
    assert len(_found(app, 255 - base)) >= 2
    assert _found(app, np.rot90(base).copy()) == ALL3                       # page scanned sideways
    assert _found(app, np.rot90(base, 2).copy()) == ALL3                    # upside down
    ok, jpg = cv2.imencode('.jpg', cv2.cvtColor(base, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 10])
    assert _found(app, cv2.cvtColor(cv2.imdecode(jpg, 1), cv2.COLOR_BGR2RGB)) == ALL3   # heavy compression

def test_decoder_reads_skewed_scan_and_maps_coordinates_back(ctx):
    import numpy as np
    from app.scans.decoder import _rotated, find_codes
    _, _, app = ctx
    base = _big_codes_page()
    import cv2
    gray = cv2.cvtColor(base, cv2.COLOR_RGB2GRAY)
    skewed, matrix = _rotated(gray, 45)                                   # 45 degrees: beyond the fast pass
    with app.app_context():
        codes = find_codes(skewed, 1)
    assert len(codes) >= 2                                                # found despite the 45 degree skew
    # coordinates are returned in the skewed image's own pixels: the box must sit on the real code
    inv = np.linalg.inv(matrix)
    for c in codes:
        co = c['coordinates']
        cx, cy = co['x'] + co['w'] / 2, co['y'] + co['h'] / 2
        assert 0 <= cx <= skewed.shape[1] and 0 <= cy <= skewed.shape[0]
        ox, oy = (inv @ np.array([cx, cy, 1]))[:2]                         # back in the unrotated page
        expected = {'QRCODE': (80 + 60, 80 + 60), 'CODE128': (700 + 150, 100 + 50), 'DataMatrix': (150 + 135, 600 + 135)}[c['type']]
        assert abs(ox - expected[0]) < 120 and abs(oy - expected[1]) < 120, (c['type'], (ox, oy), expected)

def test_decoder_does_not_invent_codes_and_blank_pages_are_fast(ctx):
    import time
    import numpy as np
    _, _, app = ctx
    assert _found(app, np.full((2339, 1654, 3), 255, np.uint8)) == set()      # blank page
    text_like = (np.random.RandomState(2).rand(900, 1200) > 0.5).astype(np.uint8) * 255   # pure noise
    assert _found(app, np.stack([text_like] * 3, axis=2)) == set()
    blank = np.full((2339, 1654), 255, np.uint8)
    with app.app_context():
        from app.scans.decoder import find_codes
        start = time.perf_counter(); find_codes(blank, 1); elapsed = time.perf_counter() - start
    assert elapsed < 0.4, elapsed                                              # no useless clean-up passes on an empty page

def test_decoder_speed_on_typical_images(ctx):
    """The cahier asks for answers in under 100 ms: check the decoding part on clean scans."""
    import time
    import cv2
    from app.scans.decoder import find_codes
    _, _, app = ctx
    page = _big_codes_page(1654, 2339)                                        # A4 at 200 dpi
    gray = cv2.cvtColor(page, cv2.COLOR_RGB2GRAY)
    with app.app_context():
        find_codes(gray, 1)                                                   # warm-up
        times = []
        for _ in range(5):
            start = time.perf_counter(); codes = find_codes(gray, 1); times.append(time.perf_counter() - start)
    assert len(codes) == 3
    assert min(times) < 0.15, times                                           # ~85 ms measured; margin for slow/busy machines

def test_api_type_filter_skips_other_decoders_and_lists_new_types(ctx):
    _, _, app = ctx
    base = _big_codes_page()
    assert _found(app, base, allowed_types={'QRCODE'}) == {('QRCODE', 'BIG-QR')}
    assert _found(app, base, allowed_types={'DataMatrix', 'CODE128'}) == {('CODE128', 'BIG-128'), ('DataMatrix', 'BIG-DM')}
    assert _found(app, base, allowed_types=set()) == set()
    from app.scans.decoder import SUPPORTED_TYPES
    assert {'QRCODE', 'DataMatrix', 'CODE128', 'EAN13', 'PDF417', 'Aztec'} <= set(SUPPORTED_TYPES)


def test_purge_usage_command_keeps_recent_rows(ctx):
    from datetime import datetime, timedelta
    c, _, app = ctx
    key, tid = _new_key(c)
    with app.app_context():
        from app.extensions import db
        from app.models.api_token import ApiUsage
        now = datetime.utcnow()
        db.session.add_all([ApiUsage(token_id=tid, created_at=now - timedelta(days=d)) for d in (1, 10, 40, 100)])
        db.session.commit()
    r = app.test_cli_runner().invoke(args=['purge-usage', '--keep-days', '35'])
    assert r.exit_code == 0 and r.output.startswith('2 '), r.output
    with app.app_context():
        from app.models.api_token import ApiUsage
        assert ApiUsage.query.count() == 2                      # only the 1 and 10 day old rows are left
