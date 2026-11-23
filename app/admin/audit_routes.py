"""Read access to the audit log (administrators only). There is no route that changes or deletes an entry."""
import csv
import io
import json
from datetime import datetime, timedelta

from flask import Blueprint, Response, jsonify, request, stream_with_context
from sqlalchemy import func

from app import audit
from app.models.audit_log import AuditLog
from .routes import admin_required

audit_bp = Blueprint('audit', __name__)

EXPORT_LIMIT = 100_000


def _error(message):
    return jsonify({'error': message}), 400


def _query():
    """(query, error response) from ?days=30&action=&success=&q= ."""
    days = request.args.get('days', 30, type=int)
    if days is None or not 1 <= days <= 3650:
        return None, _error('days doit être compris entre 1 et 3650')
    query = AuditLog.query.filter(AuditLog.created_at >= datetime.utcnow() - timedelta(days=days))
    action = request.args.get('action')
    if action:
        if action not in audit.ACTIONS:
            return None, _error('action inconnue')
        query = query.filter(AuditLog.action == action)
    success = request.args.get('success')
    if success in ('true', 'false'):
        query = query.filter(AuditLog.success == (success == 'true'))
    text = (request.args.get('q') or '').strip().lower()[:100]
    if text:
        like = f'%{text}%'
        query = query.filter(func.lower(func.coalesce(AuditLog.actor_email, '')).like(like) | func.lower(func.coalesce(AuditLog.target_name, '')).like(like))
    return query, None


def _entry_json(e):
    return {'id': e.id, 'time': e.created_at.isoformat(), 'actor_id': e.actor_id, 'actor_email': e.actor_email, 'action': e.action,
            'target_type': e.target_type, 'target_id': e.target_id, 'target_name': e.target_name,
            'details': json.loads(e.details) if e.details else None, 'ip': e.ip_address, 'success': e.success}


@audit_bp.route('', methods=['GET'])
@admin_required
def list_entries(current_admin):
    query, error = _query()
    if error:
        return error
    limit = request.args.get('limit', 100, type=int)
    before_id = request.args.get('before_id', type=int)
    if limit is None or not 1 <= limit <= 500:
        return _error('limit doit être compris entre 1 et 500')
    if before_id:
        query = query.filter(AuditLog.id < before_id)
    rows = query.order_by(AuditLog.id.desc()).limit(limit + 1).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return jsonify({'items': [_entry_json(e) for e in rows], 'next_before_id': rows[-1].id if more and rows else None,
                    'actions': list(audit.ACTIONS)})


def _csv_safe(value):
    """A spreadsheet runs text that starts with = + - @ as a formula: an attacker-chosen e-mail must not become one."""
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


@audit_bp.route('/export.csv', methods=['GET'])
@admin_required
def export_csv(current_admin):
    query, error = _query()
    if error:
        return error

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['time_utc', 'action', 'result', 'actor', 'target_type', 'target', 'details', 'ip'])
        yield '﻿' + buffer.getvalue()
        for e in query.order_by(AuditLog.id.desc()).limit(EXPORT_LIMIT).yield_per(2000):
            buffer.seek(0)
            buffer.truncate()
            writer.writerow([e.created_at.strftime('%Y-%m-%d %H:%M:%S'), e.action, 'ok' if e.success else 'failure',
                             _csv_safe(e.actor_email), e.target_type or '', _csv_safe(e.target_name), _csv_safe(e.details), e.ip_address or ''])
            yield buffer.getvalue()

    return Response(stream_with_context(generate()), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename=audit-{datetime.utcnow():%Y%m%d}.csv'})
