import pymysql
import bcrypt

def generar_hash_correcto():
    """Genera hashes REALES de 60 caracteres"""
    # Conexión a la BD
    conn = pymysql.connect(
        host='localhost',
        user='root',
        password='',
        database='hotel',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        with conn.cursor() as cursor:
            # 1. Borrar usuarios existentes
            cursor.execute("DELETE FROM users")
            cursor.execute("ALTER TABLE users AUTO_INCREMENT = 1")
            
            # 2. Contraseñas para cada usuario
            usuarios = [
                {'username': 'admin', 'password': 'admin123', 'rol': 'ADMIN_GENERAL', 'sucursal': None, 'turno': None, 'is_admin': True},
                {'username': 'admin_norte', 'password': 'norte123', 'rol': 'ADMIN_MOTEL', 'sucursal': 1, 'turno': 'MATUTINO', 'is_admin': False},
                {'username': 'recepcion1', 'password': 'recepcion1', 'rol': 'RECEPCIONISTA', 'sucursal': 1, 'turno': 'MATUTINO', 'is_admin': False},
                {'username': 'recepcion2', 'password': 'recepcion2', 'rol': 'RECEPCIONISTA', 'sucursal': 1, 'turno': 'VESPERTINO', 'is_admin': False},
                {'username': 'recepcion3', 'password': 'recepcion3', 'rol': 'RECEPCIONISTA', 'sucursal': 1, 'turno': 'NOCTURNO', 'is_admin': False},
                {'username': 'recepcion4', 'password': 'recepcion4', 'rol': 'RECEPCIONISTA', 'sucursal': 2, 'turno': 'MATUTINO', 'is_admin': False},
            ]
            
            for usuario in usuarios:
                # Generar hash BCrypt
                salt = bcrypt.gensalt(rounds=12)
                hashed = bcrypt.hashpw(usuario['password'].encode('utf-8'), salt)
                hash_str = hashed.decode('utf-8')
                
                print(f"Usuario: {usuario['username']}")
                print(f"Hash generado: {hash_str}")
                print(f"Longitud: {len(hash_str)} caracteres")
                print("-" * 50)
                
                # Insertar en BD
                if usuario['rol'] == 'ADMIN_GENERAL':
                    sql = """
                    INSERT INTO users (username, email, password_hash, rol, is_admin)
                    VALUES (%s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (
                        usuario['username'],
                        f"{usuario['username']}@halftime.com",
                        hash_str,
                        usuario['rol'],
                        usuario['is_admin']
                    ))
                else:
                    sql = """
                    INSERT INTO users (username, email, password_hash, rol, sucursal_id, turno, is_admin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (
                        usuario['username'],
                        f"{usuario['username']}@halftime.com",
                        hash_str,
                        usuario['rol'],
                        usuario['sucursal'],
                        usuario['turno'],
                        usuario['is_admin']
                    ))
            
            conn.commit()
            print("Todos los usuarios creados con hashes correctos!")
            
            # 3. Verificar
            cursor.execute("SELECT username, LENGTH(password_hash) as len_hash FROM users")
            resultados = cursor.fetchall()
            print("\nVerificación de hashes:")
            for r in resultados:
                print(f"  {r['username']}: {r['len_hash']} caracteres")
                
    finally:
        conn.close()

if __name__ == "__main__":
    generar_hash_correcto()