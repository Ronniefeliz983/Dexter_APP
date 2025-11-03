import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
from streamlit_autorefresh import st_autorefresh
import numpy as np
from io import BytesIO
import os # Importado para la conexión

# --- NUEVOS IMPORTS PARA SUPABASE ---
from sqlalchemy import create_engine, text

# --- NUEVOS IMPORTS PARA PLOTLY ---
import plotly.express as px
import plotly.graph_objects as go
# ---------------------------------


# --------------------------
# Configuración de la página
# --------------------------
# El tema se carga desde .streamlit/config.toml
st.set_page_config(page_title="Dashboard Trabajos S - v2.6.17", layout="wide") # Título actualizado

# --- INICIA CÓDIGO NUEVO v2.6.13: CSS PARA MÓVILES ---
st.markdown("""
<style>
/* Media query para pantallas de celular (ej. 640px o menos) */
@media (max-width: 640px) {
    
    /* Apunta a los bloques de columnas (stHorizontalBlock).
    Les decimos que "envuelvan" los elementos (flex-wrap: wrap) 
    si no caben en una sola fila.
    */
    div[data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
    }
    
    /* Apunta a cada KPI individual (cada columna) DENTRO de un bloque horizontal.
    'flex: 1 1 150px' significa:
    - Crece si hay espacio (flex-grow: 1)
    - Encógete si no hay espacio (flex-shrink: 1)
    - Intenta tener 150px de ancho base (flex-basis: 150px)
    */
    div[data-testid="stHorizontalBlock"] > div[data-testid="stVerticalBlock"] {
        flex: 1 1 150px !important;
        min-width: 140px; /* Asegura un ancho mínimo para que no se aplaste */
    }
}
</style>
""", unsafe_allow_html=True)
# --- FIN DEL NUEVO CÓDIGO ---


# --------------------------
# Sistema de Login
# --------------------------
def verificar_login():
    """Maneja el sistema de inicio de sesión y roles de usuario."""
    usuarios = {
        "admin": {"password": "admin123", "role": "admin", "supervisor_id": None},
        "gerencia": {"password": "gerencia123", "role": "gerencia", "supervisor_id": None},
        "supervisor": {"password": "super123", "role": "supervisor_old", "supervisor_id": None},
        "601378": {"password": "1234", "role": "supervisor", "supervisor_id": "601378"},
        "601665": {"password": "1234", "role": "supervisor", "supervisor_id": "601665"},
        "601799": {"password": "1234", "role": "supervisor", "supervisor_id": "601799"},
        "61768": {"password": "1234", "role": "supervisor", "supervisor_id": "61768"},
        "juan_perez": {"password": "1234", "role": "supervisor", "supervisor_id": "601378"},
        "maria_gonzalez": {"password": "1234", "role": "supervisor", "supervisor_id": "601665"},
    }

    st.session_state.setdefault('logged_in', False)
    st.session_state.setdefault('username', None)
    st.session_state.setdefault('user_role', None)
    st.session_state.setdefault('supervisor_id', None)

    if not st.session_state.logged_in:
        st.title("🔐 Login - Dashboard Trabajos Dexter")
        with st.form("login_form"):
            usuario = st.text_input("👤 Usuario", placeholder="Ingresa tu usuario o ID supervisor")
            password = st.text_input("🔑 Contraseña", type="password", placeholder="Ingresa tu contraseña")
            submitted = st.form_submit_button("🚀 Iniciar Sesión")
            if submitted:
                if usuario in usuarios and usuarios[usuario]["password"] == password:
                    st.session_state.logged_in = True
                    st.session_state.username = usuario
                    st.session_state.user_role = usuarios[usuario]["role"]
                    st.session_state.supervisor_id = usuarios[usuario]["supervisor_id"]
                    st.rerun()
                else:
                    st.error("❌ Usuario o contraseña incorrectos")
        return False
    else:
        # Mensajes de bienvenida en la barra lateral
        role_display = {
            "admin": "Administración",
            "gerencia": "Gerencia",
            "supervisor_old": "Supervisor General"
        }.get(st.session_state.user_role, f"Supervisor {st.session_state.supervisor_id}")
        st.sidebar.success(f"👤 **{role_display}**")


        if st.sidebar.button("🚪 Cerrar Sesión"):
            for key in ['logged_in', 'username', 'user_role', 'supervisor_id']:
                st.session_state[key] = None if key != 'logged_in' else False
            st.rerun()
        return True

if not verificar_login():
    st.stop()

# --------------------------
# Auto-refresh
# --------------------------
st_autorefresh(interval=30 * 1000, key="data_refresh")

# --------------------------
# Funciones de Cálculo
# --------------------------
def calcular_pyme_y_vence(fecha_creacion):
    if pd.isna(fecha_creacion): return False, None
    ahora = datetime.now()
    hoy = ahora.date()
    ayer = hoy - timedelta(days=1)
    # Asegurarse que fecha_creacion es datetime
    if not isinstance(fecha_creacion, pd.Timestamp):
        fecha_creacion = pd.to_datetime(fecha_creacion, errors='coerce')
        if pd.isna(fecha_creacion): return False, None # Salir si la conversión falla

    fecha = fecha_creacion.date()
    hora = fecha_creacion.time()

    if fecha == hoy:
        return True, fecha_creacion + timedelta(hours=4)
    if fecha == ayer and hora >= time(18, 0):
        return True, datetime.combine(hoy, time(12, 0))
    return False, None

# --- INICIA CORRECCIÓN v2.6.15: ZONA HORARIA ---
def calcular_vencido(row):
    # Asegurarse que 'Vence en' es datetime
    vence_en_dt = pd.to_datetime(row.get('Vence en'), errors='coerce')
    estado = str(row.get('Estado','')).lower() # Convertir estado a string minúscula

    if pd.isna(vence_en_dt) or estado not in ['activo', 'iniciado']:
        return False

    # 1. Obtener la hora actual del servidor (que está en UTC)
    # Usamos utcnow() para ser explícitos
    ahora_utc = datetime.utcnow()
    
    # 2. Definir el offset de tu zona horaria (AST = UTC-4)
    zona_horaria_offset = timedelta(hours=-4)
    
    # 3. Aplicar el offset para obtener la hora local correcta
    ahora_ast = ahora_utc + zona_horaria_offset
    
    # 4. Esta es la hora "naive" (sin info de timezone) que usaremos para comparar
    ahora_naive = ahora_ast.replace(tzinfo=None)
    
    # --- FIN CORRECCIÓN ---

    # Hacer 'Vence en' naive para comparar
    vence_en_naive = vence_en_dt.tz_convert(None) if hasattr(vence_en_dt, 'tzinfo') and vence_en_dt.tzinfo is not None else vence_en_dt.replace(tzinfo=None)

    try:
        # Ahora la comparación SÍ será correcta (ej: 09:06 > 12:00 = Falso)
        return ahora_naive > vence_en_naive
    except TypeError: # En caso de que la conversión falle de alguna manera
        return False
# --- FIN FUNCIÓN CORREGIDA ---


# --- NUEVA FUNCIÓN CACHEADA (BASADA EN LOTE_PROCESADO) ---
@st.cache_data(ttl=300) # Cachear por 5 minutos
def get_earliest_batch_initial_cohort(df_full_historial):
    """
    Identifica los tickets que estaban 'activo' o 'iniciado' en el
    *primer lote procesado* (lote_procesado == min) del día.
    Devuelve un set de IDs (OrdenExterna).
    """
    
    # 1. Validar que los datos y las columnas necesarias existan
    if (df_full_historial is None or df_full_historial.empty or
        'OrdenExterna' not in df_full_historial.columns or
        'Estado' not in df_full_historial.columns or
        'lote_procesado' not in df_full_historial.columns): # <-- Chequear por 'lote_procesado'
        # st.warning("Historial inválido o falta 'lote_procesado' para cohort inicial.") # Debug
        return set() # Devuelve un set vacío si los datos no son válidos

    try:
        # 2. Asegurar que 'lote_procesado' es numérico y encontrar el mínimo
        lotes_numericos = pd.to_numeric(df_full_historial['lote_procesado'], errors='coerce')
        
        if lotes_numericos.isna().all():
            # st.warning("La columna 'lote_procesado' no contiene valores numéricos válidos.") # Debug
            return set()
            
        min_lote = lotes_numericos.min() # <-- LÓGICA: Encontrar el lote mínimo
        
        if pd.isna(min_lote):
            # st.warning("No se encontró un 'lote_procesado' mínimo.") # Debug
            return set()

        # 3. Obtener el "snapshot" exacto de ese *primer lote*
        df_earliest_batch = df_full_historial[lotes_numericos == min_lote].copy() # <-- LÓGICA
        
        if df_earliest_batch.empty:
            # st.warning(f"Snapshot vacío para lote {min_lote}.") # Debug
            return set()

        # 4. De ese snapshot, filtrar los que estaban 'activo' o 'iniciado'
        df_initial_active_in_snapshot = df_earliest_batch[
            df_earliest_batch['Estado'].astype(str).str.lower().isin(['activo', 'iniciado'])
        ]
        
        # 5. Devolver los IDs únicos de ese grupo inicial global
        initial_cohort_ids = set(df_initial_active_in_snapshot['OrdenExterna'].unique())
        # st.info(f"Cohorte inicial global (Lote {min_lote}): {len(initial_cohort_ids)} tickets") # Debug
        return initial_cohort_ids
        
    except Exception as e:
        st.error(f"Error en get_earliest_batch_initial_cohort: {e}") # Debug
        return set()


# --- KPI Calculation Function (MODIFICADA para REBOTE) ---
def calcular_kpis(df, df_full_historial):
    """
    Calcula los nuevos KPIs de gestión, usando el cohort del primer snapshot.
    df = DataFrame de estados únicos/actuales (filtrado por página/rol).
    df_full_historial = DataFrame con todo el historial del día.
    """
    # --- KPIs Estándar (basados en el estado actual/único) ---
    default_kpis = {
            'Total': 0,'Cerrados': 0,'Referidos': 0,'Citados': 0,
            'Rebote': 0,'Pendientes': 0,'Manejados': 0,'Eficiencia_Total_%': 0.0, # <-- CAMBIO A REBOTE
            'Total_Iniciado': 0, 'Manejados_Inicial': 0, 'Eficiencia_Inicial': 0.0
        }
    if df is None or df.empty or 'Estado' not in df.columns or 'OrdenExterna' not in df.columns:
        return default_kpis
    
    df_kpi = df.copy()
    df_kpi['Estado'] = df_kpi['Estado'].fillna('desconocido').astype(str).str.lower()

    total = len(df_kpi)
    cerrados = df_kpi[df_kpi['Estado'].isin(['cerrado', 'validacion ext'])].shape[0]
    referidos = df_kpi[df_kpi['Estado'] == 'pend trab interno'].shape[0]
    citados = df_kpi[df_kpi['Estado'].isin(['pendiente de calendarizacion', 'calendarizado'])].shape[0]
    rebote = df_kpi[df_kpi['Estado'] == 'validacion int'].shape[0] # <-- CAMBIO A REBOTE
    pendientes = df_kpi[df_kpi['Estado'].isin(['activo', 'iniciado'])].shape[0]
    manejados = cerrados + referidos + citados + rebote # <-- CAMBIO A REBOTE
    eficiencia_total = round(manejados * 100 / total, 1) if total > 0 else 0.0

    # --- KPIs Nuevos (Total_Iniciado y Eficiencia_Inicial) ---
    total_iniciado_en_pagina = 0
    manejados_inicial_en_pagina = 0
    eficiencia_inicial = 0.0

    # 1. Obtener el "grupo" global de IDs del *primer LOTE*
    global_initial_cohort_ids = get_earliest_batch_initial_cohort(df_full_historial) # <-- Llama a la función de lote

    if global_initial_cohort_ids: # Solo proceder si el cohort global no está vacío
        try:
            # 2. Obtener los tickets en la *página actual* (filtrada por supervisor, etc.)
            tickets_en_pagina_actual_ids = set(df_kpi['OrdenExterna'].unique())

            # 3. Encontrar la INTERSECCIÓN: Tickets del cohort inicial global que están en esta página.
            cohort_tickets_in_current_page_ids = global_initial_cohort_ids.intersection(tickets_en_pagina_actual_ids)
            
            # Este es el KPI 'Total Iniciado' para esta página (Ej: 664)
            total_iniciado_en_pagina = len(cohort_tickets_in_current_page_ids)

            if total_iniciado_en_pagina > 0:
                # 4. Obtener el *estado actual* (de df_kpi) de *solo* ese grupo intersectado
                df_kpi_del_cohort_intersectado = df_kpi[df_kpi['OrdenExterna'].isin(cohort_tickets_in_current_page_ids)]

                # 5. Contar cuántos de *ese grupo intersectado* están ahora manejados
                cerrados_inicial = df_kpi_del_cohort_intersectado[df_kpi_del_cohort_intersectado['Estado'].isin(['cerrado', 'validacion ext'])].shape[0]
                referidos_inicial = df_kpi_del_cohort_intersectado[df_kpi_del_cohort_intersectado['Estado'] == 'pend trab interno'].shape[0]
                citados_inicial = df_kpi_del_cohort_intersectado[df_kpi_del_cohort_intersectado['Estado'].isin(['pendiente de calendarizacion', 'calendarizado'])].shape[0]
                rebote_inicial = df_kpi_del_cohort_intersectado[df_kpi_del_cohort_intersectado['Estado'] == 'validacion int'].shape[0] # <-- CAMBIO A REBOTE
                
                manejados_inicial_en_pagina = cerrados_inicial + referidos_inicial + citados_inicial + rebote_inicial # <-- CAMBIO A REBOTE
                
                # 6. Calcular Eficiencia_Inicial (Manejados de este grupo / Total de este grupo)
                eficiencia_inicial = round(manejados_inicial_en_pagina * 100 / total_iniciado_en_pagina, 1)

        except Exception as e:
            st.error(f"Error calculando KPIs iniciales: {e}") # Debug
            total_iniciado_en_pagina = 0
            manejados_inicial_en_pagina = 0
            eficiencia_inicial = 0.0

    return {
        'Total': total,
        'Cerrados': cerrados,
        'Referidos': referidos,
        'Citados': citados,
        'Rebote': rebote, # <-- CAMBIO A REBOTE
        'Pendientes': pendientes,
        'Manejados': manejados,
        'Eficiencia_Total_%': eficiencia_total,
        'Total_Iniciado': total_iniciado_en_pagina, 
        'Manejados_Inicial': manejados_inicial_en_pagina, 
        'Eficiencia_Inicial': eficiencia_inicial 
    }
# --- End of KPI Calculation Function ---


# ==============================================================================
# --- NUEVAS FUNCIONES: Conexión Supabase y Mapeo de Columnas ---
# ==============================================================================

@st.cache_resource # Cachear la conexión
def get_database_engine():
    """
    Crea una conexión a Supabase usando st.secrets (local) 
    o variables de entorno (Render).
    """
    DATABASE_URL = ""
    try:
        # 1. Intentar leer de st.secrets (para .streamlit/secrets.toml local)
        DATABASE_URL = st.secrets["postgres"]["DATABASE_URL"]
        # print("Conectado vía secrets.toml (local)") # Para depurar
    except Exception:
        # 2. Si falla, intentar leer de una variable de entorno (para Render)
        DATABASE_URL = os.environ.get("DATABASE_URL")
        # if DATABASE_URL:
        #     print("Conectado vía Environment Variable (Render)") # Para depurar

    if not DATABASE_URL:
        st.error("⚠️ No se encontró la 'DATABASE_URL'.")
        st.error("Asegúrate de crear .streamlit/secrets.toml (local) O añadir DATABASE_URL en las 'Environment Variables' de Render.")
        st.stop() # Detener la app si no hay DB
        return None

    try:
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={'options': '-csearch_path=public'}
        )
        # Probar la conexión
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        # st.sidebar.success("✅ Conectado a Supabase") # Movido a la lógica principal para evitar duplicados
        return engine
    except Exception as e:
        st.error(f"⚠️ Error conectando a Supabase: {e}")
        st.error("Verifica tu DATABASE_URL en st.secrets o en las variables de entorno de Render.")
        st.stop() # Detener la app si la conexión falla
        return None

# --------------------------
# Mapeo de Columnas (MODIFICADO para lote_procesado)
# --------------------------

def get_column_mappings():
    """Devuelve el mapeo de nombres SQL a nombres CSV (PascalCase)."""
    # Nombres de Supabase (SQL) a Nombres del Dashboard (CSV/Pandas)
    reverse_mapping = {
        'trabajo': 'Trabajo', 'orden_externa': 'OrdenExterna', 'cliente': 'Cliente', 'vence': 'Vence',
        'oe_creacion': 'OE_Creacion', 'oe_vence': 'OE_Vence', 'oe_vencimiento': 'OE_Vencimiento',
        'prioridad': 'Prioridad', 'tipo_de_prioridad': 'Tipo_de_prioridad', 'calendarizada': 'Calendarizada',
        'tanda_preferida': 'Tanda_preferida', 'reclamacion': 'Reclamacion', 'asignado_a': 'Asignado_A',
        'compania': 'Compania', 'supervisor': 'Supervisor', 'pool': 'Pool', 'estado': 'Estado',
        'tecnologia': 'Tecnologia', 'tipo_servicio': 'Tipo_servicio', 'organizacion': 'Organizacion',
        'sintoma': 'Sintoma', 'creado': 'Creado', 'tipo_cliente': 'Tipo_Cliente', 'segmento_cliente': 'Segmento_Cliente',
        'ciudad': 'Ciudad', 'sector': 'Sector', 'barrio': 'Barrio', 'cabina': 'Cabina', 'terminal': 'Terminal',
        'cantidad_de_lineas': 'Cantidad_de_lineas', 're_digitada': 'Re_Digitada', 'timestamp_procesado': 'Timestamp_Procesado',
        'fuente_paso': 'Fuente_Paso', 'tipo_evento': 'Tipo_Evento',
        
        # --- AÑADIDO POR SOLICITUD ---
        'lote_procesado': 'lote_procesado', # Mapea 'lote_procesado' (SQL) a 'lote_procesado' (Pandas)
        # ---------------------------
        
        # Ignorar columnas de DB que no usa el dashboard
        'id': None, 'fecha_actualizacion': None, 'fecha_registro': None
    }
    return reverse_mapping

COLUMN_MAPPING_REVERSE = get_column_mappings()

def denormalizar_columnas_desde_sql(df_sql):
    """Renombra columnas de formato SQL (snake_case) a formato CSV (PascalCase)."""
    if df_sql is None or df_sql.empty:
        return df_sql
    
    # Filtrar mapeos que no son None
    mapeo_valido = {k: v for k, v in COLUMN_MAPPING_REVERSE.items() if v is not None}
    
    # Seleccionar solo las columnas que existen en el DF y están en el mapeo
    columnas_a_renombrar = {k: v for k, v in mapeo_valido.items() if k in df_sql.columns}
    
    # Renombrar
    df_csv = df_sql.rename(columns=columnas_a_renombrar)
    
    # Devolver solo las columnas que espera el dashboard (las que están en los values del mapeo)
    columnas_esperadas_presentes = [v for v in mapeo_valido.values() if v in df_csv.columns]
    
    return df_csv[columnas_esperadas_presentes]

# --------------------------
# Carga y Procesamiento de Datos (MODIFICADO PARA SUPABASE)
# --------------------------
@st.cache_data(ttl=60) # Cachear los datos por 60 segundos
def cargar_datos():
    """Carga datos desde la tabla historial_cambios_hoy de Supabase."""
    
    engine = get_database_engine()
    if engine is None:
        st.error("No hay conexión a la base de datos. No se pueden cargar datos.")
        return pd.DataFrame() # Retornar DF vacío

    try:
        # 1. Cargar datos desde Supabase
        # print("Iniciando carga desde Supabase...") # Debug
        query = text("SELECT * FROM historial_cambios_hoy") # Usar text()
        with engine.connect() as conn:
            df_sql = pd.read_sql(query, conn)
        # print(f"Datos cargados desde SQL: {df_sql.shape}") # Debug
        
        if df_sql.empty:
            st.warning("La tabla 'historial_cambios_hoy' está vacía.")
            return pd.DataFrame()

        # 2. Convertir nombres de columnas (ej. orden_externa -> OrdenExterna)
        df = denormalizar_columnas_desde_sql(df_sql)
        # print(f"Columnas denormalizadas: {df.columns.tolist()}") # Debug
        
        if df.empty:
            st.error("Error al mapear columnas de Supabase. El DataFrame quedó vacío.")
            return pd.DataFrame()

    except Exception as e:
        st.error(f"❌ Error al cargar datos desde Supabase: {e}")
        return pd.DataFrame()

    # --- INICIO: Lógica de procesamiento existente (antes en cargar_datos) ---
    
    # 3. Limpieza básica de columnas de texto (las más importantes)
    # (El resto de la limpieza se hace en las funciones de cálculo si es necesario)
    df.columns = df.columns.str.strip()
    
    columnas_texto_clave = ['Supervisor', 'Estado', 'Tipo_Cliente', 'Tipo_servicio', 'Asignado_A', 'Prioridad']
    for col in df.columns.intersection(columnas_texto_clave):
        df[col] = df[col].astype(str).str.strip().str.lower().replace('nan', None).replace('<na>', None).replace('none', None)

    # 4. Procesamiento de columnas de fecha
    columnas_fechas_a_procesar = ['Creado', 'OE_Creacion', 'OE Vence', 'OE_Vencimiento', 'Vence', 'Timestamp_Procesado']
    for col in df.columns.intersection(columnas_fechas_a_procesar):
        # Guardar la versión original (ya es string o NaT de la DB)
        df[f'{col}_Original'] = df[col].astype(str).replace('NaT', None)
        # Convertir a datetime (manejando strings, NaT, etc.)
        df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True, format='mixed')

    # 5. Calcular PYME, Vencido, etc. (la lógica que ya tenías)
    if 'OE_Creacion' in df.columns and pd.api.types.is_datetime64_any_dtype(df['OE_Creacion']) and not df['OE_Creacion'].isna().all():
        # Aplicar solo a filas no-NaT
        mask_valid_oe = df['OE_Creacion'].notna()
        if mask_valid_oe.any():
            pyme_info = df.loc[mask_valid_oe, 'OE_Creacion'].apply(lambda x: pd.Series(calcular_pyme_y_vence(x), index=['PYME', 'Vence en']))
            df.loc[mask_valid_oe, ['PYME', 'Vence en']] = pyme_info.values

            df['Vence en'] = pd.to_datetime(df['Vence en'], errors='coerce')
            mask_valid_vence = df['Vence en'].notna()
            if mask_valid_vence.any():
                df.loc[mask_valid_vence, 'Vencido'] = df[mask_valid_vence].apply(calcular_vencido, axis=1).astype(bool)

            es_negocio = df.get('Tipo_Cliente', pd.Series(dtype=str)) == 'negocio'
            df['PYME'] = df['PYME'].fillna(False).astype(bool)
            df['Es_PYME_Negocio'] = df['PYME'] & es_negocio
        else:
            df['PYME'] = False
            df['Vence en'] = pd.NaT
            df['Vencido'] = False
            df['Es_PYME_Negocio'] = False
    else:
        df['PYME'] = False
        df['Vence en'] = pd.NaT
        df['Vencido'] = False
        df['Es_PYME_Negocio'] = False

    # Asegurarse de que 'Vencido' exista y sea booleano
    if 'Vencido' not in df.columns:
        df['Vencido'] = False
    else:
        df['Vencido'] = df['Vencido'].fillna(False).astype(bool)
    
    # print(f"Datos procesados listos para el dashboard: {df.shape}") # Debug
    return df

# --- FIN DE LA LÓGICA DE CARGA MODIFICADA ---


# Carga inicial de datos
df = cargar_datos()

# Manejo si la carga inicial falla completamente
if df is None or df.empty:
    st.error("No se pudieron cargar datos. Verifica la conexión a Supabase y que la tabla 'historial_cambios_hoy' no esté vacía.")
    st.stop()


# -----------------------------------------------
# Funciones para obtener y formatear datos
# -----------------------------------------------
def obtener_datos_unicos(df_input):
    if df_input is None or df_input.empty:
        return df_input

    if 'OrdenExterna' not in df_input.columns:
        st.error("Columna 'OrdenExterna' no encontrada. No se pueden obtener datos únicos.")
        return pd.DataFrame(columns=df_input.columns)

    ts_col_valid = ('Timestamp_Procesado' in df_input.columns and
                    pd.api.types.is_datetime64_any_dtype(df_input['Timestamp_Procesado']) and
                    not df_input['Timestamp_Procesado'].isna().all())

    if not ts_col_valid:
        df_temp = df_input.dropna(subset=['OrdenExterna'])
        result = df_temp.drop_duplicates(subset=['OrdenExterna'], keep='first')
        return result
    else:
        df_temp = df_input.dropna(subset=['OrdenExterna'])
        if not pd.api.types.is_datetime64_any_dtype(df_temp['Timestamp_Procesado']):
            df_temp['Timestamp_Procesado'] = pd.to_datetime(df_temp['Timestamp_Procesado'], errors='coerce')
        df_temp_valid_ts = df_temp.dropna(subset=['Timestamp_Procesado'])
        df_sorted = df_temp_valid_ts.sort_values('Timestamp_Procesado', ascending=False)
        result = df_sorted.drop_duplicates(subset=['OrdenExterna'], keep='first')
        return result


def formatear_para_display(df_input):
    if df_input is None or df_input.empty:
        return df_input
    df_display = df_input.copy()
    
    # Definir columnas de fecha (las que existen en el DF)
    columnas_fechas_a_procesar = [
        'Creado', 'OE_Creacion', 'OE Vence', 'OE_Vencimiento', 'Vence en', 'Timestamp_Procesado', 'fecha_registro'
    ]
    columnas_fechas_presentes = df_display.columns.intersection(columnas_fechas_a_procesar)

    for col in columnas_fechas_presentes:
        # Formatear si la columna es de tipo datetime y no es todo NaT
        if pd.api.types.is_datetime64_any_dtype(df_display[col]) and not df_display[col].isna().all():
            try:
                df_display[col] = df_display[col].apply(lambda x: x.strftime('%d/%m/%Y %H:%M') if pd.notna(x) else None)
            except Exception as e:
                try:
                    df_display[col] = df_display[col].astype(str).replace('NaT', None).replace('nan', None).replace('<NA>', None)
                except Exception:
                    df_display[col] = None
        else: # Si no es datetime (quizás ya es string o tiene originales)
            try:
                df_display[col] = df_display[col].apply(lambda x: str(x) if pd.notna(x) else None)
                df_display[col] = df_display[col].replace('nan', None).replace('NaT', None).replace('<NA>', None).replace('None',None)
            except Exception:
                df_display[col] = None

    # Convertir todas las columnas restantes a string para asegurar consistencia
    for col in df_display.columns:
        if col not in columnas_fechas_presentes:
            try:
                if col == 'Vencido' and df_display[col].dtype == 'bool':
                    df_display[col] = df_display[col].map({True: 'Sí', False: 'No'}).fillna('No')
                else:
                    df_display[col] = df_display[col].apply(lambda x: str(x) if pd.notna(x) else None)
                    df_display[col] = df_display[col].replace('nan', None).replace('<NA>', None).replace('None', None).replace('None ', None)
            except Exception:
                df_display[col] = None

    return df_display


def to_excel(df: pd.DataFrame):
    """Convierte un DataFrame a un archivo Excel en memoria."""
    if df is None or df.empty:
        return None

    output = BytesIO()
    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_formateada = formatear_para_display(df.copy())
            df_formateada.to_excel(writer, index=False, sheet_name='Datos')
        processed_data = output.getvalue()
        return processed_data
    except Exception as e:
        st.error(f"Error al generar el archivo Excel: {e}")
        return None

def crear_resumen_admin(df, agrupar_por='Supervisor'):
    """Crea tabla de resumen para el rol de Administración."""
    # MODIFICADO: Añade fila de TOTAL al final y cambia a Rebote
    
    cols = [agrupar_por, 'Total', 'Cerrados', 'Referidos', 'Citados', 'Rebote', 'Pendientes', 'Total Manejado', 'Eficiencia_Total_%'] # <-- CAMBIO A REBOTE
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    if agrupar_por not in df.columns or 'OrdenExterna' not in df.columns or 'Estado' not in df.columns:
        st.warning(f"Faltan columnas esenciales ('{agrupar_por}', 'OrdenExterna', 'Estado') para crear el resumen.")
        return pd.DataFrame(columns=cols)

    df_copy = df.copy()
    df_copy[agrupar_por] = df_copy[agrupar_por].fillna('Desconocido').astype(str)
    df_copy['Estado'] = df_copy['Estado'].fillna('Desconocido').astype(str).str.lower()

    resumen = df_copy.groupby(agrupar_por).agg(
        Total=('OrdenExterna', 'count'),
        Cerrados=('Estado', lambda x: x.isin(['cerrado', 'validacion ext']).sum()),
        Referidos=('Estado', lambda x: (x == 'pend trab interno').sum()),
        Citados=('Estado', lambda x: x.isin(['pendiente de calendarizacion', 'calendarizado']).sum()),
        Rebote=('Estado', lambda x: (x == 'validacion int').sum()), # <-- CAMBIO A REBOTE
        Pendientes=('Estado', lambda x: x.isin(['activo', 'iniciado']).sum())
    ).reset_index()

    resumen['Total Manejado'] = resumen['Cerrados'] + resumen['Referidos'] + resumen['Citados'] + resumen['Rebote'] # <-- CAMBIO A REBOTE
    resumen['Eficiencia_Total_%'] = np.where(resumen['Total'] > 0,
                                         round(resumen['Total Manejado'] * 100 / resumen['Total'], 1),
                                         0.0)
    
    # --- NUEVO: Añadir fila de TOTAL ---
    if not resumen.empty:
        total_row = pd.Series(name='Total')
        total_row[agrupar_por] = 'TOTAL'
        total_row['Total'] = resumen['Total'].sum()
        total_row['Cerrados'] = resumen['Cerrados'].sum()
        total_row['Referidos'] = resumen['Referidos'].sum()
        total_row['Citados'] = resumen['Citados'].sum()
        total_row['Rebote'] = resumen['Rebote'].sum() # <-- CAMBIO A REBOTE
        total_row['Pendientes'] = resumen['Pendientes'].sum()
        total_row['Total Manejado'] = resumen['Total Manejado'].sum()
        
        # Calcular Eficiencia Total General
        total_manejado_general = total_row['Total Manejado']
        total_general = total_row['Total']
        total_row['Eficiencia_Total_%'] = round(total_manejado_general * 100 / total_general, 1) if total_general > 0 else 0.0
        
        # Convertir a DataFrame antes de concatenar
        resumen = pd.concat([resumen, total_row.to_frame().T], ignore_index=True)
    # --- FIN DEL NUEVO CÓDIGO ---

    return resumen


def filtrar_dataframe(df_input, texto_busqueda):
    """Filtra el dataframe por texto de búsqueda en todas las columnas."""
    if df_input is None or df_input.empty or not texto_busqueda:
        return df_input

    texto_busqueda = texto_busqueda.lower()
    try:
        mask = df_input.apply(lambda col: col.astype(str).str.lower().str.contains(texto_busqueda, na=False)).any(axis=1)
        return df_input[mask]
    except Exception as e:
        st.error(f"Error durante el filtrado: {e}")
        return df_input


def filtrar_dataframe_con_historial(df_completo, df_unicos_filtrados, texto_busqueda, supervisor_filter=None, estado_filter=None):
    """
    Filtra y muestra el historial completo de tickets que coinciden con la búsqueda.
    """
    if df_completo is None or df_completo.empty:
        return pd.DataFrame()

    if not texto_busqueda:
        return df_unicos_filtrados if df_unicos_filtrados is not None else pd.DataFrame(columns=df_completo.columns)

    df_para_buscar = df_completo if df_unicos_filtrados is None or df_unicos_filtrados.empty else df_unicos_filtrados

    texto_busqueda = texto_busqueda.lower()
    cols_busqueda = ['OrdenExterna', 'Asignado_A', 'Cliente', 'Supervisor']
    cols_presentes = [col for col in cols_busqueda if col in df_para_buscar.columns]

    if not cols_presentes or 'OrdenExterna' not in df_para_buscar.columns:
        st.warning("Columnas clave no encontradas para búsqueda.")
        return pd.DataFrame(columns=df_completo.columns)

    try:
        mask = df_para_buscar[cols_presentes].astype(str).apply(lambda x: x.str.lower().str.contains(texto_busqueda, na=False)).any(axis=1)
    except Exception as e:
        st.error(f"Error al aplicar filtro de búsqueda: {e}")
        return pd.DataFrame(columns=df_completo.columns)

    tickets_encontrados = df_para_buscar[mask]['OrdenExterna'].unique()

    if len(tickets_encontrados) == 0:
        return pd.DataFrame(columns=df_completo.columns)

    if 'OrdenExterna' not in df_completo.columns:
        st.error("Error crítico: df_completo no tiene 'OrdenExterna'.")
        return pd.DataFrame(columns=df_completo.columns)

    df_historial = df_completo[df_completo['OrdenExterna'].isin(tickets_encontrados)].copy()

    if supervisor_filter and 'Supervisor' in df_historial.columns:
        df_historial = df_historial[df_historial['Supervisor'].astype(str) == str(supervisor_filter)]

    ts_col_valid_hist = ('Timestamp_Procesado' in df_historial.columns and
                         pd.api.types.is_datetime64_any_dtype(df_historial['Timestamp_Procesado']))

    if ts_col_valid_hist:
        df_historial = df_historial.sort_values(['OrdenExterna', 'Timestamp_Procesado'], ascending=[True, False], na_position='last')
    elif 'OrdenExterna' in df_historial.columns:
        df_historial = df_historial.sort_values('OrdenExterna')

    return df_historial


# -----------------------------------------------
# FUNCIONES DE AYUDA PARA PÁGINA DE TRACKING
# -----------------------------------------------
def get_color_estado(estado_str):
    estado_str = str(estado_str).lower()
    if estado_str in ['cerrado', 'validacion ext']:
        return '#32CD32' # Verde
    elif estado_str in ['pendiente de calendarizacion', 'calendarizado']:
        return '#FFD700' # Amarillo
    elif estado_str == 'pend trab interno':
        return '#FFA500' # Naranja
    elif estado_str in ['activo', 'iniciado']:
        return '#1E90FF' # Azul Dodger
    elif estado_str == 'validacion int': # <-- Este sigue siendo el estado 'validacion int'
        return '#8A2BE2' # Azul Violeta
    else:
        return '#696969' # Gris oscuro para otros

def formatear_fecha(fecha_dt):
    if pd.isna(fecha_dt):
        return 'N/A'
    if isinstance(fecha_dt, pd.Timestamp):
        return fecha_dt.strftime('%d/%m/%Y %H:%M')
    return str(fecha_dt) # Fallback para otros tipos

def calcular_tiempo_transcurrido(fecha_inicio):
    if pd.isna(fecha_inicio):
        return 'N/A'
    if not isinstance(fecha_inicio, pd.Timestamp):
        fecha_inicio = pd.to_datetime(fecha_inicio, errors='coerce')
        if pd.isna(fecha_inicio):
            return 'N/A'

    # --- INICIA CORRECCIÓN v2.6.15: ZONA HORARIA ---
    # 1. Obtener la hora actual del servidor (que está en UTC)
    ahora_utc = datetime.utcnow()
    # 2. Definir el offset de tu zona horaria (AST = UTC-4)
    zona_horaria_offset = timedelta(hours=-4)
    # 3. Aplicar el offset para obtener la hora local correcta
    ahora_ast = ahora_utc + zona_horaria_offset
    # 4. Esta es la hora "naive" (sin info de timezone) que usaremos para comparar
    ahora_naive = ahora_ast.replace(tzinfo=None)
    # --- FIN CORRECCIÓN ---

    # Asegurarse de que fecha_inicio es naive
    fecha_inicio_naive = fecha_inicio.tz_convert(None) if hasattr(fecha_inicio, 'tzinfo') and fecha_inicio.tzinfo is not None else fecha_inicio.replace(tzinfo=None)

    if ahora_naive < fecha_inicio_naive:
        return "Futuro"

    diferencia = ahora_naive - fecha_inicio_naive
    dias = diferencia.days
    horas = diferencia.seconds // 3600
    minutos = (diferencia.seconds % 3600) // 60

    if dias > 0:
        return f"{dias}d {horas}h {minutos}m"
    elif horas > 0:
        return f"{horas}h {minutos}m"
    else:
        return f"{minutos}m"

# ------------------------------------
# NUEVAS FUNCIONES DE RENDERIZADO (KPIs, Tabla Detalle)
# ------------------------------------

# --- MODIFICADO: Esta función ahora es CONDICIONAL y usa REBOTE ---
def display_kpi_metrics(kpis, page_key, critical_metric_key=None, critical_delta_text="Críticos"):
    """
    Muestra la cuadrícula de KPIs.
    - Muestra 10 KPIs en la página 'principal'.
    - Muestra 8 KPIs en las demás páginas.
    """

    # --- Helper function, interna a la principal ---
    def metric_with_critical(col, label, key, delta_text=None, delta_color="normal"):
        value_to_display = kpis.get(key, 0)
        if not isinstance(value_to_display, (int, float)): value_to_display = 0

        if key == critical_metric_key and value_to_display > 0:
            col.metric(label, value_to_display, delta=critical_delta_text, delta_color="inverse")
        elif key == critical_metric_key and value_to_display <= 0 :
            col.metric(label, value_to_display)
        else:
            col.metric(label, value_to_display)
    # --- Fin del Helper ---

    # --- VISTA PARA PÁGINA PRINCIPAL (10 KPIs) ---
    if page_key == "principal":
        col1, col2, col3, col4, col5 = st.columns(5)
        
        if st.session_state.user_role == "admin":
            # Fila 1
            metric_with_critical(col1, "📋 Total", 'Total', critical_metric_key == 'Total')
            metric_with_critical(col2, "⏳ Pendientes", 'Pendientes', critical_metric_key == 'Pendientes')
            metric_with_critical(col3, "🚀 Total Iniciado", 'Total_Iniciado')
            metric_with_critical(col4, "✅ Cerrados", 'Cerrados')
            metric_with_critical(col5, "🔄 Total Manejado", 'Manejados')

            # Fila 2
            col6, col7, col8, col9, col10 = st.columns(5)
            eficiencia_valor = kpis.get('Eficiencia_Total_%', 0.0)
            col6.metric("📊 Eficiencia Total", f"{eficiencia_valor:.1f}%")
            eficiencia_ini_valor = kpis.get('Eficiencia_Inicial', 0.0)
            col7.metric("📈 Eficiencia Inicial", f"{eficiencia_ini_valor:.1f}%")
            metric_with_critical(col8, "📤 Referidos", 'Referidos')
            metric_with_critical(col9, "📅 Citados", 'Citados')
            metric_with_critical(col10, "🔄 Rebote", 'Rebote') # <-- CAMBIO A REBOTE
            
        else: # Vista Gerencia / Supervisor en 'Principal'
            # Fila 1
            metric_with_critical(col1, "📋 Total", 'Total', critical_metric_key == 'Total')
            metric_with_critical(col2, "⏳ Pendientes", 'Pendientes', critical_metric_key == 'Pendientes')
            metric_with_critical(col3, "🚀 Total Iniciado", 'Total_Iniciado')
            metric_with_critical(col4, "✅ Cerrados", 'Cerrados')
            metric_with_critical(col5, "📤 Referidos", 'Referidos')

            # Fila 2
            col6, col7, col8, col9, col10 = st.columns(5)
            metric_with_critical(col6, "📅 Citados", 'Citados')
            metric_with_critical(col7, "🔄 Rebote", 'Rebote') # <-- CAMBIO A REBOTE
            metric_with_critical(col8, "🔄 Total Manejado", 'Manejados')
            eficiencia_valor = kpis.get('Eficiencia_Total_%', 0.0)
            col9.metric("📊 Eficiencia Total", f"{eficiencia_valor:.1f}%")
            eficiencia_ini_valor = kpis.get('Eficiencia_Inicial', 0.0)
            col10.metric("📈 Eficiencia Inicial", f"{eficiencia_ini_valor:.1f}%")
            
    # --- VISTA PARA OTRAS PÁGINAS (8 KPIs) ---
    else: 
        col1, col2, col3, col4 = st.columns(4)
        
        if st.session_state.user_role == "admin":
            metric_with_critical(col1, "📋 Total", 'Total', critical_metric_key == 'Total')
            eficiencia_valor = kpis.get('Eficiencia_Total_%', 0.0)
            col2.metric("📊 Eficiencia", f"{eficiencia_valor:.1f}%")
            metric_with_critical(col3, "✅ Cerrados", 'Cerrados')
            metric_with_critical(col4, "⏳ Pendientes", 'Pendientes', critical_metric_key == 'Pendientes')

            col5, col6, col7, col8 = st.columns(4)
            metric_with_critical(col5, "🔄 Total Manejado", 'Manejados')
            metric_with_critical(col6, "📤 Referidos", 'Referidos')
            metric_with_critical(col7, "📅 Citados", 'Citados')
            metric_with_critical(col8, "🔄 Rebote", 'Rebote') # <-- CAMBIO A REBOTE
            
        else: # Gerencia / Supervisor en otras páginas
            metric_with_critical(col1, "📋 Total", 'Total', critical_metric_key == 'Total')
            metric_with_critical(col2, "⏳ Pendientes", 'Pendientes', critical_metric_key == 'Pendientes')
            metric_with_critical(col3, "✅ Cerrados", 'Cerrados')
            metric_with_critical(col4, "📤 Referidos", 'Referidos')

            col5, col6, col7, col8 = st.columns(4)
            metric_with_critical(col5, "📅 Citados", 'Citados')
            metric_with_critical(col6, "🔄 Rebote", 'Rebote') # <-- CAMBIO A REBOTE
            metric_with_critical(col7, "🔄 Total Manejado", 'Manejados')
            eficiencia_valor = kpis.get('Eficiencia_Total_%', 0.0)
            col8.metric("📊 Eficiencia", f"{eficiencia_valor:.1f}%")


def display_detail_table(df_data, df_full_historial, role, role_supervisor_id, global_supervisor_sel, status_filter, page_key, file_name_prefix):
    """Muestra la barra de búsqueda, la tabla de detalles y el botón de descarga."""

    busqueda_key = f"buscar_{page_key}"
    texto_busqueda = st.text_input("🔍 Buscar en tabla", key=busqueda_key, placeholder="Buscar por Orden Externa, Cliente, Asignado...")

    df_display_original = formatear_para_display(df_data.copy() if df_data is not None else pd.DataFrame())

    if texto_busqueda:
        supervisor_filter = None
        if role == "supervisor":
            supervisor_filter = role_supervisor_id
        elif role in ["admin", "gerencia", "supervisor_old"] and global_supervisor_sel != "Todos":
            supervisor_filter = global_supervisor_sel

        df_display_filtrado = filtrar_dataframe_con_historial(df_full_historial, df_data, texto_busqueda, supervisor_filter, status_filter)
        df_display_final = formatear_para_display(df_display_filtrado)
    else:
        df_display_final = df_display_original

    st.dataframe(df_display_final, use_container_width=True, hide_index=True)

    if not df_display_original.empty:
        excel_data = to_excel(df_display_original)
        if excel_data:
            st.download_button(
                label="📥 Descargar Detalle como Excel",
                data=excel_data,
                file_name=f"{file_name_prefix}_{global_supervisor_sel}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

# --- NUEVA FUNCIÓN v2.6.13 ---
def render_hourly_efficiency_chart(df_page_data, df_full_historial, chart_key="hourly_efficiency_chart"):
    """Calcula y renderiza el gráfico de eficiencia por hora."""
    st.markdown("---")
    st.subheader("⏱️ Eficiencia por Hora del Día (Según Timestamp)")
    try:
        df_grafico = df_page_data.copy()
        df_grafico['Hora'] = df_grafico['Timestamp_Procesado'].dt.hour
        
        def agg_kpis_por_hora(group):
            # Usamos 'df_full_historial' para obtener el cohort inicial
            kpis_group = calcular_kpis(group, df_full_historial) 
            return pd.Series(kpis_group)

        # Aplicar la función de kpis a cada grupo de hora
        resumen_hora = df_grafico.groupby('Hora').apply(agg_kpis_por_hora).reset_index()

        # Asegurarse de que las columnas de eficiencia existan
        if 'Eficiencia_Total_%' not in resumen_hora.columns:
            resumen_hora['Eficiencia_Total_%'] = 0.0
        if 'Eficiencia_Inicial' not in resumen_hora.columns:
            resumen_hora['Eficiencia_Inicial'] = 0.0

        # Completar horas faltantes con 0 para un gráfico continuo
        horas_completas = pd.DataFrame({'Hora': range(24)})
        resumen_hora = pd.merge(horas_completas, resumen_hora, on='Hora', how='left').fillna(0)

        # Preparar para Plotly (melt)
        resumen_hora_melted = resumen_hora.melt(
            id_vars=['Hora'],
            value_vars=['Eficiencia_Total_%', 'Eficiencia_Inicial'],
            var_name='Tipo de Eficiencia',
            value_name='Eficiencia'
        )

        fig_linea_eficiencia = px.line(
            resumen_hora_melted,
            x='Hora',
            y='Eficiencia',
            color='Tipo de Eficiencia',
            title="Eficiencia por Hora (Total vs. Inicial)",
            markers=True,
            text='Eficiencia'
        )
        
        fig_linea_eficiencia.update_traces(texttemplate='%{text:.1f}%', textposition='top center')
        fig_linea_eficiencia.update_layout(
            xaxis_title="Hora del Día (0-23)",
            yaxis_title="Eficiencia (%)",
            xaxis=dict(tickmode='linear', dtick=1, range=[-0.5, 23.5]),
            yaxis=dict(range=[0, 105]),
            template="plotly_dark",
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            legend_title_text=''
        )
        # --- CORRECCIÓN v2.6.14 ---
        st.plotly_chart(fig_linea_eficiencia, use_container_width=True, key=chart_key)

    except Exception as e:
        st.error(f"Error al generar el gráfico de línea de eficiencia: {e}")
        st.error(traceback.format_exc()) # <-- Más detalle del error
# --- FIN NUEVA FUNCIÓN ---


# --- Render Dashboard Function (MODIFICADO para gráficos de Admin y v2.6.14) ---
def render_dashboard_page(title_prefix, df_page_data, df_full_historial, role, role_supervisor_id, global_supervisor_sel, status_filter, page_key, critical_metric_key=None):
    """
    Función genérica para renderizar una página del dashboard.
    Maneja la lógica de KPIs y resúmenes por rol.
    """
    # Chequeo robusto de df_page_data
    if df_page_data is None or df_page_data.empty:
        st.warning(f"No hay tickets para mostrar en '{title_prefix}' con los filtros actuales.")
        st.info("Ajusta los filtros de Supervisor o Estado si es necesario.")
        return

    # Calcular KPIs *antes* de los chequeos de rol
    kpis = calcular_kpis(df_page_data, df_full_historial)

    # --- Vista Admin ---
    if role == "admin":
        # KPIs específicos para la vista superior del Admin
        total_tickets_admin = kpis.get('Total', 0)
        pendientes_admin_kpi = kpis.get('Pendientes', 0)
        cerrados_admin = kpis.get('Cerrados', 0)
        manejados_kpi_admin = kpis.get('Manejados', 0)
        eficiencia_kpi_admin = kpis.get('Eficiencia_Total_%', 0.0)
        total_iniciado_admin = kpis.get('Total_Iniciado', 0)
        eficiencia_inicial_admin = kpis.get('Eficiencia_Inicial', 0.0)

        # Layout de KPIs condicional por página
        if page_key == "principal":
            st.subheader("📊 Resumen General (Todos los Supervisores)")
            col_kpi1, col_kpi2, col_kpi3, col_kpi4, col_kpi5, col_kpi6, col_kpi7 = st.columns(7)
            col_kpi1.metric("Total tickets", total_tickets_admin)
            col_kpi2.metric("Eficiencia Total", f"{eficiencia_kpi_admin:.1f}%")
            col_kpi3.metric("Total Iniciado", total_iniciado_admin)
            col_kpi4.metric("Eficiencia Inicial", f"{eficiencia_inicial_admin:.1f}%")
            col_kpi5.metric("Cerrados", cerrados_admin)
            col_kpi6.metric("Pendiente", pendientes_admin_kpi)
            col_kpi7.metric("Manejados", manejados_kpi_admin)
        else: # Vista Admin en otras páginas (PYMEs, Antiguas, etc.)
            st.subheader("📊 Resumen General (Filtro Actual)")
            col_kpi1, col_kpi2, col_kpi3, col_kpi4, col_kpi5 = st.columns(5)
            col_kpi1.metric("Total tickets", total_tickets_admin)
            col_kpi2.metric("Eficiencia", f"{eficiencia_kpi_admin:.1f}%")
            col_kpi3.metric("Cerrados", cerrados_admin)
            col_kpi4.metric("Pendiente", pendientes_admin_kpi)
            col_kpi5.metric("Manejados", manejados_kpi_admin)

        st.markdown("---")
        st.subheader("👥 Desglose por Supervisor")

        resumen_admin = crear_resumen_admin(df_page_data, agrupar_por='Supervisor')

        if resumen_admin.empty or resumen_admin['Total'].sum() == 0:
            st.warning("No hay datos de supervisores para graficar o mostrar en tabla con los filtros actuales.")
        else:
            try:
                # --- Gráficos Existentes (Eficiencia y Total Tickets) ---
                col_chart1, col_chart2 = st.columns(2)
                with col_chart1:
                    st.markdown("#### 📊 Eficiencia Total por supervisor (%)")
                    resumen_grafico_eff = resumen_admin[resumen_admin['Supervisor'] != 'TOTAL']
                    resumen_eff_sorted = resumen_grafico_eff.sort_values('Eficiencia_Total_%', ascending=True)
                    fig_eff = px.bar(resumen_eff_sorted, x='Eficiencia_Total_%', y='Supervisor', orientation='h', text='Eficiencia_Total_%', color='Eficiencia_Total_%', color_continuous_scale='Blues')
                    fig_eff.add_shape(type="line", x0=80, y0=-0.5, x1=80, y1=len(resumen_eff_sorted['Supervisor'])-0.5, line=dict(color="grey", width=2, dash="dash"))
                    fig_eff.add_annotation(x=80, y=len(resumen_eff_sorted['Supervisor'])-0.5, text="Meta 80%", showarrow=False, yshift=10, xshift=-10)
                    fig_eff.update_traces(texttemplate='%{text:.1f}%', textposition='auto')
                    fig_eff.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', xaxis_title="Eficiencia Total (%)", yaxis_title=None, coloraxis_showscale=False, uniformtext_minsize=8, uniformtext_mode='hide')
                    # --- CORRECCIÓN v2.6.14 ---
                    st.plotly_chart(fig_eff, use_container_width=True, key=f"{page_key}_eff_chart")

                with col_chart2:
                    st.markdown("#### 🎫 Tickets por supervisor")
                    resumen_grafico_total = resumen_admin[resumen_admin['Supervisor'] != 'TOTAL']
                    resumen_total_sorted = resumen_grafico_total.sort_values('Total', ascending=False)
                    fig_total = px.bar(resumen_total_sorted, x='Supervisor', y='Total', text='Total', color='Total', color_continuous_scale='Blues')
                    fig_total.update_traces(texttemplate='%{text}', textposition='outside')
                    fig_total.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', xaxis_title=None, yaxis_title="Total Tickets", coloraxis_showscale=False)
                    # --- CORRECCIÓN v2.6.14 ---
                    st.plotly_chart(fig_total, use_container_width=True, key=f"{page_key}_total_chart")

                # --- Lógica CONDICIONAL para GRÁFICOS ADICIONALES ---
                if page_key != "pymes":
                    st.markdown("#### ⏳ Tickets Pendientes por Supervisor")
                    if 'Estado' in df_page_data.columns and 'Supervisor' in df_page_data.columns:
                        pendientes_df = df_page_data[df_page_data['Estado'].astype(str).str.lower().isin(['activo', 'iniciado'])]
                    else:
                        pendientes_df = pd.DataFrame()

                    if not pendientes_df.empty:
                        resumen_pendientes = pendientes_df.groupby('Supervisor')['OrdenExterna'].count().reset_index()
                        resumen_pendientes.rename(columns={'OrdenExterna': 'Tickets Pendientes'}, inplace=True)
                        resumen_pendientes = resumen_pendientes.sort_values('Tickets Pendientes', ascending=False)
                        fig_pendientes = px.bar(resumen_pendientes, x='Supervisor', y='Tickets Pendientes', text='Tickets Pendientes', color='Tickets Pendientes', color_continuous_scale='Blues')
                        fig_pendientes.update_traces(texttemplate='%{text}', textposition='outside')
                        fig_pendientes.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', xaxis_title=None, yaxis_title="Total Tickets Pendientes", coloraxis_showscale=False)
                        # --- CORRECCIÓN v2.6.14 ---
                        st.plotly_chart(fig_pendientes, use_container_width=True, key=f"{page_key}_pending_chart")
                    else:
                        st.info("No hay tickets pendientes ('activo' o 'iniciado') para mostrar en este desglose con los filtros actuales.")

                if page_key == "pymes":
                    st.markdown("#### ⚠️ PYMEs Vencidas por Supervisor")
                    if 'Vencido' in df_page_data.columns and 'Supervisor' in df_page_data.columns:
                        try:
                            df_page_data['Vencido'] = df_page_data['Vencido'].astype(bool)
                            vencidos_pymes_df = df_page_data[df_page_data['Vencido'] == True]
                        except Exception as e:
                            st.warning(f"No se pudo filtrar por PYMEs vencidas. Verifique la columna 'Vencido'. Error: {e}")
                            vencidos_pymes_df = pd.DataFrame()
                    else:
                        st.warning("Faltan las columnas 'Vencido' o 'Supervisor' para generar el gráfico de PYMEs vencidas.")
                        vencidos_pymes_df = pd.DataFrame()

                    if not vencidos_pymes_df.empty:
                        resumen_vencidos = vencidos_pymes_df.groupby('Supervisor')['OrdenExterna'].count().reset_index()
                        resumen_vencidos.rename(columns={'OrdenExterna': 'PYMEs Vencidas'}, inplace=True)
                        resumen_vencidos = resumen_vencidos.sort_values('PYMEs Vencidas', ascending=False)
                        fig_vencidos = px.bar(
                            resumen_vencidos,
                            x='Supervisor', y='PYMEs Vencidas', text='PYMEs Vencidas',
                            color='PYMEs Vencidas', color_continuous_scale='Reds'
                        )
                        fig_vencidos.update_traces(texttemplate='%{text}', textposition='outside')
                        fig_vencidos.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                                                   xaxis_title=None, yaxis_title="Total PYMEs Vencidas", coloraxis_showscale=False)
                        # --- CORRECCIÓN v2.6.14 ---
                        st.plotly_chart(fig_vencidos, use_container_width=True, key=f"{page_key}_overdue_chart")
                    else:
                        st.info("No hay PYMEs vencidas para mostrar en este desglose con los filtros actuales.")

                # Tabla detallada (siempre visible)
                st.markdown("---")
                st.markdown("#### 📋 Resumen Detallado por Supervisor")
                st.dataframe(resumen_admin, use_container_width=True, hide_index=True)
                excel_data_resumen = to_excel(resumen_admin)
                if excel_data_resumen:
                    st.download_button(
                        label="📥 Descargar Resumen Detallado",
                        data=excel_data_resumen,
                        file_name=f"{page_key}_resumen_admin_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    )

                # --- NUEVA UBICACIÓN GRÁFICO (v2.6.13) ---
                if page_key == "rendimiento":
                    render_hourly_efficiency_chart(df_page_data, df_full_historial, chart_key=f"{page_key}_hourly_chart")

            except Exception as e:
                st.error(f"Ocurrió un error al generar los gráficos o la tabla: {e}")
                if not resumen_admin.empty:
                    st.info("Mostrando tabla detallada como alternativa.")
                    st.dataframe(resumen_admin, use_container_width=True, hide_index=True)

    # --- Vista Gerencia ---
    elif role == "gerencia":
        display_kpi_metrics(kpis, page_key, critical_metric_key)
        st.markdown("---")
        st.subheader("👥 Resumen por Supervisor")
        resumen_sup = crear_resumen_admin(df_page_data, agrupar_por='Supervisor')
        st.dataframe(resumen_sup, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("👨‍🔧 Resumen por Técnico")
        if 'Asignado_A' in df_page_data.columns:
            resumen_tec = crear_resumen_admin(df_page_data, agrupar_por='Asignado_A')
            if not resumen_tec.empty and 'Supervisor' in resumen_tec.columns:
                resumen_tec.rename(columns={'Supervisor': 'Asignado_A'}, inplace=True)
            st.dataframe(resumen_tec, use_container_width=True, hide_index=True)
        else:
            st.info("No hay datos de 'Asignado_A' para mostrar resumen por técnico.")
        
        # --- NUEVA UBICACIÓN GRÁFICO (v2.6.13) ---
        if page_key == "rendimiento":
            render_hourly_efficiency_chart(df_page_data, df_full_historial, chart_key=f"{page_key}_hourly_chart")

        st.markdown("---")
        st.subheader("🗂️ Detalle de Tickets")
        display_detail_table(df_page_data, df_full_historial, role, role_supervisor_id, global_supervisor_sel, status_filter, page_key, page_key)

    # --- Vista Supervisor / Supervisor_Old ---
    else:
        display_kpi_metrics(kpis, page_key, critical_metric_key)
        
        # --- INICIA CORRECCIÓN v2.6.16: AÑADIR RESUMEN A 'PRINCIPAL' ---
        if page_key == "principal":
            st.markdown("---")
            agrupar_por = 'Supervisor' if role == 'supervisor_old' else 'Asignado_A'
            titulo_resumen = 'Resumen por Supervisor' if role == 'supervisor_old' else 'Resumen por Técnico'

            st.subheader(f"👥 {titulo_resumen}")
            if agrupar_por in df_page_data.columns:
                resumen = crear_resumen_admin(df_page_data, agrupar_por=agrupar_por)
                if not resumen.empty and 'Supervisor' in resumen.columns and agrupar_por != 'Supervisor':
                    resumen.rename(columns={'Supervisor': agrupar_por}, inplace=True)

                if not resumen.empty:
                    st.dataframe(resumen, use_container_width=True, hide_index=True)
                    excel_data_resumen_sup = to_excel(resumen)
                    if excel_data_resumen_sup:
                        st.download_button(
                            label=f"📥 Descargar {titulo_resumen}",
                            data=excel_data_resumen_sup,
                            file_name=f"{page_key}_resumen_{agrupar_por.lower()}_{global_supervisor_sel}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            key=f"{page_key}_download_resumen" # Key única
                        )
                else:
                    st.info(f"No hay datos para generar el resumen por '{agrupar_por}'.")
            else:
                st.warning(f"La columna '{agrupar_por}' necesaria para el resumen no está disponible.")
        # --- FIN CORRECCIÓN v2.6.16 ---
        
        # --- Lógica de Resumen (para otras páginas que no son 'principal') ---
        if page_key != "principal":
            st.markdown("---")
            agrupar_por = 'Supervisor' if role == 'supervisor_old' else 'Asignado_A'
            titulo_resumen = 'Resumen por Supervisor' if role == 'supervisor_old' else 'Resumen por Técnico'

            st.subheader(f"👥 {titulo_resumen}")
            if agrupar_por in df_page_data.columns:
                resumen = crear_resumen_admin(df_page_data, agrupar_por=agrupar_por)
                if not resumen.empty and 'Supervisor' in resumen.columns and agrupar_por != 'Supervisor':
                    resumen.rename(columns={'Supervisor': agrupar_por}, inplace=True)

                if not resumen.empty:
                    st.dataframe(resumen, use_container_width=True, hide_index=True)
                    excel_data_resumen_sup = to_excel(resumen)
                    if excel_data_resumen_sup:
                        st.download_button(
                            label=f"📥 Descargar {titulo_resumen}",
                            data=excel_data_resumen_sup,
                            file_name=f"{page_key}_resumen_{agrupar_por.lower()}_{global_supervisor_sel}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            key=f"{page_key}_download_resumen" # Key única
                        )
                else:
                    st.info(f"No hay datos para generar el resumen por '{agrupar_por}'.")
            else:
                st.warning(f"La columna '{agrupar_por}' necesaria para el resumen no está disponible.")

        # --- NUEVA UBICACIÓN GRÁFICO (v2.6.13) ---
        if page_key == "rendimiento":
            render_hourly_efficiency_chart(df_page_data, df_full_historial, chart_key=f"{page_key}_hourly_chart")

        st.markdown("---")
        st.subheader("📋 Detalle de Tickets")
        display_detail_table(df_page_data, df_full_historial, role, role_supervisor_id, global_supervisor_sel, status_filter, page_key, page_key)
# --- End of Render Dashboard Function ---


# --------------------------
# Filtrado por Rol y Sidebar
# --------------------------
# Asegurarse que df_unicos_base no es None antes de proceder
# Usamos 'df' (cargado de Supabase) para obtener los únicos
df_unicos_base = obtener_datos_unicos(df) if df is not None else pd.DataFrame()


st.sidebar.title("📌 Menú")

if st.session_state.user_role == "admin":
    menu_options = ["🏠 Principal", "📊 Análisis PYMEs", "⏰ Puntualidad", "🎯 Citas Puntuales", "📅 Antiguas", "📈 Rendimiento"]
else:
    menu_options = ["🏠 Principal", "📊 Análisis PYMEs", "⏰ Puntualidad", "🎯 Citas Puntuales", "🔍 Tracking Ticket", "📅 Antiguas", "📈 Rendimiento"]

menu = st.sidebar.radio("Selecciona una página", menu_options)
st.sidebar.markdown("---")
st.sidebar.subheader("Filtros")

# Opciones de filtro basadas en df_unicos_base si está disponible
supervisor_options = ["Todos"]
estado_options = []

if df_unicos_base is not None and not df_unicos_base.empty:
    if 'Supervisor' in df_unicos_base.columns:
        supervisores_validos = sorted([str(s) for s in df_unicos_base['Supervisor'].dropna().unique() if str(s).strip()])
        supervisor_options.extend(supervisores_validos)
    if 'Estado' in df_unicos_base.columns:
        estados_validos = sorted([str(e) for e in df_unicos_base['Estado'].dropna().unique() if str(e).strip()])
        estado_options = estados_validos

# Controles de Sidebar
if st.session_state.user_role in ["admin", "gerencia", "supervisor_old"]:
    supervisor_sel = st.sidebar.selectbox("Supervisor", supervisor_options)
else:
    supervisor_sel = st.session_state.supervisor_id
estatus_sel = st.sidebar.multiselect("Estado", options=estado_options, default=estado_options)


# --- DataFrames Filtrados ---
# df_supervisor_unicos: Filtrado solo por rol/supervisor (para Tracking)
df_supervisor_unicos = df_unicos_base.copy() if df_unicos_base is not None else pd.DataFrame()
if not df_supervisor_unicos.empty:
    if st.session_state.user_role == "supervisor":
        if 'Supervisor' in df_supervisor_unicos.columns:
            df_supervisor_unicos = df_supervisor_unicos[df_supervisor_unicos['Supervisor'].astype(str) == str(st.session_state.supervisor_id)]
        else:
            df_supervisor_unicos = pd.DataFrame(columns=df_unicos_base.columns if df_unicos_base is not None else [])
    elif st.session_state.user_role in ["admin", "gerencia", "supervisor_old"] and supervisor_sel != "Todos":
        if 'Supervisor' in df_supervisor_unicos.columns:
            df_supervisor_unicos = df_supervisor_unicos[df_supervisor_unicos['Supervisor'].astype(str) == str(supervisor_sel)]
        else:
            df_supervisor_unicos = pd.DataFrame(columns=df_unicos_base.columns if df_unicos_base is not None else [])

# df_unicos: Filtrado por rol/supervisor Y por estado (para todas las demás páginas)
df_unicos = df_supervisor_unicos.copy() if df_supervisor_unicos is not None else pd.DataFrame()
if not df_unicos.empty and estatus_sel:
    if 'Estado' in df_unicos.columns:
        df_unicos = df_unicos[df_unicos['Estado'].astype(str).isin(estatus_sel)]
    elif not df_unicos.empty:
        df_unicos = pd.DataFrame(columns=df_supervisor_unicos.columns if df_supervisor_unicos is not None else [])


# --- Contenido de las Páginas ---

if menu == "🏠 Principal":
    st.title(f"🏠 Dashboard Principal - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")

    if st.session_state.user_role in ["admin", "gerencia"]:
        render_dashboard_page(
            title_prefix="Principal",
            df_page_data=df_unicos,
            df_full_historial=df, # df es el historial completo del día cargado de Supabase
            role=st.session_state.user_role,
            role_supervisor_id=st.session_state.supervisor_id,
            global_supervisor_sel=supervisor_sel,
            status_filter=estatus_sel,
            page_key="principal" 
        )
    else: # Vista Supervisor/Supervisor_Old
        
        # Calcular KPIs para el Supervisor
        kpis_supervisor = calcular_kpis(df_unicos, df)
        
        # 1. Mostrar KPIs
        display_kpi_metrics(kpis_supervisor, page_key="principal", critical_metric_key='Pendientes')
        
        # --- INICIA CORRECCIÓN v2.6.16: AÑADIR RESUMEN A 'PRINCIPAL' ---
        st.markdown("---")
        agrupar_por = 'Supervisor' if st.session_state.user_role == 'supervisor_old' else 'Asignado_A'
        titulo_resumen = 'Resumen por Supervisor' if st.session_state.user_role == 'supervisor_old' else 'Resumen por Técnico'

        st.subheader(f"👥 {titulo_resumen}")
        if agrupar_por in df_unicos.columns:
            resumen = crear_resumen_admin(df_unicos, agrupar_por=agrupar_por)
            if not resumen.empty and 'Supervisor' in resumen.columns and agrupar_por != 'Supervisor':
                resumen.rename(columns={'Supervisor': agrupar_por}, inplace=True)

            if not resumen.empty:
                st.dataframe(resumen, use_container_width=True, hide_index=True)
                excel_data_resumen_sup = to_excel(resumen)
                if excel_data_resumen_sup:
                    st.download_button(
                        label=f"📥 Descargar {titulo_resumen}",
                        data=excel_data_resumen_sup,
                        # --- INICIA CORRECCIÓN v2.6.17 ---
                        file_name=f"principal_resumen_{agrupar_por.lower()}_{supervisor_sel}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        # --- FIN CORRECCIÓN v2.6.17 ---
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        key=f"principal_download_resumen" # Key única
                    )
            else:
                st.info(f"No hay datos para generar el resumen por '{agrupar_por}'.")
        else:
            st.warning(f"La columna '{agrupar_por}' necesaria para el resumen no está disponible.")
        # --- FIN CORRECCIÓN v2.6.16 ---

        st.markdown("---")
        st.subheader("🗂️ Tabla de Tickets (Estado más reciente)")

        display_detail_table(
            df_data=df_unicos,
            df_full_historial=df, # df es el historial completo del día
            role=st.session_state.user_role,
            role_supervisor_id=st.session_state.supervisor_id,
            global_supervisor_sel=supervisor_sel,
            status_filter=estatus_sel,
            page_key="principal_sup",
            file_name_prefix="principal"
        )


elif menu == "📊 Análisis PYMEs":
    st.title(f"📊 Análisis PYMEs - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    df_pymes = pd.DataFrame()
    if df_unicos is not None and not df_unicos.empty and 'Es_PYME_Negocio' in df_unicos.columns:
        df_pymes = df_unicos[df_unicos['Es_PYME_Negocio'] == True].copy()

    render_dashboard_page(
        title_prefix="Análisis PYMEs",
        df_page_data=df_pymes,
        df_full_historial=df, # df es el historial completo del día
        role=st.session_state.user_role,
        role_supervisor_id=st.session_state.supervisor_id,
        global_supervisor_sel=supervisor_sel,
        status_filter=estatus_sel,
        page_key="pymes" 
    )

elif menu == "⏰ Puntualidad":
    st.title(f"⏰ Análisis de Puntualidad General - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    hoy = pd.Timestamp.now().normalize()
    df_puntuales = pd.DataFrame()

    if df_unicos is not None and not df_unicos.empty:
        if 'OE_Vencimiento' in df_unicos.columns and pd.api.types.is_datetime64_any_dtype(df_unicos['OE_Vencimiento']):
            mask_fecha = df_unicos['OE_Vencimiento'].dt.normalize() == hoy
            oe_venc_orig_str = df_unicos.get('OE_Vencimiento_Original', pd.Series(dtype=str)).astype(str)
            mask_texto = oe_venc_orig_str.str.lower() == 'hoy'
            df_puntuales = df_unicos[mask_fecha | mask_texto].copy()

    render_dashboard_page(
        title_prefix="Puntualidad General",
        df_page_data=df_puntuales,
        df_full_historial=df, # df es el historial completo del día
        role=st.session_state.user_role,
        role_supervisor_id=st.session_state.supervisor_id,
        global_supervisor_sel=supervisor_sel,
        status_filter=estatus_sel,
        page_key="puntualidad" 
    )

elif menu == "🎯 Citas Puntuales":
    st.title(f"🎯 Análisis de Citas Puntuales - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    hoy = pd.Timestamp.now().normalize()

    df_citas_actuales = pd.DataFrame()
    df_citas_historicas = pd.DataFrame()
    tickets_gestionados_ids = set()

    required_cols_citas = ['Prioridad', 'Vence', 'Estado', 'OrdenExterna']
    if df_unicos is not None and not df_unicos.empty and all(col in df_unicos.columns for col in required_cols_citas):
        if 'Vence' in df_unicos.columns and pd.api.types.is_datetime64_any_dtype(df_unicos['Vence']):
            df_citas_base = df_unicos.dropna(subset=['Vence']).copy()
            mask_prioridad = df_citas_base['Prioridad'].astype(str) == '100'
            mask_vencimiento_orig = df_citas_base.get('OE_Vencimiento_Original', pd.Series(dtype=str)).astype(str).str.lower() == 'vencida'
            mask_vence_hoy = df_citas_base['Vence'].dt.normalize() == hoy
            df_citas_actuales = df_citas_base[mask_prioridad & mask_vencimiento_orig & mask_vence_hoy]

        estados_gestionados = ['pendiente de calendarizacion', 'calendarizado']
        candidatos = df_unicos[df_unicos['Estado'].astype(str).isin(estados_gestionados)]['OrdenExterna'].unique()

        # Usar 'df' (historial completo del día) para buscar
        required_hist_cols = ['OrdenExterna', 'Vence', 'Prioridad', 'OE_Vencimiento_Original']
        if len(candidatos) > 0 and df is not None and not df.empty and all(c in df.columns for c in required_hist_cols) and pd.api.types.is_datetime64_any_dtype(df['Vence']):
            historial_candidatos = df[df['OrdenExterna'].isin(candidatos)].copy()

            if not historial_candidatos.empty:
                prioridad_str = historial_candidatos.get('Prioridad', pd.Series(dtype=str)).fillna('').astype(str)
                venc_orig_str = historial_candidatos.get('OE_Vencimiento_Original', pd.Series(dtype=str)).fillna('').astype(str).str.lower()
                historial_candidatos['Vence'] = pd.to_datetime(historial_candidatos['Vence'], errors='coerce')
                valid_vence_mask = historial_candidatos['Vence'].notna()

                cumplen_historico = historial_candidatos[valid_vence_mask &
                    (prioridad_str == '100') &
                    (venc_orig_str == 'vencida') &
                    (historial_candidatos.loc[valid_vence_mask, 'Vence'].dt.normalize() == hoy)
                ]
                tickets_gestionados_ids.update(cumplen_historico['OrdenExterna'].unique())

        if tickets_gestionados_ids:
            df_citas_historicas = df_unicos[df_unicos['OrdenExterna'].isin(tickets_gestionados_ids)]

    if df_citas_actuales.empty and not df_citas_historicas.empty:
        df_citas_actuales = pd.DataFrame(columns=df_citas_historicas.columns)
    elif not df_citas_actuales.empty and df_citas_historicas.empty:
        df_citas_historicas = pd.DataFrame(columns=df_citas_actuales.columns)

    if not df_citas_actuales.empty or not df_citas_historicas.empty:
        try:
            cols = df_citas_actuales.columns.union(df_citas_historicas.columns)
            df_citas_actuales = df_citas_actuales.reindex(columns=cols)
            df_citas_historicas = df_citas_historicas.reindex(columns=cols)
            df_citas = pd.concat([df_citas_actuales, df_citas_historicas]).drop_duplicates(subset=['OrdenExterna'], keep='first')
        except Exception as e:
            st.error(f"Error al combinar datos de citas: {e}")
            df_citas = df_citas_actuales if not df_citas_actuales.empty else df_citas_historicas
    else:
        df_citas = pd.DataFrame()


    render_dashboard_page(
        title_prefix="Citas Puntuales",
        df_page_data=df_citas,
        df_full_historial=df, # df es el historial completo del día
        role=st.session_state.user_role,
        role_supervisor_id=st.session_state.supervisor_id,
        global_supervisor_sel=supervisor_sel,
        status_filter=estatus_sel,
        page_key="citas" 
    )

elif menu == "🔍 Tracking Ticket":
    st.title(f"🔍 Tracking de Tickets - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    st.markdown("---")
    col_search1, col_search2 = st.columns([3, 1])

    with col_search1:
        ticket_busqueda = st.text_input(
            "🎫 Ingresa el número de Orden Externa",
            placeholder="Ejemplo: 12345678",
            key="ticket_search",
            help="Buscar por número de Orden Externa exacto o parcial"
        )

    with col_search2:
        buscar_exacto_placeholder = st.empty()

    if ticket_busqueda:
        supervisor_filter = None
        if st.session_state.user_role == "supervisor":
            supervisor_filter = st.session_state.supervisor_id
        elif st.session_state.user_role in ["admin", "gerencia", "supervisor_old"] and supervisor_sel != "Todos":
            supervisor_filter = supervisor_sel

        # df_supervisor_unicos (basado en el último estado) se usa para ENCONTRAR los tickets
        # df (el historial completo del día) se usa para MOSTRAR el historial
        df_track = filtrar_dataframe_con_historial(df, df_supervisor_unicos, ticket_busqueda, supervisor_filter, None)

        if df_track is None or df_track.empty:
            st.warning("⚠️ No se encontraron tickets con ese número de Orden Externa")
            st.info("💡 **Sugerencias:**\n- Verifica que el número sea correcto\n- Asegúrate de que el ticket pertenece a tu supervisión (o selecciona 'Todos' si eres admin)")

        else:
            num_unicos = df_track['OrdenExterna'].nunique()
            st.success(f"✅ {num_unicos} ticket(s) único(s) encontrado(s).")

            for orden_externa in df_track['OrdenExterna'].unique():
                ts_col_valid_track = ('Timestamp_Procesado' in df_track.columns and
                                      pd.api.types.is_datetime64_any_dtype(df_track['Timestamp_Procesado']))

                if ts_col_valid_track:
                    historial_ticket = df_track[df_track['OrdenExterna'] == orden_externa].sort_values('Timestamp_Procesado', ascending=False, na_position='last')
                else:
                    historial_ticket = df_track[df_track['OrdenExterna'] == orden_externa]

                if not historial_ticket.empty:
                    ticket_data = historial_ticket.iloc[0]
                else:
                    continue

                with st.container(border=True):
                    col_header1, col_header2, col_header3, col_header4 = st.columns([2, 1, 1, 1])

                    with col_header1:
                        st.markdown(f"### 🎫 Ticket: **{orden_externa}**")

                    with col_header2:
                        color_estado = get_color_estado(str(ticket_data.get('Estado', 'N/A')))
                        st.markdown(f"<div style='text-align: center; background-color: {color_estado}; color: white; padding: 8px; border-radius: 5px; font-weight: bold;'>{str(ticket_data.get('Estado', 'N/A')).upper()}</div>", unsafe_allow_html=True)

                    with col_header3:
                        es_pyme = ticket_data.get('Es_PYME_Negocio', False)
                        if es_pyme:
                            st.markdown("<div style='text-align: center; padding: 8px; border-radius: 5px; font-weight: bold; background-color: #2a2a4a;'>🏢 PYME</div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div style='text-align: center; padding: 8px; border-radius: 5px; font-weight: bold; background-color: #2a2a4a;'>👤 Regular</div>", unsafe_allow_html=True)

                    with col_header4:
                        if ticket_data.get('Vencido', False) and es_pyme:
                            st.markdown("<div style='text-align: center; background-color: #DC143C; color: white; padding: 8px; border-radius: 5px; font-weight: bold;'>⚠️ VENCIDO</div>", unsafe_allow_html=True)
                        elif es_pyme:
                            st.markdown("<div style='text-align: center; background-color: #32CD32; color: white; padding: 8px; border-radius: 5px; font-weight: bold;'>⏱️ En Tiempo</div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div style='text-align: center; padding: 8px; border-radius: 5px; font-weight: bold; background-color: #2a2a4a;'>📊 Normal</div>", unsafe_allow_html=True)

                    st.markdown("---")
                    col_main1, col_main2 = st.columns(2)

                    with col_main1:
                        st.markdown("#### 📋 Información General")
                        info_general = {
                            "🆔 Orden Externa": str(ticket_data.get('OrdenExterna', 'N/A')),
                            "👤 Cliente": str(ticket_data.get('Cliente', 'N/A')),
                            "🏢 Tipo Cliente": str(ticket_data.get('Tipo_Cliente', 'N/A')),
                            "👨‍💼 Supervisor": str(ticket_data.get('Supervisor', 'N/A')),
                            "👨‍🔧 Asignado A": str(ticket_data.get('Asignado_A', 'N/A')),
                            "📍 Ubicación": f"{ticket_data.get('Municipio', 'N/A')}, {ticket_data.get('Provincia', 'N/A')}"
                        }
                        for campo, valor in info_general.items():
                            st.text(f"{campo}: {valor}")

                    with col_main2:
                        st.markdown("#### ⏰ Timeline del Ticket")
                        fecha_creacion = ticket_data.get('Creado')
                        fecha_oe_creacion = ticket_data.get('OE_Creacion')
                        fecha_vence = ticket_data.get('Vence en')
                        timeline_info = {
                            "📅 Creado": formatear_fecha(fecha_creacion),
                            "🚀 OE Creación": formatear_fecha(fecha_oe_creacion),
                            "⏳ Tiempo Transcurrido": calcular_tiempo_transcurrido(fecha_oe_creacion),
                        }
                        if es_pyme and pd.notna(fecha_vence):
                            timeline_info["⏰ Vence/Venció"] = formatear_fecha(fecha_vence)
                            ahora = datetime.now()
                            if not isinstance(fecha_vence, pd.Timestamp):
                                fecha_vence = pd.to_datetime(fecha_vence, errors='coerce')
                            if pd.notna(fecha_vence):
                                try:
                                    # --- INICIA CORRECCIÓN v2.6.15: ZONA HORARIA ---
                                    ahora_utc = datetime.utcnow()
                                    zona_horaria_offset = timedelta(hours=-4)
                                    ahora_ast = ahora_utc + zona_horaria_offset
                                    ahora_naive = ahora_ast.replace(tzinfo=None)
                                    # --- FIN CORRECCIÓN ---
                                    
                                    fecha_vence_naive = fecha_vence.tz_convert(None) if hasattr(fecha_vence, 'tzinfo') and fecha_vence.tzinfo is not None else fecha_vence.replace(tzinfo=None)
                                    
                                    if ahora_naive < fecha_vence_naive:
                                        tiempo_restante = fecha_vence_naive - ahora_naive
                                        horas_restantes = int(tiempo_restante.total_seconds() // 3600)
                                        minutos_restantes = int((tiempo_restante.total_seconds() % 3600) // 60)
                                        timeline_info["⏱️ Tiempo Restante"] = f"{horas_restantes}h {minutos_restantes}m"
                                    else:
                                        tiempo_vencido = ahora_naive - fecha_vence_naive
                                        horas_vencidas = int(tiempo_vencido.total_seconds() // 3600)
                                        minutos_vencidos = int((tiempo_vencido.total_seconds() % 3600) // 60)
                                        timeline_info["🚨 Tiempo Vencido"] = f"{horas_vencidas}h {minutos_vencidos}m"
                                except Exception as e:
                                    timeline_info["⚠️ Error Cálculo Tiempo"] = "Verificar Fechas"

                        for campo, valor in timeline_info.items():
                            if "Vencido" in campo and "🚨" in campo:
                                st.error(f"{campo}: {valor}")
                            elif "Restante" in campo:
                                st.success(f"{campo}: {valor}")
                            else:
                                st.text(f"{campo}: {valor}")

                    st.markdown("---")
                    with st.expander("Ver Historial de Cambios 📜"):
                        df_display_track = formatear_para_display(historial_ticket)
                        st.dataframe(df_display_track, use_container_width=True, hide_index=True)

                st.markdown("<br>", unsafe_allow_html=True)

    else:
        st.info("🔍 **Instrucciones de uso:**")
        col_inst1, col_inst2 = st.columns(2)
        with col_inst1:
            st.markdown("""
            **📋 Cómo usar el Tracking:**
            1. Ingresa el número de Orden Externa en el campo de búsqueda.
            2. El sistema buscará en **todo el historial del día**.
            3. Revisa la tarjeta con el estado **más reciente** encontrado.
            4. Expande "Ver Historial de Cambios" para ver **todos** los registros de ese ticket en el día.
            """)
        with col_inst2:
            st.markdown("""
            **💡 Consejos:**
            - La búsqueda es parcial.
            - Los tickets PYME se destacan con colores.
            - El historial muestra todos los cambios detectados hoy.
            """)

        st.markdown("---")
        st.subheader("🕐 Tickets Recientes (Últimos 10 cambios)")

        tickets_recientes_base = pd.DataFrame()
        
        # --- INICIA CORRECCIÓN v2.6.16: FILTRAR RECIENTES POR SUPERVISOR ---
        # 1. Definir el dataframe base (historial completo del día)
        if df is not None and not df.empty:
            tickets_recientes_base = df.copy()
        
            # 2. Aplicar el filtro de supervisor, si aplica
            supervisor_filter = None
            if st.session_state.user_role == "supervisor":
                supervisor_filter = st.session_state.supervisor_id
            elif st.session_state.user_role in ["admin", "gerencia", "supervisor_old"] and supervisor_sel != "Todos":
                supervisor_filter = supervisor_sel
                
            if supervisor_filter and 'Supervisor' in tickets_recientes_base.columns:
                tickets_recientes_base = tickets_recientes_base[tickets_recientes_base['Supervisor'].astype(str) == str(supervisor_filter)]
        # --- FIN CORRECCIÓN v2.6.16 ---

        tickets_recientes = pd.DataFrame()
        # 3. Ordenar y tomar los 10 más recientes del dataframe *filtrado*
        if not tickets_recientes_base.empty and 'Timestamp_Procesado' in tickets_recientes_base.columns and pd.api.types.is_datetime64_any_dtype(tickets_recientes_base['Timestamp_Procesado']):
            tickets_recientes = tickets_recientes_base.sort_values('Timestamp_Procesado', ascending=False, na_position='last').head(10)
        elif not tickets_recientes_base.empty: # Fallback si no hay timestamp
            tickets_recientes = tickets_recientes_base.tail(10)


        if not tickets_recientes.empty:
            tabla_recientes = []
            # Usar .iterrows() para mostrar los 10 registros (pueden ser duplicados de OrdenExterna si cambió)
            for _, ticket in tickets_recientes.iterrows():
                tabla_recientes.append({
                    'Orden Externa': ticket.get('OrdenExterna'),
                    'Estado': ticket.get('Estado', 'N/A'),
                    'Supervisor': ticket.get('Supervisor', 'N/A'),
                    'PYME': '🏢' if ticket.get('Es_PYME_Negocio') else '👤',
                    'Timestamp': formatear_fecha(ticket.get('Timestamp_Procesado')),
                    'Tipo Evento': ticket.get('Tipo_Evento', 'N/A')
                })

            df_tabla_recientes = pd.DataFrame(tabla_recientes)
            st.dataframe(df_tabla_recientes, use_container_width=True, hide_index=True)
        else:
            st.warning("No hay tickets recientes disponibles para este supervisor.")


elif menu == "📅 Antiguas":
    st.title(f"📅 Análisis de Antigüedad - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    hoy = pd.Timestamp.now().normalize()

    tab1, tab2 = st.tabs(["📅 Antigüedad 3 Días", "⚠️ Antigüedad Extrema (+3 días)"])

    df_unicos_antiguedad = pd.DataFrame()
    if df_unicos is not None and not df_unicos.empty and 'OE_Creacion' in df_unicos.columns:
        df_copy = df_unicos.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_copy['OE_Creacion']):
            df_copy['OE_Creacion'] = pd.to_datetime(df_copy['OE_Creacion'], errors='coerce')
        df_unicos_antiguedad = df_copy.dropna(subset=['OE_Creacion'])

    with tab1:
        fecha_objetivo = hoy - timedelta(days=3)
        df_3_dias = pd.DataFrame()
        if not df_unicos_antiguedad.empty:
            if pd.api.types.is_datetime64_any_dtype(df_unicos_antiguedad['OE_Creacion']):
                df_3_dias = df_unicos_antiguedad[df_unicos_antiguedad['OE_Creacion'].dt.normalize() == fecha_objetivo]

        render_dashboard_page(
            title_prefix="Antigüedad 3 Días",
            df_page_data=df_3_dias,
            df_full_historial=df, # df es el historial completo del día
            role=st.session_state.user_role,
            role_supervisor_id=st.session_state.supervisor_id,
            global_supervisor_sel=supervisor_sel,
            status_filter=estatus_sel,
            page_key="antiguas_3_dias" 
        )

    with tab2:
        fecha_limite = hoy - timedelta(days=3)
        df_extrema = pd.DataFrame()
        if not df_unicos_antiguedad.empty:
            # --- CORRECCIÓN v2.6.11 ---
            if pd.api.types.is_datetime64_any_dtype(df_unicos_antiguedad['OE_Creacion']):
            # --- FIN CORRECCIÓN ---
                df_extrema = df_unicos_antiguedad[df_unicos_antiguedad['OE_Creacion'].dt.normalize() < fecha_limite]

        render_dashboard_page(
            title_prefix="Antigüedad Extrema",
            df_page_data=df_extrema,
            df_full_historial=df, # df es el historial completo del día
            role=st.session_state.user_role,
            role_supervisor_id=st.session_state.supervisor_id,
            global_supervisor_sel=supervisor_sel,
            status_filter=estatus_sel,
            page_key="antiguas_extrema", 
            critical_metric_key='Total'
        )

# --- INICIA BLOQUE CORREGIDO v2.6.14 ---
elif menu == "📈 Rendimiento":
    st.title(f"📈 Análisis de Rendimiento - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    st.info("Esta página filtra los tickets por la fecha y hora en que fueron PROCESADOS hoy.")

    col_date1, col_date2 = st.columns(2)
    
    # El default es HOY, porque la tabla solo tiene datos de hoy
    fecha_hoy = datetime.now().date()
    fecha_inicio_seleccionada = col_date1.date_input("Fecha Inicio", fecha_hoy)
    fecha_fin_seleccionada = col_date2.date_input("Fecha Fin", fecha_hoy)
    
    # Añadir filtros de HORA para el Timestamp
    hora_inicio = col_date1.time_input("Hora Inicio", time(0, 0)) # 00:00
    hora_fin = col_date2.time_input("Hora Fin", time(23, 59, 59)) # 23:59:59
    
    # Combinar
    dt_inicio = datetime.combine(fecha_inicio_seleccionada, hora_inicio)
    dt_fin = datetime.combine(fecha_fin_seleccionada, hora_fin)

    df_rendimiento = pd.DataFrame()

    # Usamos Timestamp_Procesado en lugar de OE_Creacion
    if df_unicos is not None and not df_unicos.empty and 'Timestamp_Procesado' in df_unicos.columns:
        df_rendimiento_base = df_unicos.copy()
        
        # Asegurar que Timestamp_Procesado es datetime
        if not pd.api.types.is_datetime64_any_dtype(df_rendimiento_base['Timestamp_Procesado']):
            df_rendimiento_base['Timestamp_Procesado'] = pd.to_datetime(df_rendimiento_base['Timestamp_Procesado'], errors='coerce')
        
        # Dropear solo si el TIMESTAMP (no la OE_Creacion) es nulo
        df_rendimiento_base = df_rendimiento_base.dropna(subset=['Timestamp_Procesado']) 

        try:
            if dt_inicio <= dt_fin:
                # Quitar timezone si existe (buena práctica)
                if df_rendimiento_base['Timestamp_Procesado'].dt.tz is not None:
                    df_rendimiento_base['Timestamp_Procesado'] = df_rendimiento_base['Timestamp_Procesado'].dt.tz_convert(None)

                df_rendimiento = df_rendimiento_base[
                    (df_rendimiento_base['Timestamp_Procesado'] >= dt_inicio) &  # <--- LÓGICA CORREGIDA
                    (df_rendimiento_base['Timestamp_Procesado'] <= dt_fin)    # <--- LÓGICA CORREGIDA
                ].copy()
            else:
                st.error("La fecha/hora de inicio no puede ser posterior a la fecha/hora de fin.")
                df_rendimiento = pd.DataFrame()

        except Exception as e:
            st.error(f"Error al procesar fechas para Rendimiento: {e}")
            df_rendimiento = pd.DataFrame()

    if df_rendimiento.empty:
        st.warning("No hay datos en el rango de fecha/hora seleccionado con los filtros actuales.")
    else:
        # El gráfico de línea ahora se renderiza DENTRO de esta función
        render_dashboard_page(
            title_prefix="Rendimiento",
            df_page_data=df_rendimiento,
            df_full_historial=df, # df es el historial completo del día
            role=st.session_state.user_role,
            role_supervisor_id=st.session_state.supervisor_id,
            global_supervisor_sel=supervisor_sel,
            status_filter=estatus_sel,
            page_key="rendimiento" 
        )
# --- FIN BLOQUE CORREGIDO v2.6.14 ---
