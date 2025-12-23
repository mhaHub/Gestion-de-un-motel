from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta, date
import bcrypt
import pymysql
from pymysql.cursors import DictCursor
import threading
import time
from functools import wraps

from models import User

app = Flask(__name__)
app.secret_key = "secret_key_123"

# ===================================================================
# MANEJADORES DE ERRORES
# ===================================================================

@app.errorhandler(403)
def forbidden(error):
    """Manejador para error 403 - Acceso denegado"""
    return render_template('error_403.html'), 403

@app.errorhandler(404)
def not_found(error):
    """Manejador para error 404 - Página no encontrada"""
    return render_template('error_404.html'), 404

@app.errorhandler(401)
def unauthorized(error):
    """Manejador para error 401 - No autorizado"""
    flash('Por favor inicia sesión para acceder a esta página', 'warning')
    return redirect(url_for('login'))

# ===================================================================
# FUNCIONES AUXILIARES DE SEGURIDAD
# ===================================================================

def check_template_access(template_name, user_role):
    """
    Verifica si un usuario tiene acceso a un template específico
    basado en su rol
    """
    # Diccionario de templates restringidos por rol
    restricted_templates = {
        # Solo administradores
        'dashboard.html': ['ADMIN_GENERAL', 'ADMIN_MOTEL'],
        'checkin_admin.html': ['ADMIN_GENERAL', 'ADMIN_MOTEL'],
        'reportes_general.html': ['ADMIN_GENERAL'],
        'reportes_sucursal.html': ['ADMIN_MOTEL'],
        'registro_usuario.html': ['ADMIN_GENERAL', 'ADMIN_MOTEL'],
        
        # Solo recepcionistas
        'dashboard_recepcionista.html': ['RECEPCIONISTA'],
        'checkin_recepcionista.html': ['RECEPCIONISTA'],
        'reportes_recepcion.html': ['RECEPCIONISTA'],
        'limpieza.html': ['RECEPCIONISTA'],
    }
    
    if template_name in restricted_templates:
        return user_role in restricted_templates[template_name]
    return True  # Templates sin restricción

def safe_render_template(template_name, **kwargs):
    """Renderiza un template solo si el usuario tiene acceso"""
    if not check_template_access(template_name, current_user.rol):
        abort(403)
    return render_template(template_name, **kwargs)

# ===================================================================
# DECORADORES DE SEGURIDAD - MEJORADOS
# ===================================================================

def admin_required(f):
    """Decorador que requiere que el usuario sea admin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Por favor inicia sesión para acceder a esta página', 'warning')
            session['next_url'] = request.url
            return redirect(url_for('login'))
        
        if current_user.rol not in ['ADMIN_GENERAL', 'ADMIN_MOTEL']:
            # BLOQUEAR ACCESO con 403
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function

def recepcionista_required(f):
    """Decorador que requiere que el usuario sea recepcionista"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Por favor inicia sesión para acceder a esta página', 'warning')
            session['next_url'] = request.url
            return redirect(url_for('login'))
        
        if current_user.rol != 'RECEPCIONISTA':
            # BLOQUEAR ACCESO con 403
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function

def admin_general_required(f):
    """Decorador que requiere que el usuario sea ADMIN_GENERAL"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Por favor inicia sesión para acceder a esta página', 'warning')
            session['next_url'] = request.url
            return redirect(url_for('login'))
        
        if current_user.rol != 'ADMIN_GENERAL':
            # BLOQUEAR ACCESO con 403
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function

def admin_motel_required(f):
    """Decorador que requiere que el usuario sea ADMIN_MOTEL"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Por favor inicia sesión para acceder a esta página', 'warning')
            session['next_url'] = request.url
            return redirect(url_for('login'))
        
        if current_user.rol != 'ADMIN_MOTEL':
            # BLOQUEAR ACCESO con 403
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function

def role_required(*allowed_roles):
    """Decorador genérico para roles específicos"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Por favor inicia sesión para acceder a esta página', 'warning')
                session['next_url'] = request.url
                return redirect(url_for('login'))
            
            if current_user.rol not in allowed_roles:
                # BLOQUEAR ACCESO con 403
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ===================================================================
# CONFIGURACIÓN DE LA APLICACIÓN
# ===================================================================

# --- CONEXIÓN A BASE DE DATOS ---
def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='12345678',
        db='hotel',
        charset='utf8mb4',
        cursorclass=DictCursor,
        autocommit=False
    )

# --- FUNCIÓN PARA GENERAR HASH CON BCRYPT ---
def generate_bcrypt_hash(password):
    """Genera hash bcrypt para contraseñas"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

# --- FUNCIÓN PARA VERIFICAR CON BCRYPT ---
def check_bcrypt_password(password_hash, password_input):
    """Verifica contraseña con bcrypt"""
    try:
        return bcrypt.checkpw(password_input.encode('utf-8'), password_hash.encode('utf-8'))
    except:
        return False


login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            data = cursor.fetchone()
            return User(data) if data else None
    finally: 
        conn.close()

# --- LÓGICA DE LIMPIEZA AUTOMÁTICA ---
def proceso_limpieza_mejorado(habitacion_id, notificar=True):
    """Función mejorada de limpieza automática - 5 minutos"""
    print(f"INICIANDO PROCESO DE LIMPIEZA para habitación ID: {habitacion_id}")
    
    # Esperar 5 minutos (300 segundos) - para pruebas usa 10 segundos
    tiempo_espera = 300  # 5 minutos en producción
    # tiempo_espera = 10  # Para pruebas
    
    # Dividir la espera para permitir actualizaciones intermedias
    for i in range(tiempo_espera // 5):
        time.sleep(5)
        # Aquí podrías notificar el progreso si quisieras una barra de progreso
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Verificar estado actual
            cursor.execute("SELECT numero, estado, sucursal_id FROM habitaciones WHERE id = %s", (habitacion_id,))
            hab = cursor.fetchone()
            
            if hab and hab['estado'] == 'LIMPIEZA':
                cursor.execute("UPDATE habitaciones SET estado='DISPONIBLE' WHERE id=%s", (habitacion_id,))
                conn.commit()
                print(f"LIMPIEZA COMPLETADA: Habitación {hab['numero']} ahora DISPONIBLE")
                
                # Registrar en log de limpiezas
                cursor.execute("""
                    INSERT INTO log_limpiezas 
                    (habitacion_id, sucursal_id, inicio_limpieza, fin_limpieza, estado)
                    VALUES (%s, %s, DATE_SUB(NOW(), INTERVAL %s SECOND), NOW(), 'COMPLETADA')
                """, (habitacion_id, hab['sucursal_id'], tiempo_espera))
                conn.commit()
                
                return True
            else:
                estado_actual = hab['estado'] if hab else 'N/A'
                print(f"Habitación ya no está en limpieza. Estado: {estado_actual}")
                return False
                
    except Exception as e:
        print(f"Error en proceso de limpieza: {e}")
        return False
    finally:
        conn.close()

# --- FUNCIONES DE APOYO ---
def get_daily_summary_por_sucursal(user):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            today = date.today()
            
            # **CLIENTES DEL DÍA - DIFERENCIADO POR ROL**
            if user.rol == 'ADMIN_GENERAL':
                # Admin General: ve todo
                q_res = "SELECT COUNT(*) as c, SUM(pago_inicial) as s FROM rentas WHERE DATE(hora_entrada) = %s"
                p_res = (today,)
            elif user.rol == 'ADMIN_MOTEL':
                # Admin Motel: solo su sucursal
                q_res = "SELECT COUNT(*) as c, SUM(pago_inicial) as s FROM rentas WHERE DATE(hora_entrada) = %s AND sucursal_id = %s"
                p_res = (today, user.sucursal_id)
            else:  # RECEPCIONISTA
                # Recepcionista: solo sus rentas
                q_res = "SELECT COUNT(*) as c, SUM(pago_inicial) as s FROM rentas WHERE DATE(hora_entrada) = %s AND recepcionista_id = %s"
                p_res = (today, user.id)
            
            cursor.execute(q_res, p_res)
            res = cursor.fetchone()
            
            # **HABITACIONES - DIFERENCIADO POR ROL**
            if user.rol == 'ADMIN_GENERAL':
                q_hab = "SELECT estado, COUNT(*) as count FROM habitaciones GROUP BY estado"
                p_hab = ()
            else:
                q_hab = "SELECT estado, COUNT(*) as count FROM habitaciones WHERE sucursal_id = %s GROUP BY estado"
                p_hab = (user.sucursal_id,)

            cursor.execute(q_hab, p_hab)
            habs = {row['estado']: row['count'] for row in cursor.fetchall()}

            return {
                'clientes_dia': res['c'] or 0,
                'ingreso_inicial_dia': float(res['s'] or 0),
                'ocupadas': habs.get('OCUPADA', 0),
                'disponibles': habs.get('DISPONIBLE', 0),
                'limpieza': habs.get('LIMPIEZA', 0),
                'total_habitaciones': sum(habs.values()) if habs else 0
            }
    finally: 
        conn.close()

# ===================================================================
# MIDDLEWARE DE SEGURIDAD GLOBAL
# ===================================================================

@app.before_request
def check_authorization():
    """Verificación global de autorización antes de cada request"""
    # Lista de rutas que requieren autenticación
    protected_paths = [
        '/dashboard', '/dashboard/', '/dashboard/admin', '/dashboard/recepcionista',
        '/checkin', '/checkin/', '/checkin/admin', '/checkin/recepcionista',
        '/reportes', '/reportes/', '/reportes/general', '/reportes/sucursal', 
        '/reportes/recepcion', '/menu_reportes', '/limpieza', '/registro_usuario',
        '/checkout_completo', '/api/estado_habitaciones', '/auditoria/rentas',
        '/reportes/rentas'
    ]
    
    # Verificar si la ruta actual está protegida
    if any(request.path.startswith(path) for path in protected_paths):
        if not current_user.is_authenticated:
            # Guardar la ruta a la que intentaba acceder
            session['next_url'] = request.url
            flash('Por favor inicia sesión para acceder a esta página', 'warning')
            return redirect(url_for('login'))

# Diccionario para seguimiento de intentos de login (protección básica)
login_attempts = {}

@app.before_request
def check_brute_force():
    """Protección básica contra fuerza bruta"""
    if request.endpoint == 'login' and request.method == 'POST':
        ip = request.remote_addr
        if ip in login_attempts:
            login_attempts[ip]['count'] += 1
            login_attempts[ip]['last_attempt'] = datetime.now()
            
            # Bloquear después de 5 intentos fallidos en 15 minutos
            if login_attempts[ip]['count'] > 5:
                time_diff = datetime.now() - login_attempts[ip]['first_attempt']
                if time_diff.seconds < 900:  # 15 minutos
                    flash('Demasiados intentos fallidos. Intenta más tarde.', 'error')
                    return redirect(url_for('login'))
        else:
            login_attempts[ip] = {
                'count': 1,
                'first_attempt': datetime.now(),
                'last_attempt': datetime.now()
            }

# ===================================================================
# RUTAS DE AUTENTICACIÓN
# ===================================================================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # Si ya está autenticado, redirigir según su rol
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        print(f"\nINTENTO DE LOGIN")
        print(f"   Usuario: {username}")
        print(f"   Contraseña ingresada: {password}")
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user_data = cursor.fetchone()
                
                if user_data:
                    print(f"Usuario encontrado en BD")
                    print(f"   ID: {user_data['id']}")
                    print(f"   Rol: {user_data['rol']}")
                    print(f"   Hash en BD (primeros 30 chars): {user_data['password_hash'][:30]}...")
                    print(f"   Longitud hash: {len(user_data['password_hash'])}")
                    
                    # Crear objeto User
                    user_obj = User(user_data)
                    
                    # Probar la verificación manualmente
                    print(f"\nProbando verificación manual...")
                    try:
                        # Convertir a bytes
                        stored_hash = user_data['password_hash'].encode('utf-8')
                        password_bytes = password.encode('utf-8')
                        
                        # Verificar con bcrypt directamente
                        import bcrypt
                        result = bcrypt.checkpw(password_bytes, stored_hash)
                        print(f"   Resultado directo bcrypt.checkpw: {result}")
                        
                        # Probar con el método del User
                        user_result = user_obj.check_password(password)
                        print(f"   Resultado user.check_password: {user_result}")
                        
                        if result or user_result:
                            login_user(user_obj)
                            print("LOGIN EXITOSO!")
                            flash('¡Inicio de sesión exitoso!', 'success')
                            
                            # Redirigir a la página que intentaba acceder o al dashboard
                            next_page = session.pop('next_url', None)
                            if next_page:
                                return redirect(next_page)
                            return redirect(url_for('dashboard'))
                        else:
                            print("Ambas verificaciones fallaron")
                            flash('Usuario o contraseña incorrectos', 'error')
                    except Exception as e:
                        print(f"Error en verificación: {e}")
                        flash('Error en el sistema de autenticación', 'error')
                else:
                    print("Usuario NO encontrado en BD")
                    flash('Usuario o contraseña incorrectos', 'error')
                    
        except Exception as e:
            print(f"Error de BD: {e}")
            flash('Error en el servidor', 'error')
        finally:
            conn.close()
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    flash('Sesión cerrada exitosamente', 'info')
    return redirect(url_for('login'))

# ===================================================================
# RUTAS PROTEGIDAS DEL SISTEMA
# ===================================================================

# --- RUTA PARA OBTENER DATOS DE GRÁFICA ---
@app.route('/api/estado_habitaciones')
@login_required
@role_required('ADMIN_GENERAL', 'ADMIN_MOTEL', 'RECEPCIONISTA')
def api_estado_habitaciones():
    """API para obtener datos de estado de habitaciones EN TIEMPO REAL"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Obtener conteo por estado según el rol
            if current_user.rol == 'ADMIN_GENERAL':
                sql = "SELECT estado, COUNT(*) as count FROM habitaciones GROUP BY estado"
                cursor.execute(sql)
            else:
                sql = "SELECT estado, COUNT(*) as count FROM habitaciones WHERE sucursal_id = %s GROUP BY estado"
                cursor.execute(sql, (current_user.sucursal_id,))
            
            resultados = cursor.fetchall()
            
            # Inicializar contadores
            estados = {
                'DISPONIBLE': 0,
                'OCUPADA': 0,
                'LIMPIEZA': 0
            }
            
            # Llenar con datos reales
            for row in resultados:
                estado = row['estado']
                if estado in estados:
                    estados[estado] = row['count']
            
            # Calcular total
            total = sum(estados.values())
            
            return jsonify({
                'ocupadas': estados['OCUPADA'],
                'disponibles': estados['DISPONIBLE'],
                'limpieza': estados['LIMPIEZA'],
                'total': total,
                'timestamp': datetime.now().isoformat()
            })
    finally:
        conn.close()

# --- DASHBOARD ---
@app.route('/dashboard')
@login_required
def dashboard():
    """Dashboard principal - redirige según rol"""
    if current_user.rol == 'RECEPCIONISTA':
        return redirect(url_for('dashboard_recepcionista'))
    elif current_user.rol in ['ADMIN_MOTEL', 'ADMIN_GENERAL']:
        return redirect(url_for('dashboard_admin'))
    else:
        abort(403)  # Rol no reconocido

@app.route('/dashboard/admin')
@login_required
@admin_required
def dashboard_admin():
    """Dashboard para administradores"""
    # Verificación doble de seguridad
    if current_user.rol not in ['ADMIN_GENERAL', 'ADMIN_MOTEL']:
        abort(403)
    
    resumen_data = get_daily_summary_por_sucursal(current_user)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # QUERY BASE MEJORADA
            sql = """
                SELECT r.id, r.cliente_nombre as cliente, r.hora_entrada as entrada, 
                       r.hora_salida_estimada as salida_estimada, h.numero, h.tipo,
                       r.sucursal_id, u.username as recepcionista, r.turno_renta as turno,
                       r.recepcionista_id
                FROM rentas r 
                JOIN habitaciones h ON r.habitacion_id = h.id 
                JOIN users u ON r.recepcionista_id = u.id
                WHERE r.estado = 'ACTIVA'
            """
            
            params = []
            
            # **FILTROS JERÁRQUICOS**
            if current_user.rol == 'ADMIN_MOTEL':
                # Admin de sucursal solo ve rentas de SU sucursal
                sql += " AND r.sucursal_id = %s"
                params.append(current_user.sucursal_id)
            
            # Ordenar para mejor visualización
            sql += " ORDER BY r.hora_entrada DESC"
            
            cursor.execute(sql, tuple(params) if params else ())
            rentas = cursor.fetchall()
            
            # Calcular tiempo restante
            ahora = datetime.now()
            for renta in rentas:
                if isinstance(renta['salida_estimada'], str):
                    try:
                        renta['salida_estimada'] = datetime.strptime(renta['salida_estimada'], '%Y-%m-%d %H:%M:%S')
                    except:
                        renta['salida_estimada'] = ahora
                
                if renta['salida_estimada'] > ahora:
                    diferencia = renta['salida_estimada'] - ahora
                    renta['horas_restantes'] = round(diferencia.total_seconds() / 3600, 2)
                else:
                    renta['horas_restantes'] = 0
            
            return safe_render_template('dashboard.html', ocupadas=rentas, resumen=resumen_data)
    finally: 
        conn.close()

@app.route('/dashboard/recepcionista')
@login_required
@recepcionista_required
def dashboard_recepcionista():
    """Dashboard para recepcionistas"""
    # Verificación doble de seguridad
    if current_user.rol != 'RECEPCIONISTA':
        abort(403)
    
    resumen_data = get_daily_summary_por_sucursal(current_user)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # FILTRAR SOLO LAS RENTAS DE ESTE RECEPCIONISTA EN SU TURNO ACTUAL
            sql = """
                SELECT r.id, r.cliente_nombre as cliente, r.hora_entrada as entrada, 
                       r.hora_salida_estimada as salida_estimada, h.numero, h.tipo
                FROM rentas r 
                JOIN habitaciones h ON r.habitacion_id = h.id 
                WHERE r.estado = 'ACTIVA'
                AND r.recepcionista_id = %s
                AND r.sucursal_id = %s
                ORDER BY r.hora_entrada DESC
            """
            cursor.execute(sql, (current_user.id, current_user.sucursal_id))
            rentas = cursor.fetchall()
            
            # Calcular tiempo restante
            ahora = datetime.now()
            for renta in rentas:
                if isinstance(renta['salida_estimada'], str):
                    try:
                        renta['salida_estimada'] = datetime.strptime(renta['salida_estimada'], '%Y-%m-%d %H:%M:%S')
                    except:
                        renta['salida_estimada'] = ahora
                
                if renta['salida_estimada'] > ahora:
                    diferencia = renta['salida_estimada'] - ahora
                    renta['horas_restantes'] = round(diferencia.total_seconds() / 3600, 2)
                else:
                    renta['horas_restantes'] = 0
            
            return safe_render_template('dashboard_recepcionista.html', ocupadas=rentas, resumen=resumen_data)
    finally: 
        conn.close()

# --- CHECKIN (PARA TODOS) ---
@app.route('/checkin', methods=['GET', 'POST'])
@login_required
def checkin():
    """Ruta principal de checkin - redirige según rol"""
    if current_user.rol == 'RECEPCIONISTA':
        return redirect(url_for('checkin_recepcionista'))
    else:
        return redirect(url_for('checkin_admin'))

# --- CHECKIN PARA ADMINISTRADORES ---
@app.route('/checkin/admin', methods=['GET', 'POST'])
@login_required
@admin_required
def checkin_admin():
    """Ruta de checkin exclusiva para administradores"""
    # Verificación doble de seguridad
    if current_user.rol not in ['ADMIN_GENERAL', 'ADMIN_MOTEL']:
        abort(403)
    
    conn = get_db_connection()
    
    if request.method == 'POST':
        try:
            habitacion_id = request.form.get('habitacion_id')
            horas_reservadas = request.form.get('horas_reservadas')
            nombre_cliente = request.form.get('nombre_cliente')
            modo_ingreso = request.form.get('modo_ingreso', 'VEHICULO')
            placas = request.form.get('placas', '')
            recepcionista_id = request.form.get('recepcionista_id', current_user.id)
            turno_renta = request.form.get('turno_renta', current_user.turno)
            
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, numero, precio_base, sucursal_id FROM habitaciones WHERE id = %s", (habitacion_id,))
                habitacion = cursor.fetchone()
                
                if not habitacion:
                    flash('Habitación no encontrada', 'error')
                    return redirect(url_for('checkin_admin'))
                
                precio_base = float(habitacion['precio_base'])
                horas = int(horas_reservadas)
                total = precio_base * (horas / 4)
                sucursal_id = habitacion['sucursal_id']
                
                # Insertar renta
                cursor.execute("""
                    INSERT INTO rentas (
                        habitacion_id, sucursal_id, recepcionista_id, cliente_nombre, 
                        hora_entrada, hora_salida_estimada, horas_pactadas, 
                        pago_inicial, estado, turno_renta
                    ) VALUES (%s, %s, %s, %s, NOW(), DATE_ADD(NOW(), INTERVAL %s HOUR), 
                    %s, %s, 'ACTIVA', %s)
                """, (habitacion_id, sucursal_id, recepcionista_id, nombre_cliente, 
                      horas, horas, total, turno_renta))
                
                renta_id = cursor.lastrowid
                
                # Insertar registro de acceso
                cursor.execute("""
                    INSERT INTO registros_acceso (
                        renta_id, modo_ingreso, placas, hora_ingreso
                    ) VALUES (%s, %s, %s, NOW())
                """, (renta_id, modo_ingreso, placas if placas else None))
                
                # Actualizar habitación
                cursor.execute("UPDATE habitaciones SET estado = 'OCUPADA' WHERE id = %s", (habitacion_id,))
                
                conn.commit()
                flash(f'Check-in exitoso! Habitación {habitacion["numero"]} ocupada. Total: ${total:.2f}', 'success')
                return redirect(url_for('dashboard_admin'))
                
        except Exception as e:
            conn.rollback()
            flash(f'Error en check-in: {str(e)}', 'error')
    
    # GET: Mostrar formulario para admin
    with conn.cursor() as cursor:
        if current_user.rol == 'ADMIN_GENERAL':
            cursor.execute("""
                SELECT h.*, s.nombre as sucursal_nombre 
                FROM habitaciones h 
                JOIN sucursales s ON h.sucursal_id = s.id 
                WHERE h.estado = 'DISPONIBLE' 
                ORDER BY h.sucursal_id, h.numero
            """)
        else:
            cursor.execute("""
                SELECT * FROM habitaciones 
                WHERE estado = 'DISPONIBLE' 
                AND sucursal_id = %s 
                ORDER BY numero
            """, (current_user.sucursal_id,))
        habitaciones = cursor.fetchall()
        
        # Obtener recepcionistas según el tipo de admin
        if current_user.rol == 'ADMIN_GENERAL':
            cursor.execute("""
                SELECT id, username, turno, sucursal_id 
                FROM users 
                WHERE rol = 'RECEPCIONISTA' 
                ORDER BY sucursal_id, username
            """)
        else:
            cursor.execute("""
                SELECT id, username, turno 
                FROM users 
                WHERE rol = 'RECEPCIONISTA' 
                AND sucursal_id = %s 
                ORDER BY username
            """, (current_user.sucursal_id,))
        recepcionistas = cursor.fetchall()
    
    class ModoIngreso:
        VEHICULO = "Vehículo"
        A_PIE = "A Pie"
        API_CAMARA = "Cámara API"
    
    return safe_render_template('checkin_admin.html', 
                         habitaciones=habitaciones,
                         recepcionistas=recepcionistas,
                         ModoIngreso=ModoIngreso,
                         current_user=current_user)

# --- CHECKIN PARA RECEPCIONISTAS ---
@app.route('/checkin/recepcionista', methods=['GET', 'POST'])
@login_required
@recepcionista_required
def checkin_recepcionista():
    """Ruta de checkin exclusiva para recepcionistas"""
    # Verificación doble de seguridad
    if current_user.rol != 'RECEPCIONISTA':
        abort(403)
    
    conn = get_db_connection()
    
    if request.method == 'POST':
        try:
            habitacion_id = request.form.get('habitacion_id')
            horas_reservadas = request.form.get('horas_reservadas')
            nombre_cliente = request.form.get('nombre_cliente')
            modo_ingreso = request.form.get('modo_ingreso', 'VEHICULO')
            placas = request.form.get('placas', '')
            
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, numero, precio_base, sucursal_id 
                    FROM habitaciones 
                    WHERE id = %s AND sucursal_id = %s
                """, (habitacion_id, current_user.sucursal_id))
                habitacion = cursor.fetchone()
                
                if not habitacion:
                    flash('Habitación no encontrada o no pertenece a tu sucursal', 'error')
                    return redirect(url_for('checkin_recepcionista'))
                
                precio_base = float(habitacion['precio_base'])
                horas = int(horas_reservadas)
                total = precio_base * (horas / 4)
                
                # Insertar renta
                cursor.execute("""
                    INSERT INTO rentas (
                        habitacion_id, sucursal_id, recepcionista_id, cliente_nombre, 
                        hora_entrada, hora_salida_estimada, horas_pactadas, 
                        pago_inicial, estado, turno_renta
                    ) VALUES (%s, %s, %s, %s, NOW(), DATE_ADD(NOW(), INTERVAL %s HOUR), 
                    %s, %s, 'ACTIVA', %s)
                """, (habitacion_id, current_user.sucursal_id, current_user.id, 
                      nombre_cliente, horas, horas, total, current_user.turno))
                
                renta_id = cursor.lastrowid
                
                # Insertar registro de acceso
                cursor.execute("""
                    INSERT INTO registros_acceso (
                        renta_id, modo_ingreso, placas, hora_ingreso
                    ) VALUES (%s, %s, %s, NOW())
                """, (renta_id, modo_ingreso, placas if placas else None))
                
                # Actualizar habitación
                cursor.execute("UPDATE habitaciones SET estado = 'OCUPADA' WHERE id = %s", (habitacion_id,))
                
                conn.commit()
                flash(f'Check-in exitoso! Habitación {habitacion["numero"]} ocupada. Total: ${total:.2f}', 'success')
                return redirect(url_for('dashboard_recepcionista'))
                
        except Exception as e:
            conn.rollback()
            flash(f'Error en check-in: {str(e)}', 'error')
    
    # GET: Mostrar formulario para recepcionista
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM habitaciones 
            WHERE estado = 'DISPONIBLE' 
            AND sucursal_id = %s 
            ORDER BY numero
        """, (current_user.sucursal_id,))
        habitaciones = cursor.fetchall()
    
    class ModoIngreso:
        VEHICULO = "Vehículo"
        A_PIE = "A Pie"
        API_CAMARA = "Cámara API"
    
    return safe_render_template('checkin_recepcionista.html', 
                         habitaciones=habitaciones,
                         ModoIngreso=ModoIngreso,
                         current_user=current_user)

# ===================================================================
# SISTEMA DE REPORTES - CORREGIDO
# ===================================================================

@app.route('/menu_reportes')
@login_required
def menu_reportes():
    """Redirige al usuario al tipo de reporte según su rol"""
    if current_user.rol == 'ADMIN_GENERAL':
        return redirect(url_for('reportes_general'))
    elif current_user.rol == 'ADMIN_MOTEL':
        return redirect(url_for('reportes_sucursal'))
    else:
        return redirect(url_for('reportes_recepcion'))

@app.route('/reportes/general')
@login_required
@admin_general_required
def reportes_general():
    """Reportes solo para ADMIN_GENERAL con filtros"""
    # Obtener parámetros de filtro
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    sucursal_id = request.args.get('sucursal_id', type=int)
    
    # Establecer fechas por defecto (últimos 30 días)
    if not fecha_inicio:
        fecha_inicio = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')
    if not fecha_fin:
        fecha_fin = date.today().strftime('%Y-%m-%d')
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Obtener todas las sucursales para el dropdown
            cursor.execute("SELECT id, nombre FROM sucursales ORDER BY nombre")
            todas_sucursales = cursor.fetchall()
            
            # Construir condiciones WHERE dinámicas
            condiciones = []
            parametros = []
            
            if fecha_inicio:
                condiciones.append("DATE(r.hora_entrada) >= %s")
                parametros.append(fecha_inicio)
            
            if fecha_fin:
                condiciones.append("DATE(r.hora_entrada) <= %s")
                parametros.append(fecha_fin)
            
            if sucursal_id and sucursal_id > 0:
                condiciones.append("r.sucursal_id = %s")
                parametros.append(sucursal_id)
            
            where_clause = "WHERE " + " AND ".join(condiciones) if condiciones else ""
            
            # 1. REPORTE DE SUCURSALES (CORREGIDO)
            sql_sucursales = f"""
                SELECT 
                    s.id,
                    s.nombre,
                    COUNT(r.id) as total_rentas,
                    COALESCE(SUM(r.pago_inicial), 0) as total,
                    COALESCE(AVG(r.pago_inicial), 0) as promedio_renta,
                    (SELECT COUNT(*) FROM habitaciones h WHERE h.sucursal_id = s.id AND h.estado = 'OCUPADA') as ocupadas,
                    (SELECT COUNT(*) FROM habitaciones h WHERE h.sucursal_id = s.id AND h.estado = 'DISPONIBLE') as disponibles,
                    (SELECT COUNT(*) FROM habitaciones h WHERE h.sucursal_id = s.id AND h.estado = 'LIMPIEZA') as limpieza
                FROM sucursales s
                LEFT JOIN rentas r ON s.id = r.sucursal_id {where_clause}
                GROUP BY s.id
                ORDER BY total DESC
            """
            cursor.execute(sql_sucursales, parametros)
            sucursales = cursor.fetchall()
            
            # Calcular totales
            total_rentas = sum(s.get('total_rentas', 0) or 0 for s in sucursales)
            total_ingresos = sum(float(s.get('total', 0) or 0) for s in sucursales)
            promedio_global = total_ingresos / total_rentas if total_rentas > 0 else 0
            total_ocupadas = sum(s.get('ocupadas', 0) or 0 for s in sucursales)
            total_disponibles = sum(s.get('disponibles', 0) or 0 for s in sucursales)
            total_limpieza = sum(s.get('limpieza', 0) or 0 for s in sucursales)
            
            # 2. REPORTE FINANCIERO
            sql_finanzas = f"""
                SELECT 
                    COALESCE(SUM(pago_inicial), 0) as total,
                    COUNT(*) as total_rentas,
                    COALESCE(AVG(pago_inicial), 0) as promedio_renta,
                    COUNT(DISTINCT DATE(hora_entrada)) as dias_analizados
                FROM rentas r
                {where_clause}
            """
            cursor.execute(sql_finanzas, parametros)
            finanzas = cursor.fetchone()
            
            # 3. REPORTE DE HABITACIONES
            sql_habitaciones = f"""
                SELECT 
                    h.tipo, 
                    COUNT(r.id) as veces_rentada, 
                    COALESCE(SUM(r.horas_pactadas), 0) as horas_totales,
                    COALESCE(SUM(r.pago_inicial), 0) as generado
                FROM habitaciones h
                LEFT JOIN rentas r ON h.id = r.habitacion_id 
                    AND DATE(r.hora_entrada) >= %s 
                    AND DATE(r.hora_entrada) <= %s
                """
            
            # Agregar filtro de sucursal si aplica
            if sucursal_id and sucursal_id > 0:
                sql_habitaciones += " WHERE h.sucursal_id = %s"
                cursor.execute(sql_habitaciones, (fecha_inicio, fecha_fin, sucursal_id))
            else:
                sql_habitaciones += " GROUP BY h.tipo ORDER BY veces_rentada DESC"
                cursor.execute(sql_habitaciones, (fecha_inicio, fecha_fin))
            
            habitaciones = cursor.fetchall()
            
            return render_template('reportes_general.html',
                                 sucursales=sucursales,
                                 todas_sucursales=todas_sucursales,
                                 sucursales_con_finanzas=sucursales,
                                 finanzas=finanzas,
                                 habitaciones=habitaciones,
                                 fecha_actual=date.today().strftime('%d/%m/%Y'),
                                 fecha_inicio_default=fecha_inicio,
                                 fecha_fin_default=fecha_fin,
                                 total_rentas=total_rentas,
                                 total_ingresos=total_ingresos,
                                 promedio_global=promedio_global,
                                 total_habitaciones_activas=total_ocupadas,
                                 total_ocupadas=total_ocupadas,
                                 total_disponibles=total_disponibles,
                                 total_limpieza=total_limpieza)
    finally: 
        conn.close()

@app.route('/reportes/sucursal')
@login_required
@admin_motel_required
def reportes_sucursal():
    """Reportes solo para ADMIN_MOTEL"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Estadísticas básicas
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_rentas,
                    SUM(pago_inicial) as total_ingresos,
                    AVG(horas_pactadas) as promedio_horas
                FROM rentas 
                WHERE sucursal_id = %s
            """, (current_user.sucursal_id,))
            stats = cursor.fetchone()
            
            # Rentas por tipo de habitación
            cursor.execute("""
                SELECT h.tipo, COUNT(r.id) as cantidad, 
                       SUM(r.pago_inicial) as ingresos
                FROM rentas r 
                JOIN habitaciones h ON r.habitacion_id = h.id 
                WHERE r.sucursal_id = %s
                GROUP BY h.tipo
            """, (current_user.sucursal_id,))
            tipo_stats = cursor.fetchall()
            
        return safe_render_template('reportes_sucursal.html', 
                             stats=stats, 
                             tipo_stats=tipo_stats)
    finally:
        conn.close()

@app.route('/reportes/recepcion')
@login_required
@recepcionista_required
def reportes_recepcion():
    """Reportes solo para RECEPCIONISTA"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Rentas del recepcionista en el día actual
            sql = """
                SELECT r.id, h.numero, h.tipo, r.pago_inicial, 
                       r.horas_pactadas, r.hora_entrada, r.cliente_nombre
                FROM rentas r 
                JOIN habitaciones h ON r.habitacion_id = h.id 
                WHERE r.recepcionista_id = %s 
                AND DATE(r.hora_entrada) = CURDATE()
                ORDER BY r.hora_entrada DESC
            """
            cursor.execute(sql, (current_user.id,))
            rentas = cursor.fetchall()

            # Estadísticas por tarifa
            resumen_tarifas = {
                '4_horas': {'cantidad': 0, 'total': 0},
                '6_horas': {'cantidad': 0, 'total': 0},
                '8_horas': {'cantidad': 0, 'total': 0},
                '12_horas': {'cantidad': 0, 'total': 0}
            }

            total_general = 0
            for r in rentas:
                total_general += float(r['pago_inicial'])
                horas = r['horas_pactadas']
                
                if horas <= 4:
                    resumen_tarifas['4_horas']['cantidad'] += 1
                    resumen_tarifas['4_horas']['total'] += float(r['pago_inicial'])
                elif horas <= 6:
                    resumen_tarifas['6_horas']['cantidad'] += 1
                    resumen_tarifas['6_horas']['total'] += float(r['pago_inicial'])
                elif horas <= 8:
                    resumen_tarifas['8_horas']['cantidad'] += 1
                    resumen_tarifas['8_horas']['total'] += float(r['pago_inicial'])
                else:
                    resumen_tarifas['12_horas']['cantidad'] += 1
                    resumen_tarifas['12_horas']['total'] += float(r['pago_inicial'])

            return safe_render_template('reportes_recepcion.html', 
                                 rentas=rentas, 
                                 resumen=resumen_tarifas, 
                                 total=total_general,
                                 fecha=date.today())
    finally:
        conn.close()

# Ruta genérica de reportes (para redirección)
@app.route('/reportes')
@login_required
def reportes():
    """Ruta genérica de reportes - redirige según rol"""
    if current_user.rol == 'ADMIN_GENERAL':
        return redirect(url_for('reportes_general'))
    elif current_user.rol == 'ADMIN_MOTEL':
        return redirect(url_for('reportes_sucursal'))
    else:
        return redirect(url_for('reportes_recepcion'))

# ===================================================================
# OPERACIONES PROTEGIDAS
# ===================================================================

@app.route('/limpieza')
@login_required
@recepcionista_required
def limpieza():
    """Limpieza solo para recepcionistas"""
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT h.id, h.numero, h.tipo, 
                   l.inicio_limpieza, 
                   TIMESTAMPDIFF(MINUTE, l.inicio_limpieza, NOW()) as minutos_transcurridos
            FROM habitaciones h
            LEFT JOIN log_limpiezas l ON h.id = l.habitacion_id 
                AND l.fin_limpieza IS NULL
            WHERE h.estado = 'LIMPIEZA' 
            AND h.sucursal_id = %s
            ORDER BY h.numero
        """, (current_user.sucursal_id,))
        habs = cursor.fetchall()
    return safe_render_template('limpieza.html', habitaciones=habs)

@app.route('/registro_usuario', methods=['GET', 'POST'])
@login_required
@admin_required
def registro_usuario():
    """Registro de usuarios solo para administradores"""
    conn = get_db_connection()
    if request.method == 'POST':
        try:
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
            rol = request.form.get('rol')
            sucursal_id = request.form.get('sucursal_id')
            turno = request.form.get('turno', 'MATUTINO')
            
            if not username or not password or not rol:
                flash('Todos los campos son requeridos', 'error')
                return redirect(url_for('registro_usuario'))
            
            # Generar hash de contraseña
            pw_hash = generate_bcrypt_hash(password)
            
            is_adm = 1 if rol in ['ADMIN_GENERAL', 'ADMIN_MOTEL'] else 0
            
            with conn.cursor() as cursor:
                # Verificar si el usuario ya existe
                cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    flash('El nombre de usuario ya existe', 'error')
                    return redirect(url_for('registro_usuario'))
                
                # Insertar nuevo usuario
                cursor.execute("""
                    INSERT INTO users (username, email, password_hash, rol, sucursal_id, turno, is_admin) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (username, email, pw_hash, rol, 
                      sucursal_id if sucursal_id else None, 
                      turno, is_adm))
                
                conn.commit()
                flash('Usuario creado exitosamente', 'success')
                return redirect(url_for('dashboard'))
                
        except Exception as e:
            conn.rollback()
            flash(f'Error al crear usuario: {str(e)}', 'error')
    
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM sucursales ORDER BY nombre")
        sucs = cursor.fetchall()
    conn.close()
    
    return safe_render_template('registro_usuario.html', sucursales=sucs)

# ===================================================================
# RUTA PRINCIPAL DE CHECKOUT (mantener igual)
# ===================================================================

@app.route('/checkout_completo', methods=['POST'])
@login_required
@role_required('ADMIN_GENERAL', 'ADMIN_MOTEL', 'RECEPCIONISTA')
def checkout_completo():
    """Ruta para procesar checkout con checklist"""
    print("=" * 60)
    print("CHECKOUT_COMPLETO - SOLICITUD RECIBIDA")
    print(f"Usuario: {current_user.username} (ID: {current_user.id})")
    
    conn = None
    try:
        # 1. Obtener ID de renta
        r_id = request.form.get('renta_id')
        print(f"renta_id recibido: '{r_id}'")
        
        if not r_id:
            return jsonify({'success': False, 'error': 'No renta_id'})
        
        renta_id_int = int(r_id)
        
        # 2. Obtener otros datos
        total_cargos_str = request.form.get('total_cargos', '0')
        try:
            total_cargos = float(total_cargos_str.replace('$', '').strip())
        except:
            total_cargos = 0.0
        
        observaciones = request.form.get('observaciones', '')
        
        conn = get_db_connection()
        
        with conn.cursor() as cursor:
            # 3. Obtener información de la renta
            cursor.execute("""
                SELECT r.*, h.numero, h.id as habitacion_id
                FROM rentas r 
                JOIN habitaciones h ON r.habitacion_id = h.id 
                WHERE r.id = %s
            """, (renta_id_int,))
            renta = cursor.fetchone()
            
            if not renta:
                print(f"ERROR: Renta {renta_id_int} NO encontrada")
                return jsonify({'success': False, 'error': f'Renta {renta_id_int} no existe'})
            
            print(f"Renta encontrada: ID {renta['id']}, Estado: {renta['estado']}")
            
            if renta['estado'] != 'ACTIVA':
                return jsonify({'success': False, 'error': f'Renta no está activa (estado: {renta["estado"]})'})
            
            # 4. Actualizar renta a CERRADA
            pago_inicial = float(renta.get('pago_inicial', 0) or 0)
            pago_final = pago_inicial + total_cargos
            
            cursor.execute("""
                UPDATE rentas 
                SET estado = 'CERRADA', 
                    hora_salida_real = NOW(),
                    monto_danos_limpieza = %s,
                    pago_final_total = %s
                WHERE id = %s
            """, (total_cargos, pago_final, renta_id_int))
            
            # 5. Actualizar habitación a LIMPIEZA
            cursor.execute("""
                UPDATE habitaciones 
                SET estado = 'LIMPIEZA' 
                WHERE id = %s
            """, (renta['habitacion_id'],))
            
            # 6. Insertar checklist si hay cargos u observaciones
            if total_cargos > 0 or observaciones.strip():
                cursor.execute("""
                    INSERT INTO checklist_salida 
                    (renta_id, usuario_id, cargo_danos, cargo_limpieza, observaciones)
                    VALUES (%s, %s, %s, %s, %s)
                """, (renta_id_int, current_user.id, total_cargos, total_cargos, observaciones))
            
            conn.commit()
            print(f"Checkout completado - Habitación #{renta['numero']}")
            
            # 7. Iniciar limpieza automática
            threading.Thread(
                target=proceso_limpieza_mejorado, 
                args=(renta['habitacion_id'],),
                daemon=True
            ).start()
            
            return jsonify({
                'success': True, 
                'message': f'Check-out completado. Habitación #{renta["numero"]} en limpieza.',
                'habitacion_numero': renta['numero']
            })
            
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"ERROR EN CHECKOUT: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False, 
            'error': f'Error: {str(e)}'
        })
    finally:
        if conn:
            conn.close()

# ===================================================================
# CONFIGURACIÓN DE SEGURIDAD ADICIONAL
# ===================================================================

# Configuración de seguridad para cookies
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8)
)

# ===================================================================
# INICIO DE LA APLICACIÓN
# ===================================================================

if __name__ == '__main__':
    app.run(debug=True, port=5000)