from flask_sqlalchemy import SQLAlchemy
from enum import Enum
from datetime import datetime
from sqlalchemy.orm import relationship, backref
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# --- Constantes de Precios ---
BASE_HOUR_PRICE = 150.00
LUXURY_HOUR_PRICE = 200.00 

# --- Enumeraciones (Python standard Enum) ---

class EstadoHabitacion(Enum):
    DISPONIBLE = 'DISPONIBLE'
    OCUPADA = 'OCUPADA'
    LIMPIEZA = 'LIMPIEZA'
    MANTENIMIENTO = 'MANTENIMIENTO'
    
    def __str__(self):
        return self.value

class TipoHabitacion(Enum):
    NORMAL = 'NORMAL'
    JACUZZI = 'JACUZZI'

    def __str__(self):
        return self.value

class ModoIngreso(Enum):
    VEHICULO = 'VEHICULO'
    API_CAMARA = 'API_CAMARA' 
    A_PIE = 'A_PIE'
    
    def __str__(self):
        return self.value
    

# --- Modelos de la Base de Datos ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    rentas = relationship("Renta", backref="recepcionista", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def _repr_(self):
        return f'<User {self.username}>'
    
    # Métodos requeridos para Flask-Login (implementados manualmente)
    @property
    def is_active(self):
        return True
    
    @property
    def is_authenticated(self):
        return True
    
    @property
    def is_anonymous(self):
        return False
    
    def get_id(self):
        return str(self.id)


class Habitacion(db.Model):
    __tablename__ = 'habitaciones'
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(10), unique=True, nullable=False)
    # Usar db.Enum para mapear el Enum de Python a SQL
    tipo = db.Column(db.Enum(TipoHabitacion), nullable=False) 
    estado = db.Column(db.Enum(EstadoHabitacion), nullable=False, default=EstadoHabitacion.DISPONIBLE)
    

    rentas = relationship("Renta", backref="habitacion", lazy=True)

    def __repr__(self):
        return f'<Habitacion {self.numero} ({self.estado.value})>'

class Renta(db.Model):
    __tablename__ = 'rentas'
    id = db.Column(db.Integer, primary_key=True)
    
    habitacion_id = db.Column(db.Integer, db.ForeignKey('habitaciones.id'), nullable=False)
    recepcionista_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    cliente_nombre = db.Column(db.String(100), nullable=True) 
    
    horas_reservadas = db.Column(db.Integer, nullable=False)
    hora_entrada = db.Column(db.DateTime, nullable=False, default=datetime.now)
    hora_salida_estimada = db.Column(db.DateTime, nullable=False)
    hora_salida_real = db.Column(db.DateTime, nullable=True) 

    # Precios
    precio_hora = db.Column(db.Float, nullable=False)
    pago_horas = db.Column(db.Float, nullable=False) # Pago inicial por las horas reservadas
    pago_extra = db.Column(db.Float, nullable=True, default=0.0)
    pago_final = db.Column(db.Float, nullable=True)
    
    # Estado de la Renta
    estado = db.Column(db.String(20), nullable=False, default='ACTIVA')

    accesos = relationship("RegistroAcceso", backref="renta", lazy=True)
    
    def _repr_(self):
        return f'<Renta {self.id} - Hab {self.habitacion_id}>'

class RegistroAcceso(db.Model):
    __tablename__ = 'registros_acceso'
    id = db.Column(db.Integer, primary_key=True)
    
    # Llave foránea a Renta
    renta_id = db.Column(db.Integer, db.ForeignKey('rentas.id'), nullable=False)
    
    # Datos de acceso
    modo_ingreso = db.Column(db.Enum(ModoIngreso), nullable=False)
    placas = db.Column(db.String(10), nullable=True)
    hora_ingreso = db.Column(db.DateTime, nullable=False, default=datetime.now)
    hora_salida = db.Column(db.DateTime, nullable=True)

    def _repr_(self):
        return f'<Acceso {self.id} - Renta {self.renta_id}>'