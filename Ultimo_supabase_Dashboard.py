import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
from streamlit_autorefresh import st_autorefresh
import numpy as np
from io import BytesIO
import os
import time as timer
from concurrent.futures import ThreadPoolExecutor
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine, text, pool

# ====================================
# CONFIGURACIÓN INICIAL
# ====================================

st.set_page_config(
    page_title="Dashboard Trabajos Claro", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# ====================================
# SISTEMA DE LOGIN
# ====================================

def verificar_login():
    """Sistema de login con todos los usuarios originales"""
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

# Auto-refresh
st_autorefresh(interval=30 * 1000, key="data_refresh")

# ====================================
# CONEXIÓN OPTIMIZADA A SUPABASE (CORREGIDA)
# ====================================

@st.cache_resource
def get_database_engine():
    """Pool de conexiones optimizado"""
    DATABASE_URL = None
    
    # 1. Intentar primero con variables de entorno (para Render / Hugging Face)
    DATABASE_URL = os.environ.get("DATABASE_URL")
    
    # 2. Si no se encuentra, intentar con los secretos de Streamlit Cloud
    if not DATABASE_URL:
        try:
            DATABASE_URL = st.secrets["postgres"]["DATABASE_URL"]
        except Exception:
            # No mostrar st.error aquí, solo imprimir en el log
            print("DATABASE_URL no encontrada en st.secrets ni en variables de entorno.")
            DATABASE_URL = None 

    # 3. Verificación final
    if not DATABASE_URL:
        # Retornar None para que la función que llama (cargar_datos) maneje el error
        return None
    
    try:
        engine = create_engine(
            DATABASE_URL,
            poolclass=pool.QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={
                'options': '-csearch_path=public',
                'connect_timeout': 10
            }
        )
        return engine
    except Exception as e:
        # Si create_engine falla (ej. URL malformada), también retornamos None.
        print(f"Error al crear el engine de base de datos: {e}")
        return None

# ====================================
# FUNCIONES DE CÁLCULO (TODAS LAS ORIGINALES)
# ====================================

def calcular_pyme_y_vence(fecha_creacion):
    """Función original de cálculo PYME"""
    if pd.isna(fecha_creacion): 
        return False, None
    
    ahora = datetime.now()
    hoy = ahora.date()
    ayer = hoy - timedelta(days=1)
    
    if not isinstance(fecha_creacion, pd.Timestamp):
        fecha_creacion = pd.to_datetime(fecha_creacion, errors='coerce')
        if pd.isna(fecha_creacion): 
            return False, None

    fecha = fecha_creacion.date()
    hora = fecha_creacion.time()

    if fecha == hoy:
        return True, fecha_creacion + timedelta(hours=4)
    if fecha == ayer and hora >= time(18, 0):
        return True, datetime.combine(hoy, time(12, 0))
    return False, None

def calcular_vencido(row):
    """Función original de cálculo de vencido"""
    vence_en_dt = pd.to_datetime(row.get('Vence en'), errors='coerce')
    estado = str(row.get('Estado','')).lower()

    if pd.isna(vence_en_dt) or estado not in ['activo', 'iniciado']:
        return False

    ahora_naive = datetime.now().replace(tzinfo=None)
    vence_en_naive = vence_en_dt.tz_convert(None) if hasattr(vence_en_dt, 'tzinfo') and vence_en_dt.tzinfo is not None else vence_en_dt.replace(tzinfo=None)

    try:
        return ahora_naive > vence_en_naive
    except TypeError:
        return False

@st.cache_data(ttl=600)
def get_earliest_snapshot_initial_cohort(df_full_historial):
    """Función original optimizada para cohort inicial"""
    if (df_full_historial is None or df_full_historial.empty or
        'OrdenExterna' not in df_full_historial.columns or
        'Estado' not in df_full_historial.columns or
        'Timestamp_Procesado' not in df_full_historial.columns):
        return set()

    try:
        min_timestamp = df_full_historial['Timestamp_Procesado'].min()
        if pd.isna(min_timestamp):
            return set()

        df_earliest_snapshot = df_full_historial[df_full_historial['Timestamp_Procesado'] == min_timestamp]
        if df_earliest_snapshot.empty:
            return set()

        df_initial_active = df_earliest_snapshot[
            df_earliest_snapshot['Estado'].astype(str).str.lower().isin(['activo', 'iniciado'])
        ]
        
        return set(df_initial_active['OrdenExterna'].unique())
        
    except Exception as e:
        return set()

def calcular_kpis(df, df_full_historial):
    """Función COMPLETA de KPIs con Total_Iniciado y Eficiencia_Inicial"""
    default_kpis = {
        'Total': 0,'Cerrados': 0,'Referidos': 0,'Citados': 0,
        'Validados': 0,'Pendientes': 0,'Manejados': 0,'Eficiencia_Total_%': 0.0,
        'Total_Iniciado': 0, 'Manejados_Inicial': 0, 'Eficiencia_Inicial': 0.0
    }
    
    if df is None or df.empty or 'Estado' not in df.columns:
        return default_kpis
    
    df_kpi = df.copy()
    df_kpi['Estado'] = df_kpi['Estado'].fillna('desconocido').astype(str).str.lower()

    total = len(df_kpi)
    cerrados = df_kpi[df_kpi['Estado'].isin(['cerrado', 'validacion ext'])].shape[0]
    referidos = df_kpi[df_kpi['Estado'] == 'pend trab interno'].shape[0]
    citados = df_kpi[df_kpi['Estado'].isin(['pendiente de calendarizacion', 'calendarizado'])].shape[0]
    validados = df_kpi[df_kpi['Estado'] == 'validacion int'].shape[0]
    pendientes = df_kpi[df_kpi['Estado'].isin(['activo', 'iniciado'])].shape[0]
    manejados = cerrados + referidos + citados + validados
    eficiencia_total = round(manejados * 100 / total, 1) if total > 0 else 0.0

    # KPIs Nuevos
    total_iniciado_en_pagina = 0
    manejados_inicial_en_pagina = 0
    eficiencia_inicial = 0.0

    global_initial_cohort_ids = get_earliest_snapshot_initial_cohort(df_full_historial)

    if global_initial_cohort_ids:
        try:
            tickets_en_pagina_actual_ids = set(df_kpi['OrdenExterna'].unique())
            cohort_tickets_in_current_page_ids = global_initial_cohort_ids.intersection(tickets_en_pagina_actual_ids)
            total_iniciado_en_pagina = len(cohort_tickets_in_current_page_ids)

            if total_iniciado_en_pagina > 0:
                df_kpi_del_cohort = df_kpi[df_kpi['OrdenExterna'].isin(cohort_tickets_in_current_page_ids)]
                
                cerrados_inicial = df_kpi_del_cohort[df_kpi_del_cohort['Estado'].isin(['cerrado', 'validacion ext'])].shape[0]
                referidos_inicial = df_kpi_del_cohort[df_kpi_del_cohort['Estado'] == 'pend trab interno'].shape[0]
                citados_inicial = df_kpi_del_cohort[df_kpi_del_cohort['Estado'].isin(['pendiente de calendarizacion', 'calendarizado'])].shape[0]
                validados_inicial = df_kpi_del_cohort[df_kpi_del_cohort['Estado'] == 'validacion int'].shape[0]
                
                manejados_inicial_en_pagina = cerrados_inicial + referidos_inicial + citados_inicial + validados_inicial
                eficiencia_inicial = round(manejados_inicial_en_pagina * 100 / total_iniciado_en_pagina, 1)

        except Exception:
            pass

    return {
        'Total': total,
        'Cerrados': cerrados,
        'Referidos': referidos,
        'Citados': citados,
        'Validados': validados,
        'Pendientes': pendientes,
        'Manejados': manejados,
        'Eficiencia_Total_%': eficiencia_total,
        'Total_Iniciado': total_iniciado_en_pagina,
        'Manejados_Inicial': manejados_inicial_en_pagina,
        'Eficiencia_Inicial': eficiencia_inicial
    }

# ====================================
# MAPEO DE COLUMNAS
# ====================================

def get_column_mappings():
    """Mapeo completo de columnas"""
    return {
        'trabajo': 'Trabajo', 'orden_externa': 'OrdenExterna', 'cliente': 'Cliente',
        'vence': 'Vence', 'oe_creacion': 'OE_Creacion', 'oe_vence': 'OE_Vence',
        'oe_vencimiento': 'OE_Vencimiento', 'prioridad': 'Prioridad',
        'tipo_de_prioridad': 'Tipo_de_prioridad', 'calendarizada': 'Calendarizada',
        'tanda_preferida': 'Tanda_preferida', 'reclamacion': 'Reclamacion',
        'asignado_a': 'Asignado_A', 'compania': 'Compania', 'supervisor': 'Supervisor',
        'pool': 'Pool', 'estado': 'Estado', 'tecnologia': 'Tecnologia',
        'tipo_servicio': 'Tipo_servicio', 'organizacion': 'Organizacion',
        'sintoma': 'Sintoma', 'creado': 'Creado', 'tipo_cliente': 'Tipo_Cliente',
        'segmento_cliente': 'Segmento_Cliente', 'ciudad': 'Ciudad', 'sector': 'Sector',
        'barrio': 'Barrio', 'cabina': 'Cabina', 'terminal': 'Terminal',
        'cantidad_de_lineas': 'Cantidad_de_lineas', 're_digitada': 'Re_Digitada',
        'timestamp_procesado': 'Timestamp_Procesado', 'fuente_paso': 'Fuente_Paso',
        'tipo_evento': 'Tipo_Evento', 'id': None, 'fecha_actualizacion': None,
        'fecha_registro': None
    }

COLUMN_MAPPING_REVERSE = get_column_mappings()

def denormalizar_columnas_desde_sql(df_sql):
    """Renombra columnas de SQL a CSV"""
    if df_sql is None or df_sql.empty:
        return df_sql
    
    mapeo_valido = {k: v for k, v in COLUMN_MAPPING_REVERSE.items() if v is not None}
    columnas_a_renombrar = {k: v for k, v in mapeo_valido.items() if k in df_sql.columns}
    df_csv = df_sql.rename(columns=columnas_a_renombrar)
    columnas_esperadas = [v for v in mapeo_valido.values() if v in df_csv.columns]
    
    return df_csv[columnas_esperadas]

# ====================================
# CARGA OPTIMIZADA DE DATOS (CORREGIDA)
# ====================================

@st.cache_data(ttl=60, show_spinner=False)
def cargar_datos():
    """Carga optimizada con todas las funcionalidades originales"""
    engine = get_database_engine()

    # --- INICIO DE LA MODIFICACIÓN ---
    # Comprueba si el engine se creó correctamente
    if engine is None:
        # Muestra el error en la app si la conexión falló (ej. secret no configurado)
        st.error("Error de Conexión: No se pudo conectar a la base de datos. Verifique la configuración.")
        return pd.DataFrame() # Devuelve un DataFrame vacío para evitar que el resto de la app falle
    # --- FIN DE LA MODIFICACIÓN ---

    try:
        with st.spinner('⚡ Cargando datos...'):
            start_time = timer.time()
            
            # Query optimizada pero con TODAS las columnas
            query = text("SELECT * FROM historial_cambios_hoy")
            
            with engine.connect() as conn:
                df_sql = pd.read_sql(query, conn)
            
            if df_sql.empty:
                st.warning("La tabla está vacía")
                return pd.DataFrame()

            # Convertir columnas
            df = denormalizar_columnas_desde_sql(df_sql)
            
            # Limpieza de columnas de texto
            df.columns = df.columns.str.strip()
            columnas_texto = ['Supervisor', 'Estado', 'Tipo_Cliente', 'Tipo_servicio', 'Asignado_A', 'Prioridad']
            for col in df.columns.intersection(columnas_texto):
                df[col] = df[col].astype(str).str.strip().str.lower().replace('nan', None)

            # Procesamiento de fechas
            columnas_fechas = ['Creado', 'OE_Creacion', 'OE Vence', 'OE_Vencimiento', 'Vence', 'Timestamp_Procesado']
            for col in df.columns.intersection(columnas_fechas):
                df[f'{col}_Original'] = df[col].astype(str).replace('NaT', None)
                df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True, format='mixed')

            # --- INICIO DE LA MODIFICACIÓN ---
            # Pre-inicializar las columnas para evitar el FutureWarning
            df['PYME'] = False
            df['Vence en'] = pd.NaT
            df['Vencido'] = False
            # --- FIN DE LA MODIFICACIÓN ---

            # Calcular PYME, Vencido, etc.
            if 'OE_Creacion' in df.columns and pd.api.types.is_datetime64_any_dtype(df['OE_Creacion']):
                mask_valid = df['OE_Creacion'].notna()
                if mask_valid.any():
                    pyme_info = df.loc[mask_valid, 'OE_Creacion'].apply(
                        lambda x: pd.Series(calcular_pyme_y_vence(x), index=['PYME', 'Vence en'])
                    )
                    df.loc[mask_valid, ['PYME', 'Vence en']] = pyme_info.values

                    df['Vence en'] = pd.to_datetime(df['Vence en'], errors='coerce')
                    mask_vence = df['Vence en'].notna()
                    if mask_vence.any():
                        df['Vencido'] = df['Vencido'].astype(bool) # Asegurar el tipo antes de asignar
                        df.loc[mask_vence, 'Vencido'] = df[mask_vence].apply(calcular_vencido, axis=1)

                es_negocio = df.get('Tipo_Cliente', pd.Series(dtype=str)) == 'negocio'
                df['PYME'] = df['PYME'].fillna(False).astype(bool) 
                df['Es_PYME_Negocio'] = df['PYME'] & es_negocio
            
            if 'Vencido' not in df.columns:
                 df['Vencido'] = False
            else:
                 df['Vencido'] = df['Vencido'].fillna(False).astype(bool)
            
            # --- MENSAJE DE ÉXITO ELIMINADO ---
            # st.success(f"✅ {len(df):,} registros en {timer.time() - start_time:.2f}s")
            return df
            
    except Exception as e:
        st.error(f"❌ Error al consultar la base de datos: {e}")
        return pd.DataFrame()

# ====================================
# FUNCIONES DE DISPLAY (TODAS LAS ORIGINALES)
# ====================================

def obtener_datos_unicos(df_input):
    """Obtiene datos únicos con el método original mejorado"""
    if df_input is None or df_input.empty or 'OrdenExterna' not in df_input.columns:
        return pd.DataFrame()

    if 'Timestamp_Procesado' in df_input.columns and pd.api.types.is_datetime64_any_dtype(df_input['Timestamp_Procesado']):
        df_temp = df_input.dropna(subset=['OrdenExterna', 'Timestamp_Procesado'])
        df_sorted = df_temp.sort_values('Timestamp_Procesado', ascending=False)
        return df_sorted.drop_duplicates(subset=['OrdenExterna'], keep='first')
    else:
        return df_input.drop_duplicates(subset=['OrdenExterna'], keep='first')

def formatear_para_display(df_input):
    """Formateo completo original"""
    if df_input is None or df_input.empty:
        return df_input
    
    df_display = df_input.copy()
    
    columnas_fechas = ['Creado', 'OE_Creacion', 'OE Vence', 'OE_Vencimiento', 'Vence en', 'Timestamp_Procesado']
    for col in df_display.columns.intersection(columnas_fechas):
        if pd.api.types.is_datetime64_any_dtype(df_display[col]):
            df_display[col] = df_display[col].apply(lambda x: x.strftime('%d/%m/%Y %H:%M') if pd.notna(x) else None)

    if 'Vencido' in df_display.columns and df_display['Vencido'].dtype == 'bool':
        df_display['Vencido'] = df_display['Vencido'].map({True: 'Sí', False: 'No'}).fillna('No')

    return df_display

def to_excel(df):
    """Exportación a Excel original"""
    if df is None or df.empty:
        return None

    output = BytesIO()
    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_formateada = formatear_para_display(df.copy())
            df_formateada.to_excel(writer, index=False, sheet_name='Datos')
        return output.getvalue()
    except Exception:
        return None

def crear_resumen_admin(df, agrupar_por='Supervisor'):
    """Resumen admin completo con fila TOTAL"""
    cols = [agrupar_por, 'Total', 'Cerrados', 'Referidos', 'Citados', 'Validados_Int', 'Pendientes', 'Total Manejado', 'Eficiencia_Total_%']
    if df is None or df.empty or agrupar_por not in df.columns:
        return pd.DataFrame(columns=cols)

    df_copy = df.copy()
    df_copy[agrupar_por] = df_copy[agrupar_por].fillna('Desconocido').astype(str)
    df_copy['Estado'] = df_copy['Estado'].fillna('Desconocido').astype(str).str.lower()

    resumen = df_copy.groupby(agrupar_por).agg(
        Total=('OrdenExterna', 'count'),
        Cerrados=('Estado', lambda x: x.isin(['cerrado', 'validacion ext']).sum()),
        Referidos=('Estado', lambda x: (x == 'pend trab interno').sum()),
        Citados=('Estado', lambda x: x.isin(['pendiente de calendarizacion', 'calendarizado']).sum()),
        Validados_Int=('Estado', lambda x: (x == 'validacion int').sum()),
        Pendientes=('Estado', lambda x: x.isin(['activo', 'iniciado']).sum())
    ).reset_index()

    resumen['Total Manejado'] = resumen['Cerrados'] + resumen['Referidos'] + resumen['Citados'] + resumen['Validados_Int']
    resumen['Eficiencia_Total_%'] = np.where(
        resumen['Total'] > 0,
        round(resumen['Total Manejado'] * 100 / resumen['Total'], 1),
        0.0
    )
    
    # Añadir fila TOTAL
    if not resumen.empty:
        total_row = pd.Series({
            agrupar_por: 'TOTAL',
            'Total': resumen['Total'].sum(),
            'Cerrados': resumen['Cerrados'].sum(),
            'Referidos': resumen['Referidos'].sum(),
            'Citados': resumen['Citados'].sum(),
            'Validados_Int': resumen['Validados_Int'].sum(),
            'Pendientes': resumen['Pendientes'].sum(),
            'Total Manejado': resumen['Total Manejado'].sum()
        })
        
        if total_row['Total'] > 0:
            total_row['Eficiencia_Total_%'] = round(total_row['Total Manejado'] * 100 / total_row['Total'], 1)
        else:
            total_row['Eficiencia_Total_%'] = 0.0
        
        resumen = pd.concat([resumen, total_row.to_frame().T], ignore_index=True)

    return resumen

def filtrar_dataframe_con_historial(df_completo, df_unicos_filtrados, texto_busqueda, supervisor_filter=None, estado_filter=None):
    """Filtrado con historial completo original"""
    if df_completo is None or df_completo.empty or not texto_busqueda:
        return pd.DataFrame()

    df_para_buscar = df_completo if df_unicos_filtrados is None else df_unicos_filtrados
    texto_busqueda = texto_busqueda.lower()
    
    cols_busqueda = ['OrdenExterna', 'Asignado_A', 'Cliente', 'Supervisor']
    cols_presentes = [col for col in cols_busqueda if col in df_para_buscar.columns]

    try:
        mask = df_para_buscar[cols_presentes].astype(str).apply(
            lambda x: x.str.lower().str.contains(texto_busqueda, na=False)
        ).any(axis=1)
    except:
        return pd.DataFrame()

    tickets_encontrados = df_para_buscar[mask]['OrdenExterna'].unique()
    if len(tickets_encontrados) == 0:
        return pd.DataFrame()

    df_historial = df_completo[df_completo['OrdenExterna'].isin(tickets_encontrados)].copy()

    if supervisor_filter and 'Supervisor' in df_historial.columns:
        df_historial = df_historial[df_historial['Supervisor'].astype(str) == str(supervisor_filter)]

    if 'Timestamp_Procesado' in df_historial.columns:
        df_historial = df_historial.sort_values(['OrdenExterna', 'Timestamp_Procesado'], ascending=[True, False])

    return df_historial

# ====================================
# FUNCIONES DE TRACKING (TODAS)
# ====================================

def get_color_estado(estado_str):
    """Colores originales por estado"""
    estado_str = str(estado_str).lower()
    colors = {
        'cerrado': '#32CD32',
        'validacion ext': '#32CD32',
        'pendiente de calendarizacion': '#FFD700',
        'calendarizado': '#FFD700',
        'pend trab interno': '#FFA500',
        'activo': '#1E90FF',
        'iniciado': '#1E90FF',
        'validacion int': '#8A2BE2'
    }
    return colors.get(estado_str, '#696969')

def formatear_fecha(fecha_dt):
    """Formateo de fecha original"""
    if pd.isna(fecha_dt):
        return 'N/A'
    if isinstance(fecha_dt, pd.Timestamp):
        return fecha_dt.strftime('%d/%m/%Y %H:%M')
    return str(fecha_dt)

def calcular_tiempo_transcurrido(fecha_inicio):
    """Cálculo de tiempo transcurrido original"""
    if pd.isna(fecha_inicio):
        return 'N/A'
    
    if not isinstance(fecha_inicio, pd.Timestamp):
        fecha_inicio = pd.to_datetime(fecha_inicio, errors='coerce')
        if pd.isna(fecha_inicio):
            return 'N/A'

    ahora = datetime.now()
    ahora_naive = ahora.replace(tzinfo=None)
    fecha_inicio_naive = fecha_inicio.replace(tzinfo=None) if hasattr(fecha_inicio, 'tzinfo') else fecha_inicio

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

# ====================================
# FUNCIONES DE RENDERIZADO (COMPLETAS)
# ====================================

def display_kpi_metrics(kpis, page_key, critical_metric_key=None, critical_delta_text="Críticos"):
    """Display KPIs con lógica condicional por página"""
    
    def metric_with_critical(col, label, key, delta_text=None, delta_color="normal"):
        value = kpis.get(key, 0)
        if not isinstance(value, (int, float)): 
            value = 0

        if key == critical_metric_key and value > 0:
            col.metric(label, value, delta=critical_delta_text, delta_color="inverse")
        else:
            col.metric(label, value)

    # Vista para página PRINCIPAL (10 KPIs)
    if page_key == "principal":
        col1, col2, col3, col4, col5 = st.columns(5)
        
        if st.session_state.user_role == "admin":
            metric_with_critical(col1, "📋 Total", 'Total')
            metric_with_critical(col2, "⏳ Pendientes", 'Pendientes')
            metric_with_critical(col3, "🚀 Total Iniciado", 'Total_Iniciado')
            metric_with_critical(col4, "✅ Cerrados", 'Cerrados')
            metric_with_critical(col5, "🔄 Total Manejado", 'Manejados')

            col6, col7, col8, col9, col10 = st.columns(5)
            col6.metric("📊 Eficiencia Total", f"{kpis.get('Eficiencia_Total_%', 0.0):.1f}%")
            col7.metric("📈 Eficiencia Inicial", f"{kpis.get('Eficiencia_Inicial', 0.0):.1f}%")
            metric_with_critical(col8, "📤 Referidos", 'Referidos')
            metric_with_critical(col9, "📅 Citados", 'Citados')
            metric_with_critical(col10, "✔️ Validados (Int)", 'Validados')
        else:
            metric_with_critical(col1, "📋 Total", 'Total')
            metric_with_critical(col2, "⏳ Pendientes", 'Pendientes')
            metric_with_critical(col3, "🚀 Total Iniciado", 'Total_Iniciado')
            metric_with_critical(col4, "✅ Cerrados", 'Cerrados')
            metric_with_critical(col5, "📤 Referidos", 'Referidos')

            col6, col7, col8, col9, col10 = st.columns(5)
            metric_with_critical(col6, "📅 Citados", 'Citados')
            metric_with_critical(col7, "✔️ Validados (Int)", 'Validados')
            metric_with_critical(col8, "🔄 Total Manejado", 'Manejados')
            col9.metric("📊 Eficiencia Total", f"{kpis.get('Eficiencia_Total_%', 0.0):.1f}%")
            col10.metric("📈 Eficiencia Inicial", f"{kpis.get('Eficiencia_Inicial', 0.0):.1f}%")
    else:
        # Vista para OTRAS PÁGINAS (8 KPIs)
        col1, col2, col3, col4 = st.columns(4)
        
        metric_with_critical(col1, "📋 Total", 'Total')
        col2.metric("📊 Eficiencia", f"{kpis.get('Eficiencia_Total_%', 0.0):.1f}%")
        metric_with_critical(col3, "✅ Cerrados", 'Cerrados')
        metric_with_critical(col4, "⏳ Pendientes", 'Pendientes')

        col5, col6, col7, col8 = st.columns(4)
        metric_with_critical(col5, "🔄 Total Manejado", 'Manejados')
        metric_with_critical(col6, "📤 Referidos", 'Referidos')
        metric_with_critical(col7, "📅 Citados", 'Citados')
        metric_with_critical(col8, "✔️ Validados (Int)", 'Validados')

def display_detail_table(df_data, df_full_historial, role, role_supervisor_id, global_supervisor_sel, status_filter, page_key, file_name_prefix):
    """Tabla de detalles completa original"""
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

def render_dashboard_page(title_prefix, df_page_data, df_full_historial, role, role_supervisor_id, global_supervisor_sel, status_filter, page_key, critical_metric_key=None):
    """Renderizado completo de dashboard con gráficos para admin"""
    if df_page_data is None or df_page_data.empty:
        st.warning(f"No hay tickets para mostrar en '{title_prefix}'")
        return

    kpis = calcular_kpis(df_page_data, df_full_historial)

    # Vista Admin con GRÁFICOS
    if role == "admin":
        # KPIs superiores
        if page_key == "principal":
            st.subheader("📊 Resumen General (Todos los Supervisores)")
            col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
            col1.metric("Total tickets", kpis['Total'])
            col2.metric("Eficiencia Total", f"{kpis['Eficiencia_Total_%']:.1f}%")
            col3.metric("Total Iniciado", kpis['Total_Iniciado'])
            col4.metric("Eficiencia Inicial", f"{kpis['Eficiencia_Inicial']:.1f}%")
            col5.metric("Cerrados", kpis['Cerrados'])
            col6.metric("Pendientes", kpis['Pendientes'])
            col7.metric("Manejados", kpis['Manejados'])
        else:
            st.subheader("📊 Resumen General")
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Total", kpis['Total'])
            col2.metric("Eficiencia", f"{kpis['Eficiencia_Total_%']:.1f}%")
            col3.metric("Cerrados", kpis['Cerrados'])
            col4.metric("Pendientes", kpis['Pendientes'])
            col5.metric("Manejados", kpis['Manejados'])

        st.markdown("---")
        st.subheader("👥 Desglose por Supervisor")

        resumen_admin = crear_resumen_admin(df_page_data, 'Supervisor')

        if not resumen_admin.empty:
            # Gráficos
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                st.markdown("#### 📊 Eficiencia por supervisor (%)")
                resumen_graf = resumen_admin[resumen_admin['Supervisor'] != 'TOTAL']
                fig_eff = px.bar(resumen_graf.sort_values('Eficiencia_Total_%'), 
                                 x='Eficiencia_Total_%', y='Supervisor', 
                                 orientation='h', text='Eficiencia_Total_%',
                                 color='Eficiencia_Total_%', color_continuous_scale='Blues')
                fig_eff.add_shape(type="line", x0=80, y0=-0.5, x1=80, 
                                  y1=len(resumen_graf)-0.5, 
                                  line=dict(color="grey", width=2, dash="dash"))
                fig_eff.update_traces(texttemplate='%{text:.1f}%')
                fig_eff.update_layout(template="plotly_dark", height=400)
                st.plotly_chart(fig_eff, use_container_width=True)

            with col_chart2:
                st.markdown("#### 🎫 Total por supervisor")
                fig_total = px.bar(resumen_graf.sort_values('Total', ascending=False),
                                   x='Supervisor', y='Total', text='Total',
                                   color='Total', color_continuous_scale='Blues')
                fig_total.update_traces(texttemplate='%{text}')
                fig_total.update_layout(template="plotly_dark", height=400)
                st.plotly_chart(fig_total, use_container_width=True)

            # Gráficos adicionales condicionales
            if page_key != "pymes":
                st.markdown("#### ⏳ Tickets Pendientes")
                if 'Estado' in df_page_data.columns:
                    pendientes_df = df_page_data[df_page_data['Estado'].str.lower().isin(['activo', 'iniciado'])]
                    if not pendientes_df.empty:
                        resumen_pend = pendientes_df.groupby('Supervisor')['OrdenExterna'].count().reset_index()
                        resumen_pend.columns = ['Supervisor', 'Pendientes']
                        fig_pend = px.bar(resumen_pend.sort_values('Pendientes', ascending=False),
                                          x='Supervisor', y='Pendientes', text='Pendientes',
                                          color='Pendientes', color_continuous_scale='Blues')
                        fig_pend.update_layout(template="plotly_dark", height=300)
                        st.plotly_chart(fig_pend, use_container_width=True)

            if page_key == "pymes" and 'Vencido' in df_page_data.columns:
                st.markdown("#### ⚠️ PYMEs Vencidas")
                vencidos_df = df_page_data[df_page_data['Vencido'] == True]
                if not vencidos_df.empty:
                    resumen_venc = vencidos_df.groupby('Supervisor')['OrdenExterna'].count().reset_index()
                    resumen_venc.columns = ['Supervisor', 'Vencidas']
                    fig_venc = px.bar(resumen_venc.sort_values('Vencidas', ascending=False),
                                      x='Supervisor', y='Vencidas', text='Vencidas',
                                      color='Vencidas', color_continuous_scale='Reds')
                    fig_venc.update_layout(template="plotly_dark", height=300)
                    st.plotly_chart(fig_venc, use_container_width=True)

            # Tabla resumen
            st.markdown("---")
            st.markdown("#### 📋 Resumen Detallado")
            st.dataframe(resumen_admin, use_container_width=True, hide_index=True)
            
            excel_resumen = to_excel(resumen_admin)
            if excel_resumen:
                st.download_button(
                    "📥 Descargar Resumen",
                    data=excel_resumen,
                    file_name=f"resumen_{page_key}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )

    # Vista Gerencia/Supervisor
    else:
        display_kpi_metrics(kpis, page_key, critical_metric_key)
        st.markdown("---")
        
        if role == "gerencia":
            st.subheader("👥 Resumen por Supervisor")
            resumen = crear_resumen_admin(df_page_data, 'Supervisor')
            st.dataframe(resumen, use_container_width=True, hide_index=True)
            
            st.markdown("---")
            st.subheader("👨‍🔧 Resumen por Técnico")
            if 'Asignado_A' in df_page_data.columns:
                resumen_tec = crear_resumen_admin(df_page_data, 'Asignado_A')
                st.dataframe(resumen_tec, use_container_width=True, hide_index=True)
        else:
            agrupar = 'Supervisor' if role == 'supervisor_old' else 'Asignado_A'
            titulo = 'Supervisor' if role == 'supervisor_old' else 'Técnico'
            st.subheader(f"👥 Resumen por {titulo}")
            if agrupar in df_page_data.columns:
                resumen = crear_resumen_admin(df_page_data, agrupar)
                st.dataframe(resumen, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("📋 Detalle de Tickets")
        display_detail_table(df_page_data, df_full_historial, role, role_supervisor_id, 
                             global_supervisor_sel, status_filter, page_key, "detalle_" + page_key) # Corregido el último parámetro

# ====================================
# APLICACIÓN PRINCIPAL
# ====================================

# Cargar datos
df = cargar_datos()

if df is None or df.empty:
    st.error("No se pudieron cargar datos o la base de datos está vacía. La aplicación no puede continuar.")
    st.stop() # Detener la ejecución si no hay datos

df_unicos_base = obtener_datos_unicos(df)

# Sidebar
st.sidebar.title("📌 Menú")

if st.session_state.user_role == "admin":
    menu_options = ["🏠 Principal", "📊 Análisis PYMEs", "⏰ Puntualidad", 
                    "🎯 Citas Puntuales", "📅 Antiguas", "📈 Rendimiento"]
else:
    menu_options = ["🏠 Principal", "📊 Análisis PYMEs", "⏰ Puntualidad", 
                    "🎯 Citas Puntuales", "🔍 Tracking Ticket", "📅 Antiguas", "📈 Rendimiento"]

menu = st.sidebar.radio("Selecciona una página", menu_options)

st.sidebar.markdown("---")
st.sidebar.subheader("Filtros")

# Filtros
supervisor_options = ["Todos"]
estado_options = []

if 'Supervisor' in df_unicos_base.columns:
    supervisores = sorted([str(s) for s in df_unicos_base['Supervisor'].dropna().unique()])
    supervisor_options.extend(supervisores)

if 'Estado' in df_unicos_base.columns:
    estados = sorted([str(e) for e in df_unicos_base['Estado'].dropna().unique()])
    estado_options = estados

if st.session_state.user_role in ["admin", "gerencia", "supervisor_old"]:
    supervisor_sel = st.sidebar.selectbox("Supervisor", supervisor_options)
else:
    supervisor_sel = st.session_state.supervisor_id

estatus_sel = st.sidebar.multiselect("Estado", options=estado_options, default=estado_options)

# Aplicar filtros
df_supervisor_unicos = df_unicos_base.copy()
if st.session_state.user_role == "supervisor" and 'Supervisor' in df_supervisor_unicos.columns:
    df_supervisor_unicos = df_supervisor_unicos[df_supervisor_unicos['Supervisor'] == st.session_state.supervisor_id]
elif supervisor_sel != "Todos" and 'Supervisor' in df_supervisor_unicos.columns:
    df_supervisor_unicos = df_supervisor_unicos[df_supervisor_unicos['Supervisor'] == supervisor_sel]

df_unicos = df_supervisor_unicos.copy()
if estatus_sel and 'Estado' in df_unicos.columns:
    df_unicos = df_unicos[df_unicos['Estado'].isin(estatus_sel)]

# ====================================
# RENDERIZAR PÁGINAS (TODAS LAS ORIGINALES)
# ====================================

if menu == "🏠 Principal":
    st.title(f"🏠 Dashboard Principal - {supervisor_sel if supervisor_sel != 'Todos' else st.session_state.user_role.title()}")
    
    if st.session_state.user_role in ["admin", "gerencia"]:
        render_dashboard_page("Principal", df_unicos, df, st.session_state.user_role,
                              st.session_state.supervisor_id, supervisor_sel, 
                              estatus_sel, "principal")
    else:
        kpis = calcular_kpis(df_unicos, df)
        display_kpi_metrics(kpis, "principal", 'Pendientes')
        st.markdown("---")
        st.subheader("🗂️ Tabla de Tickets")
        # --- CORRECCIÓN DE ERROR ---
        # Estaba pasando df_img_path que no está definido. Cambiado a df_unicos.
        display_detail_table(df_unicos, df, st.session_state.user_role, 
                             st.session_state.supervisor_id, supervisor_sel,
                             estatus_sel, "principal_sup", "principal")

elif menu == "📊 Análisis PYMEs":
    st.title(f"📊 Análisis PYMEs")
    df_pymes = pd.DataFrame()
    if 'Es_PYME_Negocio' in df_unicos.columns:
        df_pymes = df_unicos[df_unicos['Es_PYME_Negocio'] == True]
    render_dashboard_page("PYMEs", df_pymes, df, st.session_state.user_role,
                          st.session_state.supervisor_id, supervisor_sel, 
                          estatus_sel, "pymes")

elif menu == "⏰ Puntualidad":
    st.title(f"⏰ Análisis de Puntualidad")
    hoy = pd.Timestamp.now().normalize()
    df_puntuales = pd.DataFrame()
    
    if 'OE_Vencimiento' in df_unicos.columns:
        mask_fecha = df_unicos['OE_Vencimiento'].dt.normalize() == hoy
        oe_venc_orig = df_unicos.get('OE_Vencimiento_Original', pd.Series())
        mask_texto = oe_venc_orig.str.lower() == 'hoy'
        df_puntuales = df_unicos[mask_fecha | mask_texto]
    
    render_dashboard_page("Puntualidad", df_puntuales, df, st.session_state.user_role,
                          st.session_state.supervisor_id, supervisor_sel, 
                          estatus_sel, "puntualidad")

elif menu == "🎯 Citas Puntuales":
    st.title(f"🎯 Análisis de Citas Puntuales")
    hoy = pd.Timestamp.now().normalize()
    
    df_citas = pd.DataFrame()
    if all(col in df_unicos.columns for col in ['Prioridad', 'Vence', 'Estado', 'OrdenExterna']):
        df_base = df_unicos.dropna(subset=['Vence'])
        # --- CORRECCIÓN DE ERROR ---
        # El .tr.lower() era un error de tipeo, debe ser .str.lower()
        mask = (df_base['Prioridad'].astype(str) == '100') & \
               (df_base.get('OE_Vencimiento_Original', pd.Series()).str.lower() == 'vencida') & \
               (df_base['Vence'].dt.normalize() == hoy)
        df_citas = df_base[mask]
    
    render_dashboard_page("Citas", df_citas, df, st.session_state.user_role,
                          st.session_state.supervisor_id, supervisor_sel, 
                          estatus_sel, "citas")

elif menu == "🔍 Tracking Ticket":
    st.title(f"🔍 Tracking de Tickets")
    st.markdown("---")
    
    ticket_busqueda = st.text_input("🎫 Ingresa el número de Orden Externa",
                                  placeholder="Ejemplo: 12345678")
    
    if ticket_busqueda:
        df_track = filtrar_dataframe_con_historial(df, df_supervisor_unicos, 
                                                    ticket_busqueda, supervisor_sel, None)
        
        if df_track.empty:
            st.warning("⚠️ No se encontraron tickets")
        else:
            st.success(f"✅ {df_track['OrdenExterna'].nunique()} ticket(s) encontrado(s)")
            
            for orden in df_track['OrdenExterna'].unique():
                historial = df_track[df_track['OrdenExterna'] == orden].sort_values(
                    'Timestamp_Procesado', ascending=False, na_position='last')
                
                if not historial.empty:
                    ticket_data = historial.iloc[0]
                    
                    with st.container(border=True):
                        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                        
                        with col1:
                            st.markdown(f"### 🎫 Ticket: **{orden}**")
                        
                        with col2:
                            color = get_color_estado(ticket_data.get('Estado', 'N/A'))
                            st.markdown(f"""<div style='background-color: {color}; 
                                                 color: white; padding: 8px; border-radius: 5px; 
                                                 text-align: center; font-weight: bold;'>
                                                 {str(ticket_data.get('Estado', 'N/A')).upper()}</div>""", 
                                        unsafe_allow_html=True)
                        
                        with col3:
                            es_pyme = ticket_data.get('Es_PYME_Negocio', False)
                            tipo = "🏢 PYME" if es_pyme else "👤 Regular"
                            st.markdown(f"""<div style='padding: 8px; border-radius: 5px; 
                                                 text-align: center; background-color: #2a2a4a;'>
                                                 {tipo}</div>""", unsafe_allow_html=True)
                        
                        with col4:
                            if ticket_data.get('Vencido', False) and es_pyme:
                                badge = "⚠️ VENCIDO"
                                color = "#DC143C"
                            elif es_pyme:
                                badge = "⏱️ En Tiempo"
                                color = "#32CD32"
                            else:
                                badge = "📊 Normal"
                                color = "#2a2a4a"
                            
                            st.markdown(f"""<div style='background-color: {color}; 
                                                 color: white; padding: 8px; border-radius: 5px; 
                                                 text-align: center; font-weight: bold;'>
                                                 {badge}</div>""", unsafe_allow_html=True)
                        
                        st.markdown("---")
                        
                        col_info, col_time = st.columns(2)
                        
                        with col_info:
                            st.markdown("#### 📋 Información General")
                            st.text(f"🆔 Orden: {ticket_data.get('OrdenExterna', 'N/A')}")
                            st.text(f"👤 Cliente: {ticket_data.get('Cliente', 'N/A')}")
                            st.text(f"🏢 Tipo: {ticket_data.get('Tipo_Cliente', 'N/A')}")
                            st.text(f"👨‍💼 Supervisor: {ticket_data.get('Supervisor', 'N/A')}")
                            st.text(f"👨‍🔧 Asignado: {ticket_data.get('Asignado_A', 'N/A')}")
                        
                        with col_time:
                            st.markdown("#### ⏰ Timeline")
                            creacion = ticket_data.get('OE_Creacion')
                            st.text(f"📅 Creación: {formatear_fecha(creacion)}")
                            st.text(f"⏳ Transcurrido: {calcular_tiempo_transcurrido(creacion)}")
                            
                            if es_pyme and pd.notna(ticket_data.get('Vence en')):
                                vence = ticket_data.get('Vence en')
                                st.text(f"⏰ Vence: {formatear_fecha(vence)}")
                        
                        with st.expander("Ver Historial Completo 📜"):
                            df_hist_display = formatear_para_display(historial)
                            st.dataframe(df_hist_display, use_container_width=True, hide_index=True)

elif menu == "📅 Antiguas":
    st.title(f"📅 Análisis de Antigüedad")
    hoy = pd.Timestamp.now().normalize()
    
    tab1, tab2 = st.tabs(["📅 Antigüedad 3 Días", "⚠️ Antigüedad Extrema (+3 días)"])
    
    with tab1:
        fecha_3_dias = hoy - timedelta(days=3)
        df_3_dias = pd.DataFrame()
        if 'OE_Creacion' in df_unicos.columns:
            df_3_dias = df_unicos[df_unicos['OE_Creacion'].dt.normalize() == fecha_3_dias]
        
        render_dashboard_page("3 Días", df_3_dias, df, st.session_state.user_role,
                              st.session_state.supervisor_id, supervisor_sel,
                              estatus_sel, "antiguas_3_dias")
    
    with tab2:
        fecha_limite = hoy - timedelta(days=3)
        df_extrema = pd.DataFrame()
        if 'OE_Creacion' in df_unicos.columns:
            df_extrema = df_unicos[df_unicos['OE_Creacion'].dt.normalize() < fecha_limite]
        
        render_dashboard_page("Extrema", df_extrema, df, st.session_state.user_role,
                              st.session_state.supervisor_id, supervisor_sel,
                              estatus_sel, "antiguas_extrema", 'Total')

elif menu == "📈 Rendimiento":
    st.title(f"📈 Análisis de Rendimiento")
    
    col1, col2 = st.columns(2)
    fecha_inicio = col1.date_input("Fecha Inicio", datetime.now().date() - timedelta(days=30))
    fecha_fin = col2.date_input("Fecha Fin", datetime.now().date())
    
    df_rendimiento = pd.DataFrame()
    if 'OE_Creacion' in df_unicos.columns and fecha_inicio <= fecha_fin:
        fecha_inicio_dt = pd.to_datetime(fecha_info)
        fecha_fin_dt = pd.to_datetime(fecha_fin) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        
        # --- CORRECCIÓN DE ERROR ---
        # Cambiado 'OE_SISTEMA' a 'OE_Creacion' para que el filtro de fecha funcione
        df_rendimiento = df_unicos[
            (df_unicos['OE_Creacion'] >= fecha_inicio_dt) &
            (df_unicos['OE_Creacion'] <= fecha_fin_dt)
        ]
    
    if df_rendimiento.empty:
        st.warning("No hay datos en el período seleccionado")
    else:
        render_dashboard_page("Rendimiento", df_rendimiento, df, st.session_state.user_role,
                              st.session_state.supervisor_id, supervisor_sel,
                              estatus_sel, "rendimiento")
