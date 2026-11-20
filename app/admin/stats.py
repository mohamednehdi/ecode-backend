"""Admin statistics on the use of the web service (F4): totals, per-day series, per-key breakdown, latency, CSV export.

Everything is computed from the request log (`api_usage`) with SQL aggregates, so the cost does not grow with the size of
the log beyond the index scan of the chosen period. Times are UTC (the dates of the daily series are UTC days).

Latency percentiles come from a histogram of 10 ms bins (one GROUP BY), not from sorting every duration: the value returned
is the centre of the bin, so it is exact to within +-5 ms, on any database (MySQL has no percentile function).
"""
import csv
import io
from datetime import datetime, timedelta

from flask import Blueprint, Response, jsonify, request, stream_with_context
from sqlalchemy import case, func

from app.extensions import db
from app.models.api_token import ApiToken, ApiUsage
from .routes import admin_required

stats_bp = Blueprint('stats', __name__)

MAX_DAYS = 365
BIN_MS = 10
EXPORT_LIMIT = 100_000


def _error(message, status=400):
    return jsonify({'error': message}), status


def _window():
    """(since, until, token_id, conditions) from ?days=30&token_id=, or an error response."""
    days = request.args.get('days', 30, type=int)
    token_id = request.args.get('token_id', type=int)
    if days is None or not 1 <= days <= MAX_DAYS:
        return None, _error(f'days doit être compris entre 1 et {MAX_DAYS}')
    until = datetime.utcnow()
    since = (until - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    conditions = [ApiUsage.created_at >= since]
    if token_id is not None:
        conditions.append(ApiUsage.token_id == token_id)
    return {'days': days, 'since': since, 'until': until, 'token_id': token_id, 'conditions': conditions}, None


def _is_error():
    return case((ApiUsage.status_code >= 400, 1), else_=0)


def _percentile(bins, fraction):
    """Value (ms) below which `fraction` of the durations fall, from [(bin index, count)]. None when there is no data."""
    total = sum(count for _, count in bins)
    if not total:
        return None
    running = 0
    for index, count in bins:
        running += count
        if running >= fraction * total:
            return index * BIN_MS + BIN_MS // 2
    return None


def _day(value):
    return str(value)[:10]            # MySQL gives a date, SQLite a string


def _rounded(value, digits=0):
    return None if value is None else round(float(value), digits)


@stats_bp.route('/overview', methods=['GET'])
@admin_required
def overview(current_admin):
    window, error = _window()
    if error:
        return error
    conditions = window['conditions']

    total = db.session.query(
        func.count(ApiUsage.id),
        func.coalesce(func.sum(_is_error()), 0),
        func.avg(ApiUsage.duration_ms),
        func.coalesce(func.sum(ApiUsage.codes_found), 0),
        func.coalesce(func.sum(ApiUsage.pages), 0),
        func.coalesce(func.sum(ApiUsage.file_bytes), 0),
        func.coalesce(func.sum(case((ApiUsage.thorough.is_(True), 1), else_=0)), 0),
    ).filter(*conditions).one()
    requests_total, errors, average, codes, pages, size, thorough = total

    bins = db.session.query((ApiUsage.duration_ms // BIN_MS).label('bin'), func.count(ApiUsage.id)) \
        .filter(*conditions, ApiUsage.duration_ms.isnot(None)).group_by('bin').order_by('bin').all()

    per_day = {_day(d): (n, int(e), a) for d, n, e, a in db.session.query(
        func.date(ApiUsage.created_at), func.count(ApiUsage.id), func.coalesce(func.sum(_is_error()), 0),
        func.avg(ApiUsage.duration_ms)).filter(*conditions).group_by(func.date(ApiUsage.created_at)).all()}
    daily = []
    for offset in range(window['days']):                               # every day of the period, empty days included
        day = (window['since'] + timedelta(days=offset)).strftime('%Y-%m-%d')
        n, e, a = per_day.get(day, (0, 0, None))
        daily.append({'date': day, 'requests': n, 'errors': e, 'avg_ms': _rounded(a)})

    tokens = [
        {'id': tid, 'name': name, 'requests': n, 'errors': int(e), 'avg_ms': _rounded(a),
         'last_request': last.isoformat() if last else None}
        for tid, name, n, e, a, last in db.session.query(
            ApiToken.id, ApiToken.name, func.count(ApiUsage.id), func.coalesce(func.sum(_is_error()), 0),
            func.avg(ApiUsage.duration_ms), func.max(ApiUsage.created_at))
        .join(ApiToken, ApiToken.id == ApiUsage.token_id).filter(*conditions)
        .group_by(ApiToken.id, ApiToken.name).order_by(func.count(ApiUsage.id).desc()).limit(10)]

    file_types = [{'type': t or 'inconnu', 'requests': n} for t, n in db.session.query(
        ApiUsage.file_type, func.count(ApiUsage.id)).filter(*conditions).group_by(ApiUsage.file_type)
        .order_by(func.count(ApiUsage.id).desc())]
    statuses = [{'status': s, 'requests': n} for s, n in db.session.query(
        ApiUsage.status_code, func.count(ApiUsage.id)).filter(*conditions).group_by(ApiUsage.status_code)
        .order_by(func.count(ApiUsage.id).desc())]

    return jsonify({
        'period': {'days': window['days'], 'from': window['since'].isoformat(), 'to': window['until'].isoformat(),
                   'token_id': window['token_id']},
        'totals': {
            'requests': requests_total, 'errors': int(errors),
            'error_rate': round(int(errors) / requests_total, 4) if requests_total else 0,
            'avg_ms': _rounded(average), 'p50_ms': _percentile(bins, 0.50), 'p95_ms': _percentile(bins, 0.95),
            'codes_found': int(codes), 'pages': int(pages), 'bytes': int(size), 'thorough_requests': int(thorough),
        },
        'daily': daily, 'tokens': tokens, 'file_types': file_types, 'statuses': statuses,
    })


def _recent_query(window):
    return db.session.query(ApiUsage, ApiToken.name).join(ApiToken, ApiToken.id == ApiUsage.token_id) \
        .filter(*window['conditions']).order_by(ApiUsage.created_at.desc(), ApiUsage.id.desc())


def _row_json(usage, token_name):
    return {'id': usage.id, 'time': usage.created_at.isoformat(), 'token_id': usage.token_id, 'token_name': token_name,
            'status': usage.status_code, 'duration_ms': usage.duration_ms, 'codes_found': usage.codes_found,
            'pages': usage.pages, 'file_type': usage.file_type, 'file_bytes': usage.file_bytes,
            'thorough': usage.thorough, 'ip': usage.ip_address}


@stats_bp.route('/recent', methods=['GET'])
@admin_required
def recent(current_admin):
    window, error = _window()
    if error:
        return error
    limit = request.args.get('limit', 50, type=int)
    if limit is None or not 1 <= limit <= 500:
        return _error('limit doit être compris entre 1 et 500')
    return jsonify([_row_json(u, name) for u, name in _recent_query(window).limit(limit)])


_CSV_COLUMNS = ['time_utc', 'token', 'status', 'duration_ms', 'codes_found', 'pages', 'file_type', 'file_bytes',
                'thorough', 'ip']


@stats_bp.route('/export.csv', methods=['GET'])
@admin_required
def export_csv(current_admin):
    """The request log of the period as a CSV file (opens in Excel: UTF-8 with a byte-order mark), newest first."""
    window, error = _window()
    if error:
        return error

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(_CSV_COLUMNS)
        yield '﻿' + buffer.getvalue()
        for usage, name in _recent_query(window).limit(EXPORT_LIMIT).yield_per(2000):
            buffer.seek(0)
            buffer.truncate()
            writer.writerow([usage.created_at.strftime('%Y-%m-%d %H:%M:%S'), name, usage.status_code, usage.duration_ms,
                             usage.codes_found, usage.pages, usage.file_type, usage.file_bytes,
                             '' if usage.thorough is None else int(usage.thorough), usage.ip_address])
            yield buffer.getvalue()

    filename = f'api-usage-{datetime.utcnow():%Y%m%d}.csv'
    return Response(stream_with_context(generate()), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})
