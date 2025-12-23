import bcrypt

# Contraseñas que quieres usar
usuarios = [
    {'username': 'admin', 'password': 'admin123', 'rol': 'ADMIN_GENERAL'},
    {'username': 'admin_norte', 'password': 'norte123', 'rol': 'ADMIN_MOTEL'},
    {'username': 'recepcion1', 'password': 'recepcion1', 'rol': 'RECEPCIONISTA'},
    {'username': 'recepcion2', 'password': 'recepcion2', 'rol': 'RECEPCIONISTA'},
    {'username': 'recepcion3', 'password': 'recepcion3', 'rol': 'RECEPCIONISTA'},
    {'username': 'recepcion4', 'password': 'recepcion4', 'rol': 'RECEPCIONISTA'},
]

print("-- HASHS BCRYPT REALES --")
print("USE hotel;")
print()

for usuario in usuarios:
    # Generar hash bcrypt REAL
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(usuario['password'].encode('utf-8'), salt)
    hash_str = hashed.decode('utf-8')
    
    print(f"-- Usuario: {usuario['username']} (Contraseña: {usuario['password']})")
    print(f"Hash: {hash_str}")
    print(f"Longitud: {len(hash_str)} caracteres")
    print()
    
    # Generar SQL para insertar
    if usuario['rol'] == 'ADMIN_GENERAL':
        sql = f"""INSERT INTO users (username, email, password_hash, rol, is_admin) VALUES 
('{usuario['username']}', '{usuario['username']}@hotel.com', '{hash_str}', '{usuario['rol']}', TRUE);"""
    elif usuario['rol'] == 'ADMIN_MOTEL':
        sql = f"""INSERT INTO users (username, email, password_hash, rol, sucursal_id, turno) VALUES 
('{usuario['username']}', '{usuario['username']}@hotel.com', '{hash_str}', '{usuario['rol']}', 1, 'MATUTINO');"""
    else:  # RECEPCIONISTA
        sucursal = 1 if usuario['username'] in ['recepcion1', 'recepcion2', 'recepcion3'] else 2
        turno = 'MATUTINO' if '1' in usuario['username'] or '4' in usuario['username'] else 'VESPERTINO' if '2' in usuario['username'] else 'NOCTURNO'
        sql = f"""INSERT INTO users (username, email, password_hash, rol, sucursal_id, turno) VALUES 
('{usuario['username']}', '{usuario['username']}@hotel.com', '{hash_str}', '{usuario['rol']}', {sucursal}, '{turno}');"""
    
    print(f"SQL: {sql}")
    print("-" * 80)