from models import db, Habitacion, User, TipoHabitacion, EstadoHabitacion
from werkzeug.security import generate_password_hash
from models import BASE_HOUR_PRICE, LUXURY_HOUR_PRICE 

def load_initial_rooms(db):
    """Inserta el usuario recepcionista y las 10 habitaciones iniciales."""
    
    existing_user = db.session.query(User).filter_by(username='recepcionista').first()
    
    if existing_user is None:
        admin_user = User(
            username='recepcionista',
            email='admin@motel.com', 
            password_hash=generate_password_hash('motel123'), 
            is_admin=True
        )
        db.session.add(admin_user)
        db.session.commit() 
        print(f"Usuario 'recepcionista' creado con éxito (ID={admin_user.id}). Contraseña por defecto: 'motel123'")
    else:
        print("El usuario 'recepcionista' ya existe.")


    if db.session.query(Habitacion).count() == 0:
        
        habitaciones_a_crear = []
        
        for i in range(1, 9):
            habitaciones_a_crear.append(Habitacion(
                numero=f"H{i:02d}", 
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
        print(f"Se cargaron 10 habitaciones: 8 Normales y 2 Jacuzzi.")
    else:
        print("La base de datos ya contiene habitaciones. No se cargaron datos iniciales.")
