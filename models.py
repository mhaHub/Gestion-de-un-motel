from flask_sqlalchemy import SQLAlchemy
from enum import Enum
from datetime import datetime, date, time
from sqlalchemy.orm import relationship, backref
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# --- Constantes de Precios (Temporal - luego serán configurables) ---
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

class EstadoReserva(Enum):
    PENDIENTE = 'PENDIENTE'
    CONFIRMADA = 'CONFIRMADA'
    CANCELADA = 'CANCELADA'
    COMPLETADA = 'COMPLETADA'
    

# --- Modelos de la Base de Datos ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    # Para futura implementación multisucursal:
    # sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'))
    
    rentas = relationship("Renta", backref="recepcionista", lazy=True)
    reservas = relationship("Reserva", backref="recepcionista", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'
    
    # Métodos requeridos para Flask-Login
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
    tipo = db.Column(db.Enum(TipoHabitacion), nullable=False) 
    estado = db.Column(db.Enum(EstadoHabitacion), nullable=False, default=EstadoHabitacion.DISPONIBLE)
    
    # NUEVO: Catálogo administrable
    precio_base = db.Column(db.Float, nullable=False, default=150.00)
    caracteristicas = db.Column(db.Text, nullable=True)  # "Jacuzzi, TV, Estacionamiento"
    activa = db.Column(db.Boolean, default=True)
    
    # Para futura implementación multisucursal:
    # sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'))

    rentas = relationship("Renta", backref="habitacion", lazy=True)
    reservas = relationship("Reserva", backref="habitacion", lazy=True)

    def __repr__(self):
        return f'<Habitacion {self.numero} ({self.estado.value})>'
    
    def get_precio_hora(self):
        """Retorna el precio por hora de la habitación"""
        return self.precio_base


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

    # NUEVO: Para mejor tracking
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relación con reserva (si aplica)
    reserva_id = db.Column(db.Integer, db.ForeignKey('reservas.id'), nullable=True)

    accesos = relationship("RegistroAcceso", backref="renta", lazy=True)
    reserva = relationship("Reserva", backref="renta", uselist=False)
    
    def __repr__(self):
        return f'<Renta {self.id} - Hab {self.habitacion_id}>'


# NUEVO: Modelo de Reservas
class Reserva(db.Model):
    __tablename__ = 'reservas'
    id = db.Column(db.Integer, primary_key=True)
    
    habitacion_id = db.Column(db.Integer, db.ForeignKey('habitaciones.id'), nullable=False)
    recepcionista_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    cliente_nombre = db.Column(db.String(100), nullable=False)
    cliente_telefono = db.Column(db.String(20), nullable=True)
    
    fecha_reserva = db.Column(db.Date, nullable=False)
    hora_reserva = db.Column(db.Time, nullable=False)
    horas_reservadas = db.Column(db.Integer, nullable=False)
    
    estado = db.Column(db.String(20), nullable=False, default='PENDIENTE')  # PENDIENTE, CONFIRMADA, CANCELADA, COMPLETADA
    
    # Precio estimado
    precio_estimado = db.Column(db.Float, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    confirmada_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<Reserva {self.id} - {self.cliente_nombre} - {self.fecha_reserva}>'


class RegistroAcceso(db.Model):
    __tablename__ = 'registros_acceso'
    id = db.Column(db.Integer, primary_key=True)
    
    renta_id = db.Column(db.Integer, db.ForeignKey('rentas.id'), nullable=False)
    
    modo_ingreso = db.Column(db.Enum(ModoIngreso), nullable=False)
    placas = db.Column(db.String(10), nullable=True)
    hora_ingreso = db.Column(db.DateTime, nullable=False, default=datetime.now)
    hora_salida = db.Column(db.DateTime, nullable=True)

    # NUEVO: Campos para futura integración con cámaras LPR
    foto_placas_url = db.Column(db.String(255), nullable=True)
    confianza_reconocimiento = db.Column(db.Float, nullable=True)
    marca_vehiculo = db.Column(db.String(50), nullable=True)
    color_vehiculo = db.Column(db.String(30), nullable=True)

    def __repr__(self):
        return f'<Acceso {self.id} - Renta {self.renta_id}>'


# NUEVO: Modelo para Sucursales (Base para futura implementación)
class Sucursal(db.Model):
    __tablename__ = 'sucursales'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    direccion = db.Column(db.String(200), nullable=True)
    telefono = db.Column(db.String(20), nullable=True)
    activa = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    def __repr__(self):
        return f'<Sucursal {self.nombre}>'