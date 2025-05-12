from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.user import User
from app.extensions import db


admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/users', methods=['GET'])
@jwt_required()
def get_users():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user or user.role != "admin":
        return jsonify({"error": "Accès refusé"}), 403
    
    users = User.query.filter_by(is_active=False).all()
    return jsonify([{"id": u.id, "email": u.email, "is_active": u.is_active} for u in users])

@admin_bp.route('/active-users', methods=['GET'])
@jwt_required()
def get_active_users():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user or user.role != "admin":
        return jsonify({"error": "Accès refusé"}), 403
    
    users = User.query.filter_by(is_active=True, role="user").all()
    return jsonify([{"id": u.id, "email": u.email, "is_active": u.is_active} for u in users])

@admin_bp.route('/approve-user/<int:user_id>', methods=['POST'])
@jwt_required()
def approve_user(user_id):
    user = User.query.get(get_jwt_identity())
    if not user or user.role != "admin":
        return jsonify({"error": "Accès refusé"}), 403
    
    user_to_approve = User.query.get(user_id)
    if user_to_approve:
        user_to_approve.is_active = True
        user_to_approve.role = "user"
        db.session.commit()
        return jsonify({"message": "Utilisateur activé avec succès"})
    return jsonify({"error": "Utilisateur introuvable"}), 404

@admin_bp.route('/delete-user/<int:user_id>', methods=['DELETE'])
@jwt_required()
def delete_user(user_id):
    user = User.query.get(get_jwt_identity())
    if not user or user.role != "admin":
        return jsonify({"error": "Accès refusé"}), 403
    
    user_to_delete = User.query.get(user_id)
    if user_to_delete:
        db.session.delete(user_to_delete)
        db.session.commit()
        return jsonify({"message": "Utilisateur supprimé avec succès"})
    return jsonify({"error": "Utilisateur introuvable"}), 404
