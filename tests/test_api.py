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
