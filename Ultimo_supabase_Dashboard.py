import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
from streamlit_autorefresh import st_autorefresh
import numpy as np
from io import BytesIO
import os # Importado para la conexión
import traceback # Para errores detallados

# --- NUEVOS IMPORTS PARA SUPABASE ---
from sqlalchemy import create_engine, text

# --- NUEVOS IMPORTS PARA PLOTLY ---
import plotly.express as px
import plotly.graph_objects as go
# ---------------------------------


# --------------------------
# Configuración de la página
# --------------------------
# --- TÍTULO ACTUALIZADO ---
st.set_page_config(page_title="Dashboard Trabajos S - v2.7.2", layout="wide")

# --- CSS PARA MÓVILES ---
st.markdown("""
<style>
    /* --- Estilo de Tarjetas (de la respuesta anterior) --- */

    /* Estilo para las métricas (cuadros de 10.5K, 510, etc.) */
    [data-testid="stMetric"] {
        background-color: #ffffff; /* Fondo blanco */
        border: 1px solid #e0e0e0; /* Borde gris claro */
        border-radius: 10px; /* Bordes redondeados */
        padding: 20px; /* Espacio interior */
        box-shadow: 0 4px 12px rgba(0,0,0,0.04); /* Sombra sutil */
    }

    /* Estilo para los contenedores (donde van los gráficos) */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.04);
    }
    
    [data-testid="stVerticalBlockBorderWrapper"] > div {
        border: none;
    }

    /* --- ¡NUEVA REGLA PARA ENCABEZADOS DE TABLA EN NEGRITA! --- */

    /* Apunta a las celdas del encabezado de la tabla (thead th) */
    [data-testid="stDataFrame"] thead th {
        font-weight: 700 !important; /* O puedes usar 'bold' */
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


# -----------------------------------------------
# --- FUNCIÓN DE AYUDA (v2.7.0) ---
# -----------------------------------------------
def get_current_ast_time():
    """
    Devuelve la hora actual en AST (UTC-4) como un objeto datetime naive.
    """
    try:
        ahora_utc = datetime.utcnow()
        zona_horaria_offset = timedelta(hours=-4)
        ahora_ast = ahora_utc + zona_horaria_offset
        return ahora_ast.replace(tzinfo=None) # Devuelve naive
    except Exception as e:
        return datetime.now() 

# --------------------------
# Funciones de Cálculo
# --------------------------
def calcular_pyme_y_vence(fecha_creacion):
    if pd.isna(fecha_creacion): return False, None
    
    ahora_naive = get_current_ast_time()
    hoy = ahora_naive.date()
    ayer = hoy - timedelta(days=1)
    
    if not isinstance(fecha_creacion, pd.Timestamp):
        fecha_creacion = pd.to_datetime(fecha_creacion, errors='coerce')
        if pd.isna(fecha_creacion): return False, None

    fecha = fecha_creacion.date()
    hora = fecha_creacion.time()

    if fecha == hoy:
        return True, fecha_creacion + timedelta(hours=4)
    if fecha == ayer and hora >= time(18, 0):
        return True, datetime.combine(hoy, time(12, 0))
    return False, None

def calcular_vencido(row):
    """Usa la nueva función de tiempo AST."""
    vence_en_dt = pd.to_datetime(row.get('Vence en'), errors='coerce')
    estado = str(row.get('Estado','')).lower()

    if pd.isna(vence_en_dt) or estado not in ['activo', 'iniciado']:
        return False

    ahora_naive = get_current_ast_time()
    vence_en_naive = vence_en_dt.tz_convert(None) if hasattr(vence_en_dt, 'tzinfo') and vence_en_dt.tzinfo is not None else vence_en_dt.replace(tzinfo=None)

    try:
        return ahora_naive > vence_en_naive
    except TypeError:
        return False


@st.cache_data(ttl=300)
def get_earliest_batch_initial_cohort(df_full_historial):
    """
    Identifica los tickets que estaban 'activo' o 'iniciado' en el
    *primer lote procesado* (lote_procesado == min) del DÍA DE HOY.
    Devuelve un set de IDs (OrdenExterna).
    """
    
    if (df_full_historial is None or df_full_historial.empty or
        'OrdenExterna' not in df_full_historial.columns or
        'Estado' not in df_full_historial.columns or
        'lote_procesado' not in df_full_historial.columns or
        'Timestamp_Procesado' not in df_full_historial.columns or 
        not pd.api.types.is_datetime64_any_dtype(df_full_historial['Timestamp_Procesado'])
        ):
        return set()

    try:
        ahora_ast_naive = get_current_ast_time()
        fecha_hoy = ahora_ast_naive.date()
        
        df_historial_hoy = df_full_historial[df_full_historial['Timestamp_Procesado'].dt.date == fecha_hoy].copy()
        
        if df_historial_hoy.empty:
            return set()

        lotes_numericos = pd.to_numeric(df_historial_hoy['lote_procesado'], errors='coerce')
        
        if lotes_numericos.isna().all():
            return set()
            
        min_lote = lotes_numericos.min()
        
        if pd.isna(min_lote):
            return set()

        df_earliest_batch = df_historial_hoy[lotes_numericos == min_lote].copy()
        
        if df_earliest_batch.empty:
            return set()

        df_initial_active_in_snapshot = df_earliest_batch[
            df_earliest_batch['Estado'].astype(str).str.lower().isin(['activo', 'iniciado'])
        ]
        
        initial_cohort_ids = set(df_initial_active_in_snapshot['OrdenExterna'].unique())
        return initial_cohort_ids
        
    except Exception as e:
        st.error(f"Error en get_earliest_batch_initial_cohort: {e}")
        return set()


def calcular_kpis(df, df_full_historial):
    """
    Calcula los KPIs.
    df = DataFrame de estados únicos/actuales (filtrado por página/rol).
    df_full_historial = DataFrame con todo el historial (de todas las fechas).
    """
    default_kpis = {
            'Total': 0,'Cerrados': 0,'Referidos': 0,'Citados': 0,
            'Rebote': 0,'Pendientes': 0,'Manejados': 0,'Eficiencia_Total_%': 0.0,
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
    rebote = df_kpi[df_kpi['Estado'] == 'validacion int'].shape[0]
    pendientes = df_kpi[df_kpi['Estado'].isin(['activo', 'iniciado'])].shape[0]
    manejados = cerrados + referidos + citados + rebote
    eficiencia_total = round(manejados * 100 / total, 1) if total > 0 else 0.0

    total_iniciado_en_pagina = 0
    manejados_inicial_en_pagina = 0
    eficiencia_inicial = 0.0

    global_initial_cohort_ids = get_earliest_batch_initial_cohort(df_full_historial)

    if global_initial_cohort_ids:
        try:
            tickets_en_pagina_actual_ids = set(df_kpi['OrdenExterna'].unique())
            cohort_tickets_in_current_page_ids = global_initial_cohort_ids.intersection(tickets_en_pagina_actual_ids)
            total_iniciado_en_pagina = len(cohort_tickets_in_current_page_ids)

            if total_iniciado_en_pagina > 0:
                df_kpi_del_cohort_intersectado = df_kpi[df_kpi['OrdenExterna'].isin(cohort_tickets_in_current_page_ids)]

                cerrados_inicial = df_kpi_del_cohort_intersectado[df_kpi_del_cohort_intersectado['Estado'].isin(['cerrado', 'validacion ext'])].shape[0]
                referidos_inicial = df_kpi_del_cohort_intersectado[df_kpi_del_cohort_intersectado['Estado'] == 'pend trab interno'].shape[0]
                citados_inicial = df_kpi_del_cohort_intersectado[df_kpi_del_cohort_intersectado['Estado'].isin(['pendiente de calendarizacion', 'calendarizado'])].shape[0]
                rebote_inicial = df_kpi_del_cohort_intersectado[df_kpi_del_cohort_intersectado['Estado'] == 'validacion int'].shape[0]
                
                manejados_inicial_en_pagina = cerrados_inicial + referidos_inicial + citados_inicial + rebote_inicial
                eficiencia_inicial = round(manejados_inicial_en_pagina * 100 / total_iniciado_en_pagina, 1)

        except Exception as e:
            st.error(f"Error calculando KPIs iniciales: {e}")
            total_iniciado_en_pagina = 0
            manejados_inicial_en_pagina = 0
            eficiencia_inicial = 0.0

    return {
        'Total': total,
        'Cerrados': cerrados,
        'Referidos': referidos,
        'Citados': citados,
        'Rebote': rebote,
        'Pendientes': pendientes,
        'Manejados': manejados,
        'Eficiencia_Total_%': eficiencia_total,
        'Total_Iniciado': total_iniciado_en_pagina, 
        'Manejados_Inicial': manejados_inicial_en_pagina, 
        'Eficiencia_Inicial': eficiencia_inicial 
    }
# --- End of KPI Calculation Function ---


# ==============================================================================
# --- Conexión Supabase y Mapeo de Columnas ---
# ==============================================================================

@st.cache_resource
def get_database_engine():
    """Crea una conexión a Supabase."""
    DATABASE_URL = ""
    try:
        DATABASE_URL = st.secrets["postgres"]["DATABASE_URL"]
    except Exception:
        DATABASE_URL = os.environ.get("DATABASE_URL")

    if not DATABASE_URL:
        st.error("⚠️ No se encontró la 'DATABASE_URL'.")
        st.stop()
        return None

    try:
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={'options': '-csearch_path=public'}
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception as e:
        st.error(f"⚠️ Error conectando a Supabase: {e}")
        st.stop()
        return None

def get_column_mappings():
    """Devuelve el mapeo de nombres SQL a nombres CSV (PascalCase)."""
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
        'lote_procesado': 'lote_procesado',
        'id': None, 'fecha_actualizacion': None, 'fecha_registro': None
    }
    return reverse_mapping

COLUMN_MAPPING_REVERSE = get_column_mappings()

def denormalizar_columnas_desde_sql(df_sql):
    """Renombra columnas de formato SQL (snake_case) a formato CSV (PascalCase)."""
    if df_sql is None or df_sql.empty:
        return df_sql
    
    mapeo_valido = {k: v for k, v in COLUMN_MAPPING_REVERSE.items() if v is not None}
    columnas_a_renombrar = {k: v for k, v in mapeo_valido.items() if k in df_sql.columns}
    df_csv = df_sql.rename(columns=columnas_a_renombrar)
    columnas_esperadas_presentes = [v for v in mapeo_valido.values() if v in df_csv.columns]
    
    return df_csv[columnas_esperadas_presentes]

# --------------------------
# Carga y Procesamiento de Datos (CORREGIDO v2.7.2)
# --------------------------
@st.cache_data(ttl=60)
def cargar_datos():
    """Carga datos desde la tabla 'historial_cambios' de Supabase."""
    
    engine = get_database_engine()
    if engine is None:
        st.error("No hay conexión a la base de datos.")
        return pd.DataFrame()

    try:
        query = text("SELECT * FROM historial_cambios") 
        with engine.connect() as conn:
            df_sql = pd.read_sql(query, conn)
        
        if df_sql.empty:
            st.warning("La tabla 'historial_cambios' está vacía.")
            return pd.DataFrame()

        df = denormalizar_columnas_desde_sql(df_sql)
        
        if df.empty:
            st.error("Error al mapear columnas de Supabase.")
            return pd.DataFrame()

    except Exception as e:
        st.error(f"❌ Error al cargar datos desde Supabase: {e}")
        return pd.DataFrame()

    df.columns = df.columns.str.strip()
    
    columnas_texto_clave = ['Supervisor', 'Estado', 'Tipo_Cliente', 'Tipo_servicio', 'Asignado_A', 'Prioridad']
    for col in df.columns.intersection(columnas_texto_clave):
        df[col] = df[col].astype(str).str.strip().str.lower().replace('nan', None).replace('<na>', None).replace('none', None)

    # --- INICIA CORRECCIÓN v2.7.2 ---
    columnas_fechas_a_procesar = ['Creado', 'OE_Creacion', 'OE_Vence', 'OE_Vencimiento', 'Vence', 'Timestamp_Procesado']
    for col in df.columns.intersection(columnas_fechas_a_procesar):
        df[f'{col}_Original'] = df[col].astype(str).replace('NaT', None)
        
        # 1. Usar 'dayfirst=True' y 'format='mixed'' para manejar los strings de KUNAI
        df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True, format='mixed')
        
        # 2. Convertir a AST (UTC-4) y hacerlo naive
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            try:
                # Si la fecha ya tiene timezone (ej. UTC de Supabase), convertir
                if df[col].dt.tz is not None:
                     df[col] = df[col].dt.tz_convert('Etc/GMT+4').dt.tz_localize(None)
                else:
                # Si es naive (leído de un string), localizar a AST y luego quitar
                     df[col] = df[col].dt.tz_localize('Etc/GMT+4', ambiguous='infer').dt.tz_localize(None)
            except Exception:
                 # Fallback por si algo falla
                 df[col] = df[col].dt.tz_localize(None)
    # --- FIN CORRECCIÓN v2.7.2 ---

    if 'OE_Creacion' in df.columns and pd.api.types.is_datetime64_any_dtype(df['OE_Creacion']) and not df['OE_Creacion'].isna().all():
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
            df['PYME'] = False; df['Vence en'] = pd.NaT; df['Vencido'] = False; df['Es_PYME_Negocio'] = False
    else:
        df['PYME'] = False; df['Vence en'] = pd.NaT; df['Vencido'] = False; df['Es_PYME_Negocio'] = False

    if 'Vencido' not in df.columns:
        df['Vencido'] = False
    else:
        df['Vencido'] = df['Vencido'].fillna(False).astype(bool)
    
    return df
# --- FIN DE LA LÓGICA DE CARGA ---


# ==============================================================================
# --- LÓGICA PRINCIPAL (v2.7.1) ---
# ==============================================================================

# 1. Carga inicial de datos (contiene TODO el historial)
df_full_historial = cargar_datos()

# Manejo si la carga inicial falla
if df_full_historial is None or df_full_historial.empty:
    st.error("No se pudieron cargar datos. Verifica la conexión a Supabase y que la tabla 'historial_cambios' no esté vacía.")
    st.stop()
else:
    # --- INICIO DE LA LÓGICA "NUEVOS HOY" (v2.7.1) ---
    try:
        fecha_hoy = get_current_ast_time().date()
        
        if 'Timestamp_Procesado' in df_full_historial.columns and \
           pd.api.types.is_datetime64_any_dtype(df_full_historial['Timestamp_Procesado']) and \
           'OrdenExterna' in df_full_historial.columns:

            # 2. Encontrar el PRIMER timestamp (el MÍNIMO) para CADA ticket en TODO el historial
            df_full_historial['Fecha_Nacimiento'] = df_full_historial.groupby('OrdenExterna')['Timestamp_Procesado'].transform('min')

            # 3. Crear el DataFrame 'df' (para el dashboard) filtrando solo los tickets
            #    donde su 'Fecha_Nacimiento' (su primer registro) sea de HOY.
            df = df_full_historial[df_full_historial['Fecha_Nacimiento'].dt.date == fecha_hoy].copy()
            
            if df.empty:
                st.info(f"ℹ️ No hay tickets **nuevos** registrados en el día de hoy ({fecha_hoy.strftime('%d/%m/%Y')}).")
        else:
            st.error("Columnas 'Timestamp_Procesado' u 'OrdenExterna' son inválidas. No se puede filtrar por 'Nuevos Hoy'.")
            df = pd.DataFrame(columns=df_full_historial.columns)
            
    except Exception as e:
        st.error(f"Error fatal al filtrar por 'Nuevos Hoy': {e}")
        st.error(traceback.format_exc())
        df = pd.DataFrame(columns=df_full_historial.columns)
# --- FIN DE LA LÓGICA "NUEVOS HOY" ---
        
# ==============================================================================

# -----------------------------------------------
# Funciones para obtener y formatear datos
# -----------------------------------------------
def obtener_datos_unicos(df_input):
    """
    Obtiene el registro MÁS RECIENTE (por Timestamp) para cada OrdenExterna
    en el dataframe de entrada.
    """
    if df_input is None or df_input.empty:
        return df_input

    if 'OrdenExterna' not in df_input.columns:
        st.error("Columna 'OrdenExterna' no encontrada.")
        return pd.DataFrame(columns=df_input.columns)

    ts_col_valid = ('Timestamp_Procesado' in df_input.columns and
                    pd.api.types.is_datetime64_any_dtype(df_input['Timestamp_Procesado']) and
                    not df_input['Timestamp_Procesado'].isna().all())

    if not ts_col_valid:
        df_temp = df_input.dropna(subset=['OrdenExterna'])
        result = df_temp.drop_duplicates(subset=['OrdenExterna'], keep='first')
        return result
    else:
        df_temp = df_input.dropna(subset=['OrdenExterna', 'Timestamp_Procesado'])
        df_sorted = df_temp.sort_values('Timestamp_Procesado', ascending=False)
        result = df_sorted.drop_duplicates(subset=['OrdenExterna'], keep='first')
        return result


def formatear_para_display(df_input):
    if df_input is None or df_input.empty:
        return df_input
    df_display = df_input.copy()
    
    # --- INICIA CORRECCIÓN v2.7.2 ---
    columnas_fechas_a_procesar = [
        'Creado', 'OE_Creacion', 'OE_Vence', 'OE_Vencimiento', 'Vence', 'Vence en', 
        'Timestamp_Procesado', 'fecha_registro', 'Fecha_Nacimiento'
    ]
    # --- FIN CORRECCIÓN v2.7.2 ---
    
    columnas_fechas_presentes = df_display.columns.intersection(columnas_fechas_a_procesar)

    for col in columnas_fechas_presentes:
        if pd.api.types.is_datetime64_any_dtype(df_display[col]) and not df_display[col].isna().all():
            try:
                df_display[col] = df_display[col].apply(lambda x: x.strftime('%d/%m/%Y %H:%M') if pd.notna(x) else None)
            except Exception:
                df_display[col] = df_display[col].astype(str).replace('NaT', None)
        else:
            # Si no es datetime (ej. 'NaT' que falló la conversión), limpiar
            df_display[col] = df_display[col].astype(str).replace('nan', None).replace('NaT', None).replace('<NA>', None).replace('None',None)

    for col in df_display.columns:
        if col not in columnas_fechas_presentes:
            try:
                if col == 'Vencido' and df_display[col].dtype == 'bool':
                    df_display[col] = df_display[col].map({True: 'Sí', False: 'No'}).fillna('No')
                else:
                    df_display[col] = df_display[col].astype(str).replace('nan', None).replace('<NA>', None).replace('None', None)
            except Exception:
                df_display[col] = None

    return df_display


def to_excel(df: pd.DataFrame):
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
    cols = [agrupar_por, 'Total', 'Cerrados', 'Referidos', 'Citados', 'Rebote', 'Pendientes', 'Total Manejado', 'Eficiencia_Total_%']
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    if agrupar_por not in df.columns or 'OrdenExterna' not in df.columns or 'Estado' not in df.columns:
        st.warning(f"Faltan columnas esenciales para crear el resumen.")
        return pd.DataFrame(columns=cols)

    df_copy = df.copy()
    df_copy[agrupar_por] = df_copy[agrupar_por].fillna('Desconocido').astype(str)
    df_copy['Estado'] = df_copy['Estado'].fillna('Desconocido').astype(str).str.lower()

    resumen = df_copy.groupby(agrupar_por).agg(
        Total=('OrdenExterna', 'count'),
        Cerrados=('Estado', lambda x: x.isin(['cerrado', 'validacion ext']).sum()),
        Referidos=('Estado', lambda x: (x == 'pend trab interno').sum()),
        Citados=('Estado', lambda x: x.isin(['pendiente de calendarizacion', 'calendarizado']).sum()),
        Rebote=('Estado', lambda x: (x == 'validacion int').sum()),
        Pendientes=('Estado', lambda x: x.isin(['activo', 'iniciado']).sum())
    ).reset_index()

    resumen['Total Manejado'] = resumen['Cerrados'] + resumen['Referidos'] + resumen['Citados'] + resumen['Rebote']
    resumen['Eficiencia_Total_%'] = np.where(resumen['Total'] > 0,
                                         round(resumen['Total Manejado'] * 100 / resumen['Total'], 1),
                                         0.0)
    
    if not resumen.empty:
        total_row = pd.Series(name='Total')
        total_row[agrupar_por] = 'TOTAL'
        total_row['Total'] = resumen['Total'].sum()
        total_row['Cerrados'] = resumen['Cerrados'].sum()
        total_row['Referidos'] = resumen['Referidos'].sum()
        total_row['Citados'] = resumen['Citados'].sum()
        total_row['Rebote'] = resumen['Rebote'].sum()
        total_row['Pendientes'] = resumen['Pendientes'].sum()
        total_row['Total Manejado'] = resumen['Total Manejado'].sum()
        
        total_manejado_general = total_row['Total Manejado']
        total_general = total_row['Total']
        total_row['Eficiencia_Total_%'] = round(total_manejado_general * 100 / total_general, 1) if total_general > 0 else 0.0
        
        resumen = pd.concat([resumen, total_row.to_frame().T], ignore_index=True)

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

# --- FUNCIÓN MODIFICADA (v2.7.1) ---
def filtrar_dataframe_con_historial(df_completo_historial, df_unicos_para_buscar, texto_busqueda, supervisor_filter=None, estado_filter=None):
    """
    Filtra y muestra el historial completo de tickets que coinciden con la búsqueda.
    df_completo_historial = El DataFrame de historial COMPLETO (todas las fechas).
    df_unicos_para_buscar = El DataFrame de únicos (de HOY o de TODO) en el que buscar.
    """
    if df_completo_historial is None or df_completo_historial.empty:
        return pd.DataFrame()

    if not texto_busqueda:
        return df_unicos_para_buscar if df_unicos_para_buscar is not None else pd.DataFrame(columns=df_completo_historial.columns)

    if df_unicos_para_buscar is None or df_unicos_para_buscar.empty:
        return pd.DataFrame(columns=df_completo_historial.columns)

    texto_busqueda = texto_busqueda.lower()
    cols_busqueda = ['OrdenExterna', 'Asignado_A', 'Cliente', 'Supervisor']
    cols_presentes = [col for col in cols_busqueda if col in df_unicos_para_buscar.columns]

    if not cols_presentes or 'OrdenExterna' not in df_unicos_para_buscar.columns:
        st.warning("Columnas clave no encontradas para búsqueda.")
        return pd.DataFrame(columns=df_completo_historial.columns)

    try:
        mask = df_unicos_para_buscar[cols_presentes].astype(str).apply(lambda x: x.str.lower().str.contains(texto_busqueda, na=False)).any(axis=1)
    except Exception as e:
        st.error(f"Error al aplicar filtro de búsqueda: {e}")
        return pd.DataFrame(columns=df_completo_historial.columns)

    tickets_encontrados = df_unicos_para_buscar[mask]['OrdenExterna'].unique()

    if len(tickets_encontrados) == 0:
        return pd.DataFrame(columns=df_completo_historial.columns)

    if 'OrdenExterna' not in df_completo_historial.columns:
        st.error("Error crítico: df_completo_historial no tiene 'OrdenExterna'.")
        return pd.DataFrame(columns=df_completo_historial.columns)

    df_historial = df_completo_historial[df_completo_historial['OrdenExterna'].isin(tickets_encontrados)].copy()

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
    if estado_str in ['cerrado', 'validacion ext']: return '#32CD32'
    elif estado_str in ['pendiente de calendarizacion', 'calendarizado']: return '#FFD700'
    elif estado_str == 'pend trab interno': return '#FFA500'
    elif estado_str in ['activo', 'iniciado']: return '#1E90FF'
    elif estado_str == 'validacion int': return '#8A2BE2'
    else: return '#696969'

def formatear_fecha(fecha_dt):
    if pd.isna(fecha_dt): return 'N/A'
    if isinstance(fecha_dt, pd.Timestamp): return fecha_dt.strftime('%d/%m/%Y %H:%M')
    return str(fecha_dt)

def calcular_tiempo_transcurrido(fecha_inicio):
    """Usa la nueva función de tiempo AST."""
    if pd.isna(fecha_inicio): return 'N/A'
    if not isinstance(fecha_inicio, pd.Timestamp):
        fecha_inicio = pd.to_datetime(fecha_inicio, errors='coerce')
        if pd.isna(fecha_inicio): return 'N/A'

    ahora_naive = get_current_ast_time()
    fecha_inicio_naive = fecha_inicio.tz_convert(None) if hasattr(fecha_inicio, 'tzinfo') and fecha_inicio.tzinfo is not None else fecha_inicio.replace(tzinfo=None)

    if ahora_naive < fecha_inicio_naive: return "Futuro"

    diferencia = ahora_naive - fecha_inicio_naive
    dias = diferencia.days
    horas = diferencia.seconds // 3600
    minutos = (diferencia.seconds % 3600) // 60

    if dias > 0: return f"{dias}d {horas}h {minutos}m"
    elif horas > 0: return f"{horas}h {minutos}m"
    else: return f"{minutos}m"

# ------------------------------------
# FUNCIONES DE RENDERIZADO
# ------------------------------------
def display_kpi_metrics(kpis, page_key, critical_metric_key=None, critical_delta_text="Críticos"):
    """Muestra la cuadrícula de KPIs."""
    
    def metric_with_critical(col, label, key, delta_text=None, delta_color="normal"):
        value_to_display = kpis.get(key, 0)
        if not isinstance(value_to_display, (int, float)): value_to_display = 0

        if key == critical_metric_key and value_to_display > 0:
            col.metric(label, value_to_display, delta=critical_delta_text, delta_color="inverse")
        elif key == critical_metric_key and value_to_display <= 0 :
            col.metric(label, value_to_display)
        else:
            col.metric(label, value_to_display)

    if page_key == "principal":
        col1, col2, col3, col4, col5 = st.columns(5)
        
        if st.session_state.user_role == "admin":
            metric_with_critical(col1, "📋 Total (Nuevos Hoy)", 'Total', critical_metric_key == 'Total')
            metric_with_critical(col2, "⏳ Pendientes", 'Pendientes', critical_metric_key == 'Pendientes')
            metric_with_critical(col3, "🚀 Total Iniciado", 'Total_Iniciado')
            metric_with_critical(col4, "✅ Cerrados", 'Cerrados')
            metric_with_critical(col5, "🔄 Total Manejado", 'Manejados')
            col6, col7, col8, col9, col10 = st.columns(5)
            eficiencia_valor = kpis.get('Eficiencia_Total_%', 0.0)
            col6.metric("📊 Eficiencia Total", f"{eficiencia_valor:.1f}%")
            eficiencia_ini_valor = kpis.get('Eficiencia_Inicial', 0.0)
            col7.metric("📈 Eficiencia Inicial", f"{eficiencia_ini_valor:.1f}%")
            metric_with_critical(col8, "📤 Referidos", 'Referidos')
            metric_with_critical(col9, "📅 Citados", 'Citados')
            metric_with_critical(col10, "🔄 Rebote", 'Rebote')
        else: 
            metric_with_critical(col1, "📋 Total (Nuevos Hoy)", 'Total', critical_metric_key == 'Total')
            metric_with_critical(col2, "⏳ Pendientes", 'Pendientes', critical_metric_key == 'Pendientes')
            metric_with_critical(col3, "🚀 Total Iniciado", 'Total_Iniciado')
            metric_with_critical(col4, "✅ Cerrados", 'Cerrados')
            metric_with_critical(col5, "📤 Referidos", 'Referidos')
            col6, col7, col8, col9, col10 = st.columns(5)
            metric_with_critical(col6, "📅 Citados", 'Citados')
            metric_with_critical(col7, "🔄 Rebote", 'Rebote')
            metric_with_critical(col8, "🔄 Total Manejado", 'Manejados')
            eficiencia_valor = kpis.get('Eficiencia_Total_%', 0.0)
            col9.metric("📊 Eficiencia Total", f"{eficiencia_valor:.1f}%")
            eficiencia_ini_valor = kpis.get('Eficiencia_Inicial', 0.0)
            col10.metric("📈 Eficiencia Inicial", f"{eficiencia_ini_valor:.1f}%")
    else: 
        col1, col2, col3, col4 = st.columns(4)
        if st.session_state.user_role == "admin":
            metric_with_critical(col1, "📋 Total (Nuevos Hoy)", 'Total', critical_metric_key == 'Total')
            eficiencia_valor = kpis.get('Eficiencia_Total_%', 0.0)
            col2.metric("📊 Eficiencia", f"{eficiencia_valor:.1f}%")
            metric_with_critical(col3, "✅ Cerrados", 'Cerrados')
            metric_with_critical(col4, "⏳ Pendientes", 'Pendientes', critical_metric_key == 'Pendientes')
            col5, col6, col7, col8 = st.columns(4)
            metric_with_critical(col5, "🔄 Total Manejado", 'Manejados')
            metric_with_critical(col6, "📤 Referidos", 'Referidos')
            metric_with_critical(col7, "📅 Citados", 'Citados')
            metric_with_critical(col8, "🔄 Rebote", 'Rebote')
        else:
            metric_with_critical(col1, "📋 Total (Nuevos Hoy)", 'Total', critical_metric_key == 'Total')
            metric_with_critical(col2, "⏳ Pendientes", 'Pendientes', critical_metric_key == 'Pendientes')
            metric_with_critical(col3, "✅ Cerrados", 'Cerrados')
            metric_with_critical(col4, "📤 Referidos", 'Referidos')
            col5, col6, col7, col8 = st.columns(4)
            metric_with_critical(col5, "📅 Citados", 'Citados')
            metric_with_critical(col6, "🔄 Rebote", 'Rebote')
            metric_with_critical(col7, "🔄 Total Manejado", 'Manejados')
            eficiencia_valor = kpis.get('Eficiencia_Total_%', 0.0)
            col8.metric("📊 Eficiencia", f"{eficiencia_valor:.1f}%")


def display_detail_table(df_data_unicos_hoy, df_full_historial, role, role_supervisor_id, global_supervisor_sel, status_filter, page_key, file_name_prefix):
    """
    Muestra la barra de búsqueda, la tabla de detalles y el botón de descarga.
    df_data_unicos_hoy = Los únicos de HOY.
    df_full_historial = El historial COMPLETO.
    """
    busqueda_key = f"buscar_{page_key}"
    texto_busqueda = st.text_input("🔍 Buscar en tabla", key=busqueda_key, placeholder="Buscar por Orden Externa, Cliente, Asignado...")

    df_display_original = formatear_para_display(df_data_unicos_hoy.copy() if df_data_unicos_hoy is not None else pd.DataFrame())

    if texto_busqueda:
        # --- Lógica de Búsqueda (v2.7.1) ---
        # ¡IMPORTANTE! La búsqueda en el dashboard principal AHORA SOLO BUSCA en los tickets NUEVOS DE HOY.
        # Solo la página de "Tracking" busca en todo.
        supervisor_filter = None
        if role == "supervisor":
            supervisor_filter = role_supervisor_id
        elif role in ["admin", "gerencia", "supervisor_old"] and global_supervisor_sel != "Todos":
            supervisor_filter = global_supervisor_sel

        df_display_filtrado = filtrar_dataframe_con_historial(
            df_full_historial,      # El historial completo (Haystack)
            df_data_unicos_hoy,     # Los únicos de HOY (para encontrar IDs)
            texto_busqueda, 
            supervisor_filter, 
            status_filter
        )
        df_display_final = formatear_para_display(df_display_filtrado)
    else:
        df_display_final = df_display_original

    st.dataframe(df_display_final, use_container_width=True, hide_index=True)

    if not df_display_original.empty:
        excel_data = to_excel(df_display_original) 
        if excel_data:
            st.download_button(
                label="📥 Descargar Detalle (Vista Actual) como Excel",
                data=excel_data,
                file_name=f"{file_name_prefix}_{global_supervisor_sel}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

def render_hourly_efficiency_chart(df_page_data, df_full_historial, chart_key="hourly_efficiency_chart"):
    """Calcula y renderiza el gráfico de eficiencia por hora."""
    st.markdown("---")
    st.subheader("⏱️ Eficiencia por Hora del Día (Según Timestamp)")
    try:
        df_grafico = df_page_data.copy()
        df_grafico['Hora'] = df_grafico['Timestamp_Procesado'].dt.hour
        
        def agg_kpis_por_hora(group):
            kpis_group = calcular_kpis(group, df_full_historial) 
            return pd.Series(kpis_group)

        resumen_hora = df_grafico.groupby('Hora').apply(agg_kpis_por_hora).reset_index()

        if 'Eficiencia_Total_%' not in resumen_hora.columns: resumen_hora['Eficiencia_Total_%'] = 0.0
        if 'Eficiencia_Inicial' not in resumen_hora.columns: resumen_hora['Eficiencia_Inicial'] = 0.0

        horas_completas = pd.DataFrame({'Hora': range(24)})
        resumen_hora = pd.merge(horas_completas, resumen_hora, on='Hora', how='left').fillna(0)

        resumen_hora_melted = resumen_hora.melt(
            id_vars=['Hora'],
            value_vars=['Eficiencia_Total_%', 'Eficiencia_Inicial'],
            var_name='Tipo de Eficiencia',
            value_name='Eficiencia'
        )
        fig_linea_eficiencia = px.line(
            resumen_hora_melted, x='Hora', y='Eficiencia', color='Tipo de Eficiencia',
            title="Eficiencia por Hora (Total vs. Inicial)", markers=True, text='Eficiencia'
        )
        fig_linea_eficiencia.update_traces(texttemplate='%{text:.1f}%', textposition='top center')
        fig_linea_eficiencia.update_layout(
            xaxis_title="Hora del Día (0-23)", yaxis_title="Eficiencia (%)",
            xaxis=dict(tickmode='linear', dtick=1, range=[-0.5, 23.5]), yaxis=dict(range=[0, 105]),
            template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            legend_title_text=''
        )
        st.plotly_chart(fig_linea_eficiencia, use_container_width=True, key=chart_key)
    except Exception as e:
        st.error(f"Error al generar el gráfico de línea de eficiencia: {e}")
        st.error(traceback.format_exc())


def render_dashboard_page(title_prefix, df_page_data, df_full_historial, role, role_supervisor_id, global_supervisor_sel, status_filter, page_key, critical_metric_key=None):
    """
    Función genérica para renderizar una página del dashboard.
    df_page_data = Datos únicos de HOY (NUEVOS DE HOY), ya filtrados.
    df_full_historial = El historial COMPLETO de todas las fechas.
    """
    if df_page_data is None or df_page_data.empty:
        st.warning(f"No hay tickets **nuevos de hoy** para mostrar en '{title_prefix}' con los filtros actuales.")
        return

    kpis = calcular_kpis(df_page_data, df_full_historial)

    # --- Vista Admin ---
    if role == "admin":
        total_tickets_admin = kpis.get('Total', 0)
        pendientes_admin_kpi = kpis.get('Pendientes', 0)
        cerrados_admin = kpis.get('Cerrados', 0)
        manejados_kpi_admin = kpis.get('Manejados', 0)
        eficiencia_kpi_admin = kpis.get('Eficiencia_Total_%', 0.0)
        total_iniciado_admin = kpis.get('Total_Iniciado', 0)
        eficiencia_inicial_admin = kpis.get('Eficiencia_Inicial', 0.0)

        if page_key == "principal":
            st.subheader("📊 Resumen General (Todos los Supervisores - Nuevos Hoy)")
            col_kpi1, col_kpi2, col_kpi3, col_kpi4, col_kpi5, col_kpi6, col_kpi7 = st.columns(7)
            col_kpi1.metric("Total (Nuevos Hoy)", total_tickets_admin)
            col_kpi2.metric("Eficiencia Total", f"{eficiencia_kpi_admin:.1f}%")
            col_kpi3.metric("Total Iniciado", total_iniciado_admin)
            col_kpi4.metric("Eficiencia Inicial", f"{eficiencia_inicial_admin:.1f}%")
            col_kpi5.metric("Cerrados", cerrados_admin)
            col_kpi6.metric("Pendiente", pendientes_admin_kpi)
            col_kpi7.metric("Manejados", manejados_kpi_admin)
        else:
            st.subheader("📊 Resumen General (Filtro Actual - Nuevos Hoy)")
            col_kpi1, col_kpi2, col_kpi3, col_kpi4, col_kpi5 = st.columns(5)
            col_kpi1.metric("Total (Nuevos Hoy)", total_tickets_admin)
            col_kpi2.metric("Eficiencia", f"{eficiencia_kpi_admin:.1f}%")
            col_kpi3.metric("Cerrados", cerrados_admin)
            col_kpi4.metric("Pendiente", pendientes_admin_kpi)
            col_kpi5.metric("Manejados", manejados_kpi_admin)

        st.markdown("---")
        st.subheader("👥 Desglose por Supervisor")
        resumen_admin = crear_resumen_admin(df_page_data, agrupar_por='Supervisor')

        if resumen_admin.empty or resumen_admin['Total'].sum() == 0:
            st.warning("No hay datos de supervisores para graficar con los filtros actuales.")
        else:
            try:
                col_chart1, col_chart2 = st.columns(2)
                with col_chart1:
                    st.markdown("#### 📊 Eficiencia Total por supervisor (%)")
                    resumen_grafico_eff = resumen_admin[resumen_admin['Supervisor'] != 'TOTAL']
                    resumen_eff_sorted = resumen_grafico_eff.sort_values('Eficiencia_Total_%', ascending=True)
                    fig_eff = px.bar(resumen_eff_sorted, x='Eficiencia_Total_%', y='Supervisor', orientation='h', text='Eficiencia_Total_%', color='Eficiencia_Total_%', color_continuous_scale='Blues')
                    fig_eff.add_shape(type="line", x0=80, y0=-0.5, x1=80, y1=len(resumen_eff_sorted['Supervisor'])-0.5, line=dict(color="grey", width=2, dash="dash"))
                    fig_eff.update_traces(texttemplate='%{text:.1f}%', textposition='auto')
                    fig_eff.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', xaxis_title="Eficiencia Total (%)", yaxis_title=None, coloraxis_showscale=False)
                    st.plotly_chart(fig_eff, use_container_width=True, key=f"{page_key}_eff_chart")

                with col_chart2:
                    st.markdown("#### 🎫 Tickets por supervisor")
                    resumen_grafico_total = resumen_admin[resumen_admin['Supervisor'] != 'TOTAL']
                    resumen_total_sorted = resumen_grafico_total.sort_values('Total', ascending=False)
                    fig_total = px.bar(resumen_total_sorted, x='Supervisor', y='Total', text='Total', color='Total', color_continuous_scale='Blues')
                    fig_total.update_traces(texttemplate='%{text}', textposition='outside')
                    fig_total.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', xaxis_title=None, yaxis_title="Total Tickets", coloraxis_showscale=False)
                    st.plotly_chart(fig_total, use_container_width=True, key=f"{page_key}_total_chart")

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
                        st.plotly_chart(fig_pendientes, use_container_width=True, key=f"{page_key}_pending_chart")
                    else:
                        st.info("No hay tickets pendientes ('activo' o 'iniciado') para mostrar.")

                if page_key == "pymes":
                    st.markdown("#### ⚠️ PYMEs Vencidas por Supervisor")
                    if 'Vencido' in df_page_data.columns and 'Supervisor' in df_page_data.columns:
                        try:
                            df_page_data['Vencido'] = df_page_data['Vencido'].astype(bool)
                            vencidos_pymes_df = df_page_data[df_page_data['Vencido'] == True]
                        except Exception as e:
                            vencidos_pymes_df = pd.DataFrame()
                    else:
                        vencidos_pymes_df = pd.DataFrame()
                    if not vencidos_pymes_df.empty:
                        resumen_vencidos = vencidos_pymes_df.groupby('Supervisor')['OrdenExterna'].count().reset_index()
                        resumen_vencidos.rename(columns={'OrdenExterna': 'PYMEs Vencidas'}, inplace=True)
                        resumen_vencidos = resumen_vencidos.sort_values('PYMEs Vencidas', ascending=False)
                        fig_vencidos = px.bar(
                            resumen_vencidos, x='Supervisor', y='PYMEs Vencidas', text='PYMEs Vencidas',
                            color='PYMEs Vencidas', color_continuous_scale='Reds'
                        )
                        fig_vencidos.update_traces(texttemplate='%{text}', textposition='outside')
                        fig_vencidos.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                                                   xaxis_title=None, yaxis_title="Total PYMEs Vencidas", coloraxis_showscale=False)
                        st.plotly_chart(fig_vencidos, use_container_width=True, key=f"{page_key}_overdue_chart")
                    else:
                        st.info("No hay PYMEs vencidas para mostrar.")

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
                if page_key == "rendimiento":
                    render_hourly_efficiency_chart(df_page_data, df_full_historial, chart_key=f"{page_key}_hourly_chart")
            except Exception as e:
                st.error(f"Ocurrió un error al generar los gráficos o la tabla: {e}")
                if not resumen_admin.empty:
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
            if not resumen_tec.empty:
                resumen_tec.rename(columns={'Supervisor': 'Asignado_A'}, inplace=True, errors='ignore')
            st.dataframe(resumen_tec, use_container_width=True, hide_index=True)
        else:
            st.info("No hay datos de 'Asignado_A' para mostrar resumen.")
        
        if page_key == "rendimiento":
            render_hourly_efficiency_chart(df_page_data, df_full_historial, chart_key=f"{page_key}_hourly_chart")

        st.markdown("---")
        st.subheader("🗂️ Detalle de Tickets")
        display_detail_table(df_page_data, df_full_historial, role, role_supervisor_id, global_supervisor_sel, status_filter, page_key, page_key)

    # --- Vista Supervisor / Supervisor_Old ---
    else:
        display_kpi_metrics(kpis, page_key, critical_metric_key)
        
        agrupar_por = 'Supervisor' if role == 'supervisor_old' else 'Asignado_A'
        titulo_resumen = 'Resumen por Supervisor' if role == 'supervisor_old' else 'Resumen por Técnico'

        if page_key == "principal" or page_key != "principal": # Lógica unificada
            st.markdown("---")
            st.subheader(f"👥 {titulo_resumen}")
            if agrupar_por in df_page_data.columns:
                resumen = crear_resumen_admin(df_page_data, agrupar_por=agrupar_por)
                if not resumen.empty:
                    resumen.rename(columns={'Supervisor': agrupar_por}, inplace=True, errors='ignore')
                    st.dataframe(resumen, use_container_width=True, hide_index=True)
                    excel_data_resumen_sup = to_excel(resumen)
                    if excel_data_resumen_sup:
                        st.download_button(
                            label=f"📥 Descargar {titulo_resumen}",
                            data=excel_data_resumen_sup,
                            file_name=f"{page_key}_resumen_{agrupar_por.lower()}_{global_supervisor_sel}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            key=f"{page_key}_download_resumen"
                        )
                else:
                    st.info(f"No hay datos para generar el resumen por '{agrupar_por}'.")
            else:
                st.warning(f"La columna '{agrupar_por}' necesaria para el resumen no está disponible.")

        if page_key == "rendimiento":
            render_hourly_efficiency_chart(df_page_data, df_full_historial, chart_key=f"{page_key}_hourly_chart")

        st.markdown("---")
        st.subheader("📋 Detalle de Tickets")
        display_detail_table(df_page_data, df_full_historial, role, role_supervisor_id, global_supervisor_sel, status_filter, page_key, page_key)
# --- End of Render Dashboard Function ---


# --------------------------
# Filtrado por Rol y Sidebar
# --------------------------
# df_unicos_base se basa en 'df' (solo tickets que NACIERON HOY)
df_unicos_base = obtener_datos_unicos(df) if df is not None else pd.DataFrame()


st.sidebar.title("📌 Menú")

if st.session_state.user_role == "admin":
    menu_options = ["🏠 Principal", "📊 Análisis PYMEs", "⏰ Puntualidad", "🎯 Citas Puntuales", "📅 Antiguas", "📈 Rendimiento"]
else:
    menu_options = ["🏠 Principal", "📊 Análisis PYMEs", "⏰ Puntualidad", "🎯 Citas Puntuales", "🔍 Tracking Ticket", "📅 Antiguas", "📈 Rendimiento"]

menu = st.sidebar.radio("Selecciona una página", menu_options)
st.sidebar.markdown("---")
st.sidebar.subheader("Filtros")

# Opciones de filtro basadas en df_unicos_base (solo hoy)
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


# --- DataFrames Filtrados (Basados en 'df' - solo NUEVOS HOY) ---
# df_supervisor_unicos: Filtrado solo por rol/supervisor (de nuevos hoy)
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

# df_unicos: Filtrado por rol/supervisor Y por estado (de nuevos hoy)
df_unicos = df_supervisor_unicos.copy() if df_supervisor_unicos is not None else pd.DataFrame()
if not df_unicos.empty and estatus_sel:
    if 'Estado' in df_unicos.columns:
        df_unicos = df_unicos[df_unicos['Estado'].astype(str).isin(estatus_sel)]
    elif not df_unicos.empty:
        df_unicos = pd.DataFrame(columns=df_supervisor_unicos.columns if df_supervisor_unicos is not None else [])


# --- Contenido de las Páginas ---

if menu == "🏠 Principal":
    st.title(f"🏠 Dashboard Principal - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    st.info("Mostrando tickets cuyo **primer registro** fue hoy.") # <-- Aclaración

    if st.session_state.user_role in ["admin", "gerencia"]:
        render_dashboard_page(
            title_prefix="Principal",
            df_page_data=df_unicos,
            df_full_historial=df_full_historial, # <-- Pasa el historial COMPLETO
            role=st.session_state.user_role,
            role_supervisor_id=st.session_state.supervisor_id,
            global_supervisor_sel=supervisor_sel,
            status_filter=estatus_sel,
            page_key="principal" 
        )
    else: # Vista Supervisor/Supervisor_Old
        kpis_supervisor = calcular_kpis(df_unicos, df_full_historial)
        display_kpi_metrics(kpis_supervisor, page_key="principal", critical_metric_key='Pendientes')
        
        st.markdown("---")
        agrupar_por = 'Supervisor' if st.session_state.user_role == 'supervisor_old' else 'Asignado_A'
        titulo_resumen = 'Resumen por Supervisor' if st.session_state.user_role == 'supervisor_old' else 'Resumen por Técnico'

        st.subheader(f"👥 {titulo_resumen}")
        if agrupar_por in df_unicos.columns:
            resumen = crear_resumen_admin(df_unicos, agrupar_por=agrupar_por)
            if not resumen.empty:
                resumen.rename(columns={'Supervisor': agrupar_por}, inplace=True, errors='ignore')
                st.dataframe(resumen, use_container_width=True, hide_index=True)
                excel_data_resumen_sup = to_excel(resumen)
                if excel_data_resumen_sup:
                    st.download_button(
                        label=f"📥 Descargar {titulo_resumen}",
                        data=excel_data_resumen_sup,
                        file_name=f"principal_resumen_{agrupar_por.lower()}_{supervisor_sel}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        key=f"principal_download_resumen"
                    )
            else:
                st.info(f"No hay datos para generar el resumen por '{agrupar_por}'.")
        else:
            st.warning(f"La columna '{agrupar_por}' necesaria para el resumen no está disponible.")

        st.markdown("---")
        st.subheader("🗂️ Tabla de Tickets (Estado más reciente de Nuevos Hoy)")

        display_detail_table(
            df_data_unicos_hoy=df_unicos,
            df_full_historial=df_full_historial, # <-- Pasa el historial COMPLETO
            role=st.session_state.user_role,
            role_supervisor_id=st.session_state.supervisor_id,
            global_supervisor_sel=supervisor_sel,
            status_filter=estatus_sel,
            page_key="principal_sup",
            file_name_prefix="principal"
        )


elif menu == "📊 Análisis PYMEs":
    st.title(f"📊 Análisis PYMEs - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    st.info("Mostrando tickets **nuevos de hoy** que son PYME.") # <-- Aclaración
    df_pymes = pd.DataFrame()
    if df_unicos is not None and not df_unicos.empty and 'Es_PYME_Negocio' in df_unicos.columns:
        df_pymes = df_unicos[df_unicos['Es_PYME_Negocio'] == True].copy()

    render_dashboard_page(
        title_prefix="Análisis PYMEs",
        df_page_data=df_pymes,
        df_full_historial=df_full_historial, # <-- Pasa el historial COMPLETO
        role=st.session_state.user_role,
        role_supervisor_id=st.session_state.supervisor_id,
        global_supervisor_sel=supervisor_sel,
        status_filter=estatus_sel,
        page_key="pymes" 
    )

elif menu == "⏰ Puntualidad":
    st.title(f"⏰ Análisis de Puntualidad General - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    st.info("Mostrando tickets **nuevos de hoy** con vencimiento 'Hoy'.") # <-- Aclaración
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
        df_full_historial=df_full_historial, # <-- Pasa el historial COMPLETO
        role=st.session_state.user_role,
        role_supervisor_id=st.session_state.supervisor_id,
        global_supervisor_sel=supervisor_sel,
        status_filter=estatus_sel,
        page_key="puntualidad" 
    )

elif menu == "🎯 Citas Puntuales":
    st.title(f"🎯 Análisis de Citas Puntuales - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    st.info("Mostrando tickets **nuevos de hoy** que son Citas Puntuales.") # <-- Aclaración
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

        required_hist_cols = ['OrdenExterna', 'Vence', 'Prioridad', 'OE_Vencimiento_Original']
        if len(candidatos) > 0 and df_full_historial is not None and not df_full_historial.empty and all(c in df_full_historial.columns for c in required_hist_cols) and pd.api.types.is_datetime64_any_dtype(df_full_historial['Vence']):
            historial_candidatos = df_full_historial[df_full_historial['OrdenExterna'].isin(candidatos)].copy()

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
        df_full_historial=df_full_historial, # <-- Pasa el historial COMPLETO
        role=st.session_state.user_role,
        role_supervisor_id=st.session_state.supervisor_id,
        global_supervisor_sel=supervisor_sel,
        status_filter=estatus_sel,
        page_key="citas" 
    )

# --- PÁGINA "TRACKING TICKET" MODIFICADA (v2.7.1) ---
elif menu == "🔍 Tracking Ticket":
    st.title(f"🔍 Tracking de Tickets - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    st.info("Esta página busca en **todo el historial** de la base de datos, no solo en los tickets de hoy.")
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

    # --- LÓGICA DE TRACKING (v2.7.1) ---
    # 1. Crear dataframes únicos basados en el historial COMPLETO
    df_unicos_base_MASTER = obtener_datos_unicos(df_full_historial) if df_full_historial is not None else pd.DataFrame()
    df_supervisor_unicos_MASTER = df_unicos_base_MASTER.copy() if df_unicos_base_MASTER is not None else pd.DataFrame()
    
    supervisor_filter = None
    if not df_supervisor_unicos_MASTER.empty:
        if st.session_state.user_role == "supervisor":
            supervisor_filter = st.session_state.supervisor_id
            if 'Supervisor' in df_supervisor_unicos_MASTER.columns:
                df_supervisor_unicos_MASTER = df_supervisor_unicos_MASTER[df_supervisor_unicos_MASTER['Supervisor'].astype(str) == str(supervisor_filter)]
        elif st.session_state.user_role in ["admin", "gerencia", "supervisor_old"] and supervisor_sel != "Todos":
            supervisor_filter = supervisor_sel
            if 'Supervisor' in df_supervisor_unicos_MASTER.columns:
                df_supervisor_unicos_MASTER = df_supervisor_unicos_MASTER[df_supervisor_unicos_MASTER['Supervisor'].astype(str) == str(supervisor_filter)]
    # --- FIN LÓGICA DE TRACKING ---

    if ticket_busqueda:
        # 2. Llamar a la función de búsqueda usando el historial COMPLETO
        df_track = filtrar_dataframe_con_historial(
            df_full_historial,            # El historial completo (Haystack)
            df_supervisor_unicos_MASTER,  # Los únicos de todo el historial (para encontrar IDs)
            ticket_busqueda, 
            supervisor_filter, 
            None
        )

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
                                    ahora_naive = get_current_ast_time()
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
            2. El sistema buscará en **todo el historial de la base de datos**.
            3. Revisa la tarjeta con el estado **más reciente** encontrado (de cualquier fecha).
            4. Expande "Ver Historial de Cambios" para ver **todos** los registros de ese ticket.
            """)
        with col_inst2:
            st.markdown("""
            **💡 Consejos:**
            - La búsqueda es parcial.
            - Los tickets PYME se destacan con colores.
            - El historial muestra todos los cambios detectados (hoy, ayer, etc.).
            """)

        st.markdown("---")
        st.subheader("🕐 Tickets Recientes (Últimos 10 cambios en historial completo)")

        tickets_recientes_base = pd.DataFrame()
        
        if not df_supervisor_unicos_MASTER.empty and 'OrdenExterna' in df_supervisor_unicos_MASTER.columns:
            ids_del_supervisor = set(df_supervisor_unicos_MASTER['OrdenExterna'].unique())
            tickets_recientes_base = df_full_historial[df_full_historial['OrdenExterna'].isin(ids_del_supervisor)].copy()
        elif st.session_state.user_role == "admin" and supervisor_sel == "Todos": # Admin sin filtro ve todo
             tickets_recientes_base = df_full_historial.copy()
        elif not df_supervisor_unicos_MASTER.empty: # Fallback para admin con filtro
             ids_del_supervisor = set(df_supervisor_unicos_MASTER['OrdenExterna'].unique())
             tickets_recientes_base = df_full_historial[df_full_historial['OrdenExterna'].isin(ids_del_supervisor)].copy()

        tickets_recientes = pd.DataFrame()
        if not tickets_recientes_base.empty and 'Timestamp_Procesado' in tickets_recientes_base.columns and pd.api.types.is_datetime64_any_dtype(tickets_recientes_base['Timestamp_Procesado']):
            tickets_recientes = tickets_recientes_base.sort_values('Timestamp_Procesado', ascending=False, na_position='last').head(10)
        elif not tickets_recientes_base.empty:
            tickets_recientes = tickets_recientes_base.tail(10)


        if not tickets_recientes.empty:
            tabla_recientes = []
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
    st.info("Mostrando tickets **nuevos de hoy** que cumplen criterios de antigüedad (basado en 'OE_Creacion').") # <-- Aclaración
    hoy = pd.Timestamp.now().normalize()

    tab1, tab2 = st.tabs(["📅 Antigüedad 3 Días", "⚠️ Antigüedad Extrema (+3 días)"])

    df_unicos_antiguedad = pd.DataFrame()
    # df_unicos ya está filtrado por tickets que "nacieron hoy"
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
            df_full_historial=df_full_historial, # <-- Pasa el historial COMPLETO
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
            if pd.api.types.is_datetime64_any_dtype(df_unicos_antiguedad['OE_Creacion']):
                df_extrema = df_unicos_antiguedad[df_unicos_antiguedad['OE_Creacion'].dt.normalize() < fecha_limite]

        render_dashboard_page(
            title_prefix="Antigüedad Extrema",
            df_page_data=df_extrema,
            df_full_historial=df_full_historial, # <-- Pasa el historial COMPLETO
            role=st.session_state.user_role,
            role_supervisor_id=st.session_state.supervisor_id,
            global_supervisor_sel=supervisor_sel,
            status_filter=estatus_sel,
            page_key="antiguas_extrema", 
            critical_metric_key='Total'
        )

elif menu == "📈 Rendimiento":
    st.title(f"📈 Análisis de Rendimiento - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    st.info("Esta página filtra los tickets **nuevos de hoy** por la fecha y hora en que fueron PROCESADOS.") # <-- Aclaración

    col_date1, col_date2 = st.columns(2)
    
    fecha_hoy = get_current_ast_time().date()
    fecha_inicio_seleccionada = col_date1.date_input("Fecha Inicio", fecha_hoy)
    fecha_fin_seleccionada = col_date2.date_input("Fecha Fin", fecha_hoy)
    
    hora_inicio = col_date1.time_input("Hora Inicio", time(0, 0)) # 00:00
    hora_fin = col_date2.time_input("Hora Fin", time(23, 59, 59)) # 23:59:59
    
    dt_inicio = datetime.combine(fecha_inicio_seleccionada, hora_inicio)
    dt_fin = datetime.combine(fecha_fin_seleccionada, hora_fin)

    df_rendimiento = pd.DataFrame()

    # df_unicos ya está filtrado por "Nuevos Hoy"
    if df_unicos is not None and not df_unicos.empty and 'Timestamp_Procesado' in df_unicos.columns:
        df_rendimiento_base = df_unicos.copy()
        
        if not pd.api.types.is_datetime64_any_dtype(df_rendimiento_base['Timestamp_Procesado']):
            df_rendimiento_base['Timestamp_Procesado'] = pd.to_datetime(df_rendimiento_base['Timestamp_Procesado'], errors='coerce')
        
        df_rendimiento_base = df_rendimiento_base.dropna(subset=['Timestamp_Procesado']) 

        try:
            if dt_inicio <= dt_fin:
                if df_rendimiento_base['Timestamp_Procesado'].dt.tz is not None:
                    df_rendimiento_base['Timestamp_Procesado'] = df_rendimiento_base['Timestamp_Procesado'].dt.tz_convert(None)

                df_rendimiento = df_rendimiento_base[
                    (df_rendimiento_base['Timestamp_Procesado'] >= dt_inicio) & 
                    (df_rendimiento_base['Timestamp_Procesado'] <= dt_fin) 
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
        render_dashboard_page(
            title_prefix="Rendimiento",
            df_page_data=df_rendimiento,
            df_full_historial=df_full_historial, # <-- Pasa el historial COMPLETO
            role=st.session_state.user_role,
            role_supervisor_id=st.session_state.supervisor_id,
            global_supervisor_sel=supervisor_sel,
            status_filter=estatus_sel,
            page_key="rendimiento" 
        )


