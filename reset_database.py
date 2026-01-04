import pymysql
import bcrypt

def reset_database():
    """Resetea completamente la base de datos con usuarios reales"""
    
    print("Reseteando base de datos...")
    
    # Conectar a MySQL
    conn = pymysql.connect(
        host='localhost',
        user='root',
        password='12345678',  # Tu contraseña de MySQL
        db='Halftime_Inn',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        with conn.cursor() as cursor:
            # 1. Desactivar modo seguro y limpiar
            cursor.execute("SET SQL_SAFE_UPDATES = 0")
            cursor.execute("DELETE FROM users")
            cursor.execute("SET SQL_SAFE_UPDATES = 1")
            cursor.execute("ALTER TABLE users AUTO_INCREMENT = 1")
            
            print("Tabla users limpiada")
            
            # 2. Generar hashes REALES e insertar usuarios
            usuarios_config = [
                # username, plain_password, rol, sucursal_id, turno, is_admin
                ('admin', 'admin123', 'ADMIN_GENERAL', None, None, True),
                ('admin_norte', 'norte123', 'ADMIN_MOTEL', 1, 'MATUTINO', False),
                ('recepcion1', 'recepcion1', 'RECEPCIONISTA', 1, 'MATUTINO', False),
                ('recepcion2', 'recepcion2', 'RECEPCIONISTA', 1, 'VESPERTINO', False),
                ('recepcion3', 'recepcion3', 'RECEPCIONISTA', 1, 'NOCTURNO', False),
                ('recepcion4', 'recepcion4', 'RECEPCIONISTA', 2, 'MATUTINO', False),
            ]
            
            for username, password, rol, sucursal_id, turno, is_admin in usuarios_config:
                # Generar hash bcrypt REAL
                salt = bcrypt.gensalt(rounds=12)
                hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
                hash_str = hashed.decode('utf-8')
                
                print(f"\nCreando usuario: {username}")
                print(f"   Contraseña: {password}")
                print(f"   Hash: {hash_str[:30]}...")
                print(f"   Longitud hash: {len(hash_str)}")
                
                # Insertar en BD
                if rol == 'ADMIN_GENERAL':
                    sql = """
                    INSERT INTO users (username, email, password_hash, rol, is_admin)
                    VALUES (%s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (username, f"{username}@hotel.com", hash_str, rol, is_admin))
                else:
                    sql = """
                    INSERT INTO users (username, email, password_hash, rol, sucursal_id, turno, is_admin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (username, f"{username}@hotel.com", hash_str, rol, sucursal_id, turno, is_admin))
            
            conn.commit()
            print("\nTodos los usuarios creados con éxito!")
            
            # 3. Verificar
            cursor.execute("""
                SELECT username, rol, sucursal_id, turno, 
                       LENGTH(password_hash) as hash_len,
                       LEFT(password_hash, 20) as hash_preview
                FROM users
                ORDER BY id
            """)
            
            print("\nUsuarios en la base de datos:")
            print("-" * 80)
            for row in cursor.fetchall():
                status = ":)" if row['hash_len'] == 60 else ":("
                print(f"{status} {row['username']:15} | {row['rol']:20} | Sucursal: {row['sucursal_id'] or 'N/A':2} | Turno: {row['turno'] or 'N/A':10} | Hash: {row['hash_len']} chars")
            
            print("\nContraseñas para probar:")
            print("   admin / admin123")
            print("   admin_norte / norte123")
            print("   recepcion1 / recepcion1")
            print("   recepcion2 / recepcion2")
            print("   recepcion3 / recepcion3")
            print("   recepcion4 / recepcion4")
            
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    reset_database()