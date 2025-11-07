from flask import Flask, render_template, request, redirect, url_for, flash, get_flashed_messages
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from datetime import datetime, timedelta, date
import math
import click
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models import db, Habitacion, Renta, RegistroAcceso, User, EstadoHabitacion, TipoHabitacion, ModoIngreso
from models import BASE_HOUR_PRICE, LUXURY_HOUR_PRICE

from initial_data import load_initial_rooms, load_initial_user


# 🔔 NUEVA FUNCIÓN: Lógica de Autolimpieza
def check_auto_clean_complete(app):
    """
    Revisa y actualiza el estado de las habitaciones de LIMPIEZA a DISPONIBLE
    si ha pasado más de 1 MINUTO desde el check-out.
    """
    
    # Es crucial usar app.app_context() para interactuar con la DB
    with app.app_context():
        try:
            # Define el límite de tiempo: 1 minuto atrás
            limite_tiempo = datetime.now() - timedelta(seconds=15) 

            # Busca las habitaciones en estado LIMPIEZA cuya renta asociada
            # tiene una hora_salida_real (hora de check-out) anterior al límite.
            habitaciones_a_liberar = db.session.query(Habitacion).join(Renta).filter(
                Habitacion.estado == EstadoHabitacion.LIMPIEZA,
                Renta.estado == 'CERRADA',
                Renta.hora_salida_real <= limite_tiempo
            ).all()

            if habitaciones_a_liberar:
                for habitacion in habitaciones_a_liberar:
                    # Cambia el estado de la habitación
                    habitacion.estado = EstadoHabitacion.DISPONIBLE
                    
                db.session.commit()

        except Exception as e:
            db.session.rollback()


def create_app():
    app = Flask(__name__)

    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "12345678")
    MYSQL_DB = os.environ.get("MYSQL_DB", "motel_db")
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
    

    
    app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DB}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    app.secret_key = os.environ.get("SECRET_KEY", "una_clave_secreta_fuerte_y_unica_por_favor") 

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login' 
    login_manager.login_message = "Por favor, inicia sesión para acceder a esta página."

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
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
            'disponibles': disponibles_count,
            'total_habitaciones': Habitacion.query.count()
        }

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))

        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            
            user = User.query.filter_by(username=username).first()

            if user and user.check_password(password):
                login_user(user)
                
                get_flashed_messages() 
                
                flash(f'¡Bienvenido, {user.username}! Inicio de sesión exitoso.', 'success')
                
                return redirect(request.args.get('next') or url_for('dashboard'))
            else:
                flash('Usuario o contraseña incorrectos.', 'error')
                return render_template('login.html')

        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Has cerrado sesión exitosamente.', 'info')
        return redirect(url_for('login'))


    @app.route('/')
    @app.route('/dashboard')
    @login_required
    def dashboard():
        # 🔔 NUEVA FUNCIÓN: Ejecuta la revisión y limpieza automática
        check_auto_clean_complete(app) 
        
        resumen = get_daily_summary()
        actividad = get_daily_activity_data()
        rentas_activas = Renta.query.filter(Renta.estado == 'ACTIVA').all()
        distribucion = get_room_distribution()

        data = []
        for renta in rentas_activas:
            
            tiempo_restante_delta = renta.hora_salida_estimada - datetime.now()
            es_hora_extra = False
            tiempo_restante_str = ""
            horas_extra = 0
            
            if tiempo_restante_delta.total_seconds() < 0:
                es_hora_extra = True
                tiempo_restante_str = "¡TIEMPO EXTRA!"
                
                tiempo_agotado_delta = datetime.now() - renta.hora_salida_estimada
                horas_extra = tiempo_agotado_delta.total_seconds() / 3600
            else:
                total_seconds = int(tiempo_restante_delta.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                tiempo_restante_str = f"{hours}h {minutes}m"
                
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
            
        return render_template('dashboard.html', ocupadas=data, resumen=resumen, actividad=actividad, distribucion=distribucion,
                                EstadoHabitacion=EstadoHabitacion, TipoHabitacion=TipoHabitacion)


    @app.route('/checkin', methods=['GET', 'POST'])
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
                    return redirect(url_for('checkin'))

                habitacion = Habitacion.query.get(room_id)

                if not habitacion or habitacion.estado != EstadoHabitacion.DISPONIBLE:
                    flash('La habitación no está disponible o no existe.', 'error')
                    return redirect(url_for('checkin'))

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
                return redirect(url_for('checkin'))

        else:
            habitaciones_disponibles = Habitacion.query.filter_by(estado=EstadoHabitacion.DISPONIBLE).order_by(Habitacion.numero).all()
            
            return render_template('checkin.html',
                                    habitaciones=habitaciones_disponibles,
                                    ModoIngreso=ModoIngreso)


    @app.route('/checkout/<int:renta_id>', methods=['POST'])
    @login_required
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
                             'Habitación marcada como LIMPIEZA. Se liberará en 1 minuto.') # Mensaje informativo
                flash(flash_msg, 'warning')
            else:
                flash(f'Check-out de Habitación {habitacion.numero} completado sin cargos extra. Habitación marcada como LIMPIEZA. Se liberará en 1 minuto.', 'success') # Mensaje informativo

        except Exception as e:
            db.session.rollback()
            flash('Error interno al procesar el Check-out. Intente de nuevo.', 'error')
            
        return redirect(url_for('dashboard'))


    @app.route('/limpieza')
    @login_required
    def limpieza():
        habitaciones_limpieza = Habitacion.query.filter_by(estado=EstadoHabitacion.LIMPIEZA).order_by(Habitacion.numero).all()
        
        return render_template('limpieza.html', 
                                habitaciones=habitaciones_limpieza)


    @app.route('/clean_complete/<int:room_id>', methods=['POST'])
    @login_required
    def clean_complete(room_id):
        habitacion = Habitacion.query.get(room_id)
        
        if not habitacion or habitacion.estado != EstadoHabitacion.LIMPIEZA:
            flash(f'Error: La Habitación {habitacion.numero} no está en estado de LIMPIEZA.', 'error')
            return redirect(url_for('limpieza'))
            
        try:
            habitacion.estado = EstadoHabitacion.DISPONIBLE
            db.session.commit()
            flash(f'Habitación {habitacion.numero} marcada como DISPONIBLE y lista para la renta.', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Error interno al marcar como disponible. Intente de nuevo.', 'error')
            
        return redirect(url_for('limpieza'))


    @app.cli.command("init-db")
    def init_db_command():
        db.create_all()
        click.echo("Base de datos inicializada: ¡Tablas creadas en la DB MySQL!")

    @app.cli.command("load-initial-rooms")
    def load_rooms_command():
        load_initial_rooms(db)
        click.echo("Comando de carga de habitaciones ejecutado.")
        
    @app.cli.command("load-initial-user")
    def load_user_command():
        load_initial_user(db)
        click.echo("Comando de carga de usuario inicial ejecutado.")

    return app

def get_daily_activity_data():
    """Obtiene datos para la gráfica de actividad del día"""
    today = datetime.combine(date.today(), datetime.min.time())
    
    # Agrupar check-ins por hora
    checkins_por_hora = db.session.query(
        db.func.hour(Renta.hora_entrada).label('hora'),
        db.func.count(Renta.id).label('cantidad')
    ).filter(
        Renta.hora_entrada >= today
    ).group_by(
        db.func.hour(Renta.hora_entrada)
    ).all()
    
    # Agrupar check-outs por hora
    checkouts_por_hora = db.session.query(
        db.func.hour(Renta.hora_salida_real).label('hora'),
        db.func.count(Renta.id).label('cantidad')
    ).filter(
        Renta.hora_salida_real >= today
    ).group_by(
        db.func.hour(Renta.hora_salida_real)
    ).all()
    
    return {
        'checkins': {hora: cantidad for hora, cantidad in checkins_por_hora},
        'checkouts': {hora: cantidad for hora, cantidad in checkouts_por_hora}
    }

def get_room_distribution():
    """Obtiene la distribución REAL de habitaciones"""
    total_habitaciones = Habitacion.query.count()
    ocupadas = Habitacion.query.filter_by(estado=EstadoHabitacion.OCUPADA).count()
    disponibles = Habitacion.query.filter_by(estado=EstadoHabitacion.DISPONIBLE).count()
    limpieza = Habitacion.query.filter_by(estado=EstadoHabitacion.LIMPIEZA).count()
    mantenimiento = Habitacion.query.filter_by(estado=EstadoHabitacion.MANTENIMIENTO).count()
    
    return {
        'ocupadas': ocupadas,
        'disponibles': disponibles,
        'limpieza': limpieza,
        'mantenimiento': mantenimiento,
        'total': total_habitaciones
    }

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)