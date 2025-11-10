from flask import Flask, render_template, request, redirect, url_for, flash, get_flashed_messages, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta, date
import math
import click
import os
import sys
# ⚠ Importamos 'desc' de sqlalchemy para usarlo correctamente en ORDER BY
from sqlalchemy import func, desc 
# Asegura que el directorio actual esté en el PATH para importar modelos
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models import db, Habitacion, Renta, RegistroAcceso, User, EstadoHabitacion, TipoHabitacion, ModoIngreso
from models import BASE_HOUR_PRICE, LUXURY_HOUR_PRICE

# --- Funciones de Carga Inicial ---

def load_initial_rooms(app):
    """Carga un set inicial de habitaciones si no existen."""
    with app.app_context():
        # Adaptado a tus TipoHabitacion: NORMAL y JACUZZI
        rooms_data = [
            {'numero': '101', 'tipo': TipoHabitacion.NORMAL},
            {'numero': '102', 'tipo': TipoHabitacion.NORMAL},
            {'numero': '103', 'tipo': TipoHabitacion.JACUZZI},
            {'numero': '201', 'tipo': TipoHabitacion.NORMAL},
            {'numero': '202', 'tipo': TipoHabitacion.JACUZZI},
        ]
        
        try:
            if db.session.query(Habitacion).count() == 0:
                for data in rooms_data:
                    new_room = Habitacion(numero=data['numero'], tipo=data['tipo'], estado=EstadoHabitacion.DISPONIBLE)
                    db.session.add(new_room)
                db.session.commit()
                click.echo("Se cargaron 5 habitaciones iniciales.")
            else:
                click.echo("Ya existen habitaciones, no se cargaron las iniciales.")
        except Exception as e:
            db.session.rollback()
            click.echo(f"Error al cargar habitaciones: {e}")


def load_initial_user(app):
    """Carga un usuario de prueba si no existe."""
    with app.app_context():
        try:
            if db.session.query(User).filter_by(username='admin').first() is None:
                admin_user = User(username='admin', email='admin@motel.com')
                admin_user.set_password('1234') 
                admin_user.is_admin = True
                db.session.add(admin_user)
                db.session.commit()
                click.echo("Usuario 'admin' (password '1234') creado.")
            else:
                click.echo("Usuario 'admin' ya existe.")
        except Exception as e:
            db.session.rollback()
            click.echo(f"Error al cargar el usuario inicial: {e}")

# 🔔 LÓGICA DE AUTOLIMPIEZA
def check_auto_clean_complete(app):
    """
    Revisa y actualiza el estado de las habitaciones de LIMPIEZA a DISPONIBLE
    si ha pasado un tiempo prudente (0.1 MINUTOS para prueba) desde el check-out.
    """
    
    with app.app_context():
        try:
            limite_tiempo = datetime.now() - timedelta(minutes=.1) 

            habitaciones_a_liberar = db.session.query(Habitacion).join(Renta).filter(
                Habitacion.estado == EstadoHabitacion.LIMPIEZA,
                Renta.estado == 'CERRADA',
                Renta.hora_salida_real <= limite_tiempo
            ).all()

            if habitaciones_a_liberar:
                for habitacion in habitaciones_a_liberar:
                    habitacion.estado = EstadoHabitacion.DISPONIBLE
                    
                db.session.commit()

        except Exception as e:
            db.session.rollback()


# 🔔 LÓGICA DE REPORTES (Consulta datos agregados)
def get_renta_reports():
    """Obtiene datos agregados para los reportes de ingresos y rentas por tipo/modo. (CORREGIDO)"""
    
    # 1. Total de Ingresos y Rentas por Tipo de Habitación
    ingresos_por_tipo = db.session.query(
        Habitacion.tipo,
        func.count(Renta.id).label('total_rentas'),
        func.sum(Renta.pago_final).label('total_ingreso')
    ).join(Habitacion, Renta.habitacion_id == Habitacion.id).filter(
        Renta.estado == 'CERRADA'
    ).group_by(
        Habitacion.tipo
    ).all()
    
    # 2. Total de Rentas por Modo de Ingreso
    rentas_por_modo = db.session.query(
        RegistroAcceso.modo_ingreso,
        func.count(Renta.id).label('total_rentas')
    ).join(RegistroAcceso, Renta.id == RegistroAcceso.renta_id).filter(
        Renta.estado == 'CERRADA'
    ).group_by(
        RegistroAcceso.modo_ingreso
    ).all()
    
    # 3. Datos para el Top 5 de Habitaciones más Rentadas
    top_habitaciones = db.session.query(
        Habitacion.numero,
        func.count(Renta.id).label('num_rentas'),
        func.sum(Renta.pago_final).label('ingreso_total')
    ).join(Renta, Habitacion.id == Renta.habitacion_id).filter(
        Renta.estado == 'CERRADA'
    ).group_by(
        Habitacion.numero
    ).order_by(
        # 💥 CORRECCIÓN: Usamos desc() importado de sqlalchemy aplicado al alias
        desc('num_rentas') 
    ).limit(5).all()
    
    # Formateo de los resultados (usando .value para obtener el string del Enum)
    report_data = {
        'ingresos_tipo': [{'tipo': t.value, 'rentas': c, 'ingreso': i if i else 0.0} for t, c, i in ingresos_por_tipo],
        'rentas_modo': [{'modo': m.value, 'rentas': c} for m, c in rentas_por_modo],
        'top_habitaciones': [{'numero': num, 'rentas': c, 'ingreso_total': i if i else 0.0} for num, c, i in top_habitaciones]
    }
    
    return report_data


def create_app():
    app = Flask(__name__)

    # Configuración de MySQL desde variables de entorno
    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "12345678")
    MYSQL_DB = os.environ.get("MYSQL_DB", "motel_db")
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
    
    # Configuración de SQLAlchemy
    app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DB}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    app.secret_key = os.environ.get("SECRET_KEY", "una_clave_secreta_fuerte_y_unica_por_favor") 

    db.init_app(app)

    # Configuración de Flask-Login
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
        total_ingreso_inicial = sum(r.pago_horas for r in rentas_del_dia if r.pago_horas is not None)
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

    # --- RUTAS DE AUTENTICACIÓN ---
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


    # --- RUTA PRINCIPAL (DASHBOARD) ---
    @app.route('/')
    @app.route('/dashboard')
    @login_required
    def dashboard():
        # 🔔 Se ejecuta la revisión y limpieza automática al cargar el dashboard
        check_auto_clean_complete(app) 
        
        resumen = get_daily_summary()
        actividad = get_daily_activity_data()
        
        # Obtenemos las rentas activas para la carga inicial
        rentas_activas = Renta.query.filter(Renta.estado == 'ACTIVA').all()
        distribucion = get_room_distribution()

        # Procesamos los datos para la plantilla
        data = []
        for renta in rentas_activas:
            
            tiempo_restante_delta = renta.hora_salida_estimada - datetime.now()
            es_hora_extra = False
            tiempo_restante_str = ""
            horas_extra = 0
            
            if tiempo_restante_delta.total_seconds() < 0:
                es_hora_extra = True
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
                # Usar .value para obtener el string del Enum antes de pasarlo a Jinja/JSON
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

    # --- RUTA API para AJAX del Dashboard ---
    @app.route('/api/habitaciones_activas')
    @login_required
    def habitaciones_activas_api():
        # 🔔 Ejecuta la Autolimpieza antes de devolver los datos actualizados
        check_auto_clean_complete(app) 
        
        rentas_activas = Renta.query.filter(Renta.estado == 'ACTIVA').all()
        
        data = []
        for renta in rentas_activas:
            tiempo_restante_delta = renta.hora_salida_estimada - datetime.now()
            es_hora_extra = False
            tiempo_restante_str = ""
            horas_extra = 0
            
            if tiempo_restante_delta.total_seconds() < 0:
                es_hora_extra = True
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
                # Usar .value para obtener el string del Enum antes de jsonify
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
            
        return jsonify(data)

    # --- RUTA DE CHECK-IN ---
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

                # Lógica de precio basada en el nuevo TipoHabitacion
                precio_hora = LUXURY_HOUR_PRICE if habitacion.tipo == TipoHabitacion.JACUZZI else BASE_HOUR_PRICE
                pago_total = precio_hora * hours

                hora_entrada = datetime.now()
                hora_salida_estimada = hora_entrada + timedelta(hours=hours)
                
                # Obtener el Enum a partir del string del formulario
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
                flash(f'Error interno al registrar el Check-in: {str(e)}', 'error')
                return redirect(url_for('checkin'))

        else:
            habitaciones_disponibles = Habitacion.query.filter_by(estado=EstadoHabitacion.DISPONIBLE).order_by(Habitacion.numero).all()
            
            return render_template('checkin.html',
                                    habitaciones=habitaciones_disponibles,
                                    ModoIngreso=ModoIngreso)

    # --- RUTA DE CHECK-OUT ---
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
            pago_final = renta.pago_horas if renta.pago_horas is not None else 0.0

            if tiempo_extra_delta.total_seconds() > 0:
                horas_extra_flotante = tiempo_extra_delta.total_seconds() / 3600
                horas_extra_a_pagar = math.ceil(horas_extra_flotante)
                pago_extra = horas_extra_a_pagar * renta.precio_hora
                pago_final += pago_extra

            renta.hora_salida_real = hora_salida_real
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
                             'Habitación marcada como LIMPIEZA. Se liberará en 1 minuto.')
                flash(flash_msg, 'warning')
            else:
                flash(f'Check-out de Habitación {habitacion.numero} completado sin cargos extra. Habitación marcada como LIMPIEZA. Se liberará en 1 minuto.', 'success')

        except Exception as e:
            db.session.rollback()
            flash(f'Error interno al procesar el Check-out: {str(e)}', 'error')
            
        return redirect(url_for('dashboard'))

    # --- RUTA DE LIMPIEZA ---
    @app.route('/limpieza')
    @login_required
    def limpieza():
        habitaciones_limpieza = Habitacion.query.filter_by(estado=EstadoHabitacion.LIMPIEZA).order_by(Habitacion.numero).all()
        
        return render_template('limpieza.html', 
                                habitaciones=habitaciones_limpieza)

    # --- RUTA DE FIN DE LIMPIEZA MANUAL ---
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
            flash(f'Error interno al marcar como disponible: {str(e)}', 'error')
            
        return redirect(url_for('limpieza'))


    # --- 🔔 RUTA DE REPORTES Y GRÁFICAS ---
    @app.route('/reportes_rentas')
    @login_required
    def reportes_rentas():
        # Llama a la función corregida para obtener los datos agregados
        reportes = get_renta_reports()
        
        return render_template('reportes.html', 
                                reportes=reportes)


    # --- COMANDOS CLI ---
    @app.cli.command("init-db")
    def init_db_command():
        with app.app_context():
            db.create_all()
            click.echo("Base de datos inicializada: ¡Tablas creadas en la DB MySQL!")

    @app.cli.command("load-initial-rooms")
    def load_rooms_command():
        load_initial_rooms(app)
        click.echo("Comando de carga de habitaciones ejecutado.")
        
    @app.cli.command("load-initial-user")
    def load_user_command():
        load_initial_user(app)
        click.echo("Comando de carga de usuario inicial ejecutado.")

    return app


# --- FUNCIONES DE SOPORTE PARA EL DASHBOARD ---

def get_daily_activity_data():
    """Obtiene datos para la gráfica de actividad del día"""
    today = datetime.combine(date.today(), datetime.min.time())
    
    # Agrupar check-ins por hora
    checkins_por_hora = db.session.query(
        func.hour(Renta.hora_entrada).label('hora'),
        func.count(Renta.id).label('cantidad')
    ).filter(
        Renta.hora_entrada >= today
    ).group_by(
        func.hour(Renta.hora_entrada)
    ).all()
    
    # Agrupar check-outs por hora
    checkouts_por_hora = db.session.query(
        func.hour(Renta.hora_salida_real).label('hora'),
        func.count(Renta.id).label('cantidad')
    ).filter(
        Renta.hora_salida_real >= today
    ).group_by(
        func.hour(Renta.hora_salida_real)
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