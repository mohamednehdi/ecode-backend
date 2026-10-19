from functools import wraps

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.models.user import User
from app.extensions import db


admin_bp = Blueprint('admin', __name__)


def admin_required(fn):
    """Allows the request only for a logged-in admin. The admin is passed as `current_admin`."""
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        admin = db.session.get(User, int(get_jwt_identity()))
        if not admin or admin.role != 'admin':
            return jsonify({'error': 'Accès refusé'}), 403
        return fn(*args, current_admin=admin, **kwargs)
    return wrapper


def _user_json(u):
    return {
        'id': u.id,
        'email': u.email,
        'firstname': u.firstname,
        'lastname': u.lastname,
        'is_active': u.is_active,
    }


@admin_bp.route('/users', methods=['GET'])
@admin_required
def get_users(current_admin):
    """Accounts waiting for approval."""
    users = User.query.filter_by(is_active=False).filter(User.role != 'admin').all()
    return jsonify([_user_json(u) for u in users])


@admin_bp.route('/active-users', methods=['GET'])
@admin_required
def get_active_users(current_admin):
    users = User.query.filter_by(is_active=True, role='user').all()
    return jsonify([_user_json(u) for u in users])


@admin_bp.route('/approve-user/<int:user_id>', methods=['POST'])
@admin_required
def approve_user(user_id, current_admin):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404
    if user.role == 'admin':
        return jsonify({'error': 'Action impossible sur un administrateur'}), 400

    user.is_active = True
    db.session.commit()
    return jsonify({'message': 'Utilisateur activé avec succès'})


@admin_bp.route('/delete-user/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id, current_admin):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404
    if user.id == current_admin.id or user.role == 'admin':
        return jsonify({'error': 'Impossible de supprimer un administrateur'}), 400

    db.session.delete(user)  # sessions and scan history are deleted too (cascade)
    db.session.commit()
    return jsonify({'message': 'Utilisateur supprimé avec succès'})
