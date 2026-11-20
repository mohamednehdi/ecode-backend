"""Synthetic traffic for the statistics dashboard (demo and screenshots only).

    flask --app run seed-demo-usage --days 30 --per-day 300
    flask --app run clear-demo-usage

A dashboard on an empty request log shows nothing. These commands create three clearly labelled demo keys ("[DEMO] ...",
their secret is unknown so they cannot be used) and request-log rows spread over the last days, with a working-hours
rhythm, quiet weekends, a realistic mix of images and PDFs, a few errors and one slow period. Every demo row uses an IP
address of the documentation range 203.0.113.0/24, so they are easy to recognise and remove.

THE NUMBERS ARE INVENTED. Anything shown from this data (a screenshot in the report, a demo) must say it is demo data.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import insert

from .extensions import db
from .models.api_token import ApiToken, ApiUsage

DEMO_PREFIX = '[DEMO] '
DEMO_IP_PREFIX = '203.0.113.'
DEMO_KEYS = (('Application comptabilité', 0.5), ('Logistique entrepôt', 0.3), ('Site e-commerce', 0.2))


def seed(days=30, per_day=300, seed_value=7):
    rng = np.random.default_rng(seed_value)
    now = datetime.utcnow()
    tokens = []
    for name, share in DEMO_KEYS:
        token = ApiToken(name=DEMO_PREFIX + name, token_prefix='ecode_demo', token_hash=hashlib.sha256(secrets.token_bytes(16)).hexdigest(),
                         is_active=True, created_at=now - timedelta(days=days))
        db.session.add(token)
        tokens.append((token, share))
    db.session.flush()

    hour_weights = np.array([1, 1, 1, 1, 1, 2, 4, 8, 12, 14, 14, 12, 9, 11, 14, 14, 12, 9, 5, 3, 2, 2, 1, 1], dtype=float)
    hour_weights /= hour_weights.sum()
    rows = []
    for offset in range(days, -1, -1):
        day = (now - timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        weekend = day.weekday() >= 5
        volume = int(per_day * (0.3 if weekend else 1.0) * rng.uniform(0.75, 1.25))
        slow_period = offset == 9                                           # one bad day: the service was 3x slower
        for token, share in tokens:
            for _ in range(int(volume * share)):
                created = day + timedelta(hours=int(rng.choice(24, p=hour_weights)), minutes=int(rng.integers(60)),
                                          seconds=int(rng.integers(60)))
                if created > now:
                    continue
                is_pdf = rng.random() < 0.2
                thorough = rng.random() < 0.15
                roll = rng.random()
                status = 500 if roll < 0.006 else (400 if roll < 0.026 else 200)
                median = (240 if is_pdf else 55) + (60 if thorough else 0)
                duration = int(rng.lognormal(np.log(median), 0.45) * (3 if slow_period else 1))
                rows.append({
                    'token_id': token.id, 'created_at': created, 'ip_address': f'{DEMO_IP_PREFIX}{int(rng.integers(1, 250))}',
                    'status_code': status, 'duration_ms': duration,
                    'codes_found': int(rng.poisson(2.2)) if status == 200 else 0,
                    'pages': int(rng.integers(1, 9)) if is_pdf and status == 200 else (1 if status == 200 else 0),
                    'file_type': 'pdf' if is_pdf else 'image',
                    'file_bytes': int(rng.integers(150_000, 3_000_000) if is_pdf else rng.integers(60_000, 900_000)),
                    'thorough': bool(thorough),
                })
    for start in range(0, len(rows), 5000):
        db.session.execute(insert(ApiUsage), rows[start:start + 5000])
    db.session.commit()
    return len(rows)


def clear():
    demo_ids = [t.id for t in ApiToken.query.filter(ApiToken.name.like(DEMO_PREFIX + '%'))]
    removed = ApiUsage.query.filter(ApiUsage.ip_address.like(DEMO_IP_PREFIX + '%')).delete(synchronize_session=False)
    if demo_ids:
        ApiUsage.query.filter(ApiUsage.token_id.in_(demo_ids)).delete(synchronize_session=False)
        ApiToken.query.filter(ApiToken.id.in_(demo_ids)).delete(synchronize_session=False)
    db.session.commit()
    return removed, len(demo_ids)
