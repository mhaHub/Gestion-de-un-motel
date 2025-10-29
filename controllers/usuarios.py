from flask import Blueprint, request, jsonify

usuarios_bp = Blueprint('usuarios', __name__, url_prefix="/usuarios")

# obtener todos los usuarios
@usuarios_bp.route('/usuarios', methods=['GET'])
def get_usuarios():
    return jsonify({"ejemplo XD"})

# obtener usuario espcifico
@usuarios_bp.route('/usuarios/<int:usuario_id>', methods=['GET'])
def get_usuario(usuario_id):
    return jsonify({"usuario": {"id": usuario_id}})

# crear un nuevo usuario
@usuarios_bp.route('/usuarios', methods=['POST'])
def create_usuario():
    data = request.get_json()
    return jsonify({"mensaje": "Usuario creado", "usuario": data}), 201

# actualizar un usuario existente
@usuarios_bp.route('/usuarios/<int:usuario_id>', methods=['PUT'])
def update_usuario(usuario_id):
    data = request.get_json()
    return jsonify({"mensaje": "Usuario actualizado", "usuario": {"id": usuario_id, **data}})

# cancelar un usuario
@usuarios_bp.route('/usuariosEliminar/<int:usuario_id>', methods=['PUT'])
def delete_usuario(usuario_id):
    return jsonify({"mensaje": "Usuario eliminado", "usuario_id": usuario_id})