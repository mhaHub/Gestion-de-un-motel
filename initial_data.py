from models import Habitacion, TipoHabitacion, EstadoHabitacion, User
from models import BASE_HOUR_PRICE, LUXURY_HOUR_PRICE
from werkzeug.security import generate_password_hash

def load_initial_rooms(db):
    if db.session.query(Habitacion).count() == 0:
        
        habitaciones_a_crear = []
        
        for i in range(1, 9):
            habitaciones_a_crear.append(Habitacion(
                numero=f"H0{i}",
                tipo=TipoHabitacion.NORMAL,
                estado=EstadoHabitacion.DISPONIBLE,
            ))
            
        habitaciones_a_crear.append(Habitacion(
            numero="J09",
            tipo=TipoHabitacion.JACUZZI,
            estado=EstadoHabitacion.DISPONIBLE,
        ))
        habitaciones_a_crear.append(Habitacion(
            numero="J10",
            tipo=TipoHabitacion.JACUZZI,
            estado=EstadoHabitacion.DISPONIBLE,
        ))

        db.session.add_all(habitaciones_a_crear)
        db.session.commit()
        print("✅ Se cargaron 10 habitaciones: 8 Normales y 2 Jacuzzi.")
    else:
        print("La base de datos ya contiene habitaciones. No se cargaron datos iniciales.")

def load_initial_user(db):
    if db.session.query(User).count() == 0:
        
        password_hash = generate_password_hash('123')
        
        admin_user = User(
            username='admin',
            email='admin@motel.com',
            password_hash=password_hash,
            is_admin=True
        )
        
        db.session.add(admin_user)
        db.session.commit()
        print("Usuario 'admin' (Contraseña: 123) creado exitosamente.")
    else:
        print("Ya existe al menos un usuario en la base de datos.")