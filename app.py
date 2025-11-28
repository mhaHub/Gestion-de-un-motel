from flask import Flask, render_template, request, redirect, url_for, flash, get_flashed_messages, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta, date
from flask_migrate import Migrate
import math
import click
import os
import sys
from sqlalchemy import func, desc, or_
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models import db, Habitacion, Renta, RegistroAcceso, User, EstadoHabitacion, TipoHabitacion, ModoIngreso
from models import BASE_HOUR_PRICE, LUXURY_HOUR_PRICE, Sucursal, CorteCaja, ChecklistSalida, RolUsuario, TurnoTrabajo

# --- Funciones de Carga Inicial Mejoradas ---

def load_initial_data(app):
    """Carga datos iniciales para el sistema multisucursal."""
    with app.app_context():
        try:
            # 1. Crear sucursal principal si no existe
            if db.session.query(Sucursal).count() == 0:
                sucursal_principal = Sucursal(
                    nombre="Halftime Inn Principal",
                    direccion="Av. Principal #123",
                    telefono="555-1234"
                )
                db.session.add(sucursal_principal)
                db.session.flush()
                click.echo("Sucursal principal creada.")
            else:
                sucursal_principal = Sucursal.query.first()

            # 2. Cargar habitaciones iniciales
            if db.session.query(Habitacion).count() == 0:
                rooms_data = [
                    {'numero': '101', 'tipo': TipoHabitacion.NORMAL, 'sucursal_id': sucursal_principal.id},
                    {'numero': '102', 'tipo': TipoHabitacion.NORMAL, 'sucursal_id': sucursal_principal.id},
                    {'numero': '103', 'tipo': TipoHabitacion.JACUZZI, 'sucursal_id': sucursal_principal.id},
                    {'numero': '201', 'tipo': TipoHabitacion.NORMAL, 'sucursal_id': sucursal_principal.id},
                    {'numero': '202', 'tipo': TipoHabitacion.JACUZZI, 'sucursal_id': sucursal_principal.id},
                ]
                
                for data in rooms_data:
                    new_room = Habitacion(
                        numero=data['numero'], 
                        tipo=data['tipo'], 
                        estado=EstadoHabitacion.DISPONIBLE,
                        sucursal_id=data['sucursal_id'],
                        precio_base=200.00 if data['tipo'] == TipoHabitacion.JACUZZI else 150.00
                    )
                    db.session.add(new_room)
                click.echo("5 habitaciones iniciales creadas.")

            # 3. Cargar usuarios iniciales con roles
            if db.session.query(User).filter_by(username='admin').first() is None:
                # Admin General
                admin_general = User(
                    username='admin', 
                    email='admin@motel.com',
                    rol=RolUsuario.ADMIN_GENERAL.value
                )
                admin_general.set_password('1234')
                
                # Admin de Motel
                admin_motel = User(
                    username='gerente',
                    email='gerente@motel.com', 
                    rol=RolUsuario.ADMIN_MOTEL.value,
                    sucursal_id=sucursal_principal.id
                )
                admin_motel.set_password('1234')
                
                # Recepcionista
                recepcionista = User(
                    username='recepcion',
                    email='recepcion@motel.com',
                    rol=RolUsuario.RECEPCIONISTA.value,
                    sucursal_id=sucursal_principal.id,
                    turno=TurnoTrabajo.MATUTINO.value
                )
                recepcionista.set_password('1234')
                
                db.session.add_all([admin_general, admin_motel, recepcionista])
                click.echo("Usuarios iniciales creados: admin, gerente, recepcion (password: 1234)")

            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            click.echo(f"Error al cargar datos iniciales: {e}")

def check_auto_clean_complete(app):
    """Revisa y actualiza el estado de las habitaciones de LIMPIEZA a DISPONIBLE."""
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

# --- Funciones de Soporte Mejoradas ---

def get_sucursal_actual():
    """Obtiene la sucursal actual del usuario."""
    if current_user.es_admin_general():
        return None
    return current_user.sucursal_id

def filtrar_por_sucursal(query, modelo):
    """Aplica filtro de sucursal según los permisos del usuario."""
    sucursal_id = get_sucursal_actual()
    if sucursal_id is not None and hasattr(modelo, 'sucursal_id'):
        return query.filter(modelo.sucursal_id == sucursal_id)
    return query

def get_daily_summary():
    """Obtiene resumen del día filtrado por sucursal."""
    today = datetime.combine(date.today(), datetime.min.time())
    
    rentas_query = Renta.query.filter(Renta.hora_entrada >= today)
    rentas_query = filtrar_por_sucursal(rentas_query, Renta)
    rentas_del_dia = rentas_query.all()
    
    habitaciones_query = Habitacion.query
    habitaciones_query = filtrar_por_sucursal(habitaciones_query, Habitacion)
    
    total_clientes = len(rentas_del_dia)
    total_ingreso_inicial = sum(r.pago_horas for r in rentas_del_dia if r.pago_horas is not None)
    total_horas_rentadas = sum(r.horas_reservadas for r in rentas_del_dia)
    
    ocupadas_count = habitaciones_query.filter_by(estado=EstadoHabitacion.OCUPADA).count()
    disponibles_count = habitaciones_query.filter_by(estado=EstadoHabitacion.DISPONIBLE).count()
    total_habitaciones = habitaciones_query.count()
    
    return {
        'clientes_dia': total_clientes,
        'ingreso_inicial_dia': total_ingreso_inicial,
        'horas_totales_dia': total_horas_rentadas,
        'ocupadas': ocupadas_count,
        'disponibles': disponibles_count,
        'total_habitaciones': total_habitaciones
    }

# --- Funciones para Corte de Caja ---

def get_corte_abierto(usuario_id, sucursal_id):
    """Obtiene el corte de caja abierto para un usuario y sucursal."""
    return CorteCaja.query.filter_by(
        usuario_id=usuario_id,
        sucursal_id=sucursal_id,
        estado='ABIERTO'
    ).first()

def calcular_totales_corte(corte):
    """Calcula los totales para un corte de caja."""
    rentas_turno = Renta.query.filter(
        Renta.sucursal_id == corte.sucursal_id,
        Renta.hora_entrada >= corte.fecha_apertura,
        Renta.estado == 'CERRADA'
    ).all()
    
    total_ventas = sum(r.pago_final for r in rentas_turno if r.pago_final)
    total_cancelaciones = sum(r.monto_devolucion for r in rentas_turno if r.monto_devolucion)
    
    return total_ventas, total_cancelaciones

# --- Aplicación Principal ---

def create_app():
    app = Flask(__name__)

    # Configuración
    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "12345678")
    MYSQL_DB = os.environ.get("MYSQL_DB", "motel_db")
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
    
    app.config["SQLALCHEMY_DATABASE_URI"] = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DB}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    app.secret_key = os.environ.get("SECRET_KEY", "una_clave_secreta_fuerte_y_unica_por_favor") 

    db.init_app(app)
    
    migrate = Migrate(app, db)


    # Configuración de Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

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
                
                # Verificar si tiene corte de caja abierto
                if user.sucursal_id and not user.es_admin_general():
                    corte_abierto = get_corte_abierto(user.id, user.sucursal_id)
                    if not corte_abierto and user.es_recepcionista():
                        flash('Debe abrir un corte de caja para comenzar su turno.', 'warning')
                        return redirect(url_for('abrir_corte'))
                
                flash(f'¡Bienvenido, {user.username}!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Usuario o contraseña incorrectos.', 'error')
                return render_template('login.html')

        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        if current_user.sucursal_id and current_user.es_recepcionista():
            corte_abierto = get_corte_abierto(current_user.id, current_user.sucursal_id)
            if corte_abierto:
                flash('Cierre su corte de caja antes de salir.', 'warning')
                return redirect(url_for('cerrar_corte'))
        
        logout_user()
        flash('Has cerrado sesión exitosamente.', 'info')
        return redirect(url_for('login'))

    # --- RUTA PRINCIPAL (DASHBOARD) ---
    @app.route('/')
    @app.route('/dashboard')
    @login_required
    def dashboard():
        check_auto_clean_complete(app) 
        
        resumen = get_daily_summary()
        
        # Obtener rentas activas filtradas por sucursal
        rentas_query = Renta.query.filter(Renta.estado == 'ACTIVA')
        rentas_query = filtrar_por_sucursal(rentas_query, Renta)
        rentas_activas = rentas_query.all()

        # Procesar datos para el dashboard
        data = []
        for renta in rentas_activas:
            tiempo_restante_delta = renta.hora_salida_estimada - datetime.now()
            es_hora_extra = tiempo_restante_delta.total_seconds() < 0
            tiempo_restante_str = ""
            horas_extra = 0
            
            if es_hora_extra:
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
        
        # Obtener distribución de habitaciones
        habitaciones_query = Habitacion.query
        habitaciones_query = filtrar_por_sucursal(habitaciones_query, Habitacion)
        
        distribucion = {
            'ocupadas': habitaciones_query.filter_by(estado=EstadoHabitacion.OCUPADA).count(),
            'disponibles': habitaciones_query.filter_by(estado=EstadoHabitacion.DISPONIBLE).count(),
            'limpieza': habitaciones_query.filter_by(estado=EstadoHabitacion.LIMPIEZA).count(),
            'mantenimiento': habitaciones_query.filter_by(estado=EstadoHabitacion.MANTENIMIENTO).count(),
            'total': habitaciones_query.count()
        }
        
        # Información de corte de caja para recepcionistas
        corte_info = None
        if current_user.sucursal_id and current_user.es_recepcionista():
            corte_abierto = get_corte_abierto(current_user.id, current_user.sucursal_id)
            if corte_abierto:
                total_ventas, total_cancelaciones = calcular_totales_corte(corte_abierto)
                corte_info = {
                    'abierto': True,
                    'monto_inicial': corte_abierto.monto_inicial,
                    'total_ventas': total_ventas,
                    'total_cancelaciones': total_cancelaciones
                }
            else:
                corte_info = {'abierto': False}
            
        return render_template('dashboard.html', 
                             ocupadas=data, 
                             resumen=resumen, 
                             distribucion=distribucion,
                             corte_info=corte_info,
                             EstadoHabitacion=EstadoHabitacion, 
                             TipoHabitacion=TipoHabitacion)

    # --- RUTA DE CHECK-IN MEJORADA ---
    @app.route('/checkin', methods=['GET', 'POST'])
    @login_required
    def checkin():
        if request.method == 'POST':
            try:
                # Horas predefinidas
                horas_opciones = {'4': 4, '6': 6, '12': 12}
                horas_seleccionadas = request.form.get('horas_reservadas')
                
                if horas_seleccionadas not in horas_opciones:
                    flash('Seleccione una opción válida de horas.', 'error')
                    return redirect(url_for('checkin'))
                
                hours = horas_opciones[horas_seleccionadas]
                room_id = request.form.get('habitacion_id', type=int)
                nombre_cliente = request.form.get('nombre_cliente')
                modo_ingreso_str = request.form.get('modo_ingreso') 
                placas = request.form.get('placas', '').upper()

                if not all([room_id, nombre_cliente, modo_ingreso_str]):
                    flash('Faltan datos obligatorios para el Check-in.', 'error')
                    return redirect(url_for('checkin'))

                habitacion = Habitacion.query.get(room_id)
                
                # Verificar permisos de sucursal
                if not habitacion or not current_user.puede_ver_sucursal(habitacion.sucursal_id):
                    flash('No tiene permisos para acceder a esta habitación.', 'error')
                    return redirect(url_for('checkin'))

                if habitacion.estado != EstadoHabitacion.DISPONIBLE:
                    flash('La habitación no está disponible.', 'error')
                    return redirect(url_for('checkin'))

                # Lógica de precio
                precio_hora = habitacion.get_precio_hora()
                pago_total = precio_hora * hours

                hora_entrada = datetime.now()
                hora_salida_estimada = hora_entrada + timedelta(hours=hours)
                
                modo_ingreso = ModoIngreso[modo_ingreso_str] 

                # Crear renta
                nueva_renta = Renta(
                    habitacion_id=room_id,
                    recepcionista_id=current_user.id,
                    sucursal_id=habitacion.sucursal_id,
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
            # GET - Mostrar formulario
            habitaciones_query = Habitacion.query.filter_by(estado=EstadoHabitacion.DISPONIBLE)
            habitaciones_query = filtrar_por_sucursal(habitaciones_query, Habitacion)
            habitaciones_disponibles = habitaciones_query.order_by(Habitacion.numero).all()
            
            return render_template('checkin.html',
                                    habitaciones=habitaciones_disponibles,
                                    ModoIngreso=ModoIngreso)

    # --- RUTA DE CHECK-OUT ---
    @app.route('/checkout/<int:renta_id>', methods=['POST'])
    @login_required
    def checkout(renta_id):
        renta = Renta.query.get(renta_id)
        
        # Verificar permisos de sucursal
        if not renta or not current_user.puede_ver_sucursal(renta.sucursal_id):
            flash('No tiene permisos para acceder a esta renta.', 'error')
            return redirect(url_for('dashboard'))

        if renta.estado != 'ACTIVA':
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

    # --- RUTAS NUEVAS (AGREGAR DESPUÉS DE LAS RUTAS EXISTENTES) ---

    @app.route('/checkout_completo', methods=['POST'])
    @login_required
    def checkout_completo():
        """Procesa el checklist de salida y finaliza la renta (NUEVA RUTA)"""
        try:
            renta_id = request.form.get('renta_id')
            renta = Renta.query.get_or_404(renta_id)
            
            # Verificar permisos de sucursal
            if not current_user.puede_ver_sucursal(renta.sucursal_id):
                return jsonify({'success': False, 'error': 'No tiene permisos para esta sucursal'})
            
            # Calcular tiempo extra si existe
            hora_salida_real = datetime.now()
            tiempo_extra_delta = hora_salida_real - renta.hora_salida_estimada
            horas_extra_a_pagar = 0.0
            pago_extra_tiempo = 0.0
            
            if tiempo_extra_delta.total_seconds() > 0:
                horas_extra_flotante = tiempo_extra_delta.total_seconds() / 3600
                horas_extra_a_pagar = math.ceil(horas_extra_flotante)
                pago_extra_tiempo = horas_extra_a_pagar * renta.precio_hora

            # CORRECCIÓN: Manejar campos vacíos en los cargos
            def safe_float(value, default=0.0):
                """Convierte seguro un string a float, manejando vacíos"""
                if not value or value == '':
                    return default
                try:
                    return float(value)
                except ValueError:
                    return default

            # Crear checklist de salida con valores seguros
            checklist = ChecklistSalida(
                renta_id=renta_id,
                usuario_id=current_user.id,
                limpieza_correcta=bool(request.form.get('limpieza_correcta')),
                danos_habitacion=bool(request.form.get('danos_habitacion')),
                muebles_danados=bool(request.form.get('muebles_danados')),
                equipo_danado=bool(request.form.get('equipo_danado')),
                objetos_olvidados=bool(request.form.get('objetos_olvidados')),
                cargo_danos=safe_float(request.form.get('cargo_danos')),
                cargo_limpieza=safe_float(request.form.get('cargo_limpieza')),
                otros_cargos=safe_float(request.form.get('otros_cargos')),
                observaciones_generales=request.form.get('observaciones_generales', ''),
                created_at=datetime.now()
            )
            
            # Calcular total de cargos adicionales
            total_cargos = checklist.cargo_danos + checklist.cargo_limpieza + checklist.otros_cargos
            
            # Actualizar renta
            renta.hora_salida_real = hora_salida_real
            renta.pago_extra = pago_extra_tiempo + total_cargos
            renta.pago_final = renta.pago_horas + renta.pago_extra
            renta.estado = 'CERRADA'
            
            # Liberar habitación (poner en estado LIMPIEZA)
            habitacion = Habitacion.query.get(renta.habitacion_id)
            habitacion.estado = EstadoHabitacion.LIMPIEZA
            
            # Actualizar registro de acceso
            registro_acceso = RegistroAcceso.query.filter_by(renta_id=renta.id).first()
            if registro_acceso:
                registro_acceso.hora_salida = hora_salida_real
            
            db.session.add(checklist)
            db.session.commit()
            
            # Mensaje informativo
            mensaje = f'Check-out completado para habitación {habitacion.numero}. '
            if pago_extra_tiempo > 0:
                mensaje += f'Tiempo extra: ${pago_extra_tiempo:.2f}. '
            if total_cargos > 0:
                mensaje += f'Cargos adicionales: ${total_cargos:.2f}. '
            mensaje += f'Total: ${renta.pago_final:.2f}'
            
            return jsonify({'success': True, 'message': mensaje})
            
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/cancelar_renta', methods=['POST'])
    @login_required
    def cancelar_renta():
        """Cancela una renta con devolución"""
        try:
            renta_id = request.form.get('renta_id')
            motivo = request.form.get('motivo_cancelacion')
            monto_devolucion = float(request.form.get('monto_devolucion', 0))
            
            renta = Renta.query.get_or_404(renta_id)
            
            # Verificar permisos de sucursal
            if not current_user.puede_ver_sucursal(renta.sucursal_id):
                flash('No tiene permisos para acceder a esta renta.', 'error')
                return redirect(url_for('dashboard'))
            
            # Validar que la renta esté activa
            if renta.estado != 'ACTIVA':
                flash('No se puede cancelar una renta que no está activa', 'error')
                return redirect(url_for('dashboard'))
            
            # Validar monto de devolución
            if monto_devolucion < 0 or monto_devolucion > renta.pago_horas:
                flash('El monto de devolución no es válido', 'error')
                return redirect(url_for('dashboard'))
            
            # Actualizar renta
            renta.estado = 'CANCELADA'
            renta.motivo_cancelacion = motivo
            renta.monto_devolucion = monto_devolucion
            renta.cancelada_por = current_user.id
            renta.hora_salida_real = datetime.now()
            renta.pago_final = renta.pago_horas - monto_devolucion
            
            # Liberar habitación (poner DISPONIBLE inmediatamente)
            habitacion = Habitacion.query.get(renta.habitacion_id)
            habitacion.estado = EstadoHabitacion.DISPONIBLE
            
            # Actualizar registro de acceso
            registro_acceso = RegistroAcceso.query.filter_by(renta_id=renta.id).first()
            if registro_acceso:
                registro_acceso.hora_salida = datetime.now()
            
            db.session.commit()
            
            flash(f'Renta cancelada para habitación {habitacion.numero}. Devolución: ${monto_devolucion:.2f}', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al cancelar renta: {str(e)}', 'error')
            return redirect(url_for('dashboard'))

    @app.route('/api/tiempo_restante/<int:renta_id>')
    @login_required
    def api_tiempo_restante(renta_id):
        """API para obtener tiempo restante en tiempo real"""
        try:
            renta = Renta.query.get_or_404(renta_id)
            
            # Verificar permisos de sucursal
            if not current_user.puede_ver_sucursal(renta.sucursal_id):
                return jsonify({'error': 'No tiene permisos'})
            
            ahora = datetime.now()
            salida_estimada = renta.hora_salida_estimada
            
            # Calcular tiempo restante
            if ahora > salida_estimada:
                # Tiempo extra
                tiempo_extra = ahora - salida_estimada
                horas_extra = tiempo_extra.total_seconds() / 3600
                horas = int(horas_extra)
                minutos = int((horas_extra * 60) % 60)
                return jsonify({
                    'tiempo_restante': f'+{horas}h {minutos}m',
                    'es_hora_extra': True,
                    'horas_extra': round(horas_extra, 2),
                    'color': 'red'
                })
            else:
                # Tiempo restante normal
                tiempo_restante = salida_estimada - ahora
                horas = int(tiempo_restante.total_seconds() // 3600)
                minutos = int((tiempo_restante.total_seconds() % 3600) // 60)
                return jsonify({
                    'tiempo_restante': f'{horas}h {minutos}m',
                    'es_hora_extra': False,
                    'horas_extra': 0,
                    'color': 'green'
                })
                
        except Exception as e:
            return jsonify({'error': str(e)})
    # --- RUTAS DE CORTE DE CAJA ---
    @app.route('/abrir_corte', methods=['GET', 'POST'])
    @login_required
    def abrir_corte():
        """Abrir un nuevo corte de caja."""
        if not current_user.es_recepcionista():
            flash('Solo los recepcionistas pueden abrir cortes de caja.', 'error')
            return redirect(url_for('dashboard'))
        
        if request.method == 'POST':
            try:
                monto_inicial = float(request.form.get('monto_inicial', 0))
                
                # Verificar que no tenga corte abierto
                corte_existente = get_corte_abierto(current_user.id, current_user.sucursal_id)
                if corte_existente:
                    flash('Ya tiene un corte de caja abierto.', 'error')
                    return redirect(url_for('dashboard'))
                
                nuevo_corte = CorteCaja(
                    usuario_id=current_user.id,
                    sucursal_id=current_user.sucursal_id,
                    turno=current_user.turno or TurnoTrabajo.MATUTINO.value,
                    monto_inicial=monto_inicial,
                    estado='ABIERTO'
                )
                
                db.session.add(nuevo_corte)
                db.session.commit()
                
                flash(f'Corte de caja abierto con monto inicial: ${monto_inicial:.2f}', 'success')
                return redirect(url_for('dashboard'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Error al abrir corte de caja: {str(e)}', 'error')
                return redirect(url_for('abrir_corte'))
        
        return render_template('abrir_corte.html')

    @app.route('/cerrar_corte', methods=['GET', 'POST'])
    @login_required
    def cerrar_corte():
        """Cerrar el corte de caja actual."""
        if not current_user.es_recepcionista():
            flash('Solo los recepcionistas pueden cerrar cortes de caja.', 'error')
            return redirect(url_for('dashboard'))
        
        corte = get_corte_abierto(current_user.id, current_user.sucursal_id)
        if not corte:
            flash('No tiene un corte de caja abierto.', 'error')
            return redirect(url_for('dashboard'))
        
        if request.method == 'POST':
            try:
                total_efectivo = float(request.form.get('total_efectivo', 0))
                total_tarjeta = float(request.form.get('total_tarjeta', 0))
                observaciones = request.form.get('observaciones', '')
                
                # Calcular totales
                total_ventas, total_cancelaciones = calcular_totales_corte(corte)
                monto_final = corte.monto_inicial + total_ventas - total_cancelaciones
                
                # Actualizar corte
                corte.fecha_cierre = datetime.now()
                corte.monto_final = monto_final
                corte.total_ventas = total_ventas
                corte.total_cancelaciones = total_cancelaciones
                corte.total_efectivo = total_efectivo
                corte.total_tarjeta = total_tarjeta
                corte.observaciones = observaciones
                corte.estado = 'CERRADO'
                
                db.session.commit()
                
                flash(f'Corte de caja cerrado. Monto final: ${monto_final:.2f}', 'success')
                return redirect(url_for('dashboard'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Error al cerrar corte de caja: {str(e)}', 'error')
                return redirect(url_for('cerrar_corte'))
        
        # Calcular datos para mostrar
        total_ventas, total_cancelaciones = calcular_totales_corte(corte)
        monto_teorico = corte.monto_inicial + total_ventas - total_cancelaciones
        
        return render_template('cerrar_corte.html', 
                             corte=corte,
                             total_ventas=total_ventas,
                             total_cancelaciones=total_cancelaciones,
                             monto_teorico=monto_teorico)

    # --- RUTAS ADICIONALES ---
    @app.route('/limpieza')
    @login_required
    def limpieza():
        """Página de limpieza de habitaciones"""
        habitaciones_query = Habitacion.query.filter_by(estado=EstadoHabitacion.LIMPIEZA)
        habitaciones_query = filtrar_por_sucursal(habitaciones_query, Habitacion)
        habitaciones_limpieza = habitaciones_query.order_by(Habitacion.numero).all()
        
        return render_template('limpieza.html', 
                                habitaciones=habitaciones_limpieza)

    @app.route('/clean_complete/<int:room_id>', methods=['POST'])
    @login_required
    def clean_complete(room_id):
        """Completar limpieza de habitación"""
        habitacion = Habitacion.query.get(room_id)
        
        # Verificar permisos de sucursal
        if not habitacion or not current_user.puede_ver_sucursal(habitacion.sucursal_id):
            flash('No tiene permisos para acceder a esta habitación.', 'error')
            return redirect(url_for('limpieza'))
        
        if habitacion.estado != EstadoHabitacion.LIMPIEZA:
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

    # --- RUTAS DE REPORTES ---
    @app.route('/reportes_rentas')
    @login_required
    def reportes_rentas():
        flash('Módulo de reportes en desarrollo', 'info')
        return redirect(url_for('dashboard'))

    # --- COMANDOS CLI ---
    @app.cli.command("init-db")
    def init_db_command():
        with app.app_context():
            db.create_all()
            load_initial_data(app)
            click.echo("Base de datos inicializada SIN sistema de reservas.")

    @app.cli.command("create-admin")
    @click.argument('username')
    @click.argument('password')
    def create_admin_command(username, password):
        """Crear un usuario administrador."""
        with app.app_context():
            if User.query.filter_by(username=username).first():
                click.echo(f"El usuario {username} ya existe.")
                return
            
            admin = User(
                username=username,
                email=f"{username}@motel.com",
                rol=RolUsuario.ADMIN_GENERAL.value
            )
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            click.echo(f"Administrador {username} creado exitosamente.")

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)