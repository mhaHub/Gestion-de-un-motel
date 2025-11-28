from flask_sqlalchemy import SQLAlchemy
from enum import Enum
from datetime import datetime, date, time
from sqlalchemy.orm import relationship, backref
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# --- Constantes de Precios ---
BASE_HOUR_PRICE = 150.00
LUXURY_HOUR_PRICE = 200.00 

# --- Enumeraciones ---

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

class RolUsuario(Enum):
    ADMIN_GENERAL = 'admin_general'
    ADMIN_MOTEL = 'admin_motel'
    RECEPCIONISTA = 'recepcionista'

class TurnoTrabajo(Enum):
    MATUTINO = 'matutino'
    VESPERTINO = 'vespertino'
    NOCTURNO = 'nocturno'

# --- Modelos de la Base de Datos ---

class Sucursal(db.Model):
    __tablename__ = 'sucursales'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    direccion = db.Column(db.String(200), nullable=True)
    telefono = db.Column(db.String(20), nullable=True)
    activa = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Relaciones
    habitaciones = relationship("Habitacion", backref="sucursal", lazy=True)
    usuarios = relationship("User", backref="sucursal", lazy=True)
    rentas = relationship("Renta", backref="sucursal", lazy=True)
    cortes_caja = relationship("CorteCaja", backref="sucursal", lazy=True)
    
    def __repr__(self):
        return f'<Sucursal {self.nombre}>'

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    
    # Campos para multisucursal y roles
    rol = db.Column(db.String(20), default=RolUsuario.RECEPCIONISTA.value)
    turno = db.Column(db.String(10), nullable=True)
    sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'), nullable=True)
    
    # Campos existentes
    is_admin = db.Column(db.Boolean, default=False)
    
    # ✅ CORREGIDO: Especificar foreign_keys explícitamente
    rentas = relationship("Renta", 
                         foreign_keys="[Renta.recepcionista_id]", 
                         backref="recepcionista", 
                         lazy=True)
    
    cortes_caja = relationship("CorteCaja", backref="usuario", lazy=True)
    
    cancelaciones = relationship("Renta", 
                                foreign_keys="[Renta.cancelada_por]", 
                                backref="cancelador", 
                                lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # Métodos de verificación de roles
    def es_admin_general(self):
        return self.rol == RolUsuario.ADMIN_GENERAL.value
    
    def es_admin_motel(self):
        return self.rol == RolUsuario.ADMIN_MOTEL.value
    
    def es_recepcionista(self):
        return self.rol == RolUsuario.RECEPCIONISTA.value
    
    def puede_ver_sucursal(self, sucursal_id):
        if self.es_admin_general():
            return True
        return self.sucursal_id == sucursal_id

    def __repr__(self):
        return f'<User {self.username} ({self.rol})>'
    
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
    
    # Para multisucursal
    sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'), nullable=False)
    
    # Campos existentes
    precio_base = db.Column(db.Float, nullable=False, default=150.00)
    caracteristicas = db.Column(db.Text, nullable=True)
    activa = db.Column(db.Boolean, default=True)

    rentas = relationship("Renta", backref="habitacion", lazy=True)

    def __repr__(self):
        return f'<Habitacion {self.numero} ({self.estado.value})>'
    
    def get_precio_hora(self):
        """Retorna el precio por hora de la habitación"""
        return self.precio_base

class Renta(db.Model):
    __tablename__ = 'rentas'
    id = db.Column(db.Integer, primary_key=True)
    
    # Para multisucursal
    sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'), nullable=False)
    
    # Relaciones existentes
    habitacion_id = db.Column(db.Integer, db.ForeignKey('habitaciones.id'), nullable=False)
    recepcionista_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Datos del cliente
    cliente_nombre = db.Column(db.String(100), nullable=True) 
    
    # Tiempos
    horas_reservadas = db.Column(db.Integer, nullable=False)
    hora_entrada = db.Column(db.DateTime, nullable=False, default=datetime.now)
    hora_salida_estimada = db.Column(db.DateTime, nullable=False)
    hora_salida_real = db.Column(db.DateTime, nullable=True) 

    # Precios
    precio_hora = db.Column(db.Float, nullable=False)
    pago_horas = db.Column(db.Float, nullable=False)
    pago_extra = db.Column(db.Float, nullable=True, default=0.0)
    pago_final = db.Column(db.Float, nullable=True)
    
    # Campos para cancelaciones
    motivo_cancelacion = db.Column(db.Text, nullable=True)
    monto_devolucion = db.Column(db.Float, default=0)
    cancelada_por = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Estado
    estado = db.Column(db.String(20), nullable=False, default='ACTIVA')

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    accesos = relationship("RegistroAcceso", backref="renta", lazy=True)
    checklist = relationship("ChecklistSalida", backref="renta", uselist=False)
    
    def __repr__(self):
        return f'<Renta {self.id} - Hab {self.habitacion_id}>'

class RegistroAcceso(db.Model):
    __tablename__ = 'registros_acceso'
    id = db.Column(db.Integer, primary_key=True)
    
    renta_id = db.Column(db.Integer, db.ForeignKey('rentas.id'), nullable=False)
    
    modo_ingreso = db.Column(db.Enum(ModoIngreso), nullable=False)
    placas = db.Column(db.String(10), nullable=True)
    hora_ingreso = db.Column(db.DateTime, nullable=False, default=datetime.now)
    hora_salida = db.Column(db.DateTime, nullable=True)

    # Campos para futura integración con cámaras LPR
    foto_placas_url = db.Column(db.String(255), nullable=True)
    confianza_reconocimiento = db.Column(db.Float, nullable=True)
    marca_vehiculo = db.Column(db.String(50), nullable=True)
    color_vehiculo = db.Column(db.String(30), nullable=True)

    def __repr__(self):
        return f'<Acceso {self.id} - Renta {self.renta_id}>'

# Modelo para Corte de Caja
class CorteCaja(db.Model):
    __tablename__ = 'cortes_caja'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey('sucursales.id'), nullable=False)
    turno = db.Column(db.String(10), nullable=False)
    
    # Fechas
    fecha_apertura = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_cierre = db.Column(db.DateTime, nullable=True)
    
    # Montos
    monto_inicial = db.Column(db.Float, default=0)
    monto_final = db.Column(db.Float, nullable=True)
    total_ventas = db.Column(db.Float, default=0)
    total_cancelaciones = db.Column(db.Float, default=0)
    total_efectivo = db.Column(db.Float, default=0)
    total_tarjeta = db.Column(db.Float, default=0)
    
    # Control
    estado = db.Column(db.String(15), default='ABIERTO')
    observaciones = db.Column(db.Text, nullable=True)
    
    def __repr__(self):
        return f'<CorteCaja {self.id} - {self.turno} - {self.estado}>'

# Modelo para Checklist de Salida
class ChecklistSalida(db.Model):
    __tablename__ = 'checklists_salida'
    id = db.Column(db.Integer, primary_key=True)
    renta_id = db.Column(db.Integer, db.ForeignKey('rentas.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Checklist items
    limpieza_correcta = db.Column(db.Boolean, default=True)
    danos_habitacion = db.Column(db.Boolean, default=False)
    objetos_olvidados = db.Column(db.Boolean, default=False)
    muebles_danados = db.Column(db.Boolean, default=False)
    equipo_danado = db.Column(db.Boolean, default=False)
    
    # Cargos adicionales
    cargo_danos = db.Column(db.Float, default=0)
    cargo_limpieza = db.Column(db.Float, default=0)
    otros_cargos = db.Column(db.Float, default=0)
    
    # Observaciones
    observaciones_danos = db.Column(db.Text, nullable=True)
    observaciones_generales = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    def __repr__(self):
        return f'<ChecklistSalida {self.id} - Renta {self.renta_id}>'