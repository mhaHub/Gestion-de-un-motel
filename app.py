from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, date
import math
import click


from models import db, Habitacion, Renta, RegistroAcceso, User, EstadoHabitacion, TipoHabitacion, ModoIngreso
from models import BASE_HOUR_PRICE, LUXURY_HOUR_PRICE

from init_db import load_initial_rooms


def create_app():
    app = Flask(__name__)

    MYSQL_USER = "root"
    MYSQL_PASSWORD = "12345678"
    MYSQL_DB = "motel_db"
    MYSQL_HOST = "localhost"

    app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DB}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.secret_key = 'tu_clave_secreta_aqui'

    db.init_app(app)


    def get_daily_summary():
        today = datetime.combine(date.today(), datetime.min.time())
        
        rentas_del_dia = Renta.query.filter(Renta.hora_entrada >= today).all()
        
        total_clientes = len(rentas_del_dia)
        total_ingreso_inicial = sum(r.pago_horas for r in rentas_del_dia)
        total_horas_rentadas = sum(r.horas_reservadas for r in rentas_del_dia)
        
        ocupadas_count = Habitacion.query.filter_by(estado=EstadoHabitacion.OCUPADA).count()
        disponibles_count = Habitacion.query.filter_by(estado=EstadoHabitacion.DISPONIBLE).count()
        
        return {
            'clientes_dia': total_clientes,
            'ingreso_inicial_dia': total_ingreso_inicial,
            'horas_totales_dia': total_horas_rentadas,
            'ocupadas': ocupadas_count,
            'disponibles': disponibles_count
        }



    @app.route('/checkin', methods=['GET', 'POST'])
    def checkin():
        recepcionista = User.query.get(1)

        if request.method == 'POST':
            try:
                room_id = request.form.get('habitacion_id', type=int)
                hours = request.form.get('horas_reservadas', type=int)
                nombre_cliente = request.form.get('nombre_cliente')
                modo_ingreso_str = request.form.get('modo_ingreso')
                placas = request.form.get('placas', '').upper()

                if not room_id or not hours or not nombre_cliente:
                    flash('Faltan datos obligatorios para el Check-in.', 'error')
                    return redirect(url_for('checkin'))

                habitacion = Habitacion.query.get(room_id)

                if not habitacion or habitacion.estado != EstadoHabitacion.DISPONIBLE:
                    flash('La habitación no está disponible o no existe.', 'error')
                    return redirect(url_for('checkin'))

                precio_hora = LUXURY_HOUR_PRICE if habitacion.tipo == TipoHabitacion.JACUZZI else BASE_HOUR_PRICE
                pago_total = precio_hora * hours

                hora_entrada = datetime.now()
                hora_salida_estimada = hora_entrada + timedelta(hours=hours)

                # 1. Crear Renta
                nueva_renta = Renta(
                    habitacion_id=room_id,
                    recepcionista_id=recepcionista.id,
                    cliente_nombre=nombre_cliente,
                    horas_reservadas=hours,
                    hora_entrada=hora_entrada,
                    hora_salida_estimada=hora_salida_estimada,
                    pago_horas=pago_total,
                    precio_hora=precio_hora,
                    estado='ACTIVA'
                )
                db.session.add(nueva_renta)
                db.session.flush() # Obtener el ID de la renta antes de hacer commit

                # 2. Crear Registro de Acceso
                modo_ingreso = ModoIngreso[modo_ingreso_str]
                registro_acceso = RegistroAcceso(
                    renta_id=nueva_renta.id,
                    modo_ingreso=modo_ingreso,
                    placas=placas if placas and modo_ingreso == ModoIngreso.VEHICULO else None,
                    hora_ingreso=hora_entrada
                )
                db.session.add(registro_acceso)

                # 3. Actualizar estado de la habitación
                habitacion.estado = EstadoHabitacion.OCUPADA
                
                db.session.commit()

                flash(f'Check-in exitoso! Habitación {habitacion.numero} rentada por {hours} horas.', 'success')
                return redirect(url_for('dashboard'))

            except Exception as e:
                db.session.rollback()
                flash('Error interno al registrar el Check-in. Intente de nuevo.', 'error')
                print(f"Error al procesar Check-in: {e}")
                return redirect(url_for('checkin'))

        else:
            # Manejo del GET
            if not recepcionista:
                 flash('Error: No se encontró el usuario recepcionista (ID 1). Ejecute flask load-initial-rooms.', 'error')
                 return redirect(url_for('dashboard'))
                 
            habitaciones_disponibles = Habitacion.query.filter_by(estado=EstadoHabitacion.DISPONIBLE).order_by(Habitacion.numero).all()
            
            return render_template('checkin.html',
                                   habitaciones=habitaciones_disponibles,
                                   ModoIngreso=ModoIngreso,
                                   recepcionista=recepcionista)


    @app.route('/')
    @app.route('/dashboard')
    def dashboard():
        resumen = get_daily_summary()
        
        # Filtra rentas activas
        rentas_activas = Renta.query.filter_by(estado='ACTIVA').all()

        data = []
        for renta in rentas_activas:
            
            tiempo_restante_delta = renta.hora_salida_estimada - datetime.now()
            es_hora_extra = False
            tiempo_restante_str = ""
            horas_extra = 0
            
            # Calcular tiempo extra
            if tiempo_restante_delta.total_seconds() < 0:
                es_hora_extra = True
                tiempo_restante_str = "¡TIEMPO EXTRA!"
                
                # Calcula cuánto tiempo ha pasado desde la hora de salida estimada
                tiempo_agotado_delta = datetime.now() - renta.hora_salida_estimada
                horas_extra = tiempo_agotado_delta.total_seconds() / 3600
            else:
                # Calcular horas y minutos restantes
                total_seconds = int(tiempo_restante_delta.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                tiempo_restante_str = f"{hours}h {minutes}m"
                
            # Busca el registro de acceso para obtener las placas
            acceso = RegistroAcceso.query.filter_by(renta_id=renta.id).first()
            
            data.append({
                'renta_id': renta.id,
                'numero': renta.habitacion.numero,
                'tipo': renta.habitacion.tipo.value,
                'cliente': renta.cliente_nombre,
                'placas': acceso.placas if acceso and acceso.placas else 'N/A',
                'entrada': renta.hora_entrada.strftime('%H:%M:%S'),
                'salida_estimada': renta.hora_salida_estimada.strftime('%H:%M:%S'),
                'pago_inicial': renta.pago_horas,
                'tiempo_restante': tiempo_restante_str,
                'es_hora_extra': es_hora_extra,
                'horas_extra': horas_extra,
                'precio_hora': renta.precio_hora
            })
            
        return render_template('dashboard.html', ocupadas=data, resumen=resumen)


    @app.route('/checkout/<int:renta_id>', methods=['POST'])
    def checkout(renta_id):
        renta = Renta.query.get(renta_id)

        if not renta or renta.estado != 'ACTIVA':
            flash('Error: La renta no existe o ya ha sido cerrada.', 'error')
            return redirect(url_for('dashboard'))

        try:
            hora_salida_real = datetime.now()
            tiempo_extra_delta = hora_salida_real - renta.hora_salida_estimada
            horas_extra_a_pagar = 0.0
            pago_extra = 0.0
            pago_final = renta.pago_horas # Pago inicial

            # Calcular si hubo tiempo extra
            if tiempo_extra_delta.total_seconds() > 0:
                horas_extra_flotante = tiempo_extra_delta.total_seconds() / 3600
                # Redondeamos al techo (ceiling) para cobrar la hora completa extra
                horas_extra_a_pagar = math.ceil(horas_extra_flotante)
                pago_extra = horas_extra_a_pagar * renta.precio_hora
                pago_final += pago_extra

            # 1. Actualizar Renta
            renta.hora_salida_real = hora_salida_real
            renta.horas_extra = horas_extra_a_pagar
            renta.pago_extra = pago_extra
            renta.pago_final = pago_final
            renta.estado = 'CERRADA'

            # 2. Actualizar estado de la habitación a LIMPIEZA
            habitacion = Habitacion.query.get(renta.habitacion_id)
            if habitacion:
                habitacion.estado = EstadoHabitacion.LIMPIEZA

            # 3. Actualizar Registro de Acceso (Hora de salida)
            registro_acceso = RegistroAcceso.query.filter_by(renta_id=renta.id).first()
            if registro_acceso:
                registro_acceso.hora_salida = hora_salida_real

            db.session.commit()

            # Mensaje de feedback
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
            print(f"Error al procesar Check-out: {e}")
            
        return redirect(url_for('dashboard'))



    @app.cli.command("init-db")
    def init_db_command():
        """Crea todas las tablas de la base de datos (Habitacion, Renta, User) en MySQL."""
        db.create_all()
        click.echo("Base de datos inicializada: ¡Tablas creadas en la DB MySQL!")

    @app.cli.command("load-initial-rooms")
    def load_rooms_command():
        """Carga las 10 habitaciones iniciales del Half Time Inn."""
        # Llama a la función importada de init_db.py
        load_initial_rooms(db)
        click.echo("Comando de carga de habitaciones ejecutado.")

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
