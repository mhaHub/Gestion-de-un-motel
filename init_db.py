from app import app, db
from models import Habitacion, Renta, User 

PRECIO_SENCILLA_POR_HORA = 100.00
PRECIO_JACUZZI_POR_HORA = 150.00

def load_initial_rooms():
    """Inserta las 10 habitaciones del motel solo si la tabla está vacía."""
    
    if db.session.query(Habitacion).count() == 0:
        
        habitaciones_a_crear = []
        
        for i in range(1, 9):
            habitaciones_a_crear.append(Habitacion(
                numero=f"H0{i}",
                tipo="Sencilla",
                precio_por_hora=PRECIO_SENCILLA_POR_HORA,
                estado="Disponible",
            ))
            
        habitaciones_a_crear.append(Habitacion(
            numero="J09",
            tipo="Jacuzzi",
            precio_por_hora=PRECIO_JACUZZI_POR_HORA,
            estado="Disponible",
        ))
        habitaciones_a_crear.append(Habitacion(
            numero="J10",
            tipo="Jacuzzi",
            precio_por_hora=PRECIO_JACUZZI_POR_HORA,
            estado="Disponible",
        ))

        db.session.add_all(habitaciones_a_crear)
        db.session.commit()
        print(f"Se cargaron 10 habitaciones: 8 Sencillas y 2 Jacuzzi.")
    else:
        print("La base de datos ya contiene habitaciones. No se cargaron datos iniciales.")

if __name__ == "__main__":
    with app.app_context():
        print("Iniciando creación de tablas...")
        db.create_all()
        print("Tablas creadas con éxito.")
        
        load_initial_rooms()
        
        print("Base de datos lista.")
