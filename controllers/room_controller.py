from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import math
from ..models import db, Habitacion, Renta, RegistroAcceso, EstadoHabitacion, TipoHabitacion, ModoIngreso
from ..models import BASE_HOUR_PRICE, LUXURY_HOUR_PRICE

rooms_bp = Blueprint('rooms_bp', __name__)

@rooms_bp.route('/checkin', methods=['GET', 'POST'])
@login_required
def checkin():
    recepcionista_id = current_user.id 

    if request.method == 'POST':
        try:
            room_id = request.form.get('habitacion_id', type=int)
            hours = request.form.get('horas_reservadas', type=int)
            nombre_cliente = request.form.get('nombre_cliente')
            modo_ingreso_str = request.form.get('modo_ingreso') 
            placas = request.form.get('placas', '').upper()

            if not room_id or not hours or not nombre_cliente or not modo_ingreso_str:
                flash('Faltan datos obligatorios para el Check-in.', 'error')
                return redirect(url_for('rooms_bp.checkin'))

            habitacion = Habitacion.query.get(room_id)

            if not habitacion or habitacion.estado != EstadoHabitacion.DISPONIBLE:
                flash('La habitación no está disponible o no existe.', 'error')
                return redirect(url_for('rooms_bp.checkin'))

            precio_hora = LUXURY_HOUR_PRICE if habitacion.tipo == TipoHabitacion.JACUZZI else BASE_HOUR_PRICE
            pago_total = precio_hora * hours

            hora_entrada = datetime.now()
            hora_salida_estimada = hora_entrada + timedelta(hours=hours)
            modo_ingreso = ModoIngreso[modo_ingreso_str] 

            nueva_renta = Renta(
                habitacion_id=room_id,
                recepcionista_id=recepcionista_id,
                cliente_nombre=nombre_cliente,
                horas_reservadas=hours,
                hora_entrada=hora_entrada,
                hora_salida_estimada=hora_salida_estimada,
                pago_horas=pago_total,
                precio_hora=precio_hora,
                estado='ACTIVA'
            )
            db.session.add(nueva_renta)
            db.session.flush() 

            registro_acceso = RegistroAcceso(
                renta_id=nueva_renta.id,
                modo_ingreso=modo_ingreso,
                placas=placas if placas and modo_ingreso == ModoIngreso.VEHICULO else None, 
                hora_ingreso=hora_entrada
            )
            db.session.add(registro_acceso)

            habitacion.estado = EstadoHabitacion.OCUPADA
            
            db.session.commit()

            flash(f'Check-in exitoso! Habitación {habitacion.numero} rentada por {hours} horas. Pago inicial: ${pago_total:.2f}.', 'success')
            return redirect(url_for('dashboard')) 

        except Exception as e:
            db.session.rollback()
            flash('Error interno al registrar el Check-in. Intente de nuevo.', 'error')
            return redirect(url_for('rooms_bp.checkin'))

    else:
        habitaciones_disponibles = Habitacion.query.filter_by(estado=EstadoHabitacion.DISPONIBLE).order_by(Habitacion.numero).all()
        
        return render_template('checkin.html',
                                habitaciones=habitaciones_disponibles,
                                ModoIngreso=ModoIngreso)


@rooms_bp.route('/checkout/<int:renta_id>', methods=['POST'])
@login_required
def checkout_renta(renta_id):
    renta = Renta.query.get(renta_id)

    if not renta or renta.estado != 'ACTIVA':
        flash('Error: La renta no existe o ya ha sido cerrada.', 'error')
        return redirect(url_for('dashboard'))

    try:
        hora_salida_real = datetime.now()
        tiempo_extra_delta = hora_salida_real - renta.hora_salida_estimada
        horas_extra_a_pagar = 0.0
        pago_extra = 0.0
        pago_final = renta.pago_horas

        if tiempo_extra_delta.total_seconds() > 0:
            horas_extra_flotante = tiempo_extra_delta.total_seconds() / 3600
            horas_extra_a_pagar = math.ceil(horas_extra_flotante)
            pago_extra = horas_extra_a_pagar * renta.precio_hora
            pago_final += pago_extra

        renta.hora_salida_real = hora_salida_real
        renta.horas_extra = horas_extra_a_pagar
        renta.pago_extra = pago_extra
        renta.pago_final = pago_final
        renta.estado = 'CERRADA'

        habitacion = Habitacion.query.get(renta.habitacion_id)
        if habitacion:
            habitacion.estado = EstadoHabitacion.LIMPIEZA

        registro_acceso = RegistroAcceso.query.filter_by(renta_id=renta.id).first()
        if registro_acceso:
            registro_acceso.hora_salida = hora_salida_real

        db.session.commit()

        if pago_extra > 0:
            flash_msg = (f'Check-out de Habitación {habitacion.numero} finalizado. '
                         f'Tiempo extra: {horas_extra_a_pagar} horas. '
                         f'Pago extra requerido: ${pago_extra:.2f}. Pago Total: ${pago_final:.2f}. '
                         'Habitación marcada como LIMPIEZA.')
            flash(flash_msg, 'warning')
        else:
            flash(f'Check-out de Habitación {habitacion.numero} completado sin cargos extra. Habitación marcada como LIMPIEZA.', 'success')

    except Exception as e:
        db.session.rollback()
        flash('Error interno al procesar el Check-out. Intente de nuevo.', 'error')
        
    return redirect(url_for('dashboard'))


@rooms_bp.route('/limpieza')
@login_required
def limpieza():
    habitaciones_limpieza = Habitacion.query.filter_by(estado=EstadoHabitacion.LIMPIEZA).order_by(Habitacion.numero).all()
    
    return render_template('limpieza.html', 
                            habitaciones=habitaciones_limpieza)


@rooms_bp.route('/clean_complete/<int:room_id>', methods=['POST'])
@login_required
def clean_complete(room_id):
    habitacion = Habitacion.query.get(room_id)
    
    if not habitacion or habitacion.estado != EstadoHabitacion.LIMPIEZA:
        flash(f'Error: La Habitación {habitacion.numero} no está en estado de LIMPIEZA.', 'error')
        return redirect(url_for('rooms_bp.limpieza'))
        
    try:
        habitacion.estado = EstadoHabitacion.DISPONIBLE
        db.session.commit()
        flash(f'Habitación {habitacion.numero} marcada como DISPONIBLE y lista para la renta.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error interno al marcar como disponible. Intente de nuevo.', 'error')
        
    return redirect(url_for('rooms_bp.limpieza'))
