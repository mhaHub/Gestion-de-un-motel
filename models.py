from flask_login import UserMixin
import bcrypt

class User(UserMixin):
    def __init__(self, data):
        self.id = data['id']
        self.username = data['username']
        self.email = data['email']
        self.password_hash = data['password_hash']
        self.rol = data['rol']
        self.sucursal_id = data['sucursal_id']
        self.turno = data['turno']
        self.is_admin = bool(data.get('is_admin', False))

    def check_password(self, password):
        """Verifica contraseña usando bcrypt - VERSIÓN CORREGIDA"""
        try:
            # Depuración
            print(f"check_password llamado para: {self.username}")
            print(f"   Hash almacenado tipo: {type(self.password_hash)}")
            print(f"   Hash almacenado valor (inicio): {str(self.password_hash)[:30]}...")
            
            # Asegurar que tenemos string
            if isinstance(self.password_hash, str):
                stored_bytes = self.password_hash.encode('utf-8')
            elif isinstance(self.password_hash, bytes):
                stored_bytes = self.password_hash
            elif self.password_hash is None:
                print("Error: password_hash es None")
                return False
            else:
                # Intentar convertir a string primero
                stored_bytes = str(self.password_hash).encode('utf-8')
            
            # Verificar
            password_bytes = password.encode('utf-8')
            result = bcrypt.checkpw(password_bytes, stored_bytes)
            
            print(f"   Resultado de bcrypt.checkpw: {result}")
            return result
            
        except Exception as e:
            print(f"Excepción en check_password: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def es_admin_general(self):
        return self.rol == 'ADMIN_GENERAL'

    def es_admin_motel(self):
        return self.rol == 'ADMIN_MOTEL'

    def es_recepcionista(self):
        return self.rol == 'RECEPCIONISTA'