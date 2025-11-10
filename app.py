from flask import Flask, render_template, request, redirect, url_for, flash, get_flashed_messages, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta, date
import math
import click
import os
import sys
from sqlalchemy import func, desc 
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models import db, Habitacion, Renta, RegistroAcceso, User, EstadoHabitacion, TipoHabitacion, ModoIngreso, Reserva
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


# 🔔 LÓGICA DE REPORTES (Consulta datos agregados) - VERSIÓN ORIGINAL
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


# 🔔 LÓGICA DE REPORTES MEJORADA CON FILTROS - VERSIÓN CORREGIDA
def get_renta_reports_mejorado(fecha_inicio=None, fecha_fin=None):
    """Obtiene datos agregados para reportes con filtros de fecha - VERSIÓN CORREGIDA"""
    
    try:
        # Base query con filtro de estado CERRADA
        base_query = Renta.query.filter(Renta.estado == 'CERRADA')
        
        # Aplicar filtros de fecha si están presentes
        if fecha_inicio and fecha_fin:
            try:
                fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
                fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
                base_query = base_query.filter(
                    Renta.hora_entrada.between(fecha_inicio_dt, fecha_fin_dt)
                )
            except ValueError:
                # Si hay error en el formato, ignorar filtros
                pass

        # Obtener IDs de rentas filtradas
        rentas_filtradas_ids = [r.id for r in base_query.all()]

        # 1. Total de Ingresos y Rentas por Tipo de Habitación
        ingresos_por_tipo = db.session.query(
            Habitacion.tipo,
            func.count(Renta.id).label('total_rentas'),
            func.sum(Renta.pago_final).label('total_ingreso')
        ).join(Habitacion, Renta.habitacion_id == Habitacion.id
        ).filter(Renta.id.in_(rentas_filtradas_ids) if rentas_filtradas_ids else Renta.estado == 'CERRADA'
        ).group_by(Habitacion.tipo).all()
        
        # 2. Total de Rentas por Modo de Ingreso
        rentas_por_modo = db.session.query(
            RegistroAcceso.modo_ingreso,
            func.count(Renta.id).label('total_rentas')
        ).join(RegistroAcceso, Renta.id == RegistroAcceso.renta_id
        ).filter(Renta.id.in_(rentas_filtradas_ids) if rentas_filtradas_ids else Renta.estado == 'CERRADA'
        ).group_by(RegistroAcceso.modo_ingreso).all()
        
        # 3. Top 5 Habitaciones más Rentadas
        top_habitaciones = db.session.query(
            Habitacion.numero,
            func.count(Renta.id).label('num_rentas'),
            func.sum(Renta.pago_final).label('ingreso_total')
        ).join(Renta, Habitacion.id == Renta.habitacion_id
        ).filter(Renta.id.in_(rentas_filtradas_ids) if rentas_filtradas_ids else Renta.estado == 'CERRADA'
        ).group_by(Habitacion.numero
        ).order_by(desc('num_rentas')).limit(5).all()
        
        # 4. Reporte de Horas Extras (SIMPLIFICADO)
        horas_extras_query = db.session.query(
            Renta.hora_entrada,
            Habitacion.numero,
            Renta.cliente_nombre,
            Renta.pago_extra
        ).join(Habitacion, Renta.habitacion_id == Habitacion.id
        ).filter(
            Renta.estado == 'CERRADA',
            Renta.pago_extra > 0
        )
        
        # Aplicar filtros de fecha a horas extras
        if fecha_inicio and fecha_fin:
            try:
                fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
                fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
                horas_extras_query = horas_extras_query.filter(
                    Renta.hora_entrada.between(fecha_inicio_dt, fecha_fin_dt)
                )
            except ValueError:
                pass
        
        horas_extras = horas_extras_query.order_by(desc(Renta.hora_entrada)).limit(50).all()
        
        # 5. Reporte Vehicular Detallado (SIMPLIFICADO)
        ingresos_vehiculares_query = db.session.query(
            RegistroAcceso.placas,
            Habitacion.numero,
            Renta.hora_entrada,
            Renta.hora_salida_real,
            Renta.pago_final
        ).join(Renta, RegistroAcceso.renta_id == Renta.id
        ).join(Habitacion, Renta.habitacion_id == Habitacion.id
        ).filter(
            Renta.estado == 'CERRADA',
            RegistroAcceso.modo_ingreso == ModoIngreso.VEHICULO,
            RegistroAcceso.placas.isnot(None)
        )
        
        # Aplicar filtros de fecha a ingresos vehiculares
        if fecha_inicio and fecha_fin:
            try:
                fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
                fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
                ingresos_vehiculares_query = ingresos_vehiculares_query.filter(
                    Renta.hora_entrada.between(fecha_inicio_dt, fecha_fin_dt)
                )
            except ValueError:
                pass
        
        ingresos_vehiculares = ingresos_vehiculares_query.order_by(desc(Renta.hora_entrada)).limit(50).all()
        
        # Calcular totales de horas extras (SIMPLIFICADO)
        total_monto_extra = sum(float(h.pago_extra) for h in horas_extras if h.pago_extra)
        total_horas_extra = round(total_monto_extra / 150.00, 2)  # Aproximación simple
        
        # Formateo de los resultados
        report_data = {
            'ingresos_tipo': [{'tipo': t.value, 'rentas': c, 'ingreso': float(i) if i else 0.0} for t, c, i in ingresos_por_tipo],
            'rentas_modo': [{'modo': m.value, 'rentas': c} for m, c in rentas_por_modo],
            'top_habitaciones': [{'numero': num, 'rentas': c, 'ingreso_total': float(i) if i else 0.0} for num, c, i in top_habitaciones],
            # NUEVOS DATOS (SIMPLIFICADOS)
            'horas_extras': [{
                'fecha': h.hora_entrada.strftime('%Y-%m-%d %H:%M') if h.hora_entrada else 'N/A',
                'habitacion': h.numero,
                'cliente': h.cliente_nombre,
                'horas_extra': round(float(h.pago_extra) / 150.00, 2) if h.pago_extra else 0.0,
                'monto_extra': float(h.pago_extra) if h.pago_extra else 0.0
            } for h in horas_extras],
            'ingreso_vehiculos': [{
                'placas': v.placas,
                'habitacion': v.numero,
                'entrada': v.hora_entrada.strftime('%Y-%m-%d %H:%M') if v.hora_entrada else 'N/A',
                'salida': v.hora_salida_real.strftime('%Y-%m-%d %H:%M') if v.hora_salida_real else 'N/A',
                'pago_total': float(v.pago_final) if v.pago_final else 0.0,
                'tiempo_total': 'Calculado'  # Simplificado para evitar errores
            } for v in ingresos_vehiculares],
            'total_horas_extra': total_horas_extra,
            'total_monto_extra': total_monto_extra
        }
        
        return report_data
        
    except Exception as e:
        print(f"Error en get_renta_reports_mejorado: {e}")
        # Retornar estructura vacía pero válida
        return {
            'ingresos_tipo': [],
            'rentas_modo': [],
            'top_habitaciones': [],
            'horas_extras': [],
            'ingreso_vehiculos': [],
            'total_horas_extra': 0,
            'total_monto_extra': 0
        }


# --- FUNCIÓN SIMPLIFICADA PARA MÉTRICAS COMPARATIVAS - VERSIÓN CORREGIDA ---
def get_metricas_comparativas(fecha_inicio=None, fecha_fin=None):
    """Calcula métricas comparativas SIMPLIFICADAS - VERSIÓN CORREGIDA"""
    
    try:
        # Si no hay fechas, no calcular métricas comparativas
        if not fecha_inicio or not fecha_fin:
            return {
                'ventas_actual': 0,
                'ventas_anterior': 0,
                'variacion_porcentaje': 0,
                'periodo_actual': 'Sin filtros aplicados',
                'periodo_anterior': 'Selecciona un período'
            }

        # Convertir fechas de string a datetime
        fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d')
        
        # Ventas del período actual
        ventas_actual = db.session.query(func.sum(Renta.pago_final)).filter(
            Renta.estado == 'CERRADA',
            Renta.hora_entrada.between(fecha_inicio_dt, fecha_fin_dt + timedelta(days=1))
        ).scalar() or 0

        # Calcular período anterior (30 días antes) - EVITAR CÁLCULOS COMPLEJOS
        fecha_inicio_anterior = fecha_inicio_dt - timedelta(days=30)
        fecha_fin_anterior = fecha_fin_dt - timedelta(days=30)
        
        ventas_anterior = db.session.query(func.sum(Renta.pago_final)).filter(
            Renta.estado == 'CERRADA',
            Renta.hora_entrada.between(fecha_inicio_anterior, fecha_fin_anterior + timedelta(days=1))
        ).scalar() or 0

        # Calcular variación
        variacion = 0
        if ventas_anterior > 0:
            variacion = ((ventas_actual - ventas_anterior) / ventas_anterior) * 100
        
        return {
            'ventas_actual': float(ventas_actual),
            'ventas_anterior': float(ventas_anterior),
            'variacion_porcentaje': round(variacion, 2),
            'periodo_actual': f"{fecha_inicio} a {fecha_fin}",
            'periodo_anterior': f"{fecha_inicio_anterior.strftime('%Y-%m-%d')} a {fecha_fin_anterior.strftime('%Y-%m-%d')}"
        }
        
    except Exception as e:
        print(f"Error en get_metricas_comparativas: {e}")
        return {
            'ventas_actual': 0,
            'ventas_anterior': 0,
            'variacion_porcentaje': 0,
            'periodo_actual': 'Error en cálculo',
            'periodo_anterior': 'Error en cálculo'
        }


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


    # --- RUTA DE REPORTES Y GRÁFICAS MEJORADA ---
    @app.route('/reportes_rentas')
    @login_required
    def reportes_rentas():
        # Obtener parámetros de filtro
        fecha_inicio = request.args.get('fecha_inicio')
        fecha_fin = request.args.get('fecha_fin')
        tipo_reporte = request.args.get('tipo_reporte', 'general')
        
        # Llama a la función mejorada para obtener los datos
        reportes = get_renta_reports_mejorado(fecha_inicio, fecha_fin)
        
        # Datos adicionales para métricas comparativas
        metricas = get_metricas_comparativas(fecha_inicio, fecha_fin)
        
        return render_template('reportes.html', 
                              reportes=reportes,
                              metricas=metricas,
                              fecha_inicio=fecha_inicio,
                              fecha_fin=fecha_fin,
                              tipo_reporte=tipo_reporte)


    # --- RUTA API PARA REPORTES ESPECÍFICOS ---
    @app.route('/api/reportes/horas-extras')
    @login_required
    def api_horas_extras():
        """API para obtener solo datos de horas extras"""
        fecha_inicio = request.args.get('fecha_inicio')
        fecha_fin = request.args.get('fecha_fin')
        
        reportes = get_renta_reports_mejorado(fecha_inicio, fecha_fin)
        return jsonify({
            'horas_extras': reportes['horas_extras'],
            'total_monto_extra': reportes['total_monto_extra']
        })


    @app.route('/api/reportes/vehicular')
    @login_required
    def api_vehicular():
        """API para obtener solo datos vehiculares"""
        fecha_inicio = request.args.get('fecha_inicio')
        fecha_fin = request.args.get('fecha_fin')
        
        reportes = get_renta_reports_mejorado(fecha_inicio, fecha_fin)
        return jsonify({
            'ingreso_vehiculos': reportes['ingreso_vehiculos']
        })

    #SISTEMA DE RESERVAS - AGREGADO EN LA POSICIÓN CORRECTA

    @app.route('/reservas')
    @login_required
    def reservas():
        """Lista todas las reservas"""
        try:
            reservas_lista = Reserva.query.order_by(Reserva.fecha_reserva.desc()).all()
            habitaciones = Habitacion.query.all()
            
            return render_template('reservas.html', 
                                 reservas=reservas_lista, 
                                 habitaciones=habitaciones)
        except Exception as e:
            flash(f'Error al cargar reservas: {str(e)}', 'error')
            return redirect(url_for('dashboard'))

    @app.route('/nueva_reserva', methods=['GET', 'POST'])
    @login_required
    def nueva_reserva():
        """Crear nueva reserva"""
        if request.method == 'POST':
            try:
                habitacion_id = request.form.get('habitacion_id', type=int)
                cliente_nombre = request.form.get('cliente_nombre')
                cliente_telefono = request.form.get('cliente_telefono', '')
                fecha_reserva_str = request.form.get('fecha_reserva')
                hora_reserva_str = request.form.get('hora_reserva')
                horas_reservadas = request.form.get('horas_reservadas', type=int)

                # Validaciones básicas
                if not all([habitacion_id, cliente_nombre, fecha_reserva_str, hora_reserva_str, horas_reservadas]):
                    flash('Todos los campos son obligatorios', 'error')
                    return redirect(url_for('nueva_reserva'))

                # Convertir fechas
                fecha_reserva = datetime.strptime(fecha_reserva_str, '%Y-%m-%d').date()
                hora_reserva = datetime.strptime(hora_reserva_str, '%H:%M').time()

                # Verificar disponibilidad de habitación
                habitacion = Habitacion.query.get(habitacion_id)
                if not habitacion or not habitacion.activa:
                    flash('Habitación no disponible', 'error')
                    return redirect(url_for('nueva_reserva'))

                # Calcular precio estimado
                precio_estimado = habitacion.precio_base * horas_reservadas

                # Crear reserva
                nueva_reserva = Reserva(
                    habitacion_id=habitacion_id,
                    recepcionista_id=current_user.id,
                    cliente_nombre=cliente_nombre,
                    cliente_telefono=cliente_telefono,
                    fecha_reserva=fecha_reserva,
                    hora_reserva=hora_reserva,
                    horas_reservadas=horas_reservadas,
                    precio_estimado=precio_estimado,
                    estado='PENDIENTE'
                )

                db.session.add(nueva_reserva)
                db.session.commit()

                flash(f'Reserva creada exitosamente para {cliente_nombre}. Precio estimado: ${precio_estimado:.2f}', 'success')
                return redirect(url_for('reservas'))

            except Exception as e:
                db.session.rollback()
                flash(f'Error al crear reserva: {str(e)}', 'error')
                return redirect(url_for('nueva_reserva'))

        else:
            # GET - Mostrar formulario
            habitaciones_disponibles = Habitacion.query.filter_by(activa=True).all()
            
            # Fecha mínima (hoy)
            fecha_minima = datetime.now().strftime('%Y-%m-%d')
            
            return render_template('nueva_reserva.html',
                                 habitaciones=habitaciones_disponibles,
                                 fecha_minima=fecha_minima)

    @app.route('/confirmar_reserva/<int:reserva_id>', methods=['POST'])
    @login_required
    def confirmar_reserva(reserva_id):
        """Confirmar una reserva pendiente"""
        try:
            reserva = Reserva.query.get_or_404(reserva_id)
            
            if reserva.estado != 'PENDIENTE':
                flash('Solo se pueden confirmar reservas pendientes', 'error')
                return redirect(url_for('reservas'))

            reserva.estado = 'CONFIRMADA'
            reserva.confirmada_at = datetime.now()
            
            db.session.commit()
            
            flash(f'Reserva de {reserva.cliente_nombre} confirmada exitosamente', 'success')
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al confirmar reserva: {str(e)}', 'error')
        
        return redirect(url_for('reservas'))

    @app.route('/convertir_a_checkin/<int:reserva_id>', methods=['POST'])
    @login_required
    def convertir_a_checkin(reserva_id):
        """Convertir reserva confirmada a check-in"""
        try:
            reserva = Reserva.query.get_or_404(reserva_id)
            
            if reserva.estado != 'CONFIRMADA':
                flash('Solo se pueden convertir reservas confirmadas', 'error')
                return redirect(url_for('reservas'))

            # Verificar que la habitación esté disponible
            habitacion = reserva.habitacion
            if habitacion.estado != EstadoHabitacion.DISPONIBLE:
                flash(f'La habitación {habitacion.numero} no está disponible', 'error')
                return redirect(url_for('reservas'))

            # Crear renta a partir de la reserva
            hora_entrada = datetime.now()
            hora_salida_estimada = hora_entrada + timedelta(hours=reserva.horas_reservadas)

            nueva_renta = Renta(
                habitacion_id=reserva.habitacion_id,
                recepcionista_id=current_user.id,
                cliente_nombre=reserva.cliente_nombre,
                horas_reservadas=reserva.horas_reservadas,
                hora_entrada=hora_entrada,
                hora_salida_estimada=hora_salida_estimada,
                pago_horas=reserva.precio_estimado,
                precio_hora=habitacion.precio_base,
                estado='ACTIVA',
                reserva_id=reserva.id  # Relacionar con la reserva
            )

            db.session.add(nueva_renta)
            db.session.flush()

            # Crear registro de acceso
            registro_acceso = RegistroAcceso(
                renta_id=nueva_renta.id,
                modo_ingreso=ModoIngreso.A_PIE,  # Por defecto a pie para reservas
                hora_ingreso=hora_entrada
            )
            db.session.add(registro_acceso)

            # Actualizar estado de habitación y reserva
            habitacion.estado = EstadoHabitacion.OCUPADA
            reserva.estado = 'COMPLETADA'

            db.session.commit()

            flash(f'Check-in exitoso desde reserva! Habitación {habitacion.numero} ocupada.', 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error al convertir reserva a check-in: {str(e)}', 'error')
            return redirect(url_for('reservas'))

    @app.route('/cancelar_reserva/<int:reserva_id>', methods=['POST'])
    @login_required
    def cancelar_reserva(reserva_id):
        """Cancelar una reserva"""
        try:
            reserva = Reserva.query.get_or_404(reserva_id)
            
            if reserva.estado == 'COMPLETADA':
                flash('No se puede cancelar una reserva ya completada', 'error')
                return redirect(url_for('reservas'))

            reserva.estado = 'CANCELADA'
            db.session.commit()
            
            flash(f'Reserva de {reserva.cliente_nombre} cancelada', 'info')
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al cancelar reserva: {str(e)}', 'error')
        
        return redirect(url_for('reservas'))

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