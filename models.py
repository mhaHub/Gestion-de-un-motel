from datetime import datetime
from app import db

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rentas_realizadas = db.relationship('Renta', backref='recepcionista_en_turno', lazy=True)

    def __repr__(self):
        return f"<User {self.email}>"
    
class Habitacion(db.Model):
    __tablename__ = "habitaciones"
    
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(10), unique=True, nullable=False)
    tipo = db.Column(db.String(50), nullable=False) 
    
    precio_por_hora = db.Column(db.Float, nullable=False) 
    
    estado = db.Column(db.String(50), default="Disponible", nullable=False)

    historial_rentas = db.relationship('Renta', backref='habitacion_rentada', lazy=True)

    def __repr__(self):
        return f"<Habitacion {self.numero} ({self.estado})>"

class Renta(db.Model):
    __tablename__ = "rentas"

    id = db.Column(db.Integer, primary_key=True)

    habitacion_id = db.Column(db.Integer, db.ForeignKey("habitaciones.id"), nullable=False)
    recepcionista_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    horas_reservadas = db.Column(db.Integer, nullable=False)
    hora_entrada = db.Column(db.DateTime, nullable=False)
    hora_salida_esperada = db.Column(db.DateTime, nullable=False) 
    pago_horas = db.Column(db.Float, nullable=False)

    hora_salida_real = db.Column(db.DateTime, nullable=True) 
    horas_extras = db.Column(db.Float, default=0.0)
    horas_extras_pagadas = db.Column(db.Float, default=0.0)
    pago_final = db.Column(db.Float, default=0.0)

    def __repr__(self):
        return f"<Renta {self.id} | Hab: {self.habitacion_rentada.numero if self.habitacion_rentada else 'N/A'}>"
