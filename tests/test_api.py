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
                  SMTP_USERNAME='test@example.com', SMTP_PASSWORD='x')
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

def test_register_validation_and_pending_login(ctx):
    c, _, _ = ctx
    assert c.post('/auth/register', json={'email':'u@t.com','password':'short'}).status_code == 400
    assert c.post('/auth/register', json={'email':'u@t.com','password':'goodpass1'}).status_code == 201
    r = login(c, 'u@t.com', 'goodpass1'); assert r.status_code == 403, r.json   # not approved yet
    assert login(c, 'u@t.com', 'wrongpass').status_code == 401

def test_admin_approve_delete_and_guards(ctx):
    c, _, _ = ctx
    c.post('/auth/register', json={'email':'u@t.com','password':'goodpass1'})
    tok = login(c, 'admin@t.com', 'adminpass1').json['access_token']
    pending = c.get('/admin/users', headers=H(tok)).json
    assert [u['email'] for u in pending] == ['u@t.com']
    uid = pending[0]['id']
    assert c.post(f'/admin/approve-user/{uid}', headers=H(tok)).status_code == 200
    utok = login(c, 'u@t.com', 'goodpass1').json['access_token']
    assert c.get('/admin/users', headers=H(utok)).status_code == 403          # user can't use admin API
    assert c.delete('/admin/delete-user/1', headers=H(tok)).status_code == 400 # can't delete admin/self
    assert c.delete(f'/admin/delete-user/{uid}', headers=H(tok)).status_code == 200  # has a token row -> cascade
    assert c.get('/auth/me', headers=H(utok)).status_code == 401              # their session is gone

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

def test_upload(ctx):
    c, _, _ = ctx
    tok = login(c, 'admin@t.com', 'adminpass1').json['access_token']
    png, (dx, dy, (dw, dh)) = _sample_image()
    r = c.post('/scans/upload', headers=H(tok), data={'file': (io.BytesIO(png), 'doc.png')}, content_type='multipart/form-data')
    assert r.status_code == 200, r.json
    found = {b['type']: b for b in r.json['barcodes']}
    print({k: (v['data'], v['coordinates']) for k, v in found.items()}, 'DM placed at', dx, dy, dw, dh)
    assert found['QRCODE']['data'] == 'HELLO-QR' and found['CODE128']['data'] == 'ABC-123' and found['DataMatrix']['data'] == 'HELLO-DM'
    assert abs(found['DataMatrix']['coordinates']['y'] - dy) < 40   # box is where the code really is
    assert len(c.get('/scans/history', headers=H(tok)).json) == 3
    assert c.post('/scans/upload', headers=H(tok), data={'file': (io.BytesIO(b'x'), 'a.exe')}, content_type='multipart/form-data').status_code == 415
    assert c.post('/scans/upload', headers=H(tok), data={'file': (io.BytesIO(b'notanimage'), 'a.png')}, content_type='multipart/form-data').status_code == 400
    big = io.BytesIO(b'0' * (11 * 1024 * 1024))
    assert c.post('/scans/upload', headers=H(tok), data={'file': (big, 'big.png')}, content_type='multipart/form-data').status_code == 413


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
    tok = login(c, 'admin@t.com', 'adminpass1').json['access_token']
    up = lambda data, name: c.post('/scans/upload', headers=H(tok), data={'file': (io.BytesIO(data), name)}, content_type='multipart/form-data')
    r = up(_sample_pdf(), 'doc.pdf')
    assert r.status_code == 200, r.json
    j = r.json
    assert j['file_type'] == 'pdf' and j['page_count'] == 3 and len(j['pages']) == 3
    found = {(b['page'], b['type'], b['data']) for b in j['barcodes']}
    assert {(1, 'QRCODE', 'HELLO-QR'), (1, 'CODE128', 'ABC-123'), (1, 'DataMatrix', 'HELLO-DM'), (3, 'QRCODE', 'PAGE-3')} <= found
    assert j['pages'][1]['barcodes'] == []
    assert all(p['image'] for p in j['pages'])
    hist = c.get('/scans/history', headers=H(tok)).json
    assert {h['page'] for h in hist} == {1, 3}
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
    tok = login(c, 'admin@t.com', 'adminpass1').json['access_token']
    r = c.post('/scans/upload', headers=H(tok), data={'file': (io.BytesIO(doc.tobytes()), 'big.pdf')}, content_type='multipart/form-data')
    assert r.status_code == 400 and 'pages' in r.json['error']
