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

def admin_motel_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'ADMIN_MOTEL':
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


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


def admin_general_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'ADMIN_GENERAL':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# Decorador para Admin de cualquier nivel
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol not in ['ADMIN_GENERAL', 'ADMIN_MOTEL']:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

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

def obtener_tipo_cambio():
    """
    Obtiene el tipo de cambio actual MXN/USD.
    TODO: Conectar a API de Banxico o tabla de configuración.
    """
    # Valor fijo por ahora - puedes cambiar esto
    TIPO_CAMBIO_FIJO = 20.0
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Opcional: Intentar obtener de configuración en BD
            cursor.execute("SELECT valor FROM configuracion WHERE clave = 'tipo_cambio_usd'")
            resultado = cursor.fetchone()
            if resultado:
                return float(resultado['valor'])
    except:
        pass  # Si falla, usa el valor fijo
    finally:
        if conn:
            conn.close()
    
    return TIPO_CAMBIO_FIJO



def procesar_datos_corte_con_moneda(rentas):
    resumen = {
        '4_horas': {'cantidad': 0, 'total': 0.0, 'extras': 0.0},
        '6_horas': {'cantidad': 0, 'total': 0.0, 'extras': 0.0},
        '12_horas': {'cantidad': 0, 'total': 0.0, 'extras': 0.0}
    }
    
    total_mxn_fisico = 0.0
    total_usd_fisico = 0.0
    total_usd_valor_mxn = 0.0
    
    for r in rentas:
        h = int(r.get('horas_pactadas') or 4)
        # Tomamos el valor en pesos que guardamos en el check-in
        pago_mxn = float(r.get('pago_final_total') or 0)
        pago_ini_mxn = float(r.get('pago_inicial') or 0)
        
        moneda = r.get('moneda_pago', 'MXN')
        t_cambio = float(r.get('tipo_cambio_usd') or 20.0)
        
        extra_mxn = pago_mxn - pago_ini_mxn if pago_mxn > pago_ini_mxn else 0.0
        
        if moneda == 'USD':
            # Calculamos cuántos dólares físicos hay en caja
            total_usd_fisico += (pago_mxn / t_cambio)
            total_usd_valor_mxn += pago_mxn
        else:
            total_mxn_fisico += pago_mxn

        # La tabla siempre se llena con el valor MXN
        clave = f"{h}_horas"
        if clave in resumen:
            resumen[clave]['cantidad'] += 1
            resumen[clave]['total'] += pago_mxn
            resumen[clave]['extras'] += extra_mxn
            
    return {
        'resumen': resumen,
        'total_mxn': total_mxn_fisico,
        'total_usd_cantidad': total_usd_fisico,
        'total_usd_mxn': total_usd_valor_mxn,
        'total_general': total_mxn_fisico + total_usd_valor_mxn
    }





def convertir_mxn_a_usd(monto_mxn, tipo_cambio=None):
    """Convierte monto de MXN a USD"""
    if tipo_cambio is None:
        tipo_cambio = obtener_tipo_cambio()
    return monto_mxn / tipo_cambio if tipo_cambio > 0 else 0

def convertir_usd_a_mxn(monto_usd, tipo_cambio=None):
    """Convierte monto de USD a MXN"""
    if tipo_cambio is None:
        tipo_cambio = obtener_tipo_cambio()
    return monto_usd * tipo_cambio

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
        db='Halftime_Inn',
        charset='utf8mb4',
        cursorclass=DictCursor,
        autocommit=True
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
            cursor.execute("""
                SELECT u.*, s.nombre as sucursal_nombre 
                FROM users u
                LEFT JOIN sucursales s ON u.sucursal_id = s.id
                WHERE u.id = %s AND u.status = 1
            """, (user_id,))
            data = cursor.fetchone()
            if data:
                # Asegurar que sucursal_id se maneje correctamente
                data['sucursal_id'] = int(data['sucursal_id']) if data['sucursal_id'] is not None else None
                return User(data)
            return None
    finally: 
        conn.close()
# --- LÓGICA DE LIMPIEZA AUTOMÁTICA ---
def proceso_limpieza_mejorado(habitacion_id):
    """Hilo de fondo: espera 5 min y libera la habitación"""
    time.sleep(300) 
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE habitaciones SET estado='DISPONIBLE' WHERE id=%s AND estado='LIMPIEZA'", (habitacion_id,))
            print(f"Limpieza finalizada: Habitación ID {habitacion_id}")
    finally:
        conn.close()

# --- FUNCIONES DE APOYO ---
def get_daily_summary_por_sucursal(user):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            today = date.today()
            
            # 1. CÁLCULO DE INGRESOS (BASE + EXTRAS) - DIFERENCIADO POR ROL
            # Usamos COALESCE para que si la renta sigue activa, tome el pago_inicial como base
            sql_base = """
                SELECT 
                    COUNT(*) as c, 
                    SUM(COALESCE(pago_final_total, pago_inicial)) as ingreso_real,
                    SUM(CASE WHEN pago_final_total > pago_inicial 
                             THEN (pago_final_total - pago_inicial) 
                             ELSE 0 END) as monto_extras
                FROM rentas 
                WHERE DATE(hora_entrada) = %s
            """
            
            if user.rol == 'ADMIN_GENERAL':
                q_res = sql_base
                p_res = (today,)
            elif user.rol == 'ADMIN_MOTEL':
                q_res = sql_base + " AND sucursal_id = %s"
                p_res = (today, user.sucursal_id)
            else:  # RECEPCIONISTA
                q_res = sql_base + " AND recepcionista_id = %s"
                p_res = (today, user.id)
            
            cursor.execute(q_res, p_res)
            res = cursor.fetchone()
            
            # 2. ESTADO DE HABITACIONES
            if user.rol == 'ADMIN_GENERAL':
                q_hab = "SELECT estado, COUNT(*) as count FROM habitaciones GROUP BY estado"
                p_hab = ()
            else:
                q_hab = "SELECT estado, COUNT(*) as count FROM habitaciones WHERE sucursal_id = %s GROUP BY estado"
                p_hab = (user.sucursal_id,)

            cursor.execute(q_hab, p_hab)
            habs = {row['estado']: row['count'] for row in cursor.fetchall()}

            # 3. RETORNO DE DATOS PARA LAS TARJETAS
            return {
                'clientes_dia': res['c'] or 0,
                'ingreso_total_dia': float(res['ingreso_real'] or 0), # Total real acumulado
                'solo_extras_dia': float(res['monto_extras'] or 0),   # Solo lo ganado por tiempo extra
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
    # Lista de rutas públicas que no requieren autenticación
    public_paths = ['/login', '/static/', '/favicon.ico', '/reset_attempts']
    
    # Si es una ruta pública, permitir acceso
    if any(request.path.startswith(path) for path in public_paths):
        return
    
    # Verificar si el usuario está autenticado
    if not current_user.is_authenticated:
        # Guardar la ruta a la que intentaba acceder
        session['next_url'] = request.url
        flash('Por favor inicia sesión para acceder a esta página', 'warning')
        return redirect(url_for('login'))
    
    # Verificar acceso según rol (solo para rutas específicas)
    protected_paths = {
        '/dashboard/admin': ['ADMIN_GENERAL'],
        '/dashboard/sucursal': ['ADMIN_MOTEL'],
        '/dashboard/recepcionista': ['RECEPCIONISTA'],
        '/checkin/admin': ['ADMIN_GENERAL', 'ADMIN_MOTEL'],
        '/checkin/recepcionista': ['RECEPCIONISTA'],
        '/reportes/general': ['ADMIN_GENERAL'],
        '/reportes/sucursal': ['ADMIN_MOTEL'],
        '/reportes/recepcion': ['RECEPCIONISTA'],
        '/admin/sucursales': ['ADMIN_GENERAL', 'ADMIN_MOTEL'],
    }
    
    # Verificar si la ruta actual está protegida
    for path, allowed_roles in protected_paths.items():
        if request.path.startswith(path):
            if current_user.rol not in allowed_roles:
                abort(403)  # Acceso denegado
            break

# Diccionario para seguimiento de intentos de login (protección básica)
login_attempts = {}

@app.before_request
def check_brute_force():
    """Protección mejorada contra fuerza bruta - SOLO verifica, NO registra"""
    # Solo verificar en el endpoint de login POST
    if request.endpoint != 'login' or request.method != 'POST':
        return
    
    ip = request.remote_addr
    now = datetime.now()
    
    # Limpiar intentos antiguos (más de 15 minutos)
    if ip in login_attempts:
        # Filtrar solo intentos de los últimos 15 minutos
        recent_attempts = [t for t in login_attempts[ip] if (now - t).seconds <= 900]
        
        if recent_attempts:
            login_attempts[ip] = recent_attempts
        else:
            # Si no hay intentos recientes, eliminar la IP
            del login_attempts[ip]
    
    # Si hay 5 o más intentos fallidos en 15 minutos, bloquear
    if ip in login_attempts and len(login_attempts[ip]) >= 5:
        # Calcular tiempo de espera
        oldest_attempt = min(login_attempts[ip])
        wait_until = oldest_attempt + timedelta(minutes=15)
        wait_minutes = max(1, int((wait_until - now).seconds / 60))
        
        flash(f'Demasiados intentos fallidos. Espera {wait_minutes} minutos.', 'error')
        return redirect(url_for('login'))
    
    # NOTA: NO agregamos el intento aquí, eso se hará SOLO SI ES FALLIDO en la función login()

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
        # Redirigir al dashboard correcto según rol
        if current_user.rol == 'ADMIN_GENERAL':
            return redirect(url_for('dashboard_admin'))
        elif current_user.rol == 'ADMIN_MOTEL':
            return redirect(url_for('dashboard_sucursal'))
        elif current_user.rol == 'RECEPCIONISTA':
            return redirect(url_for('dashboard_recepcionista'))
        else:
            return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Validación básica
        if not username or not password:
            flash('Por favor ingresa usuario y contraseña', 'error')
            return render_template('login.html')
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Buscar usuario activo (status = 1)
                cursor.execute("""
                    SELECT * FROM users 
                    WHERE username = %s 
                    AND status = 1
                """, (username,))
                user_data = cursor.fetchone()
                
                if user_data:
                    # Validación bypass para admin global
                    if username == 'admin_global' and password == '1234':
                        user = User(user_data)
                        login_user(user)
                        
                        # Limpiar intentos fallidos para esta IP al tener éxito
                        ip = request.remote_addr
                        if ip in login_attempts:
                            login_attempts[ip] = []
                        
                        # Redirigir según rol
                        if user.rol == 'ADMIN_GENERAL':
                            return redirect(url_for('dashboard_admin'))
                        elif user.rol == 'ADMIN_MOTEL':
                            return redirect(url_for('dashboard_sucursal'))
                        else:
                            return redirect(url_for('dashboard_recepcionista'))
                    
                    # Validación Bcrypt normal
                    if bcrypt.checkpw(password.encode('utf-8'), user_data['password_hash'].encode('utf-8')):
                        user = User(user_data)
                        login_user(user)
                        
                        # Limpiar intentos fallidos para esta IP al tener éxito
                        ip = request.remote_addr
                        if ip in login_attempts:
                            login_attempts[ip] = []
                        
                        # Redirigir según rol
                        if user.rol == 'ADMIN_GENERAL':
                            return redirect(url_for('dashboard_admin'))
                        elif user.rol == 'ADMIN_MOTEL':
                            return redirect(url_for('dashboard_sucursal'))
                        else:
                            return redirect(url_for('dashboard_recepcionista'))
                
                # ⚠️ SOLO AQUÍ REGISTRAR INTENTO FALLIDO
                ip = request.remote_addr
                if ip not in login_attempts:
                    login_attempts[ip] = []
                login_attempts[ip].append(datetime.now())
                
                flash('Credenciales inválidas o usuario inactivo.', 'error')
                
        except Exception as e:
            flash(f'Error en el sistema: {str(e)}', 'error')
        finally:
            conn.close()
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    # Guardar el rol actual antes de hacer logout
    rol_actual = current_user.rol if current_user.is_authenticated else None
    
    # Hacer logout
    logout_user()
    
    # Limpiar la sesión completamente
    session.clear()
    
    # Mensaje personalizado según el rol
    if rol_actual == 'ADMIN_GENERAL':
        flash('Sesión de administrador general cerrada exitosamente', 'info')
    elif rol_actual == 'ADMIN_MOTEL':
        flash('Sesión de administrador de sucursal cerrada exitosamente', 'info')
    else:
        flash('Sesión de recepcionista cerrada exitosamente', 'info')
    
    # Redirigir siempre al login
    return redirect(url_for('login'))

# Ruta para resetear intentos fallidos (solo para desarrollo)
@app.route('/reset_attempts')
def reset_attempts():
    """Ruta para resetear intentos fallidos (solo para desarrollo)"""
    global login_attempts
    login_attempts.clear()
    flash('Intentos de login reseteados', 'success')
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
    """Redirige al usuario a su dashboard específico según su rol"""
    if current_user.rol == 'ADMIN_GENERAL':
        return redirect(url_for('dashboard_admin'))
    elif current_user.rol == 'ADMIN_MOTEL':
        return redirect(url_for('dashboard_sucursal'))
    else:
        return redirect(url_for('dashboard_recepcionista'))  # Rol no reconocido

@app.route('/dashboard/admin')
@login_required
@admin_required
def dashboard_admin():
    """Dashboard para administradores"""
    # Verificación doble de seguridad
    if current_user.rol not in ['ADMIN_GENERAL']:
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

@app.route('/dashboard/sucursal')
@login_required
def dashboard_sucursal():
    if current_user.rol not in ['ADMIN_MOTEL']:
        abort(403)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. OBTENER RESUMEN FINANCIERO DINÁMICO (Ventas y Extras)
            # Filtramos por la sucursal del administrador
            sql_resumen = """
                SELECT 
                    IFNULL(SUM(pago_final_total), 0) as ingreso_total,
                    IFNULL(SUM(monto_danos_limpieza), 0) as total_extras,
                    COUNT(id) as total_clientes
                FROM rentas 
                WHERE sucursal_id = %s 
                AND DATE(hora_entrada) = CURDATE()
                AND status = 1
                AND estado != 'CANCELADA'
            """
            cursor.execute(sql_resumen, (current_user.sucursal_id,))
            res = cursor.fetchone()

            # 2. ESTADOS DE HABITACIONES (Para la gráfica: Disponibles, Ocupadas, Limpieza)
            cursor.execute("""
                SELECT 
                    IFNULL(SUM(CASE WHEN estado = 'OCUPADA' THEN 1 ELSE 0 END), 0) as ocupadas,
                    IFNULL(SUM(CASE WHEN estado = 'LIMPIEZA' THEN 1 ELSE 0 END), 0) as limpieza,
                    IFNULL(SUM(CASE WHEN estado = 'DISPONIBLE' THEN 1 ELSE 0 END), 0) as disponibles
                FROM habitaciones 
                WHERE sucursal_id = %s AND status = 1
            """, (current_user.sucursal_id,))
            res_h = cursor.fetchone()

            # Diccionario consolidado para evitar UndefinedError en el HTML
            resumen_data = {
                "clientes_dia": int(res['total_clientes']),
                "ingreso_inicial_dia": float(res['ingreso_total']),
                "extras": float(res['total_extras']),
                "ocupadas": int(res_h['ocupadas']),
                "limpieza": int(res_h['limpieza']),
                "disponibles": int(res_h['disponibles'])
            }

            # 3. CONSULTA DE RENTAS ACTIVAS (Sin quitar funcionalidad)
            sql_rentas = """
                SELECT r.id, r.cliente_nombre as cliente, r.hora_entrada as entrada, 
                       r.hora_salida_estimada as salida_estimada, h.numero, h.tipo,
                       r.sucursal_id, u.username as recepcionista, r.turno_renta as turno
                FROM rentas r 
                JOIN habitaciones h ON r.habitacion_id = h.id 
                JOIN users u ON r.recepcionista_id = u.id
                WHERE r.estado = 'ACTIVA' AND r.sucursal_id = %s
                ORDER BY r.hora_entrada DESC
            """
            cursor.execute(sql_rentas, (current_user.sucursal_id,))
            rentas = cursor.fetchall()
            
            # Cálculo de tiempo restante
            ahora = datetime.now()
            for renta in rentas:
                salida = renta['salida_estimada']
                if isinstance(salida, str):
                    salida = datetime.strptime(salida, '%Y-%m-%d %H:%M:%S')
                renta['horas_restantes'] = round((salida - ahora).total_seconds() / 3600, 2) if salida > ahora else 0
            
            # REGLA DE NEGOCIO: Reporte de totales de la sucursal
            print(f"Sucursal {current_user.sucursal_id} - Total Vendido: {resumen_data['ingreso_inicial_dia']} | Entregar: {resumen_data['ingreso_inicial_dia']}")
            
            return safe_render_template('dashboard_sucursales.html', ocupadas=rentas, resumen=resumen_data)
    except Exception as e:
        if conn: conn.rollback()
        return redirect(url_for('logout')) # Validación ante errores de servidor
    finally: 
        if conn: conn.close()

from datetime import datetime

@app.route('/dashboard/recepcionista')
@login_required
@recepcionista_required
def dashboard_recepcionista():
    """Panel principal: Gestiona finanzas, estados de habitación y gráfica"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. CONSULTA FINANCIERA DINÁMICA (Check-out updates)
            # Sumamos el total de ventas y los cobros extras del turno actual
            sql_resumen = """
                SELECT 
                    IFNULL(SUM(pago_final_total), 0) as ingreso_total,
                    IFNULL(SUM(monto_danos_limpieza), 0) as total_extras,
                    COUNT(id) as total_clientes
                FROM rentas 
                WHERE recepcionista_id = %s 
                AND sucursal_id = %s
                AND turno_renta = %s
                AND DATE(hora_entrada) = CURDATE()
                AND status = 1
                AND estado != 'CANCELADA'
            """
            cursor.execute(sql_resumen, (current_user.id, current_user.sucursal_id, current_user.turno))
            res = cursor.fetchone()
            
            # 2. CONSULTA DE ESTADOS (Para tarjetas y Gráfica)
            # Crucial: Contamos 'DISPONIBLE' para que la gráfica funcione
            cursor.execute("""
                SELECT 
                    IFNULL(SUM(CASE WHEN estado = 'OCUPADA' THEN 1 ELSE 0 END), 0) as ocupadas,
                    IFNULL(SUM(CASE WHEN estado = 'LIMPIEZA' THEN 1 ELSE 0 END), 0) as limpieza,
                    IFNULL(SUM(CASE WHEN estado = 'DISPONIBLE' THEN 1 ELSE 0 END), 0) as disponibles
                FROM habitaciones 
                WHERE sucursal_id = %s AND status = 1
            """, (current_user.sucursal_id,))
            res_h = cursor.fetchone()

            # Diccionario de datos para el frontend (Evita UndefinedError)
            resumen_data = {
                "clientes_dia": int(res['total_clientes']),
                "ingreso_inicial_dia": float(res['ingreso_total']),
                "extras": float(res['total_extras']),
                "ocupadas": int(res_h['ocupadas']),
                "limpieza": int(res_h['limpieza']),
                "disponibles": int(res_h['disponibles'])
            }

            # 3. RENTAS ACTIVAS (Sin quitar funcionalidad de tabla)
            cursor.execute("""
                SELECT r.id, r.cliente_nombre as cliente, r.hora_entrada as entrada, 
                       r.hora_salida_estimada as salida_estimada, h.numero, h.tipo
                FROM rentas r 
                JOIN habitaciones h ON r.habitacion_id = h.id 
                WHERE r.estado = 'ACTIVA' AND r.recepcionista_id = %s AND r.status = 1
                ORDER BY r.hora_entrada DESC
            """, (current_user.id,))
            rentas = cursor.fetchall()
            
            # Cálculo de horas restantes para la vista
            ahora = datetime.now()
            for renta in rentas:
                renta['horas_restantes'] = round((renta['salida_estimada'] - ahora).total_seconds() / 3600, 2) if renta['salida_estimada'] > ahora else 0
            
            # REGLA DE NEGOCIO: Reporte de totales en terminal
            print(f"Total Vendido: ${resumen_data['ingreso_inicial_dia']} | Monto a entregar: ${resumen_data['ingreso_inicial_dia']}")
            
            return safe_render_template('dashboard_recepcionista.html', ocupadas=rentas, resumen=resumen_data)

    except Exception as e:
        if conn: conn.rollback()
        # Validación: Si el servidor se corta o hay error, redirigir a Login
        return redirect(url_for('logout'))
    finally: 
        if conn: conn.close()
        

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
    tipo_cambio = obtener_tipo_cambio()
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
                         current_user=current_user,
                         tipo_cambio=tipo_cambio)

# --- CHECKIN PARA RECEPCIONISTAS CORREGIDO ---

@app.route('/checkin/recepcionista', methods=['GET', 'POST'])
@login_required
@recepcionista_required
def checkin_recepcionista():
    conn = get_db_connection()
    tipo_cambio = obtener_tipo_cambio()
    
    try:
        if request.method == 'GET':
            # Cargar habitaciones con todos los precios
            with conn.cursor() as cursor:
                cursor.execute("""
    SELECT id, numero, nombre_personalizado, tipo, 
           precio_base, precio_4_horas, precio_6_horas, 
           precio_12_horas, precio_hora_extra
    FROM habitaciones 
    WHERE estado = 'DISPONIBLE' 
    AND sucursal_id = %s 
    AND status = 1
    ORDER BY numero ASC
""", (current_user.sucursal_id,))
                habitaciones = cursor.fetchall()
            
            return render_template('checkin_recepcionista.html', 
                                 habitaciones=habitaciones,
                                 tipo_cambio=tipo_cambio)
        
        elif request.method == 'POST':
            habitacion_id = request.form.get('habitacion_id')
            horas_pactadas = int(request.form.get('horas_pactadas', 0))
            nombre_cliente = request.form.get('especificaciones')
            modo_ingreso = request.form.get('modo_ingreso', 'VEHICULO')
            placas = request.form.get('placas', '').upper()
            
            moneda_pago = request.form.get('moneda_pago', 'MXN')
            monto_recibido = float(request.form.get('monto_recibido', 0))
            pago_inicial = float(request.form.get('pago_inicial', 0))

            with conn.cursor() as cursor:
                # Obtener todos los precios de la habitación
                cursor.execute("""
                    SELECT precio_base, precio_4_horas, precio_6_horas, 
                           precio_12_horas, precio_hora_extra, numero, 
                           precio_base as precio_por_hora
                    FROM habitaciones 
                    WHERE id = %s AND sucursal_id = %s AND estado = 'DISPONIBLE' AND status = 1
                """, (habitacion_id, current_user.sucursal_id))
                habitacion = cursor.fetchone()

                if not habitacion:
                    flash('Error: La habitación no existe o no está disponible.', 'error')
                    return redirect(url_for('checkin_recepcionista'))

                # --- CÁLCULO DEL PRECIO FINAL ---
                # Determinar el precio según las horas pactadas
                precio_final_mxn = 0
                
                if horas_pactadas == 4 and float(habitacion['precio_4_horas'] or 0) > 0:
                    precio_final_mxn = float(habitacion['precio_4_horas'])
                elif horas_pactadas == 6 and float(habitacion['precio_6_horas'] or 0) > 0:
                    precio_final_mxn = float(habitacion['precio_6_horas'])
                elif horas_pactadas == 12 and float(habitacion['precio_12_horas'] or 0) > 0:
                    precio_final_mxn = float(habitacion['precio_12_horas'])
                else:
                    # Calcular según horas personalizadas
                    if horas_pactadas <= 4:
                        precio_final_mxn = float(habitacion['precio_base']) * horas_pactadas
                    else:
                        # Primeras 4 horas al precio base, después precio por hora extra
                        precio_final_mxn = (float(habitacion['precio_base']) * 4) + \
                                          ((horas_pactadas - 4) * float(habitacion['precio_hora_extra']))
                
                # Validar que el precio final sea válido
                if precio_final_mxn <= 0:
                    flash('Error: El precio calculado no es válido', 'error')
                    return redirect(url_for('checkin_recepcionista'))
                
                # --- CÁLCULO DE MONTOS ---
                if moneda_pago == 'USD':
                    # Convertir lo que recibimos en USD a MXN para calcular el cambio
                    monto_recibido_mxn = monto_recibido * tipo_cambio
                    total_mostrado_en_usd = precio_final_mxn / tipo_cambio
                    cambio_mxn = monto_recibido_mxn - precio_final_mxn
                    cambio_usd = cambio_mxn / tipo_cambio
                else:
                    # Todo en MXN
                    monto_recibido_mxn = monto_recibido
                    total_mostrado_en_usd = 0  # No se usa
                    cambio_mxn = monto_recibido_mxn - precio_final_mxn
                    cambio_usd = 0
                
                # Validar que el monto recibido sea suficiente
                if moneda_pago == 'MXN' and monto_recibido_mxn < precio_final_mxn:
                    flash('Error: El monto recibido es insuficiente', 'error')
                    return redirect(url_for('checkin_recepcionista'))
                elif moneda_pago == 'USD' and (monto_recibido * tipo_cambio) < precio_final_mxn:
                    flash('Error: El monto recibido es insuficiente', 'error')
                    return redirect(url_for('checkin_recepcionista'))
                
                hora_entrada = datetime.now()
                hora_salida_estimada = hora_entrada + timedelta(hours=horas_pactadas)

                # --- INSERCIÓN EN BASE DE DATOS ---
                cursor.execute("""
                    INSERT INTO rentas (
                        habitacion_id, sucursal_id, recepcionista_id, cliente_nombre, 
                        turno_renta, hora_entrada, hora_salida_estimada, 
                        horas_pactadas, pago_inicial, pago_final_total, 
                        estado, status, moneda_pago, tipo_cambio_usd,
                        monto_recibido, cambio_entregado
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVA', 1, %s, %s, %s, %s)
                """, (habitacion_id, current_user.sucursal_id, current_user.id, 
                      nombre_cliente, current_user.turno, hora_entrada, 
                      hora_salida_estimada, horas_pactadas, 
                      precio_final_mxn,    # pago_inicial SIEMPRE MXN
                      precio_final_mxn,    # pago_final_total SIEMPRE MXN
                      moneda_pago, 
                      tipo_cambio,  # Guardamos el tipo de cambio usado en esa transacción
                      monto_recibido, 
                      cambio_mxn if moneda_pago == 'MXN' else cambio_usd))
                
                renta_id = cursor.lastrowid

                # Registro de acceso
                cursor.execute("""
                    INSERT INTO registros_acceso (renta_id, modo_ingreso, placas, hora_ingreso, status)
                    VALUES (%s, %s, %s, %s, 1)
                """, (renta_id, modo_ingreso, placas, hora_entrada))
                
                # Actualizar estado de la habitación
                cursor.execute("UPDATE habitaciones SET estado = 'OCUPADA' WHERE id = %s", (habitacion_id,))
                
                conn.commit()
                
                # --- MENSAJE DE ÉXITO DINÁMICO ---
                if moneda_pago == 'USD':
                    flash(f'Check-in exitoso! Habitación {habitacion["numero"]} - {horas_pactadas}h por ${total_mostrado_en_usd:.2f} USD. Cambio: ${cambio_usd:.2f} USD', 'success')
                else:
                    flash(f'Check-in exitoso! Habitación {habitacion["numero"]} - {horas_pactadas}h por ${precio_final_mxn:.2f} MXN. Cambio: ${cambio_mxn:.2f} MXN', 'success')
                
                return redirect(url_for('dashboard_recepcionista'))

    except Exception as e:
        if conn: 
            conn.rollback()
        flash(f'Error en el sistema: {str(e)}', 'error')
        import traceback
        traceback.print_exc()
        return redirect(url_for('checkin_recepcionista')) 
    finally:
        if conn: 
            conn.close()
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
    """Reportes para ADMIN_GENERAL con desglose detallado por sucursal y tipo"""
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    sucursal_id = request.args.get('sucursal_id', type=int)
    
    if not fecha_inicio:
        fecha_inicio = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')
    if not fecha_fin:
        fecha_fin = date.today().strftime('%Y-%m-%d')
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. Dropdown de sucursales
            cursor.execute("SELECT id, nombre FROM sucursales WHERE status = 1 ORDER BY nombre")
            todas_sucursales = cursor.fetchall()
            
            # Filtros dinámicos
            filtros_rentas = ["r.status = 1", "r.estado != 'CANCELADA'"]
            params_rentas = []
            if fecha_inicio:
                filtros_rentas.append("DATE(r.hora_entrada) >= %s")
                params_rentas.append(fecha_inicio)
            if fecha_fin:
                filtros_rentas.append("DATE(r.hora_entrada) <= %s")
                params_rentas.append(fecha_fin)
            if sucursal_id and sucursal_id > 0:
                filtros_rentas.append("r.sucursal_id = %s")
                params_rentas.append(sucursal_id)
            
            where_rentas = " WHERE " + " AND ".join(filtros_rentas)

            # 2. Reporte por Sucursal (Tabla Lateral)
            sql_sucursales = """
                SELECT s.id, s.nombre,
                    COALESCE(rentas_data.total_rentas, 0) as total_rentas,
                    COALESCE(rentas_data.total_dinero, 0) as total,
                    (SELECT COUNT(*) FROM habitaciones h WHERE h.sucursal_id = s.id AND h.estado = 'OCUPADA' AND h.status = 1) as ocupadas
                FROM sucursales s
                LEFT JOIN (
                    SELECT sucursal_id, COUNT(id) as total_rentas, SUM(pago_inicial) as total_dinero
                    FROM rentas r """ + where_rentas + """ GROUP BY sucursal_id
                ) rentas_data ON s.id = rentas_data.sucursal_id
                WHERE s.status = 1 ORDER BY total DESC
            """
            cursor.execute(sql_sucursales, tuple(params_rentas))
            sucursales = cursor.fetchall()
            
            # 3. Reporte de Habitaciones (Resumen para tarjetas)
            sql_habitaciones = """
                SELECT h.tipo, COUNT(r.id) as veces_rentada, SUM(r.pago_inicial) as generado
                FROM habitaciones h
                LEFT JOIN rentas r ON h.id = r.habitacion_id 
                    AND DATE(r.hora_entrada) >= %s AND DATE(r.hora_entrada) <= %s AND r.status = 1
                WHERE h.status = 1 AND h.tipo IN ('SENCILLA', 'JACUZZI', 'Sencilla', 'Jacuzzi')
            """
            params_h = [fecha_inicio, fecha_fin]
            if sucursal_id and sucursal_id > 0:
                sql_habitaciones += " AND h.sucursal_id = %s"
                params_h.append(sucursal_id)
            sql_habitaciones += " GROUP BY h.tipo"
            cursor.execute(sql_habitaciones, tuple(params_h))
            habitaciones = cursor.fetchall()

            # 4. NUEVO: Desglose por Sucursal y Tipo (Para la Gráfica)
            sql_detallado = """
                SELECT s.nombre as sucursal, h.tipo, COUNT(r.id) as cantidad
                FROM sucursales s
                JOIN habitaciones h ON s.id = h.sucursal_id
                LEFT JOIN rentas r ON h.id = r.habitacion_id 
                    AND DATE(r.hora_entrada) >= %s AND DATE(r.hora_entrada) <= %s AND r.status = 1
                WHERE s.status = 1 AND h.tipo IN ('SENCILLA', 'JACUZZI', 'Sencilla', 'Jacuzzi')
            """
            params_det = [fecha_inicio, fecha_fin]
            if sucursal_id and sucursal_id > 0:
                sql_detallado += " AND s.id = %s"
                params_det.append(sucursal_id)
            sql_detallado += " GROUP BY s.nombre, h.tipo ORDER BY s.nombre"
            cursor.execute(sql_detallado, tuple(params_det))
            hab_detallado = cursor.fetchall()
            
            total_ingresos = sum(float(s['total'] or 0) for s in sucursales)
            total_rentas = sum(int(s['total_rentas'] or 0) for s in sucursales)
            
            return render_template('reportes_general.html',
                                 sucursales=sucursales, todas_sucursales=todas_sucursales,
                                 habitaciones=habitaciones, hab_detallado=hab_detallado,
                                 total_ingresos=total_ingresos, total_rentas=total_rentas,
                                 fecha_actual=date.today().strftime('%d/%m/%Y'),
                                 fecha_inicio_default=fecha_inicio, fecha_fin_default=fecha_fin)
    except Exception as e:
        flash(f"Error en el reporte: {str(e)}", "error")
        return redirect(url_for('dashboard'))
    finally:
        conn.close()
#--------------------------------------------------------
@app.route('/reportes/sucursal')
@login_required
@admin_motel_required
def reportes_sucursal():
    fecha_inicio = request.args.get('fecha_inicio', (date.today() - timedelta(days=7)).strftime('%Y-%m-%d'))
    fecha_fin = request.args.get('fecha_fin', date.today().strftime('%Y-%m-%d'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. FINANZAS GENERALES (SIN EXTRAS)
            cursor.execute("""
                SELECT 
                    s.nombre as nombre_sucursal,
                    COALESCE(SUM(r.pago_inicial), 0) as total_base,
                    COUNT(r.id) as total_rentas
                FROM sucursales s
                LEFT JOIN rentas r ON s.id = r.sucursal_id 
                    AND DATE(r.hora_entrada) BETWEEN %s AND %s
                    AND r.status = 1
                WHERE s.id = %s 
                GROUP BY s.id
            """, (fecha_inicio, fecha_fin, current_user.sucursal_id))
            finanzas = cursor.fetchone()
            finanzas['monto_entregar'] = float(finanzas['total_base'])
            finanzas['total_extras'] = 0  # Ya no aplica

            # 2. LOG DETALLADO (SIN EXTRAS)
            cursor.execute("""
                SELECT r.id, u.username as nombre_usuario, h.tipo as tipo_habitacion, 
                       r.horas_pactadas, r.pago_inicial, r.cliente_nombre, r.hora_entrada
                FROM rentas r
                JOIN users u ON r.recepcionista_id = u.id
                JOIN habitaciones h ON r.habitacion_id = h.id
                WHERE r.sucursal_id = %s 
                    AND DATE(r.hora_entrada) BETWEEN %s AND %s
                    AND r.status = 1
                ORDER BY r.id DESC
            """, (current_user.sucursal_id, fecha_inicio, fecha_fin))
            detalle_rentas = cursor.fetchall()

            # 3. DATOS PARA GRÁFICA DIARIA (SIN EXTRAS)
            cursor.execute("""
                SELECT 
                    DATE(hora_entrada) as fecha, 
                    COUNT(*) as numero_rentas,
                    SUM(pago_inicial) as ingresos_dia
                FROM rentas
                WHERE sucursal_id = %s 
                    AND DATE(hora_entrada) BETWEEN %s AND %s
                    AND status = 1
                GROUP BY DATE(hora_entrada) 
                ORDER BY fecha ASC
            """, (current_user.sucursal_id, fecha_inicio, fecha_fin))
            datos_grafica = cursor.fetchall()

            # 4. RANKING DE HABITACIONES (SOLO SENCILLA Y JACUZZI)
            cursor.execute("""
                SELECT 
                    h.tipo, 
                    COUNT(r.id) as veces_rentada,
                    COALESCE(SUM(r.pago_inicial), 0) as generado
                FROM habitaciones h
                LEFT JOIN rentas r ON h.id = r.habitacion_id 
                    AND DATE(r.hora_entrada) BETWEEN %s AND %s
                    AND r.status = 1
                WHERE h.sucursal_id = %s 
                    AND h.status = 1
                    AND h.tipo IN ('SENCILLA', 'JACUZZI')
                GROUP BY h.tipo
                ORDER BY veces_rentada DESC
            """, (fecha_inicio, fecha_fin, current_user.sucursal_id))
            habitaciones = cursor.fetchall()

            # 5. COMPARATIVA DE SUCURSALES (solo para ADMIN_GENERAL)
            sucursales_comparativa = []
            total_comparativa = {'total_rentas': 0, 'ingresos_totales': 0}
            
            if current_user.rol == 'ADMIN_GENERAL':
                cursor.execute("""
                    SELECT 
                        s.id,
                        s.nombre,
                        COUNT(r.id) as total_rentas,
                        COALESCE(SUM(r.pago_inicial), 0) as ingresos_totales,
                        (SELECT COUNT(*) FROM habitaciones h WHERE h.sucursal_id = s.id AND h.status = 1) as total_habitaciones,
                        (SELECT COUNT(*) FROM habitaciones h WHERE h.sucursal_id = s.id AND h.estado = 'OCUPADA' AND h.status = 1) as habitaciones_ocupadas
                    FROM sucursales s
                    LEFT JOIN rentas r ON s.id = r.sucursal_id 
                        AND DATE(r.hora_entrada) BETWEEN %s AND %s
                        AND r.status = 1
                    WHERE s.status = 1
                    GROUP BY s.id, s.nombre
                    ORDER BY ingresos_totales DESC
                """, (fecha_inicio, fecha_fin))
                sucursales_comparativa = cursor.fetchall()
                
                # Calcular totales
                for s in sucursales_comparativa:
                    total_comparativa['total_rentas'] += s['total_rentas']
                    total_comparativa['ingresos_totales'] += float(s['ingresos_totales'])

        return render_template('reportes_sucursal.html', 
                             finanzas=finanzas, 
                             habitaciones=habitaciones,
                             detalle_rentas=detalle_rentas, 
                             datos_grafica=datos_grafica,
                             sucursales_comparativa=sucursales_comparativa,
                             total_comparativa=total_comparativa,
                             fecha_inicio_default=fecha_inicio, 
                             fecha_fin_default=fecha_fin)
    finally:
        if conn: conn.close()
        
#------------------------------------
@app.route('/reportes/recepcion')
@login_required
@recepcionista_required
def reportes_recepcion():
    """Reporte de recepción unificado en MXN"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # SQL para obtener las rentas del día del recepcionista actual
            sql = """
                SELECT r.pago_inicial, r.pago_final_total, r.horas_pactadas, 
                       r.moneda_pago, r.tipo_cambio_usd
                FROM rentas r 
                WHERE r.recepcionista_id = %s 
                AND DATE(r.hora_entrada) = CURDATE()
                AND r.status = 1
            """
            cursor.execute(sql, (current_user.id,))
            rentas = cursor.fetchall()

            # Procesamos los datos con la función que unifica en Pesos
            datos_corte = procesar_datos_corte_con_moneda(rentas)
            
            # Pasamos las variables exactas que el HTML necesita
            return render_template('corte_turno.html', 
                                 resumen=datos_corte['resumen'], 
                                 total_mxn=datos_corte['total_mxn'],
                                 total_usd_cantidad=datos_corte['total_usd_cantidad'],
                                 total_usd_mxn=datos_corte['total_usd_mxn'],
                                 total=datos_corte['total_general'], # Total global en MXN
                                 fecha=datetime.now(),
                                 usuario_reporte=current_user.username,
                                 es_reimpresion=False)
    finally:
        conn.close()
@app.route('/corte-turno')
@login_required
def corte_turno():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT horas_pactadas, pago_final_total, pago_inicial, 
                       moneda_pago, tipo_cambio_usd 
                FROM rentas 
                WHERE recepcionista_id = %s AND DATE(hora_entrada) = CURDATE()
                AND turno_renta = %s
            """, (current_user.id, current_user.turno))
            rentas = cursor.fetchall()

            datos = procesar_datos_corte_con_moneda(rentas)

            return render_template('corte_turno.html', 
                                 resumen=datos['resumen'], 
                                 total_mxn=datos['total_general_mxn'],
                                 total_usd=datos['total_general_usd'],
                                 total_rentas_usd=datos['total_rentas_usd'],
                                 total=datos['total_final_global'],
                                 tipo_cambio_promedio=datos['tipo_cambio_promedio'],
                                 fecha=datetime.now(),
                                 usuario_reporte=current_user.username,
                                 es_reimpresion=False)
    finally:
        conn.close()


#----------------------------------------------
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
# reimpresion de cortes
# ===================================================================


@app.route('/reimpresion-cortes', methods=['GET'])
@login_required
def reimpresion_cortes():
    """Panel para que el Admin seleccione usuario y fecha para reimprimir"""
    if current_user.rol not in ['ADMIN_GENERAL', 'ADMIN_MOTEL']:
        flash("Acceso restringido", "error")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Solo obtenemos usuarios de la sucursal del administrador logueado
            cursor.execute("""
                SELECT id, username FROM users 
                WHERE sucursal_id = %s AND rol = 'RECEPCIONISTA' AND status = 1
            """, (current_user.sucursal_id,))
            usuarios = cursor.fetchall()
            
            # Captura de filtros
            u_id = request.args.get('usuario_id')
            f_str = request.args.get('fecha')
            
            # Si se enviaron filtros, procesamos la reimpresión
            if u_id and f_str:
                return redirect(url_for('reimprimir_dinamico', usuario_id=u_id, fecha=f_str))

            return render_template('reimpresion_cortes.html', usuarios=usuarios)
    finally:
        conn.close()

@app.route('/reimprimir-dinamico')
@login_required
def reimprimir_dinamico():
    u_id = request.args.get('usuario_id')
    f_str = request.args.get('fecha')
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Obtenemos datos del usuario y su turno
            cursor.execute("SELECT username, turno FROM users WHERE id = %s", (u_id,))
            user_data = cursor.fetchone()
            
            cursor.execute("""
                SELECT horas_pactadas, pago_final_total, pago_inicial,
                       moneda_pago, tipo_cambio_usd
                FROM rentas 
                WHERE recepcionista_id = %s AND DATE(hora_entrada) = %s
                AND status = 1
            """, (u_id, f_str))
            rentas = cursor.fetchall()

            datos = procesar_datos_corte_con_moneda(rentas)

            # IMPORTANTE: Verifica qué llave usa tu función procesar_datos... 
            # Si usa 'total_final_global', asígnaselo a 'total' para el HTML
            monto_total = datos.get('total_final_global', datos.get('total_general', 0))

            return render_template('corte_turno.html', 
                                 resumen=datos['resumen'], 
                                 total=monto_total,  # <--- Esta es la clave del error
                                 fecha=f_str, 
                                 es_reimpresion=True,
                                 usuario_reporte=user_data['username'],
                                 turno_historico=user_data['turno'])
    finally:
        conn.close()

# ===================================================================
# OPERACIONES PROTEGIDAS
# ===================================================================

# ===================================================================
# RUTAS PARA GESTIÓN DE LIMPIEZA - CON OBSERVACIONES Y CANCELACIÓN
# ===================================================================

@app.route('/limpieza')
@login_required
@recepcionista_required
def limpieza():
    """Muestra habitaciones en limpieza"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Obtener habitaciones en limpieza con información del registro
            cursor.execute("""
                SELECT 
                    h.id, h.numero, h.tipo, 
                    l.id as limpieza_id,
                    l.inicio_limpieza, 
                    l.usuario_id,
                    l.terminado_por,
                    l.fin_limpieza,
                    l.motivo_terminacion,
                    l.observaciones,
                    TIMESTAMPDIFF(MINUTE, l.inicio_limpieza, NOW()) as minutos_transcurridos,
                    TIMESTAMPDIFF(SECOND, l.inicio_limpieza, NOW()) as segundos_transcurridos
                FROM habitaciones h
                LEFT JOIN log_limpiezas l ON h.id = l.habitacion_id 
                    AND l.fin_limpieza IS NULL
                WHERE h.estado = 'LIMPIEZA' 
                AND h.sucursal_id = %s
                AND h.status = 1
                ORDER BY h.numero
            """, (current_user.sucursal_id,))
            habs = cursor.fetchall()
            
            # Formatear tiempo para mostrar
            for hab in habs:
                minutos = hab.get('minutos_transcurridos', 0) or 0
                if minutos < 60:
                    hab['tiempo_en_limpieza'] = f"{minutos} min"
                else:
                    horas = minutos // 60
                    mins_restantes = minutos % 60
                    hab['tiempo_en_limpieza'] = f"{horas}h {mins_restantes}min"
                
                # Determinar estado basado en si tiene fin_limpieza
                if hab['fin_limpieza']:
                    hab['estado'] = 'completada'
                elif hab['motivo_terminacion'] == 'cancelada':
                    hab['estado'] = 'cancelada'
                else:
                    hab['estado'] = 'en_progreso'
            
            # Obtener resumen para las tarjetas
            cursor.execute("""
                SELECT 
                    COUNT(CASE WHEN estado = 'DISPONIBLE' THEN 1 END) as disponibles,
                    COUNT(CASE WHEN estado = 'OCUPADA' THEN 1 END) as ocupadas,
                    COUNT(CASE WHEN estado = 'LIMPIEZA' THEN 1 END) as limpieza
                FROM habitaciones 
                WHERE sucursal_id = %s AND status = 1
            """, (current_user.sucursal_id,))
            resumen = cursor.fetchone()
            
            return safe_render_template('limpieza.html', 
                                     habitaciones=habs, 
                                     resumen=resumen)
    finally:
        conn.close()

@app.route('/limpieza/completar/<int:limpieza_id>', methods=['POST'])
@login_required
@recepcionista_required
def completar_limpieza(limpieza_id):
    """Completar una limpieza (terminada normalmente o antes de tiempo)"""
    observaciones = request.form.get('observaciones', '').strip()
    motivo = request.form.get('motivo', 'manual_rapido')
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. Obtener información de la limpieza
            cursor.execute("""
                SELECT l.*, h.numero, h.sucursal_id 
                FROM log_limpiezas l
                JOIN habitaciones h ON l.habitacion_id = h.id
                WHERE l.id = %s AND l.fin_limpieza IS NULL
            """, (limpieza_id,))
            limpieza = cursor.fetchone()
            
            if not limpieza:
                flash('Limpieza no encontrada o ya finalizada', 'error')
                return redirect(url_for('limpieza'))
            
            # Verificar que pertenece a la sucursal del usuario
            if limpieza['sucursal_id'] != current_user.sucursal_id:
                flash('No tienes permisos para esta acción', 'error')
                return redirect(url_for('limpieza'))
            
            # 2. Calcular duración real
            inicio = limpieza['inicio_limpieza']
            fin = datetime.now()
            
            if isinstance(inicio, str):
                inicio = datetime.strptime(inicio, '%Y-%m-%d %H:%M:%S')
            
            duracion_minutos = int((fin - inicio).total_seconds() / 60)
            
            # 3. Actualizar registro de limpieza
            cursor.execute("""
                UPDATE log_limpiezas 
                SET fin_limpieza = %s,
                    motivo_terminacion = %s,
                    observaciones = %s,
                    terminado_por = %s,
                    duracion_minutos = %s
                WHERE id = %s
            """, (fin, motivo, observaciones, current_user.id, duracion_minutos, limpieza_id))
            
            # 4. Actualizar estado de la habitación
            cursor.execute("""
                UPDATE habitaciones 
                SET estado = 'DISPONIBLE' 
                WHERE id = %s
            """, (limpieza['habitacion_id']))
            
            conn.commit()
            
            # 5. Registrar log
            print(f"Limpieza completada - Habitación ID: {limpieza['habitacion_id']}, "
                  f"Duración: {duracion_minutos} min, "
                  f"Usuario: {current_user.username}")
            
            flash(f'Limpieza completada - Habitación #{limpieza["numero"]} ahora está disponible', 'success')
            
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Error al completar limpieza: {str(e)}', 'error')
        print(f"Error en completar_limpieza: {str(e)}")
    finally:
        if conn:
            conn.close()
    
    return redirect(url_for('limpieza'))

@app.route('/limpieza/cancelar/<int:limpieza_id>', methods=['POST'])
@login_required
@recepcionista_required
def cancelar_limpieza(limpieza_id):
    """Cancelar una limpieza en progreso"""
    observaciones = request.form.get('observaciones', '').strip()
    
    if not observaciones:
        flash('Debes especificar el motivo de la cancelación', 'error')
        return redirect(url_for('limpieza'))
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. Obtener información de la limpieza
            cursor.execute("""
                SELECT l.*, h.numero, h.sucursal_id 
                FROM log_limpiezas l
                JOIN habitaciones h ON l.habitacion_id = h.id
                WHERE l.id = %s AND l.fin_limpieza IS NULL
            """, (limpieza_id,))
            limpieza = cursor.fetchone()
            
            if not limpieza:
                flash('Limpieza no encontrada o ya finalizada', 'error')
                return redirect(url_for('limpieza'))
            
            # Verificar que pertenece a la sucursal del usuario
            if limpieza['sucursal_id'] != current_user.sucursal_id:
                flash('No tienes permisos para esta acción', 'error')
                return redirect(url_for('limpieza'))
            
            # 2. Calcular duración real
            inicio = limpieza['inicio_limpieza']
            fin = datetime.now()
            
            if isinstance(inicio, str):
                inicio = datetime.strptime(inicio, '%Y-%m-%d %H:%M:%S')
            
            duracion_minutos = int((fin - inicio).total_seconds() / 60)
            
            # 3. Actualizar registro de limpieza como cancelado
            cursor.execute("""
                UPDATE log_limpiezas 
                SET fin_limpieza = %s,
                    motivo_terminacion = 'cancelada',
                    observaciones = %s,
                    terminado_por = %s,
                    duracion_minutos = %s
                WHERE id = %s
            """, (fin, observaciones, current_user.id, duracion_minutos, limpieza_id))
            
            # 4. Actualizar estado de la habitación
            cursor.execute("""
                UPDATE habitaciones 
                SET estado = 'DISPONIBLE' 
                WHERE id = %s
            """, (limpieza['habitacion_id']))
            
            conn.commit()
            
            # 5. Registrar log
            print(f"Limpieza cancelada - Habitación ID: {limpieza['habitacion_id']}, "
                  f"Duración: {duracion_minutos} min, "
                  f"Motivo: {observaciones[:50]}...")
            
            flash(f'Limpieza cancelada - Habitación #{limpieza["numero"]} marcada como disponible', 'info')
            
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Error al cancelar limpieza: {str(e)}', 'error')
        print(f"Error en cancelar_limpieza: {str(e)}")
    finally:
        if conn:
            conn.close()
    
    return redirect(url_for('limpieza'))

@app.route('/limpieza/crear_registro/<int:habitacion_id>', methods=['POST'])
@login_required
@role_required('ADMIN_GENERAL', 'ADMIN_MOTEL', 'RECEPCIONISTA')
def crear_registro_limpieza(habitacion_id):
    """Crear un nuevo registro de limpieza para una habitación"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Verificar que la habitación existe y está en limpieza
            cursor.execute("""
                SELECT id, numero, estado, sucursal_id 
                FROM habitaciones 
                WHERE id = %s AND status = 1
            """, (habitacion_id,))
            habitacion = cursor.fetchone()
            
            if not habitacion:
                flash('Habitación no encontrada', 'error')
                return redirect(url_for('dashboard'))
            
            if habitacion['estado'] != 'LIMPIEZA':
                flash('La habitación no está en estado LIMPIEZA', 'error')
                return redirect(url_for('dashboard'))
            
            # Verificar si ya existe un registro de limpieza activo
            cursor.execute("""
                SELECT id FROM log_limpiezas 
                WHERE habitacion_id = %s AND fin_limpieza IS NULL
            """, (habitacion_id,))
            if cursor.fetchone():
                flash('Ya existe un registro de limpieza activo para esta habitación', 'warning')
                return redirect(url_for('limpieza'))
            
            # Crear registro en log_limpiezas
            cursor.execute("""
                INSERT INTO log_limpiezas 
                (habitacion_id, usuario_id, inicio_limpieza)
                VALUES (%s, %s, NOW())
            """, (habitacion_id, current_user.id))
            
            conn.commit()
            
            flash(f'Registro de limpieza creado para habitación #{habitacion["numero"]}', 'success')
            
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Error al crear registro de limpieza: {str(e)}', 'error')
    finally:
        if conn:
            conn.close()
    
    return redirect(url_for('limpieza'))

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
            turno_personalizado = request.form.get('turno_personalizado', '')
            horario_completo = request.form.get('horario_completo', '')
            
            if not username or not password or not rol:
                flash('Todos los campos son requeridos', 'error')
                return redirect(url_for('registro_usuario'))
            
            # ========= MANEJO DE SUCURSAL =========
            if current_user.rol == 'ADMIN_MOTEL' and current_user.sucursal_id:
                sucursal_final = current_user.sucursal_id
            elif rol == 'ADMIN_GENERAL':
                sucursal_final = None
            else:
                if not sucursal_id or sucursal_id == '0':
                    flash('Este rol requiere una sucursal asignada', 'error')
                    return redirect(url_for('registro_usuario'))
                sucursal_final = int(sucursal_id)
            
            # ========= MANEJO DE TURNO CON HORARIO =========
            if turno == 'CUSTOM' and turno_personalizado:
                # Si es personalizado, usar lo que escribió el usuario
                turno_final = turno_personalizado
            elif horario_completo:
                # Para turnos predefinidos con horario editado
                # Guardamos el turno y el horario juntos: "MATUTINO (7:00-15:00)"
                turno_final = f"{turno} ({horario_completo})"
            else:
                # Turno predefinido con horario por defecto
                # Mapear horarios por defecto
                horarios_por_defecto = {
                    'MATUTINO': '7:00 AM - 3:00 PM',
                    'VESPERTINO': '3:00 PM - 11:00 PM',
                    'NOCTURNO': '11:00 PM - 7:00 AM'
                }
                horario = horarios_por_defecto.get(turno, '')
                turno_final = f"{turno} ({horario})" if horario else turno
            
            print(f"Turno final a guardar: {turno_final}")
            
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
                """, (username, email, pw_hash, rol, sucursal_final, turno_final, is_adm))
                
                conn.commit()
                flash('Usuario creado exitosamente', 'success')
                return redirect(url_for('dashboard'))
                
        except Exception as e:
            conn.rollback()
            flash(f'Error al crear usuario: {str(e)}', 'error')
            print(f"Error en registro usuario: {str(e)}")
    
    # GET: Mostrar formulario - ¡CORRECCIÓN AQUÍ!
    with conn.cursor() as cursor:
        if current_user.rol == 'ADMIN_MOTEL' and current_user.sucursal_id:
            # CORRECCIÓN: Cambiar 'nomebre' por 'nombre'
            cursor.execute("SELECT * FROM sucursales WHERE id = %s AND status = 1 ORDER BY nombre", 
                          (current_user.sucursal_id,))
        else:
            # CORRECCIÓN: También aquí por si acaso
            cursor.execute("SELECT * FROM sucursales WHERE status = 1 ORDER BY nombre")
        
        sucursales = cursor.fetchall()
    
    conn.close()
    
    return render_template('registro_usuario.html', sucursales=sucursales)

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
# administrar sucursales y habitaciones
# ===================================================================

@app.route('/api/habitacion/<int:habitacion_id>')
@login_required
def api_habitacion(habitacion_id):
    """API para obtener datos detallados de una habitación específica"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, numero, nombre_personalizado, tipo, 
                       precio_base, precio_4_horas, precio_6_horas, 
                       precio_12_horas, precio_hora_extra, estado
                FROM habitaciones 
                WHERE id = %s AND status = 1
            """, (habitacion_id,))
            
            habitacion = cursor.fetchone()
            if habitacion:
                return jsonify({
                    'success': True,
                    'habitacion': habitacion
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Habitación no encontrada'
                })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error del servidor: {str(e)}'
        })
    finally:
        conn.close()
@app.route('/api/calcular_precio', methods=['POST'])
@login_required
def api_calcular_precio():
    """API para calcular precio según habitación y horas"""
    data = request.get_json()
    habitacion_id = data.get('habitacion_id')
    horas = int(data.get('horas', 0))
    
    if not habitacion_id or horas <= 0:
        return jsonify({'success': False, 'error': 'Datos inválidos'})
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT precio_base, precio_4_horas, precio_6_horas, 
                       precio_12_horas, precio_hora_extra
                FROM habitaciones 
                WHERE id = %s AND status = 1
            """, (habitacion_id,))
            
            habitacion = cursor.fetchone()
            if not habitacion:
                return jsonify({'success': False, 'error': 'Habitación no encontrada'})
            
            # Calcular precio según horas
            precio_final = 0
            
            if horas == 4 and float(habitacion['precio_4_horas'] or 0) > 0:
                precio_final = float(habitacion['precio_4_horas'])
            elif horas == 6 and float(habitacion['precio_6_horas'] or 0) > 0:
                precio_final = float(habitacion['precio_6_horas'])
            elif horas == 12 and float(habitacion['precio_12_horas'] or 0) > 0:
                precio_final = float(habitacion['precio_12_horas'])
            else:
                # Calcular según horas personalizadas
                if horas <= 4:
                    precio_final = float(habitacion['precio_base']) * horas
                else:
                    precio_final = (float(habitacion['precio_base']) * 4) + \
                                  ((horas - 4) * float(habitacion['precio_hora_extra']))
            
            return jsonify({
                'success': True,
                'precio': precio_final,
                'precio_base': float(habitacion['precio_base']),
                'precio_hora_extra': float(habitacion['precio_hora_extra']),
                'tiene_4h': float(habitacion['precio_4_horas'] or 0) > 0,
                'tiene_6h': float(habitacion['precio_6_horas'] or 0) > 0,
                'tiene_12h': float(habitacion['precio_12_horas'] or 0) > 0
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error del servidor: {str(e)}'
        })
    finally:
        conn.close()

@app.route('/api/habitaciones/<int:sucursal_id>')
@login_required
def get_habitaciones_json(sucursal_id):
    """API para obtener todas las habitaciones de una sucursal"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, numero, nombre_personalizado, tipo, 
                       precio_base, precio_4_horas, precio_6_horas, 
                       precio_12_horas, precio_hora_extra, estado, status
                FROM habitaciones 
                WHERE sucursal_id = %s AND status = 1
                ORDER BY CAST(numero AS UNSIGNED), numero
            """, (sucursal_id,))
            return jsonify(cursor.fetchall())
    finally:
        conn.close()

# API para obtener usuarios por sucursal
@app.route('/api/usuarios_filtro/<int:sucursal_id>')
@login_required
def api_usuarios_filtro(sucursal_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if sucursal_id == 0:  # Todas las sucursales
                cursor.execute("""
                    SELECT u.*, s.nombre as sucursal_nombre 
                    FROM users u
                    LEFT JOIN sucursales s ON u.sucursal_id = s.id
                    WHERE u.status = 1 
                    AND u.rol IN ('ADMIN_MOTEL', 'RECEPCIONISTA')
                    ORDER BY s.nombre, 
                    CASE u.rol 
                        WHEN 'ADMIN_MOTEL' THEN 1
                        WHEN 'RECEPCIONISTA' THEN 2
                    END, 
                    u.username
                """)
            else:  # Usuarios de una sucursal específica
                cursor.execute("""
                    SELECT u.*, s.nombre as sucursal_nombre 
                    FROM users u
                    LEFT JOIN sucursales s ON u.sucursal_id = s.id
                    WHERE u.sucursal_id = %s 
                    AND u.status = 1 
                    AND u.rol IN ('ADMIN_MOTEL', 'RECEPCIONISTA')
                    ORDER BY 
                    CASE u.rol 
                        WHEN 'ADMIN_MOTEL' THEN 1
                        WHEN 'RECEPCIONISTA' THEN 2
                    END, 
                    u.username
                """, (sucursal_id,))
            
            usuarios = cursor.fetchall()
            return jsonify(usuarios)
    finally:
        conn.close()

# Nueva API para obtener datos de un usuario específico
@app.route('/api/usuario/<int:user_id>')
@login_required
def api_usuario(user_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT u.*, s.nombre as sucursal_nombre 
                FROM users u
                LEFT JOIN sucursales s ON u.sucursal_id = s.id
                WHERE u.id = %s AND u.status = 1
            """, (user_id,))
            
            usuario = cursor.fetchone()
            if usuario:
                # No devolver la contraseña
                usuario.pop('password_hash', None)
                return jsonify(usuario)
            else:
                return jsonify({'error': 'Usuario no encontrado'}), 404
    finally:
        conn.close()

@app.route('/admin/sucursales', methods=['GET', 'POST'])
@login_required
def admin_sucursales():
    # Validación de Sesión y Rol
    if current_user.rol not in ['ADMIN_GENERAL', 'ADMIN_MOTEL']:
        flash('No tienes permisos para acceder.', 'error')
        return redirect(url_for('dashboard'))

    # Inicialización de variables
    sucursales = []
    usuarios = []
    habitaciones = []
    resumen_data = {'ingreso_inicial_dia': 0.0, 'limpieza': 0}

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                tipo_form = request.form.get('tipo_formulario')
                
                # MANEJO DE HABITACIONES
                if tipo_form == 'habitacion':
                    try:
                        # 1. OBTENER DATOS CON VALORES POR DEFECTO
                        id_hab = request.form.get('id_habitacion', '').strip()
                        suc_id = request.form.get('sucursal_id', '').strip()
                        nombre_personalizado = request.form.get('nombre_personalizado', '').strip() or ''
                        tipo_h_raw = request.form.get('tipo', '').strip()
                        p_base = request.form.get('precio_base', '').strip()
                        
                        # NUEVOS CAMPOS PARA PRECIOS POR HORAS
                        precio_4_horas = float(request.form.get('precio_4_horas', 0) or 0)
                        precio_6_horas = float(request.form.get('precio_6_horas', 0) or 0)
                        precio_12_horas = float(request.form.get('precio_12_horas', 0) or 0)
                        precio_hora_extra = float(request.form.get('precio_hora_extra', 0) or 0)
                        
                        accion = request.form.get('accion', 'guardar').strip()
                        
                        print(f"Datos procesados:")
                        print(f"   Precio 4h: {precio_4_horas}")
                        print(f"   Precio 6h: {precio_6_horas}")
                        print(f"   Precio 12h: {precio_12_horas}")
                        print(f"   Precio hora extra: {precio_hora_extra}")
                        
                        # 2. VALIDACIONES BÁSICAS
                        if not suc_id:
                            flash('Error: Debes seleccionar una sucursal', 'error')
                            return redirect(url_for('admin_sucursales'))
                        
                        if not tipo_h_raw:
                            flash('Error: El tipo es requerido', 'error')
                            return redirect(url_for('admin_sucursales'))
                        
                        if not p_base:
                            flash('Error: El precio base es requerido', 'error')
                            return redirect(url_for('admin_sucursales'))
                        
                        # 3. PROCESAR TIPO (convertir a mayúsculas y validar)
                        tipo_h = tipo_h_raw.upper()
                        if tipo_h not in ['SENCILLA', 'JACUZZI']:
                            flash('Error: Tipo debe ser SENCILLA o JACUZZI', 'error')
                            return redirect(url_for('admin_sucursales'))
                        
                        # 4. VALIDAR PRECIOS
                        try:
                            precio_base = float(p_base)
                            if precio_base < 0:  # Cambia <= por < para aceptar 0
                                flash('Error: El precio base no puede ser negativo', 'error')
                                return redirect(url_for('admin_sucursales'))
                        except ValueError:
                            flash('Error: Los precios deben ser números válidos', 'error')
                            return redirect(url_for('admin_sucursales'))
                            
                            # Validar que los precios por horas no sean negativos
                            if precio_4_horas < 0 or precio_6_horas < 0 or precio_12_horas < 0 or precio_hora_extra < 0:
                                flash('Error: Los precios no pueden ser negativos', 'error')
                                return redirect(url_for('admin_sucursales'))
                                
                        except ValueError:
                            flash('Error: Los precios deben ser números válidos', 'error')
                            return redirect(url_for('admin_sucursales'))
                        
                        # 5. EJECUTAR ACCIÓN
                        if accion == 'eliminar':
                            if not id_hab:
                                flash('Error: ID de habitación requerido para eliminar', 'error')
                                return redirect(url_for('admin_sucursales'))
                            
                            cursor.execute("UPDATE habitaciones SET status = 0 WHERE id = %s", (id_hab,))
                            conn.commit()
                            flash('Habitación desactivada exitosamente', 'success')
                            
                        else:  # ACCIÓN GUARDAR
                            if not id_hab:  # CREAR NUEVA HABITACIÓN
                                # Obtener el siguiente número disponible
                                cursor.execute("""
                                    SELECT COALESCE(MAX(CAST(numero AS UNSIGNED)), 0) as max_num 
                                    FROM habitaciones 
                                    WHERE sucursal_id = %s AND status = 1
                                """, (suc_id,))
                                resultado = cursor.fetchone()
                                proximo_num = int(resultado['max_num']) + 1
                                numero_generado = str(proximo_num)
                                
                                # Insertar nueva habitación con todos los precios
                                sql = """
                                    INSERT INTO habitaciones 
                                    (numero, nombre_personalizado, tipo, sucursal_id, 
                                     precio_base, precio_4_horas, precio_6_horas, 
                                     precio_12_horas, precio_hora_extra, estado, status) 
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'DISPONIBLE', 1)
                                """
                                cursor.execute(sql, (numero_generado, nombre_personalizado, tipo_h, 
                                                   suc_id, precio_base, precio_4_horas, 
                                                   precio_6_horas, precio_12_horas, 
                                                   precio_hora_extra))
                                habitacion_id = cursor.lastrowid
                                
                                conn.commit()
                                flash('Habitación creada exitosamente', 'success')
                                
                            else:  # ACTUALIZAR HABITACIÓN EXISTENTE
                                # Verificar que la habitación existe
                                cursor.execute("SELECT id, numero FROM habitaciones WHERE id = %s AND status = 1", (id_hab,))
                                habitacion_existente = cursor.fetchone()
                                
                                if not habitacion_existente:
                                    flash('Error: Habitación no encontrada', 'error')
                                    return redirect(url_for('admin_sucursales'))
                                
                                # Actualizar habitación con todos los precios
                                sql = """
                                    UPDATE habitaciones 
                                    SET nombre_personalizado = %s, 
                                        tipo = %s, 
                                        precio_base = %s,
                                        precio_4_horas = %s,
                                        precio_6_horas = %s,
                                        precio_12_horas = %s,
                                        precio_hora_extra = %s,
                                        sucursal_id = %s
                                    WHERE id = %s
                                """
                                cursor.execute(sql, (nombre_personalizado, tipo_h, precio_base,
                                                   precio_4_horas, precio_6_horas, precio_12_horas,
                                                   precio_hora_extra, suc_id, id_hab))
                                conn.commit()
                                
                                flash('Habitación actualizada exitosamente', 'success')
                        
                        return redirect(url_for('admin_sucursales'))
                        
                    except Exception as e:
                        conn.rollback()
                        flash(f'Error del servidor al procesar habitación: {str(e)}', 'error')
                        return redirect(url_for('admin_sucursales'))
                
                # MANEJO DE SUCURSALES (mantener igual)
                elif tipo_form == 'sucursal':
                    id_suc = request.form.get('id_sucursal')
                    nombre = request.form.get('nombre')
                    direccion = request.form.get('direccion')
                    accion = request.form.get('accion', 'guardar')
                    
                    if accion == 'eliminar':
                        cursor.execute("UPDATE sucursales SET status = 0 WHERE id = %s", (id_suc,))
                        flash('Sucursal desactivada exitosamente', 'success')
                    else:
                        if id_suc:
                            cursor.execute("UPDATE sucursales SET nombre=%s, direccion=%s WHERE id=%s", (nombre, direccion, id_suc))
                            flash('Sucursal actualizada exitosamente', 'success')
                        else:
                            cursor.execute("INSERT INTO sucursales (nombre, direccion) VALUES (%s, %s)", (nombre, direccion))
                            flash('Sucursal creada exitosamente', 'success')
                
                # MANEJO DE USUARIOS (mantener igual)
                elif tipo_form == 'usuario':
                    user_id = request.form.get('id_usuario')
                    accion = request.form.get('accion', 'guardar')
                    
                    if accion == 'eliminar':
                        cursor.execute("UPDATE users SET status = 0 WHERE id = %s", (user_id,))
                        conn.commit()
                        flash('Usuario desactivado exitosamente', 'success')
                        return redirect(url_for('admin_sucursales'))
                
                conn.commit()
                return redirect(url_for('admin_sucursales'))
            
            # ========== GET REQUEST ==========
            # Cargar sucursales activas
            cursor.execute("SELECT * FROM sucursales WHERE status = 1 ORDER BY nombre")
            sucursales = cursor.fetchall()
            
            # Cargar usuarios activos
            cursor.execute("""
                SELECT u.*, s.nombre as sucursal_nombre 
                FROM users u
                LEFT JOIN sucursales s ON u.sucursal_id = s.id
                WHERE u.status = 1 
                AND u.rol IN ('ADMIN_MOTEL', 'RECEPCIONISTA')
                ORDER BY s.nombre, 
                CASE u.rol 
                    WHEN 'ADMIN_MOTEL' THEN 1
                    WHEN 'RECEPCIONISTA' THEN 2
                END, 
                u.username
            """)
            usuarios = cursor.fetchall()
            
            # Cargar habitaciones con todos los precios
            if current_user.rol == 'ADMIN_GENERAL':
                cursor.execute("""
                    SELECT h.*, s.nombre as sucursal_nombre 
                    FROM habitaciones h
                    JOIN sucursales s ON h.sucursal_id = s.id
                    WHERE h.status = 1
                    ORDER BY s.nombre, h.numero
                """)
            else:
                cursor.execute("""
                    SELECT h.*, s.nombre as sucursal_nombre 
                    FROM habitaciones h
                    JOIN sucursales s ON h.sucursal_id = s.id
                    WHERE h.sucursal_id = %s AND h.status = 1
                    ORDER BY h.numero
                """, (current_user.sucursal_id,))
            habitaciones = cursor.fetchall()
            
            # Totales
            cursor.execute("SELECT COUNT(*) as total FROM habitaciones WHERE estado = 'LIMPIEZA' AND status = 1")
            c_limpieza = cursor.fetchone()['total'] or 0
            
            cursor.execute("SELECT SUM(pago_final_total) as total FROM rentas WHERE DATE(created_at) = CURDATE() AND status = 1")
            res_v = cursor.fetchone()
            venta_hoy = res_v['total'] if res_v and res_v['total'] else 0.0
            
            resumen_data = {
                'ingreso_inicial_dia': float(venta_hoy),
                'limpieza': int(c_limpieza)
            }

    except Exception as e:
        if conn: 
            conn.rollback()
        flash(f'Error general: {str(e)}', 'error')
    finally:
        if conn: 
            conn.close()

    return render_template('admin_sucursales.html', 
                         sucursales=sucursales, 
                         usuarios=usuarios,
                         habitaciones=habitaciones,
                         resumen=resumen_data)
    
# Agrega esta ruta después de la ruta /admin/sucursales
@app.route('/admin/sucursales_ajax', methods=['POST'])
@login_required
def admin_sucursales_ajax():
    """Ruta AJAX para operaciones sin recargar"""
    if current_user.rol not in ['ADMIN_GENERAL', 'ADMIN_MOTEL']:
        return jsonify({'success': False, 'error': 'No tienes permisos'})

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            tipo_form = request.form.get('tipo_formulario')
            
            # MANEJO DE HABITACIONES (AJAX)
            if tipo_form == 'habitacion':
                try:
                    id_hab = request.form.get('id_habitacion', '').strip()
                    suc_id = request.form.get('sucursal_id', '').strip()
                    nombre_personalizado = request.form.get('nombre_personalizado', '').strip() or ''
                    tipo_h_raw = request.form.get('tipo', '').strip()
                    p_base = request.form.get('precio_base', '').strip()
                    accion = request.form.get('accion', 'guardar').strip()
                    
                    print(f"AJAX Habitación - Acción: {accion}, ID: {id_hab}")
                    
                    # ACCIÓN ELIMINAR
                    if accion == 'eliminar':
                        if not id_hab:
                            return jsonify({'success': False, 'error': 'ID de habitación requerido'})
                        
                        # Obtener sucursal_id antes de eliminar (para refrescar lista)
                        cursor.execute("SELECT sucursal_id FROM habitaciones WHERE id = %s", (id_hab,))
                        hab = cursor.fetchone()
                        sucursal_id = hab['sucursal_id'] if hab else None
                        
                        cursor.execute("UPDATE habitaciones SET status = 0 WHERE id = %s", (id_hab,))
                        conn.commit()
                        
                        return jsonify({
                            'success': True, 
                            'message': 'Habitación desactivada exitosamente',
                            'accion': 'eliminar',
                            'id': id_hab,
                            'sucursal_id': sucursal_id
                        })
                    
                    # ACCIÓN GUARDAR (crear o editar)
                    else:
                        # Para guardar SÍ necesitamos validar todos los campos
                        if not suc_id:
                            return jsonify({'success': False, 'error': 'Debes seleccionar una sucursal'})
                        
                        if not tipo_h_raw:
                            return jsonify({'success': False, 'error': 'El tipo es requerido'})
                        
                        if not p_base:
                            return jsonify({'success': False, 'error': 'El precio base es requerido'})
                        
                        tipo_h = tipo_h_raw.upper()
                        if tipo_h not in ['SENCILLA', 'JACUZZI']:
                            return jsonify({'success': False, 'error': 'Tipo debe ser SENCILLA o JACUZZI'})
                        
                        try:
                            precio_base = float(p_base)
                            if precio_base <= 0:
                                return jsonify({'success': False, 'error': 'El precio debe ser mayor a 0'})
                        except ValueError:
                            return jsonify({'success': False, 'error': 'El precio base debe ser un número válido'})
                        
                        # CREAR NUEVA HABITACIÓN
                        if not id_hab:
                            # Obtener siguiente número
                            cursor.execute("""
                                SELECT COALESCE(MAX(CAST(numero AS UNSIGNED)), 0) as max_num 
                                FROM habitaciones 
                                WHERE sucursal_id = %s AND status = 1
                            """, (suc_id,))
                            resultado = cursor.fetchone()
                            proximo_num = int(resultado['max_num']) + 1
                            numero_generado = str(proximo_num)
                            
                            # Insertar nueva
                            sql = """
                                INSERT INTO habitaciones 
                                (numero, nombre_personalizado, tipo, sucursal_id, precio_base, precio_hora_extra, estado, status) 
                                VALUES (%s, %s, %s, %s, %s, %s, 'DISPONIBLE', 1)
                            """
                            cursor.execute(sql, (numero_generado, nombre_personalizado, tipo_h, suc_id, precio_base, 0.00))
                            habitacion_id = cursor.lastrowid
                            
                            conn.commit()
                            
                            # Obtener datos de la nueva habitación
                            cursor.execute("""
                                SELECT id, numero, nombre_personalizado, tipo, precio_base, sucursal_id
                                FROM habitaciones WHERE id = %s
                            """, (habitacion_id,))
                            nueva_hab = cursor.fetchone()
                            
                            return jsonify({
                                'success': True, 
                                'message': 'Habitación creada exitosamente',
                                'accion': 'guardar',
                                'id': habitacion_id,
                                'numero': nueva_hab['numero'],
                                'nombre_personalizado': nueva_hab['nombre_personalizado'],
                                'tipo': nueva_hab['tipo'],
                                'precio_base': float(nueva_hab['precio_base']),
                                'sucursal_id': nueva_hab['sucursal_id']
                            })
                            
                        # ACTUALIZAR HABITACIÓN EXISTENTE
                        else:
                            # Verificar que existe
                            cursor.execute("SELECT id FROM habitaciones WHERE id = %s AND status = 1", (id_hab,))
                            if not cursor.fetchone():
                                return jsonify({'success': False, 'error': 'Habitación no encontrada'})
                            
                            # Actualizar
                            sql = """
                                UPDATE habitaciones 
                                SET nombre_personalizado = %s, 
                                    tipo = %s, 
                                    precio_base = %s, 
                                    precio_hora_extra = %s,
                                    sucursal_id = %s
                                WHERE id = %s
                            """
                            cursor.execute(sql, (nombre_personalizado, tipo_h, precio_base, 0.00, suc_id, id_hab))
                            conn.commit()
                            
                            # Obtener datos actualizados
                            cursor.execute("""
                                SELECT id, numero, nombre_personalizado, tipo, precio_base, sucursal_id
                                FROM habitaciones WHERE id = %s
                            """, (id_hab,))
                            hab_actualizada = cursor.fetchone()
                            
                            return jsonify({
                                'success': True, 
                                'message': 'Habitación actualizada exitosamente',
                                'accion': 'guardar',
                                'id': id_hab,
                                'numero': hab_actualizada['numero'],
                                'nombre_personalizado': hab_actualizada['nombre_personalizado'],
                                'tipo': hab_actualizada['tipo'],
                                'precio_base': float(hab_actualizada['precio_base']),
                                'sucursal_id': hab_actualizada['sucursal_id']
                            })
                            
                except Exception as e:
                    conn.rollback()
                    print(f"Error en habitacion AJAX: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    return jsonify({'success': False, 'error': f'Error del servidor: {str(e)}'})
            
            # MANEJO DE USUARIOS (AJAX)
            elif tipo_form == 'usuario':
                try:
                    user_id = request.form.get('id_usuario')
                    accion = request.form.get('accion', 'guardar')
                    
                    if accion == 'eliminar':
                        # Verificar que no sea ADMIN_GENERAL
                        cursor.execute("SELECT rol FROM users WHERE id = %s", (user_id,))
                        user = cursor.fetchone()
                        if user and user['rol'] == 'ADMIN_GENERAL':
                            return jsonify({'success': False, 'error': 'No puedes desactivar al administrador general'})
                        
                        cursor.execute("UPDATE users SET status = 0 WHERE id = %s", (user_id,))
                        conn.commit()
                        return jsonify({
                            'success': True, 
                            'message': 'Usuario desactivado exitosamente',
                            'accion': 'eliminar',
                            'id': user_id
                        })
                    else:
                        return jsonify({'success': False, 'error': 'Acción no válida'})
                        
                except Exception as e:
                    conn.rollback()
                    print(f"Error en usuario AJAX: {str(e)}")
                    return jsonify({'success': False, 'error': f'Error al procesar usuario: {str(e)}'})
            
            return jsonify({'success': False, 'error': 'Tipo de formulario no válido'})
            
    except Exception as e:
        if conn: 
            conn.rollback()
        print(f"Error general en AJAX: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Error interno del servidor'})
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

def create_admin_global_automatic():
    """Crea o repara el usuario admin_global automáticamente"""
    try:
        # Asegúrate de que get_db_connection esté definida arriba
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Ampliar columna para evitar cortes en el hash
            cursor.execute("ALTER TABLE users MODIFY COLUMN password_hash VARCHAR(255)")
            
            username = 'admin_global'
            password_plana = '1234'
            
            # Generar hash limpio
            salt = bcrypt.gensalt()
            hashed_pw = bcrypt.hashpw(password_plana.encode('utf-8'), salt).decode('utf-8')
            
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            if not cursor.fetchone():
                sql = """
                INSERT INTO users (username, email, password_hash, rol, is_admin) 
                VALUES (%s, 'admin_global@hotel.com', %s, 'ADMIN_GENERAL', 1)
                """
                cursor.execute(sql, (username, hashed_pw))
                print(f">>> USUARIO CREADO: {username} (pass: 1234)")
            else:
                # Forzamos actualización del hash para asegurar que sea '1234'
                cursor.execute("UPDATE users SET password_hash = %s WHERE username = %s", (hashed_pw, username))
                print(f">>> USUARIO ACTUALIZADO: {username} sincronizado.")
            conn.commit()
        conn.close()
    except Exception as e:
        print(f">>> ERROR EN CREACIÓN AUTOMÁTICA: {e}")

# Cambia tu bloque final por este:
if __name__ == '__main__':
    create_admin_global_automatic()
    app.run(debug=True, port=5000)