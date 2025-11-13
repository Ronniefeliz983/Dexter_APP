import streamlit as st
import pandas as pd
from datetime import datetime, date
import os
import io
import re
from sqlalchemy import create_engine, text, inspect
import traceback # Para mostrar errores detallados

# Intenta importar pyperclip y maneja el error si no está instalado
try:
    import pyperclip
except ImportError:
    st.error("La librería 'pyperclip' es necesaria. Por favor, instálala con: pip install pyperclip")
    st.stop()

# ==============================================================================
# --- CONFIGURACIÓN Y CONSTANTES ---
# ==============================================================================
st.set_page_config(
    page_title="Sistema KUNAI - v2.9.0", # Título actualizado
    page_icon="📋",
    layout="wide"
)

# ***** CONEXIÓN A SUPABASE *****
DATABASE_URL = "postgresql://postgres.jbsycnrlkvdjbiktkjpl:xCt4FTBhDPbFT@aws-1-us-east-2.pooler.supabase.com:6543/postgres"

# ***** ARCHIVOS LOCALES *****
ARCHIVO_SNAPSHOT_HOY = "kunai_snapshot_hoy.csv"
ARCHIVO_HISTORIAL_CAMBIOS = "kunai_historial_cambios.csv"
ARCHIVO_REABIERTOS = "kunai_reabiertos_hoy.csv" # Es histórico
ARCHIVO_FECHA_ULTIMO_RESET = "ultima_fecha_reset.txt"
ARCHIVO_LOTE_ACTUAL = "lote_actual.txt"
# --- v2.9.0: Nuevos archivos para Head Count ---
ARCHIVO_HC_TECNICOS = "kunai_hc_tecnicos.csv"
ARCHIVO_HC_SUPERVISORES = "kunai_hc_supervisores.csv"

# FILTROS DE SUPERVISORES PERMITIDOS
SUPERVISORES_PERMITIDOS = ['601665', '601378', '61768', '601799']
FILTRAR_POR_SUPERVISOR = True

# ***** COLUMNAS A IGNORAR EN DETECCIÓN DE CAMBIOS *****
COLUMNAS_IGNORAR_CAMBIOS = {
    'Timestamp_Procesado',
    'Fuente_Paso',
    'Tipo_Evento',
    'Lote_Procesado',
    'Cabina',
    'Terminal',
    'Cantidad_de_lineas',
    'Re_Digitada',
    'Fecha_Nacimiento' 
}

# ==============================================================================
# --- CONEXIÓN Y CREACIÓN DE TABLAS EN SUPABASE ---
# ==============================================================================

@st.cache_resource
def get_database_engine():
    """Crea una conexión a Supabase y se asegura de que las tablas/columnas existan."""
    try:
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            connect_args={
                'options': '-csearch_path=public',
                'connect_timeout': 10
            }
        )

        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS snapshot_hoy (
                    id SERIAL PRIMARY KEY, trabajo TEXT, orden_externa TEXT UNIQUE, cliente TEXT, vence TEXT,
                    oe_creacion TEXT, oe_vence TEXT, oe_vencimiento TEXT, prioridad TEXT,
                    tipo_de_prioridad TEXT, calendarizada TEXT, tanda_preferida TEXT, reclamacion TEXT,
                    asignado_a TEXT, compania TEXT, supervisor TEXT, pool TEXT, estado TEXT, tecnologia TEXT,
                    tipo_servicio TEXT, organizacion TEXT, sintoma TEXT, creado TEXT, tipo_cliente TEXT,
                    segmento_cliente TEXT, ciudad TEXT, sector TEXT, barrio TEXT, cabina TEXT, terminal TEXT,
                    cantidad_de_lineas TEXT, re_digitada TEXT, timestamp_procesado TIMESTAMP, fuente_paso TEXT,
                    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS historial_cambios (
                    id SERIAL PRIMARY KEY, trabajo TEXT, orden_externa TEXT, cliente TEXT, vence TEXT,
                    oe_creacion TEXT, oe_vence TEXT, oe_vencimiento TEXT, prioridad TEXT,
                    tipo_de_prioridad TEXT, calendarizada TEXT, tanda_preferida TEXT, reclamacion TEXT,
                    asignado_a TEXT, compania TEXT, supervisor TEXT, pool TEXT, estado TEXT, tecnologia TEXT,
                    tipo_servicio TEXT, organizacion TEXT, sintoma TEXT, creado TEXT, tipo_cliente TEXT,
                    segmento_cliente TEXT, ciudad TEXT, sector TEXT, barrio TEXT, cabina TEXT, terminal TEXT,
                    cantidad_de_lineas TEXT, re_digitada TEXT, timestamp_procesado TIMESTAMP, fuente_paso TEXT,
                    tipo_evento TEXT,
                    lote_procesado INTEGER,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS reabiertos (
                    caso TEXT,
                    codigo TEXT,
                    tarjeta TEXT,
                    supervisor TEXT,
                    fecha TEXT,
                    condicion TEXT
                );
                
                /* --- v2.9.0: Nuevas tablas de Head Count --- */
                CREATE TABLE IF NOT EXISTS head_count_tecnico (
                    ficha TEXT,
                    tarjeta TEXT PRIMARY KEY, /* Usamos tarjeta como Primary Key */
                    nombre TEXT,
                    telefono TEXT,
                    funcion TEXT,
                    supervisor TEXT,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS head_count_supervisor (
                    ficha TEXT,
                    tarjeta TEXT PRIMARY KEY, /* Usamos tarjeta como Primary Key */
                    nombre TEXT,
                    telefono TEXT,
                    rol TEXT,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                /* --- Fin v2.9.0 --- */
            """))

            inspector = inspect(engine)
            for table_name in ['historial_cambios']: 
                columns = [col['name'] for col in inspector.get_columns(table_name)]
                if 'lote_procesado' not in columns:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN lote_procesado INTEGER;"))
                    st.info(f"Columna 'lote_procesado' añadida a la tabla '{table_name}' en Supabase.")
                    conn.commit()

            reabiertos_columns = [col['name'] for col in inspector.get_columns('reabiertos')]
            
            if 'tarjeta_supervisor' not in reabiertos_columns: 
                try:
                    conn.execute(text("ALTER TABLE reabiertos ADD COLUMN tarjeta_supervisor TEXT;"))
                    st.info("Columna 'tarjeta_supervisor' añadida a 'reabiertos'. Rellenando datos existentes...")
                    
                    conn.execute(text("""
                        UPDATE reabiertos
                        SET tarjeta_supervisor = CASE
                            WHEN LOWER(TRIM(supervisor)) = 'aneudy peralta garcia' THEN '601378'
                            WHEN LOWER(TRIM(supervisor)) = 'evangelista nu?ez' THEN '61768'
                            WHEN LOWER(TRIM(supervisor)) = 'evangelista nuñez' THEN '61768'
                            WHEN LOWER(TRIM(supervisor)) = 'iven eduardo urbaez gonzalez' THEN '601665'
                            WHEN LOWER(TRIM(supervisor)) = 'jean carlos ramirez' THEN '601799'
                            ELSE NULL
                        END
                        WHERE tarjeta_supervisor IS NULL;
                    """))
                    st.success("¡Datos rellenados! Los registros existentes de 'reabiertos' han sido actualizados.")
                    conn.commit() 
                except Exception as e:
                    st.error(f"¡Error! No se pudo añadir/rellenar la columna 'tarjeta_supervisor': {e}")
                    conn.rollback() 
            
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_snapshot_orden ON snapshot_hoy(orden_externa);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_historial_orden ON historial_cambios(orden_externa);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_historial_lote ON historial_cambios(lote_procesado);"))
            
            # --- v2.9.0: Índices para las nuevas tablas ---
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_hc_tecnico_tarjeta ON head_count_tecnico(tarjeta);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_hc_supervisor_tarjeta ON head_count_supervisor(tarjeta);"))
            # --- Fin v2.9.0 ---

            conn.commit()

        st.sidebar.success("✅ Conectado a Supabase")
        return engine
    except Exception as e:
        st.sidebar.error(f"⚠️ Error conectando/creando tablas en Supabase: {e}")
        st.sidebar.info("📋 Continuando con CSVs locales únicamente")
        return None

engine = get_database_engine()

# ==============================================================================
# --- FUNCIONES HELPER ---
# ==============================================================================
def get_column_mappings():
    forward = {
        'Trabajo': 'trabajo', 'OrdenExterna': 'orden_externa', 'Cliente': 'cliente', 'Vence': 'vence',
        'OE_Creacion': 'oe_creacion', 'OE_Vence': 'oe_vence', 'OE_Vencimiento': 'oe_vencimiento',
        'Prioridad': 'prioridad', 'Tipo_de_prioridad': 'tipo_de_prioridad', 'Calendarizada': 'calendarizada',
        'Tanda_preferida': 'tanda_preferida', 'Reclamacion': 'reclamacion', 'Asignado_A': 'asignado_a',
        'Compania': 'compania', 'Supervisor': 'supervisor', 'Pool': 'pool', 'Estado': 'estado',
        'Tecnologia': 'tecnologia', 'Tipo_servicio': 'tipo_servicio', 'Organizacion': 'organizacion',
        'Sintoma': 'sintoma', 'Creado': 'creado', 'Tipo_Cliente': 'tipo_cliente', 'Segmento_Cliente': 'segmento_cliente',
        'Ciudad': 'ciudad', 'Sector': 'sector', 'Barrio': 'barrio', 'Cabina': 'cabina', 'Terminal': 'terminal',
        'Cantidad_de_lineas': 'cantidad_de_lineas', 'Re_Digitada': 're_digitada', 'Timestamp_Procesado': 'timestamp_procesado',
        'Fuente_Paso': 'fuente_paso', 'Tipo_Evento': 'tipo_evento',
        'Lote_Procesado': 'lote_procesado',
        'Fecha_Nacimiento': 'fecha_nacimiento' 
    }
    reverse = {v: k for k, v in forward.items()}
    return forward, reverse

COLUMN_MAPPING_FORWARD, COLUMN_MAPPING_REVERSE = get_column_mappings()

def reordenar_dataframe_para_salida(df, es_snapshot=False):
    if df.empty:
        return df

    columnas_orden_base = list(COLUMN_MAPPING_FORWARD.keys())
    columnas_finales = []

    for col in columnas_orden_base:
        if col == 'Lote_Procesado' and es_snapshot:
            continue
        if col in df.columns:
            columnas_finales.append(col)

    for col in df.columns:
        if col not in columnas_finales:
            if col == 'Lote_Procesado' and not es_snapshot:
                continue 
            columnas_finales.append(col)
    
    if not es_snapshot and 'Lote_Procesado' in df.columns and 'Lote_Procesado' not in columnas_finales:
            columnas_finales.append('Lote_Procesado')

    if 'Fecha_Nacimiento' in columnas_finales:
        columnas_finales.remove('Fecha_Nacimiento')
        columnas_finales.append('Fecha_Nacimiento')

    try:
        return df[columnas_finales]
    except KeyError as e:
        st.warning(f"Advertencia al reordenar columnas: {e}. Mostrando orden por defecto.")
        return df

def normalizar_columnas_para_sql(df):
    if df.empty: return df
    df_sql = df.copy()
    if 'Lote_Procesado' not in df_sql.columns:
        df_sql['Lote_Procesado'] = 0
    else:
        df_sql['Lote_Procesado'] = pd.to_numeric(df_sql['Lote_Procesado'], errors='coerce').astype('Int64')

    
    df_sql = df_sql.rename(columns=COLUMN_MAPPING_FORWARD)

    for col_ts in ['timestamp_procesado', 'fecha_nacimiento']:
        if col_ts in df_sql.columns:
            if df_sql[col_ts].dtype == 'object':
                df_sql[col_ts] = pd.to_datetime(df_sql[col_ts], errors='coerce')
            df_sql[col_ts] = df_sql[col_ts].replace({pd.NaT: None})

    if 'lote_procesado' in df_sql.columns:
        df_sql['lote_procesado'] = df_sql['lote_procesado'].replace({pd.NA: None})

    
    return df_sql

def normalizar_timestamps(df):
    if df.empty:
        return df
    df = df.copy()
    for col_ts in ['Timestamp_Procesado', 'Fecha_Nacimiento']:
        if col_ts in df.columns:
            df[col_ts] = pd.to_datetime(df[col_ts], errors='coerce')
    return df

def align_and_concat(df_base, df_new, fill_val=''):
    df_base = normalizar_timestamps(df_base)
    df_new = normalizar_timestamps(df_new)
    
    for df in [df_base, df_new]:
        if 'Lote_Procesado' not in df.columns:
            df['Lote_Procesado'] = 0
        else:
            df['Lote_Procesado'] = pd.to_numeric(df['Lote_Procesado'], errors='coerce').fillna(0).astype(int)

    
    cols_base = set(df_base.columns)
    cols_new = set(df_new.columns)
    
    if len(cols_base.intersection(cols_new)) < (len(cols_base) / 2):
        return pd.concat([df_base, df_new], ignore_index=True)
    
    all_cols = list(cols_base.union(cols_new))

    df_base_aligned = df_base.reindex(columns=all_cols, fill_value=fill_val)
    df_new_aligned = df_new.reindex(columns=all_cols, fill_value=fill_val)

    if 'Lote_Procesado' in all_cols:
        if fill_val == '':
            df_base_aligned['Lote_Procesado'] = pd.to_numeric(df_base_aligned['Lote_Procesado'], errors='coerce').fillna(0).astype(int)
            df_new_aligned['Lote_Procesado'] = pd.to_numeric(df_new_aligned['Lote_Procesado'], errors='coerce').fillna(0).astype(int)
        else: 
            if df_base_aligned['Lote_Procesado'].dtype not in ['int64', 'int32', 'Int64']:
                    df_base_aligned['Lote_Procesado'] = df_base_aligned['Lote_Procesado'].astype(int)
            if df_new_aligned['Lote_Procesado'].dtype not in ['int64', 'int32', 'Int64']:
                    df_new_aligned['Lote_Procesado'] = df_new_aligned['Lote_Procesado'].astype(int)

    
    return pd.concat([df_base_aligned, df_new_aligned], ignore_index=True)

# ==============================================================================
# --- GESTIÓN DEL CONTADOR DE LOTE ---
# ==============================================================================

def leer_lote_actual() -> int:
    if os.path.exists(ARCHIVO_LOTE_ACTUAL):
        try:
            with open(ARCHIVO_LOTE_ACTUAL, 'r') as f:
                content = f.read().strip()
                return int(content) if content else 0
        except ValueError:
                st.warning(f"⚠️ Archivo de lote '{ARCHIVO_LOTE_ACTUAL}' contiene valor no numérico. Reiniciando a 0.")
                return 0 
        except Exception as e:
                st.warning(f"⚠️ Error leyendo lote de '{ARCHIVO_LOTE_ACTUAL}': {e}. Reiniciando a 0.")
                return 0 
    return 0 

def guardar_lote_actual(lote: int):
    try:
        with open(ARCHIVO_LOTE_ACTUAL, 'w') as f:
            f.write(str(lote))
    except Exception as e:
        st.warning(f"⚠️ No se pudo guardar el número de lote ({lote}) en '{ARCHIVO_LOTE_ACTUAL}': {e}")

# ==============================================================================
# --- GESTIÓN DE ARCHIVOS Y ESTADO ---
# ==============================================================================
def verificar_y_limpiar_archivos_dia():
    hoy_iso = date.today().isoformat()
    ultima_fecha_reset = None
    fecha_reset_leida = False

    if os.path.exists(ARCHIVO_FECHA_ULTIMO_RESET):
        try:
            with open(ARCHIVO_FECHA_ULTIMO_RESET, 'r') as f:
                ultima_fecha_reset = f.read().strip()
                fecha_reset_leida = True
        except Exception as e:
            st.warning(f"⚠️ Error leyendo fecha de reset: {e}")

    if not fecha_reset_leida or ultima_fecha_reset != hoy_iso:
        st.info(f"🆕 Detectado nuevo día ({hoy_iso}) o primer inicio.")

        # --- MODIFICACIÓN v2.8.0: 'reabiertos' YA NO SE BORRA ---
        # --- v2.9.0: 'hc_tecnicos' y 'hc_supervisores' TAMPOCO SE BORRAN ---
        for f in [ARCHIVO_SNAPSHOT_HOY, ARCHIVO_HISTORIAL_CAMBIOS]: # ARCHIVO_REABIERTOS y HC* quitados
            if os.path.exists(f):
                try:
                    os.remove(f)
                    st.info(f"🗑️ Archivo CSV diario limpiado: {f}")
                except Exception as e:
                    st.warning(f"⚠️ No se pudo limpiar el archivo {f}: {e}")

        if engine:
            try:
                with engine.connect() as conn:
                    # --- MODIFICACIÓN v2.8.0 / v2.9.0: Tablas persistentes NO SE TRUNCAN ---
                    conn.execute(text("TRUNCATE TABLE snapshot_hoy;"))
                    conn.execute(text("TRUNCATE TABLE historial_cambios;")) 
                    # TRUNCATE TABLE reabiertos; <-- SE HA QUITADO
                    # TRUNCATE TABLE head_count_tecnico; <-- NO SE AÑADE
                    # TRUNCATE TABLE head_count_supervisor; <-- NO SE AÑADE
                    conn.commit()
                st.info("🆕 Tablas diarias ('snapshot_hoy' y 'historial_cambios') limpiadas en Supabase. 'reabiertos' y 'head_count' son historiales permanentes.")
            except Exception as e: st.warning(f"⚠️ Error limpiando tablas diarias de Supabase: {e}")

        try:
            with open(ARCHIVO_FECHA_ULTIMO_RESET, 'w') as f: f.write(hoy_iso)
        except Exception as e:
            st.warning(f"⚠️ No se pudo guardar la fecha de reset: {e}")

        
        guardar_lote_actual(0)
        st.info("🔢 Contador de Lote reseteado a 0.")
        if 'lote_actual' in st.session_state:
            st.session_state['lote_actual'] = 0

        
        # --- MODIFICACIÓN v2.8.0: 'reabiertos' YA NO SE RESETEA ---
        for state_key in ['snapshot_hoy', 'historial_cambios']: # 'reabiertos' y 'hc_*' quitados
            if state_key in st.session_state:
                st.session_state[state_key] = pd.DataFrame()

def inicializar_estado():
    verificar_y_limpiar_archivos_dia() 

    if 'lote_actual' not in st.session_state:
        st.session_state['lote_actual'] = leer_lote_actual()

    # --- v2.9.0: Añadidas nuevas tablas persistentes a la carga ---
    estados_tablas = {
        "snapshot_hoy": ("snapshot_hoy", ARCHIVO_SNAPSHOT_HOY),
        "historial_cambios": ("historial_cambios", ARCHIVO_HISTORIAL_CAMBIOS),
        "reabiertos": ("reabiertos", ARCHIVO_REABIERTOS),
        "head_count_tecnicos": ("head_count_tecnico", ARCHIVO_HC_TECNICOS),
        "head_count_supervisores": ("head_count_supervisor", ARCHIVO_HC_SUPERVISORES)
    }

    columnas_esperadas = list(COLUMN_MAPPING_FORWARD.keys())

    for estado, (tabla, archivo) in estados_tablas.items():
        if estado not in st.session_state:
            df_cargado = pd.DataFrame()

            # --- v2.9.0: Lógica de carga unificada para todas las tablas persistentes ---
            if estado in ["reabiertos", "head_count_tecnicos", "head_count_supervisores"]:
                if engine:
                    try:
                        # Para head_count, quitamos columnas de registro que no se editan
                        query = f"SELECT * FROM {tabla}"
                        cols_to_select = []
                        
                        if estado in ["head_count_tecnicos", "head_count_supervisores"]:
                            inspector = inspect(engine)
                            cols = [col['name'] for col in inspector.get_columns(tabla)]
                            cols_to_select = [c for c in cols if c != 'fecha_registro']
                        
                        if cols_to_select:
                             query = f"SELECT {', '.join(cols_to_select)} FROM {tabla}"

                        df_cargado = pd.read_sql(query, engine)
                        df_cargado = df_cargado.fillna('').replace('None', '')
                    except Exception as e:
                        st.warning(f"⚠️ Error cargando '{tabla}' desde Supabase: {e}. Intentando CSV...")
                
                if df_cargado.empty and os.path.exists(archivo):
                    try:
                        df_cargado = pd.read_csv(archivo, sep=';', dtype=str).fillna('').replace('None', '')
                        # Limpiar columnas extra de CSV si es necesario
                        if 'fecha_registro' in df_cargado.columns:
                            df_cargado = df_cargado.drop(columns=['fecha_registro'])
                    except Exception as e:
                        st.warning(f"⚠️ Error cargando '{archivo}': {e}")
                
                st.session_state[estado] = df_cargado
                continue 
            
            # --- Lógica existente para snapshot_hoy y historial_cambios ---
            es_snapshot = (estado == "snapshot_hoy")
            
            if engine:
                try:
                    df_cargado = pd.read_sql(f"SELECT * FROM {tabla} ORDER BY id", engine)
                    if not df_cargado.empty:
                        if 'lote_procesado' not in df_cargado.columns and not es_snapshot:
                            df_cargado['lote_procesado'] = 0
                        columnas_sql_mapeadas = {v: k for k, v in COLUMN_MAPPING_FORWARD.items() if v in df_cargado.columns}
                        df_cargado.rename(columns=columnas_sql_mapeadas, inplace=True)
                        
                        for col in columnas_esperadas:
                            if col not in df_cargado.columns:
                                df_cargado[col] = '' if col != 'Lote_Procesado' else 0

                        df_cargado = reordenar_dataframe_para_salida(df_cargado, es_snapshot=es_snapshot)

                        df_cargado = df_cargado.fillna('').replace('None', '')
                        if 'Lote_Procesado' in df_cargado.columns:
                            df_cargado['Lote_Procesado'] = pd.to_numeric(df_cargado['Lote_Procesado'], errors='coerce').fillna(0).astype(int)
                        
                        df_cargado = normalizar_timestamps(df_cargado)
                        
                except Exception as e:
                    st.warning(f"⚠️ Error cargando '{tabla}' desde Supabase: {e}. Intentando CSV...")
                    df_cargado = pd.DataFrame()

            if df_cargado.empty and os.path.exists(archivo):
                try:
                    df_cargado = pd.read_csv(archivo, sep=';', dtype=str).fillna('').replace('None', '')
                    if not df_cargado.empty: 
                        if 'lote_procesado' not in df_cargado.columns and not es_snapshot:
                            df_cargado['Lote_Procesado'] = '0'

                        for col in columnas_esperadas:
                            if col not in df_cargado.columns:
                                df_cargado[col] = '' if col != 'Lote_Procesado' else '0'
                                
                        df_cargado = reordenar_dataframe_para_salida(df_cargado, es_snapshot=es_snapshot)
                        
                        if 'Lote_Procesado' in df_cargado.columns:
                            df_cargado['Lote_Procesado'] = pd.to_numeric(df_cargado['Lote_Procesado'], errors='coerce').fillna(0).astype(int)
                        
                        df_cargado = normalizar_timestamps(df_cargado)

                except Exception as e:
                    st.warning(f"⚠️ Error cargando '{archivo}': {e}")
                    df_cargado = pd.DataFrame()

            if estado == "historial_cambios" and not df_cargado.empty and 'OrdenExterna' in df_cargado.columns and 'Timestamp_Procesado' in df_cargado.columns:
                if not df_cargado['Timestamp_Procesado'].isna().all():
                    df_cargado['Fecha_Nacimiento'] = df_cargado.groupby('OrdenExterna')['Timestamp_Procesado'].transform('min')
                else:
                    df_cargado['Fecha_Nacimiento'] = pd.NaT

            st.session_state[estado] = df_cargado

    # --- v2.9.0: Añadidos estados de acumulación para las nuevas pestañas ---
    keys_restantes = ["datos_paso1_acumulado", "datos_paso2_acumulado", "ordenes_a_buscar",
                        "ordenes_no_encontradas", "clasificaciones", 
                        "datos_monitoreo_acumulado_gen", 
                        "datos_monitoreo_acumulado_hoy", 
                        "ordenes_monitoreo_no_encontradas_gen", 
                        "ordenes_monitoreo_no_encontradas_hoy", 
                        "datos_correccion_acumulado",
                        "datos_reabiertos_acumulado",
                        "datos_hc_tecnicos_acumulado",
                        "datos_hc_supervisores_acumulado"
                    ] 
                        
    for key in keys_restantes:
        if key not in st.session_state:
            st.session_state[key] = pd.DataFrame() if 'datos' in key else [] if 'ordenes' in key else {}

inicializar_estado()

with st.sidebar:
    st.markdown("---")
    st.header("🔄 Sincronización")
    if st.button("Forzar Recarga de Datos", type="primary", use_container_width=True, help="Borra la memoria local y recarga todo desde Supabase/CSVs."):
        # --- v2.9.0: Añadidas nuevas keys a limpiar ---
        keys_a_limpiar = [
            "snapshot_hoy", 
            "historial_cambios",
            "reabiertos", 
            "head_count_tecnicos",
            "head_count_supervisores",
            "datos_paso1_acumulado", 
            "datos_paso2_acumulado", 
            "ordenes_a_buscar",
            "ordenes_no_encontradas", 
            "clasificaciones", 
            "datos_monitoreo_acumulado_gen",
            "datos_monitoreo_acumulado_hoy",
            "ordenes_monitoreo_no_encontradas_gen",
            "ordenes_monitoreo_no_encontradas_hoy",
            "datos_correccion_acumulado",
            "datos_reabiertos_acumulado", 
            "datos_hc_tecnicos_acumulado",
            "datos_hc_supervisores_acumulado",
            "lote_actual"
        ]
        
        for key in keys_a_limpiar:
            if key in st.session_state:
                del st.session_state[key]
        
        st.success("Memoria local limpiada. Recargando...")
        st.rerun()


# ==============================================================================
# --- FUNCIONES DE PROCESAMIENTO ---
# ==============================================================================

def procesar_pegado_simple(texto: str, columnas: list) -> pd.DataFrame:
    """
    Procesa texto pegado (asume tab-separated de Excel) sin encabezados.
    Usado para 'Reabiertos' y 'Head Count'.
    """
    if not texto or texto.isspace():
        return pd.DataFrame()
    try:
        df = pd.read_csv(
            io.StringIO(texto), 
            sep='\t',       
            header=None,    
            dtype=str,
            on_bad_lines='warn' 
        )
        df = df.dropna(how='all') 
        
        if df.empty:
            st.warning("No se encontraron datos en el portapapeles.")
            return pd.DataFrame()

        if len(df.columns) != len(columnas):
            st.error(f"Error: Se esperaban {len(columnas)} columnas ({', '.join(columnas)}), pero se encontraron {len(df.columns)}. Verifica los datos copiados de Excel.")
            return pd.DataFrame()
        
        df.columns = columnas
        df = df.fillna('') 
        st.success(f"Se procesaron {len(df)} filas.")
        return df
    except Exception as e:
        st.error(f"Error al procesar los datos pegados: {e}")
        st.error(traceback.format_exc())
        return pd.DataFrame()


def procesar_texto_kunai_mejorado(texto: str) -> pd.DataFrame:
    try:
        if not texto or texto.isspace():
            return pd.DataFrame()

        lineas = [l.strip() for l in texto.splitlines()
                    if l.strip() and not l.strip().startswith("Items por página") and l.strip().lower() != 'none']
        indices_inicio = [i for i, linea in enumerate(lineas) if linea.startswith('Reparacion')]

        columnas_kunai = [
            'Trabajo', 'OrdenExterna', 'Cliente', 'Vence', 'OE_Creacion', 'OE_Vence',
            'OE_Vencimiento', 'Prioridad', 'Tipo_de_prioridad', 'Calendarizada',
            'Tanda_preferida', 'Reclamacion', 'Asignado_A', 'Compania', 'Supervisor',
            'Pool', 'Estado', 'Tecnologia', 'Tipo_servicio', 'Organizacion', 'Sintoma',
            'Creado', 'Tipo_Cliente', 'Segmento_Cliente', 'Ciudad', 'Sector', 'Barrio',
            'Cabina', 'Terminal', 'Cantidad_de_lineas', 'Re_Digitada'
        ]

        all_records = []

        for idx_reg, idx_start in enumerate(indices_inicio):
            idx_end = indices_inicio[idx_reg + 1] if idx_reg + 1 < len(indices_inicio) else len(lineas)
            campos_raw = lineas[idx_start:idx_end]

            record = {col: '' for col in columnas_kunai}
            campo_idx = 0

            idx_hasta_barrio = columnas_kunai.index('Barrio')
            i = 0
            while i <= idx_hasta_barrio:
                col_name = columnas_kunai[i]
                if campo_idx >= len(campos_raw): break 

                valor_actual = campos_raw[campo_idx]

                posibles_tandas = ['Mañana', 'Tarde', 'Noche', 'Todo el día']
                if col_name == 'Calendarizada' and valor_actual in posibles_tandas:
                    record['Calendarizada'] = ''
                    record['Tanda_preferida'] = valor_actual
                    campo_idx += 1
                    i += 1 
                elif col_name == 'Tecnologia' and ('CFS' in valor_actual or 'Intern' in valor_actual):
                    record['Tecnologia'] = ''
                    record['Tipo_servicio'] = valor_actual
                    campo_idx += 1
                    i += 1 
                else:
                    record[col_name] = valor_actual
                    campo_idx += 1
                i += 1 

            
            campos_restantes = campos_raw[campo_idx:]
            if campos_restantes:
                if campos_restantes[-1] in ['Si', 'No']:
                    record['Re_Digitada'] = campos_restantes.pop(-1)
                if campos_restantes and str(campos_restantes[-1]).isdigit():
                    record['Cantidad_de_lineas'] = campos_restantes.pop(-1)
                if campos_restantes:
                    record['Cabina'] = campos_restantes.pop(0)
                if campos_restantes:
                    record['Terminal'] = " ".join(campos_restantes)

            if record['OrdenExterna'] and record['OrdenExterna'].replace(' ', '').isdigit():
                all_records.append(record)

        if not all_records:
            return pd.DataFrame()

        df = pd.DataFrame(all_records).fillna('').replace('None', '')
        df['OrdenExterna'] = df['OrdenExterna'].astype(str).str.strip()
        df = df[df['OrdenExterna'].str.match(r'^\d{5,}$', na=False)]
        df = df[df['Supervisor'].astype(str).str.strip() != '']
        df = df.drop_duplicates(subset=['OrdenExterna'], keep='first').reset_index(drop=True)

        if FILTRAR_POR_SUPERVISOR and 'Supervisor' in df.columns and not df.empty:
            df_antes = len(df)
            df = df[df['Supervisor'].isin(SUPERVISORES_PERMITIDOS)]
            df_filtradas = df_antes - len(df)
            if df_filtradas > 0 and df_antes > 0:
                st.info(f"ℹ️ Se filtraron {df_filtradas} órdenes de otros supervisores.")

        if not df.empty:
            df['Timestamp_Procesado'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            return pd.DataFrame()
            
        return df

    except Exception as e:
        st.error(f"Error Crítico al procesar los datos de KUNAI: {e}")
        st.error(traceback.format_exc()) 
        return pd.DataFrame()

# ==============================================================================
# --- FUNCIONES DE GUARDADO ---
# ==============================================================================

def guardar_snapshot_y_detectar_cambios(df_nuevo_snapshot: pd.DataFrame) -> tuple:
    if df_nuevo_snapshot.empty: return 0, 0, True
    try:
        lote_actual = st.session_state.get('lote_actual', 0)
        lote_para_guardar = lote_actual + 1
        
        is_supabase_empty = False
        if engine:
            try:
                with engine.connect() as conn:
                    result = conn.execute(text("SELECT 1 FROM historial_cambios LIMIT 1")).scalar()
                    is_supabase_empty = result is None
            except Exception as e:
                st.warning(f"⚠️ No se pudo verificar estado de Supabase (historial_cambios): {e}.")
                is_supabase_empty = True
                
        is_first_run_local = st.session_state.historial_cambios.empty
        is_first_run = is_first_run_local and is_supabase_empty

        eventos_para_historial = [] 
        count_activos = 0 

        if is_first_run:
            df_cambios_inicial = df_nuevo_snapshot.copy()
            df_cambios_inicial['Tipo_Evento'] = 'NUEVO'
            df_cambios_inicial['Lote_Procesado'] = lote_para_guardar
            eventos_para_historial = df_cambios_inicial.to_dict('records')
        else:
            historial_ultimo = pd.DataFrame()
            if not st.session_state.historial_cambios.empty:
                try:
                    historial_ultimo = normalizar_timestamps(st.session_state.historial_cambios).sort_values('Timestamp_Procesado', ascending=False).drop_duplicates(subset=['OrdenExterna'], keep='first')
                except Exception as e:
                    st.error(f"Error procesando historial_cambios local: {e}")
                    historial_ultimo = pd.DataFrame()

            historial_idx = historial_ultimo.set_index('OrdenExterna') if not historial_ultimo.empty else pd.DataFrame()
            
            for _, fila_nueva in df_nuevo_snapshot.iterrows():
                orden_id = fila_nueva['OrdenExterna']
                fila_anterior = None
                                
                if not historial_idx.empty and orden_id in historial_idx.index:
                    fila_anterior = historial_idx.loc[orden_id]

                cambio_base = fila_nueva.to_dict()
                cambio_base['Lote_Procesado'] = lote_para_guardar

                if fila_anterior is not None:
                    cols_comparar = [c for c in df_nuevo_snapshot.columns if c in fila_anterior.index and c not in COLUMNAS_IGNORAR_CAMBIOS]
                    dict_nuevo = {c: str(fila_nueva.get(c, '')).strip() for c in cols_comparar}
                    dict_anterior = {c: str(fila_anterior.get(c, '')).strip() for c in cols_comparar}

                    if dict_nuevo != dict_anterior:
                        cambio_base['Tipo_Evento'] = 'CAMBIO'
                        eventos_para_historial.append(cambio_base.copy())
                    else:
                        cambio_base['Tipo_Evento'] = 'ACTIVO'
                        count_activos += 1
                        pass
                else:
                    cambio_base['Tipo_Evento'] = 'NUEVO'
                    eventos_para_historial.append(cambio_base.copy())
                
        if eventos_para_historial:
            df_eventos_historial = pd.DataFrame(eventos_para_historial)
            st.session_state.historial_cambios = align_and_concat(
                st.session_state.historial_cambios, df_eventos_historial
            )
            try:
                df_para_csv_hist_ordenado = reordenar_dataframe_para_salida(st.session_state.historial_cambios)
                df_para_csv_hist_ordenado.to_csv(ARCHIVO_HISTORIAL_CAMBIOS, sep=';', index=False)
            except Exception as e:
                st.warning(f"⚠️ Error guardando CSV {ARCHIVO_HISTORIAL_CAMBIOS}: {e}")
            
            if engine: 
                try:
                    df_sql_completo = normalizar_columnas_para_sql(df_eventos_historial.copy())
                    with engine.begin() as conn:
                        df_sql_completo.to_sql('historial_cambios', conn, if_exists='append', index=False, method='multi', chunksize=100)
                except Exception as e: st.warning(f"⚠️ Error Supabase (historial_completo): {e}")

        df_snapshot_guardar = df_nuevo_snapshot.copy()
        if 'Lote_Procesado' in df_snapshot_guardar.columns:
            df_snapshot_guardar = df_snapshot_guardar.drop(columns=['Lote_Procesado'])
        
        try:
            df_snapshot_ordenado = reordenar_dataframe_para_salida(df_snapshot_guardar, es_snapshot=True)
            df_snapshot_ordenado.to_csv(ARCHIVO_SNAPSHOT_HOY, sep=';', index=False)
            st.session_state.snapshot_hoy = df_snapshot_ordenado 
        except Exception as e:
            st.warning(f"⚠️ Error guardando CSV {ARCHIVO_SNAPSHOT_HOY}: {e}")
            st.session_state.snapshot_hoy = df_snapshot_guardar 

        if engine: 
            try:
                with engine.begin() as conn:
                    conn.execute(text("TRUNCATE TABLE snapshot_hoy;"))
                    df_sql_snapshot = normalizar_columnas_para_sql(df_snapshot_guardar.copy())
                    if 'lote_procesado' in df_sql_snapshot.columns: 
                        df_sql_snapshot = df_sql_snapshot.drop(columns=['lote_procesado'])
                    df_sql_snapshot.to_sql('snapshot_hoy', conn, if_exists='append', index=False, method='multi', chunksize=100)
            except Exception as e: st.warning(f"⚠️ Error Supabase (snapshot): {e}")

        st.session_state['lote_actual'] = lote_para_guardar
        guardar_lote_actual(lote_para_guardar)
        st.info(f"🔢 Lote de procesamiento incrementado a: {lote_para_guardar}")

        return len(eventos_para_historial), count_activos, True 
    except Exception as e:
        st.error(f"Error fatal al guardar snapshot: {e}")
        st.error(traceback.format_exc())
        return 0, 0, False


def guardar_en_historial_con_comparacion(df_nuevos: pd.DataFrame, tipo_evento: str) -> tuple:
    if df_nuevos.empty: return 0, 0
    try:
        lote_actual = st.session_state.get('lote_actual', 1)
        
        cambios_para_completo = []
        sin_cambios = 0
        
        h_idx = pd.DataFrame()
        if not st.session_state.historial_cambios.empty:
            try:
                h_idx = normalizar_timestamps(st.session_state.historial_cambios).sort_values('Timestamp_Procesado', ascending=False).drop_duplicates(subset='OrdenExterna').set_index('OrdenExterna')
            except Exception as e:
                st.error(f"Error procesando historial local (P2/Mon): {e}")
                h_idx = pd.DataFrame()

        for _, fila_nueva in df_nuevos.iterrows():
            orden_id = fila_nueva['OrdenExterna']
            fila_h = None
            
            if not h_idx.empty and orden_id in h_idx.index:
                fila_h = h_idx.loc[orden_id]
            
            cambio_base = fila_nueva.to_dict()
            cambio_base['Tipo_Evento'] = tipo_evento
            cambio_base['Lote_Procesado'] = lote_actual

            hubo_cambio_real = False
            if fila_h is not None:
                cols_comp = [c for c in df_nuevos.columns if c in fila_h.index and c not in COLUMNAS_IGNORAR_CAMBIOS]
                dict_nuevo = {c: str(fila_nueva.get(c, '')).strip() for c in cols_comp}
                dict_hist = {c: str(fila_h.get(c, '')).strip() for c in cols_comp}
                if dict_nuevo != dict_hist:
                    hubo_cambio_real = True
            else:
                hubo_cambio_real = True
            
            if tipo_evento == 'ENCONTRADO':
                hubo_cambio_real = True 

            if hubo_cambio_real:
                cambios_para_completo.append(cambio_base.copy())
            else:
                sin_cambios += 1
        
        if cambios_para_completo:
            df_cambios_reales = pd.DataFrame(cambios_para_completo)
            st.session_state.historial_cambios = align_and_concat(st.session_state.historial_cambios, df_cambios_reales)
            try:
                df_para_csv_hist_ordenado = reordenar_dataframe_para_salida(st.session_state.historial_cambios)
                df_para_csv_hist_ordenado.to_csv(ARCHIVO_HISTORIAL_CAMBIOS, sep=';', index=False)
            except Exception as e: st.warning(f"⚠️ Error CSV {ARCHIVO_HISTORIAL_CAMBIOS}: {e}")
            if engine:
                try:
                    df_sql = normalizar_columnas_para_sql(df_cambios_reales.copy()) 
                    with engine.begin() as conn:
                        df_sql.to_sql('historial_cambios', conn, if_exists='append', index=False, method='multi', chunksize=100)
                except Exception as e: st.warning(f"⚠️ Error Supabase (P2/Mon C): {e}")
                
        return len(cambios_para_completo), sin_cambios
    except Exception as e:
        st.error(f"Error fatal guardando (P2/Monitoreo): {e}")
        st.error(traceback.format_exc())
        return 0, 0

def guardar_correccion_manual(df_correccion: pd.DataFrame) -> int:
    if df_correccion.empty: return 0
    try:
        lote_actual = st.session_state.get('lote_actual', 1)
        
        cambios_para_completo = []
        
        for _, fila_nueva in df_correccion.iterrows():
            cambio_base = fila_nueva.to_dict()
            cambio_base['Lote_Procesado'] = lote_actual
            cambios_para_completo.append(cambio_base.copy())
        
        if cambios_para_completo:
            df_cambios_reales = pd.DataFrame(cambios_para_completo)
            st.session_state.historial_cambios = align_and_concat(st.session_state.historial_cambios, df_cambios_reales)
            try:
                df_para_csv_hist_ordenado = reordenar_dataframe_para_salida(st.session_state.historial_cambios)
                df_para_csv_hist_ordenado.to_csv(ARCHIVO_HISTORIAL_CAMBIOS, sep=';', index=False)
            except Exception as e: st.warning(f"⚠️ Error CSV {ARCHIVO_HISTORIAL_CAMBIOS}: {e}")
            if engine:
                try:
                    df_sql = normalizar_columnas_para_sql(df_cambios_reales.copy()) 
                    with engine.begin() as conn:
                        df_sql.to_sql('historial_cambios', conn, if_exists='append', index=False, method='multi', chunksize=100)
                except Exception as e: st.warning(f"⚠️ Error Supabase (Corrección C): {e}")
                
        return len(cambios_para_completo)
    except Exception as e:
        st.error(f"Error fatal guardando corrección: {e}")
        st.error(traceback.format_exc())
        return 0

# Mapeo de Supervisor (Nombre a ID)
def mapear_tarjeta(supervisor_nombre):
    """Función global para mapear nombre de supervisor a ID."""
    if pd.isna(supervisor_nombre):
        return None
    nombre = str(supervisor_nombre).lower().strip()
    
    if nombre == 'aneudy peralta garcia': return '601378'
    if nombre == 'evangelista nu?ez': return '61768' # Con ?
    if nombre == 'evangelista nuñez': return '61768'  # Con ñ
    if nombre == 'iven eduardo urbaez gonzalez': return '601665'
    if nombre == 'jean carlos ramirez': return '601799'
    
    return None 

# --- v2.9.0: Función de guardado genérica para tablas persistentes (Reabiertos, HC) ---
def guardar_datos_persistentes(df_nuevos: pd.DataFrame, table_name: str, file_name: str, state_key: str, p_key: str = None) -> int:
    """
    Guarda datos en tablas persistentes (Supabase, CSV, session_state)
    Solo para CARGA RÁPIDA (append).
    """
    if df_nuevos.empty: return 0
    try:
        df_nuevos_guardar = df_nuevos.copy()
        
        # 1. Guardar en Supabase (solo los nuevos)
        if engine:
            try:
                with engine.begin() as conn:
                    # Usamos 'append'. Si hay duplicados en PKEY (ej. tarjeta), Supabase dará error.
                    # Para carga rápida, asumimos que el usuario maneja duplicados.
                    # El CRUD manual usará 'ON CONFLICT'
                    df_nuevos_guardar.to_sql(table_name, conn, if_exists='append', index=False, method='multi')
            except Exception as e:
                st.error(f"⚠️ Error Supabase (guardando en {table_name}): {e}")
                st.info("Verifica si estás intentando insertar 'tarjetas' que ya existen.")
                return 0 # No continuar si falla la BD

        # 2. Actualizar session_state
        # Usamos drop_duplicates si hay PKEY para mantener el estado limpio
        df_actualizado = pd.concat(
            [st.session_state[state_key], df_nuevos_guardar], 
            ignore_index=True
        )
        
        if p_key and p_key in df_actualizado.columns:
            st.session_state[state_key] = df_actualizado.drop_duplicates(subset=[p_key], keep='last').reset_index(drop=True)
        else:
            st.session_state[state_key] = df_actualizado.drop_duplicates(keep='last').reset_index(drop=True)


        # 3. Guardar en CSV (el estado completo)
        try:
            st.session_state[state_key].to_csv(file_name, sep=';', index=False)
        except Exception as e:
            st.warning(f"⚠️ Error guardando CSV {file_name}: {e}")
        
        return len(df_nuevos_guardar)
    except Exception as e:
        st.error(f"Error fatal guardando datos persistentes: {e}")
        st.error(traceback.format_exc())
        return 0

# --- v2.9.0: Funciones para CRUD de Head Count ---
def recargar_datos_persistentes(table_name: str, state_key: str):
    """Recarga los datos de una tabla persistente desde Supabase a session_state."""
    if not engine:
        st.error("No hay conexión a Supabase para recargar.")
        return
    try:
        # Excluir fecha_registro de la carga
        inspector = inspect(engine)
        cols = [col['name'] for col in inspector.get_columns(table_name)]
        cols_to_select = [c for c in cols if c != 'fecha_registro']
        
        if not cols_to_select: # Fallback si no hay columnas
             query = f"SELECT * FROM {table_name}"
        else:
             query = f"SELECT {', '.join(cols_to_select)} FROM {table_name}"
             
        df_cargado = pd.read_sql(query, engine)
        st.session_state[state_key] = df_cargado.fillna('').replace('None', '')
        
        # Actualizar CSV de respaldo
        st.session_state[state_key].to_csv(
            ARCHIVO_HC_TECNICOS if state_key == 'head_count_tecnicos' else ARCHIVO_HC_SUPERVISORES,
            sep=';',
            index=False
        )
    except Exception as e:
        st.error(f"Error al recargar {table_name}: {e}")

def ejecutar_crud_sql(query: str, params: dict, success_msg: str):
    """Ejecuta una operación CRUD (INSERT, UPDATE, DELETE) y maneja la respuesta."""
    if not engine:
        st.error("No hay conexión a Supabase para realizar la operación.")
        return False
    try:
        with engine.begin() as conn:
            conn.execute(text(query), params)
        st.success(success_msg)
        return True
    except Exception as e:
        st.error(f"Error en operación CRUD: {e}")
        st.error(traceback.format_exc())
        return False
# --- Fin v2.9.0 ---


def convertir_a_excel(df, es_snapshot=False):
    output = io.BytesIO()
    if df.empty:
        return None
    try:
        df_ordenado = reordenar_dataframe_para_salida(df, es_snapshot=es_snapshot)

        with pd.ExcelWriter(output, engine='openpyxl', datetime_format='YYYY-MM-DD HH:MM:SS') as writer:
            df_copy = df_ordenado.copy() 
            if 'Lote_Procesado' in df_copy.columns:
                df_copy['Lote_Procesado'] = pd.to_numeric(df_copy['Lote_Procesado'], errors='coerce').fillna(0).astype(int)
            df_copy.to_excel(writer, index=False, sheet_name='KUNAI_Datos')

        processed_data = output.getvalue()
        return processed_data
    except Exception as e:
        st.error(f"Error al convertir a Excel: {e}")
        try: 
            output = io.BytesIO()
            df_ordenado_texto = reordenar_dataframe_para_salida(df, es_snapshot=es_snapshot).astype(str) 
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_ordenado_texto.to_excel(writer, index=False, sheet_name='KUNAI_Datos')
            processed_data = output.getvalue()
            st.warning("⚠️ Exportado a Excel como texto debido a error de tipo.")
            return processed_data
        except Exception as e2:
            st.error(f"Error crítico al convertir a Excel (texto): {e2}")
            return None

def convertir_a_excel_simple(df):
    """Convierte un DataFrame simple a Excel sin lógica de reordenamiento."""
    output = io.BytesIO()
    if df.empty: 
        return None
    try:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Datos')
        return output.getvalue()
    except Exception as e:
        st.error(f"Error al convertir a Excel: {e}")
        return None

# ==============================================================================
# --- INTERFAZ DE USUARIO (Streamlit) ---
# ==============================================================================
st.title("📋 Sistema KUNAI - v2.9.0 (CRUD HC)")
st.markdown("---")

with st.expander("ℹ️ Estado de Archivos del Sistema", expanded=False):
    col_info1, col_info2, col_info3, col_info4, col_info5 = st.columns(5) # <-- v2.9.0: 5 columnas
    with col_info1:
        st.markdown("**📸 Snapshot Hoy**")
        snap_len = len(st.session_state.get('snapshot_hoy', pd.DataFrame()))
        if snap_len > 0: st.success(f"✅ {snap_len} registros")
        else: st.info("📭 Vacío")
    with col_info2:
        st.markdown("**📚 Historial de Cambios**")
        hist_comp_len = len(st.session_state.get('historial_cambios', pd.DataFrame()))
        if hist_comp_len > 0: st.success(f"✅ {hist_comp_len} registros")
        else: st.info("📭 Vacío")
    with col_info3:
        st.markdown("**🔄 Reabiertos (Histórico)**")
        reab_len = len(st.session_state.get('reabiertos', pd.DataFrame()))
        if reab_len > 0: st.success(f"✅ {reab_len} registros")
        else: st.info("📭 Vacío")
    # --- v2.9.0: Nuevos estados ---
    with col_info4:
        st.markdown("🧑‍🔧 **HC Técnicos**")
        hc_t_len = len(st.session_state.get('head_count_tecnicos', pd.DataFrame()))
        if hc_t_len > 0: st.success(f"✅ {hc_t_len} registros")
        else: st.info("📭 Vacío")
    with col_info5:
        st.markdown("🧑‍💼 **HC Supervisores**")
        hc_s_len = len(st.session_state.get('head_count_supervisores', pd.DataFrame()))
        if hc_s_len > 0: st.success(f"✅ {hc_s_len} registros")
        else: st.info("📭 Vacío")
    # --- Fin v2.9.0 ---
    
    st.markdown("---")
    lote_actual_display = st.session_state.get('lote_actual', 0)
    st.caption(f"🔢 **Lote de Procesamiento Actual:** {lote_actual_display} (El próximo snapshot iniciará el lote **{lote_actual_display + 1}**)")
    st.caption(f"🗓️ **Fecha actual:** {date.today().strftime('%d/%m/%Y')}")

# --- v2.9.0: Añadidas nuevas pestañas ---
tab1, tab2, tab3, tab_monitoreo, tab_correccion, tab_reabiertos, tab_hc_tecnicos, tab_hc_supervisores, tab4 = st.tabs([
    "📥 P1: Cargar Activos",
    "🔍 P2: Buscar Desaparecidas",
    "✅ P3: Clasificar",
    "🔄 Monitoreo",
    "🔧 Corrección Manual",
    "🔄 Reabiertos", 
    "🧑‍🔧 HC Técnicos",
    "🧑‍💼 HC Supervisores",
    "📊 Historial"
])

# ------------------------------------------------------------------------------
# --- PESTAÑA 1: CARGAR ACTIVOS ---
# ------------------------------------------------------------------------------
with tab1:
    st.header("Paso 1: Cargar Órdenes en Estado 'Activo' e 'Iniciado'")
    with st.expander("📖 Instrucciones (v2.7.4)", expanded=True):
        st.markdown(f"""
        **Lógica del Sistema v2.7.4 (Historial de Cambios):**
        
        1.  **`Historial Completo`**:
            * Es el **ÚNICO** historial.
            * Recibe **SOLO** los tickets `NUEVO` y `CAMBIO` del Lote.
            * **NO GUARDA** tickets `ACTIVO` (sin cambios).
            * Nunca se borra.
        
        2.  **`Paso 2 / Monitoreo / Corrección`**:
            * Si un ticket encontrado/corregido tiene cambios reales -> Se guarda en el `Historial Completo`.
        
        3.  **`Pestaña Monitoreo`**:
            * Dividida en "General" (por último estado) y "Nuevos de Hoy" (por fecha de nacimiento).
        """)

    
    ESTADOS_PERMITIDOS_PASO1 = ['activo', 'iniciado']
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        if st.button("📋 Pegar y Agregar desde Portapapeles", type="primary", use_container_width=True, key="pegar_p1"):
            texto = pyperclip.paste()
            df_temp = procesar_texto_kunai_mejorado(texto)
            if not df_temp.empty:
                estado_limpio = df_temp['Estado'].astype(str).str.strip().str.lower()
                df_temp_validos = df_temp[estado_limpio.isin(ESTADOS_PERMITIDOS_PASO1)]
                df_temp_rechazados = df_temp[~estado_limpio.isin(ESTADOS_PERMITIDOS_PASO1)]
                
                if not df_temp_validos.empty:
                    st.session_state.datos_paso1_acumulado = align_and_concat(
                        st.session_state.datos_paso1_acumulado, df_temp_validos
                    ).drop_duplicates(subset=['OrdenExterna'], keep='last').reset_index(drop=True)
                    st.success(f"✅ Agregadas {len(df_temp_validos)} órdenes. Total acumulado: {len(st.session_state.datos_paso1_acumulado)}")
                
                if not df_temp_rechazados.empty:
                    st.warning(f"⚠️ Se descartaron {len(df_temp_rechazados)} órdenes porque NO están en 'Activo' o 'Iniciado'.")
                    st.dataframe(df_temp_rechazados[['OrdenExterna', 'Estado', 'Cliente']], use_container_width=True)
                
                if df_temp_validos.empty and not df_temp_rechazados.empty:
                    st.warning("⚠️ De los datos pegados, ninguna orden era 'Activo' o 'Iniciado'.")
                elif df_temp_validos.empty and df_temp_rechazados.empty:
                    st.warning("⚠️ No se encontraron datos válidos en el portapapeles.")
            else:
                st.warning("⚠️ No se encontraron datos válidos en el portapapeles.")
                
    with col2:
        if st.button("⚡ Finalizar Snapshot e Incrementar Lote", use_container_width=True, key="finalizar_p1",
                    disabled=st.session_state.datos_paso1_acumulado.empty):
            with st.spinner(f"Procesando Snapshot (Lote {st.session_state.get('lote_actual', 0) + 1})..."):
                df_acumulado_raw = st.session_state.datos_paso1_acumulado.copy()
                estado_limpio_raw = df_acumulado_raw['Estado'].astype(str).str.strip().str.lower()
                df_actual = df_acumulado_raw[estado_limpio_raw.isin(ESTADOS_PERMITIDOS_PASO1)].reset_index(drop=True)
                df_rechazado_final = df_acumulado_raw[~estado_limpio_raw.isin(ESTADOS_PERMITIDOS_PASO1)]
                
                if not df_rechazado_final.empty:
                    st.error(f"❌ **Error Consistencia:** {len(df_rechazado_final)} órdenes acumuladas NO son 'Activo'/'Iniciado'. Se filtrarán.")

                if df_actual.empty:
                    st.error("❌ No hay órdenes válidas ('Activo' o 'Iniciado') para finalizar.")
                else:
                    df_actual['Fuente_Paso'] = 'Paso 1: Activos'
                    ids_actuales = set(df_actual['OrdenExterna'])
                    ids_maestra_anteriores = set()
                    
                    snapshot_anterior = st.session_state.snapshot_hoy.copy()
                    if not snapshot_anterior.empty: 
                        ids_maestra_anteriores.update(snapshot_anterior['OrdenExterna'])
                    
                    historial_completo = st.session_state.historial_cambios
                    if not historial_completo.empty and 'Estado' in historial_completo.columns:
                        try:
                            hist_ult = normalizar_timestamps(historial_completo).sort_values('Timestamp_Procesado', ascending=False).drop_duplicates(subset=['OrdenExterna'], keep='first')
                            hist_ant_act = hist_ult[hist_ult['Estado'].astype(str).str.strip().str.lower().isin(['activo', 'iniciado'])]
                            if not hist_ant_act.empty: ids_maestra_anteriores.update(hist_ant_act['OrdenExterna'])
                        except Exception as e: st.warning(f"⚠️ Error procesando historial para desaparecidos: {e}")
                    
                    ids_desaparecidos = ids_maestra_anteriores - ids_actuales
                    st.session_state.ordenes_a_buscar = sorted(list(ids_desaparecidos))

                    eventos_guardados, activos_ignorados, exito = guardar_snapshot_y_detectar_cambios(df_actual)
                    
                    if exito: 
                        nuevo_lote = st.session_state.get('lote_actual', 0)
                        st.success(f"✅ Snapshot Lote {nuevo_lote} finalizado ({len(df_actual)} regs)! Se añadieron **{eventos_guardados}** eventos (NUEVO/CAMBIO) al Historial.")
                        if activos_ignorados > 0:
                            st.info(f"ℹ️ Se ignoraron **{activos_ignorados}** tickets 'ACTIVO' (sin cambios).")
                        
                        st.info(f"💾 Snapshot reemplazado, historial actualizado en CSV y Supabase ☁️.")
                        if st.session_state.ordenes_a_buscar:
                            st.warning(f"🔍 Detectadas **{len(st.session_state.ordenes_a_buscar)}** órdenes desaparecidas. Pasa al Paso 2.")
                        st.session_state.datos_paso1_acumulado = pd.DataFrame()
                        st.rerun()
                    else:
                        st.error("❌ Ocurrió un error al guardar el snapshot.")
                
    with col3:
        if st.button("🗑️ Limpiar Acumulado P1", use_container_width=True, key="limpiar_p1",
                    disabled=st.session_state.datos_paso1_acumulado.empty):
            st.session_state.datos_paso1_acumulado = pd.DataFrame()
            st.rerun()
    
    if not st.session_state.datos_paso1_acumulado.empty:
        st.metric("Órdenes Acumuladas para Snapshot (Solo Activo/Iniciado)", len(st.session_state.datos_paso1_acumulado))
        
        df_acumulado_ordenado = reordenar_dataframe_para_salida(st.session_state.datos_paso1_acumulado, es_snapshot=True)

        excel_data_p1 = convertir_a_excel(df_acumulado_ordenado, es_snapshot=True) 
        if excel_data_p1:
            st.download_button(label="📥 Descargar Acumulado (Excel)", data=excel_data_p1,
                                file_name=f"acumulado_paso1_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key='download-excel-paso1')
        st.dataframe(df_acumulado_ordenado, use_container_width=True, height=400) 

# ------------------------------------------------------------------------------
# --- PESTAÑA 2: BUSCAR DESAPARECIDAS ---
# ------------------------------------------------------------------------------
with tab2:
    st.header("Paso 2: Buscar Órdenes Desaparecidas")
    lote_actual_p2 = st.session_state.get('lote_actual', 0)

    if st.session_state.ordenes_a_buscar:
        st.info(f"🔍 Se deben buscar **{len(st.session_state.ordenes_a_buscar)}** órdenes (del Lote {lote_actual_p2}).")
        st.text_area("1️⃣ Copia esta lista y búscala en KUNAI:", value=','.join(st.session_state.ordenes_a_buscar), height=100, key="lista_buscar_p2")
        st.markdown("---")
        st.subheader("2️⃣ Pega aquí los resultados encontrados")
        col1_p2, col2_p2, col3_p2 = st.columns([2, 2, 1])
        with col1_p2:
            if st.button("📋 Pegar y Agregar Encontradas", type="primary", use_container_width=True, key="pegar_p2"):
                texto = pyperclip.paste()
                df_temp = procesar_texto_kunai_mejorado(texto)
                if not df_temp.empty:
                    st.session_state.datos_paso2_acumulado = align_and_concat(st.session_state.datos_paso2_acumulado, df_temp).drop_duplicates(subset=['OrdenExterna'], keep='last').reset_index(drop=True)
                    st.success(f"✅ Agregadas {len(df_temp)}. Total encontradas: {len(st.session_state.datos_paso2_acumulado)}")
                else: st.warning("⚠️ No se procesaron datos válidos.")
        with col2_p2:
            if st.button("⚡ Guardar Encontradas", use_container_width=True, key="finalizar_p2", disabled=st.session_state.datos_paso2_acumulado.empty):
                with st.spinner(f"Guardando órdenes encontradas (Lote {lote_actual_p2})..."):
                    df_encontradas = st.session_state.datos_paso2_acumulado.copy()
                    df_encontradas['Fuente_Paso'] = 'Paso 2: Encontrados'
                    guardados, sin_cambios = guardar_en_historial_con_comparacion(df_encontradas, 'ENCONTRADO')
                    ids_buscados = set(st.session_state.ordenes_a_buscar)
                    ids_encontrados_ahora = set(df_encontradas['OrdenExterna'])
                    st.session_state.ordenes_no_encontradas = sorted(list(ids_buscados - ids_encontrados_ahora))
                    st.success(f"✅ {guardados} órdenes con cambios **añadidas** al Historial Completo (Lote {lote_actual_p2}).")
                    if sin_cambios > 0: st.info(f"ℹ️ {sin_cambios} órdenes encontradas sin cambios (no se guardaron).")
                    if st.session_state.ordenes_no_encontradas: st.warning(f"⚠️ **{len(st.session_state.ordenes_no_encontradas)}** órdenes buscadas NO estaban en los datos pegados → Pasa a Paso 3.")
                    else: st.success("🎉 ¡Todas las órdenes buscadas fueron encontradas!")
                    st.session_state.datos_paso2_acumulado = pd.DataFrame()
                    st.session_state.ordenes_a_buscar = []
                    st.rerun()
        with col3_p2:
            if st.button("🗑️ Limpiar Acum. P2", use_container_width=True, key="limpiar_p2", disabled=st.session_state.datos_paso2_acumulado.empty):
                st.session_state.datos_paso2_acumulado = pd.DataFrame()
                st.rerun()
            if st.session_state.ordenes_a_buscar and st.session_state.datos_paso2_acumulado.empty:
                if st.button("❌ Marcar Todas Como No Encontradas", use_container_width=True, key="no_encontrado_p2"):
                    st.session_state.ordenes_no_encontradas = sorted(list(st.session_state.ordenes_a_buscar))
                    st.warning(f"⚠️ {len(st.session_state.ordenes_no_encontradas)} órdenes marcadas como 'No Encontradas' → Pasa a Paso 3.")
                    st.session_state.datos_paso2_acumulado = pd.DataFrame()
                    st.session_state.ordenes_a_buscar = []
                    st.rerun()
    else: st.info("📌 No hay órdenes pendientes de búsqueda.")
    if not st.session_state.datos_paso2_acumulado.empty:
        st.markdown("---")
        st.subheader(f"Órdenes encontradas acumuladas ({len(st.session_state.datos_paso2_acumulado)}):")
        df_p2_ordenado = reordenar_dataframe_para_salida(st.session_state.datos_paso2_acumulado)
        st.dataframe(df_p2_ordenado, use_container_width=True, height=400)

# ------------------------------------------------------------------------------
# --- PESTAÑA 3: CLASIFICAR ---
# ------------------------------------------------------------------------------
with tab3:
    st.header("Paso 3: Clasificar Órdenes No Encontradas")
    if st.session_state.ordenes_no_encontradas:
        st.warning(f"⚠️ Hay **{len(st.session_state.ordenes_no_encontradas)}** órdenes que no se encontraron.")
        with st.form("form_no_encontradas"):
            clasificaciones_actuales = {}
            for orden in st.session_state.ordenes_no_encontradas:
                clasificaciones_actuales[orden]=st.radio(f"`{orden}`:",["Mantener","Eliminar"],key=f"noenc_{orden}",horizontal=True, index=0)
            if st.form_submit_button("✅ Procesar Clasificación",use_container_width=True):
                eliminar=[o for o, c in clasificaciones_actuales.items() if c == "Eliminar"]
                mantener = [o for o, c in clasificaciones_actuales.items() if c == "Mantener"]
                if eliminar:
                    with st.spinner(f"Eliminando {len(eliminar)} órdenes..."):
                        h_completo=st.session_state.historial_cambios[~st.session_state.historial_cambios['OrdenExterna'].isin(eliminar)]
                        try: h_completo.to_csv(ARCHIVO_HISTORIAL_CAMBIOS,sep=';',index=False)
                        except Exception as e: st.warning(f"⚠️ Error CSV {ARCHIVO_HISTORIAL_CAMBIOS}: {e}")
                        st.session_state.historial_cambios = h_completo
                        
                        if engine:
                            try:
                                query = text("DELETE FROM historial_cambios WHERE orden_externa IN :lista_ids")
                                with engine.begin() as conn:
                                    conn.execute(query, {"lista_ids": tuple(eliminar)})
                            except Exception as e: st.warning(f"⚠️ Error Supabase (Eliminar P3): {e}")
                        
                        st.success(f"🗑️ {len(eliminar)} órdenes eliminadas.")
                if mantener: st.info(f"✅ {len(mantener)} órdenes marcadas para **Mantener**.")
                st.session_state.ordenes_no_encontradas=[]
                st.rerun()
    else: st.info("📌 No hay órdenes 'No Encontradas' por clasificar.")

# ------------------------------------------------------------------------------
# --- PESTAÑA 4: MONITOREO ---
# ------------------------------------------------------------------------------
with tab_monitoreo:
    st.header("🔄 Monitoreo de Otros Estados")
    st.info("Busca órdenes cuyo último estado NO sea 'Activo'/'Iniciado', basado en el Historial Completo.")
    
    lote_actual_mon = st.session_state.get('lote_actual', 0)
    
    # --- LÓGICA DE PREPARACIÓN (Se usa en ambas pestañas) ---
    historial_completo = st.session_state.historial_cambios
    df_monitoreo_base = pd.DataFrame()
    
    if not historial_completo.empty:
        try:
            df_ultimo_estado = normalizar_timestamps(historial_completo).sort_values('Timestamp_Procesado', ascending=False).drop_duplicates('OrdenExterna', keep='first')
            estados_a_excluir = ['activo', 'iniciado']
            df_monitoreo_base = df_ultimo_estado[~df_ultimo_estado['Estado'].astype(str).str.strip().str.lower().isin(estados_a_excluir)]
        except Exception as e:
            st.error(f"Error al preparar datos base para monitoreo: {e}")
    
    
    tab_mon_general, tab_mon_nuevos_hoy = st.tabs(["Monitoreo General (Último Estado)", "Monitoreo (Nuevos de Hoy)"])
    
    # --- PESTAÑA 1: MONITOREO GENERAL (LÓGICA ANTIGUA) ---
    with tab_mon_general:
        st.subheader("Monitoreo General (basado en Último Estado)")
        
        df_monitoreo_filtrado_gen = pd.DataFrame()
        ids_monitoreo_gen = []
        
        if not df_monitoreo_base.empty:
            try:
                df_monitoreo_base_gen = df_monitoreo_base.copy()
                df_monitoreo_base_gen['Fecha_Procesado'] = pd.to_datetime(df_monitoreo_base_gen['Timestamp_Procesado'], errors='coerce').dt.date
                df_monitoreo_base_gen = df_monitoreo_base_gen.dropna(subset=['Fecha_Procesado'])
                fechas_disponibles_gen = sorted(df_monitoreo_base_gen['Fecha_Procesado'].unique(), reverse=True)
                
                if fechas_disponibles_gen:
                    fechas_disponibles_str_gen = [f.strftime('%Y-%m-%d') for f in fechas_disponibles_gen]
                    key_multiselect_monitoreo_gen = f"filtro_fecha_monitoreo_gen_{len(fechas_disponibles_str_gen)}"
                    
                    fechas_seleccionadas_str_gen = st.multiselect("📅 Filtrar por Fecha de Último Estado:", options=fechas_disponibles_str_gen, default=fechas_disponibles_str_gen, key=key_multiselect_monitoreo_gen)
                    
                    if fechas_seleccionadas_str_gen:
                        fechas_seleccionadas_gen = [datetime.strptime(f_str, '%Y-%m-%d').date() for f_str in fechas_seleccionadas_str_gen]
                        df_monitoreo_filtrado_gen = df_monitoreo_base_gen[df_monitoreo_base_gen['Fecha_Procesado'].isin(fechas_seleccionadas_gen)]
                    
                    if not df_monitoreo_filtrado_gen.empty:
                        ids_monitoreo_gen = sorted(df_monitoreo_filtrado_gen['OrdenExterna'].tolist())
                        st.info(f"Mostrando **{len(df_monitoreo_filtrado_gen)}** tickets para monitorear (Lote {lote_actual_mon}).")
                        st.text_area("📋 Copia IDs (General) y búscalas:", value=','.join(ids_monitoreo_gen), height=100, key="lista_buscar_monitoreo_gen")
                    elif fechas_seleccionadas_str_gen:
                        st.info("No hay órdenes para monitorear que coincidan con las fechas seleccionadas.")
                else:
                    st.success("🎉 ¡Excelente! No hay órdenes en otros estados registradas en el historial.")
            except Exception as e:
                st.error(f"Error al preparar datos para monitoreo general: {e}")
        else:
            st.info("📌 El historial completo está vacío o no hay tickets para monitorear.")
        
        # --- UI de guardado (General) ---
        st.markdown("---")
        st.subheader("Pegar y Guardar Resultados (General)")
        col_m1_gen, col_m2_gen, col_m3_gen = st.columns([2, 2, 1])
        with col_m1_gen:
            if st.button("📋 Pegar Resultados (General)", type="primary", use_container_width=True, key="pegar_monitoreo_gen"):
                texto = pyperclip.paste()
                df_temp = procesar_texto_kunai_mejorado(texto)
                if not df_temp.empty:
                    st.session_state.datos_monitoreo_acumulado_gen = align_and_concat(st.session_state.datos_monitoreo_acumulado_gen, df_temp).drop_duplicates(subset=['OrdenExterna'], keep='last').reset_index(drop=True)
                    st.success(f"✅ Agregados {len(df_temp)} resultados (General).")
                else: st.warning("⚠️ No se procesaron datos válidos.")
        with col_m2_gen:
            if st.button("⚡ Guardar Cambios (General)", use_container_width=True, key="finalizar_monitoreo_gen", disabled=st.session_state.datos_monitoreo_acumulado_gen.empty):
                with st.spinner(f"Guardando actualizaciones (Lote {lote_actual_mon})..."):
                    df_encontradas_mon_gen = st.session_state.datos_monitoreo_acumulado_gen.copy()
                    df_encontradas_mon_gen['Fuente_Paso'] = "Monitoreo"
                    guardados_mon, sin_cambios_mon = guardar_en_historial_con_comparacion(df_encontradas_mon_gen, 'MONITOREO')
                    
                    ids_buscados_mon_gen = set(ids_monitoreo_gen) 
                    ids_encontrados_mon_gen = set(df_encontradas_mon_gen['OrdenExterna'])
                    st.session_state.ordenes_monitoreo_no_encontradas_gen = sorted(list(ids_buscados_mon_gen - ids_encontrados_mon_gen))
                    
                    st.success(f"✅ {guardados_mon} actualizaciones con cambios **añadidas** al Historial Completo (Lote {lote_actual_mon}).")
                    if sin_cambios_mon > 0: st.info(f"ℹ️ {sin_cambios_mon} tickets sin cambios (no se guardaron).")
                    if st.session_state.ordenes_monitoreo_no_encontradas_gen: st.warning(f"⚠️ **{len(st.session_state.ordenes_monitoreo_no_encontradas_gen)}** órdenes (General) NO estaban en los datos pegados.")
                    else: st.success("🎉 ¡Todos los tickets (General) monitoreados fueron encontrados!")
                    st.session_state.datos_monitoreo_acumulado_gen = pd.DataFrame()
                    st.rerun()
        with col_m3_gen:
            if st.button("🗑️ Limpiar Acum. (General)", use_container_width=True, key="limpiar_monitoreo_gen", disabled=st.session_state.datos_monitoreo_acumulado_gen.empty):
                st.session_state.datos_monitoreo_acumulado_gen = pd.DataFrame()
                st.rerun()
        
        if not st.session_state.datos_monitoreo_acumulado_gen.empty:
            st.markdown("---")
            st.subheader(f"Resultados acumulados (General) ({len(st.session_state.datos_monitoreo_acumulado_gen)}):")
            df_mon_acum_ordenado_gen = reordenar_dataframe_para_salida(st.session_state.datos_monitoreo_acumulado_gen)
            st.dataframe(df_mon_acum_ordenado_gen, use_container_width=True, height=300)

        # --- Clasificación de NO encontrados (General) ---
        if st.session_state.get('ordenes_monitoreo_no_encontradas_gen', []):
            st.markdown("---")
            st.subheader("⚠️ Clasificar Desaparecidas (General)")
            with st.form("form_monitoreo_no_encontradas_gen"):
                clasificaciones_mon_actuales_gen = {}
                for orden in st.session_state.ordenes_monitoreo_no_encontradas_gen:
                    clasificaciones_mon_actuales_gen[orden] = st.radio(f"`{orden}`:", ["Mantener", "Eliminar"], key=f"mon_noenc_gen_{orden}", horizontal=True, index=0)
                if st.form_submit_button("✅ Procesar Clasificación (General)"):
                    eliminar_mon = [o for o, c in clasificaciones_mon_actuales_gen.items() if c == "Eliminar"]
                    mantener_mon = [o for o, c in clasificaciones_mon_actuales_gen.items() if c == "Mantener"]
                    if eliminar_mon:
                        with st.spinner(f"Eliminando {len(eliminar_mon)} órdenes (monitoreo gen)..."):
                            h_completo_mon=st.session_state.historial_cambios[~st.session_state.historial_cambios['OrdenExterna'].isin(eliminar_mon)]
                            try: h_completo_mon.to_csv(ARCHIVO_HISTORIAL_CAMBIOS, sep=';', index=False)
                            except Exception as e: st.warning(f"⚠️ Error CSV {ARCHIVO_HISTORIAL_CAMBIOS}: {e}")
                            
                            st.session_state.historial_cambios = h_completo_mon
                            
                            if engine:
                                try:
                                    query_mon = text("DELETE FROM historial_cambios WHERE orden_externa IN :lista_ids")
                                    with engine.begin() as conn:
                                        conn.execute(query_mon, {"lista_ids": tuple(eliminar_mon)})
                                except Exception as e: st.warning(f"⚠️ Error Supabase (Eliminar Mon Gen): {e}")
                                
                            st.success(f"🗑️ Eliminadas {len(eliminar_mon)} órdenes (monitoreo gen).")
                    if mantener_mon: st.info(f"✅ {len(mantener_mon)} órdenes (monitoreo gen) **mantenidas**.")
                    st.session_state.ordenes_monitoreo_no_encontradas_gen = []
                    st.rerun()


    # --- PESTAÑA 2: MONITOREO (NUEVOS DE HOY) ---
    with tab_mon_nuevos_hoy:
        st.subheader("Monitoreo de Tickets 'Nuevos de Hoy'")
        st.info("Muestra tickets cuyo primer registro (Fecha_Nacimiento) fue hoy, pero su último estado NO es 'Activo' o 'Iniciado'.")
        
        df_monitoreo_nuevos_hoy = pd.DataFrame()
        ids_monitoreo_nuevos_hoy = []
        
        if not df_monitoreo_base.empty and 'Fecha_Nacimiento' in df_monitoreo_base.columns:
            try:
                hoy = date.today()
                df_monitoreo_base['Fecha_Nacimiento'] = pd.to_datetime(df_monitoreo_base['Fecha_Nacimiento'], errors='coerce')
                df_monitoreo_nuevos_hoy = df_monitoreo_base[df_monitoreo_base['Fecha_Nacimiento'].dt.date == hoy]
                
                if not df_monitoreo_nuevos_hoy.empty:
                    ids_monitoreo_nuevos_hoy = sorted(df_monitoreo_nuevos_hoy['OrdenExterna'].tolist())
                    st.info(f"Mostrando **{len(df_monitoreo_nuevos_hoy)}** tickets 'Nuevos de Hoy' para monitorear (Lote {lote_actual_mon}).")
                    st.text_area("📋 Copia IDs (Nuevos de Hoy) y búscalas:", value=','.join(ids_monitoreo_nuevos_hoy), height=100, key="lista_buscar_monitoreo_nuevos_hoy")
                else:
                    st.success("🎉 No hay tickets 'Nuevos de Hoy' que requieran monitoreo (ej. ya están cerrados, etc.).")
            except Exception as e:
                st.error(f"Error al filtrar tickets 'Nuevos de Hoy': {e}")
        elif df_monitoreo_base.empty:
            st.info("📌 No hay tickets que requieran monitoreo general.")
        else:
            st.error("❌ No se pudo calcular la 'Fecha_Nacimiento' en el historial. No se puede filtrar por 'Nuevos de Hoy'.")

        # --- UI de guardado (Nuevos de Hoy) ---
        st.markdown("---")
        st.subheader("Pegar y Guardar Resultados (Nuevos de Hoy)")
        col_m1_hoy, col_m2_hoy, col_m3_hoy = st.columns([2, 2, 1])
        with col_m1_hoy:
            if st.button("📋 Pegar Resultados (Nuevos de Hoy)", type="primary", use_container_width=True, key="pegar_monitoreo_hoy"):
                texto = pyperclip.paste()
                df_temp = procesar_texto_kunai_mejorado(texto)
                if not df_temp.empty:
                    st.session_state.datos_monitoreo_acumulado_hoy = align_and_concat(st.session_state.datos_monitoreo_acumulado_hoy, df_temp).drop_duplicates(subset=['OrdenExterna'], keep='last').reset_index(drop=True)
                    st.success(f"✅ Agregados {len(df_temp)} resultados (Nuevos de Hoy).")
                else: st.warning("⚠️ No se procesaron datos válidos.")
        with col_m2_hoy:
            if st.button("⚡ Guardar Cambios (Nuevos de Hoy)", use_container_width=True, key="finalizar_monitoreo_hoy", disabled=st.session_state.datos_monitoreo_acumulado_hoy.empty):
                with st.spinner(f"Guardando actualizaciones (Lote {lote_actual_mon})..."):
                    df_encontradas_mon_hoy = st.session_state.datos_monitoreo_acumulado_hoy.copy()
                    df_encontradas_mon_hoy['Fuente_Paso'] = "Monitoreo"
                    guardados_mon, sin_cambios_mon = guardar_en_historial_con_comparacion(df_encontradas_mon_hoy, 'MONITOREO')
                    
                    ids_buscados_mon_hoy = set(ids_monitoreo_nuevos_hoy)
                    ids_encontrados_mon_hoy = set(df_encontradas_mon_hoy['OrdenExterna'])
                    st.session_state.ordenes_monitoreo_no_encontradas_hoy = sorted(list(ids_buscados_mon_hoy - ids_encontrados_mon_hoy))
                    
                    st.success(f"✅ {guardados_mon} actualizaciones con cambios **añadidas** al Historial Completo (Lote {lote_actual_mon}).")
                    if sin_cambios_mon > 0: st.info(f"ℹ️ {sin_cambios_mon} tickets sin cambios (no se guardaron).")
                    if st.session_state.ordenes_monitoreo_no_encontradas_hoy: st.warning(f"⚠️ **{len(st.session_state.ordenes_monitoreo_no_encontradas_hoy)}** órdenes (Nuevos de Hoy) NO estaban en los datos pegados.")
                    else: st.success("🎉 ¡Todos los tickets (Nuevos de Hoy) monitoreados fueron encontrados!")
                    st.session_state.datos_monitoreo_acumulado_hoy = pd.DataFrame()
                    st.rerun()
        with col_m3_hoy:
            if st.button("🗑️ Limpiar Acum. (Nuevos de Hoy)", use_container_width=True, key="limpiar_monitoreo_hoy", disabled=st.session_state.datos_monitoreo_acumulado_hoy.empty):
                st.session_state.datos_monitoreo_acumulado_hoy = pd.DataFrame()
                st.rerun()
        
        if not st.session_state.datos_monitoreo_acumulado_hoy.empty:
            st.markdown("---")
            st.subheader(f"Resultados acumulados (Nuevos de Hoy) ({len(st.session_state.datos_monitoreo_acumulado_hoy)}):")
            df_mon_acum_ordenado_hoy = reordenar_dataframe_para_salida(st.session_state.datos_monitoreo_acumulado_hoy)
            st.dataframe(df_mon_acum_ordenado_hoy, use_container_width=True, height=300)

        # --- Clasificación de NO encontrados (Nuevos de Hoy) ---
        if st.session_state.get('ordenes_monitoreo_no_encontradas_hoy', []):
            st.markdown("---")
            st.subheader("⚠️ Clasificar Desaparecidas (Nuevos de Hoy)")
            with st.form("form_monitoreo_no_encontradas_hoy"):
                clasificaciones_mon_actuales_hoy = {}
                for orden in st.session_state.ordenes_monitoreo_no_encontradas_hoy:
                    clasificaciones_mon_actuales_hoy[orden] = st.radio(f"`{orden}`:", ["Mantener", "Eliminar"], key=f"mon_noenc_hoy_{orden}", horizontal=True, index=0)
                if st.form_submit_button("✅ Procesar Clasificación (Nuevos de Hoy)"):
                    eliminar_mon = [o for o, c in clasificaciones_mon_actuales_hoy.items() if c == "Eliminar"]
                    mantener_mon = [o for o, c in clasificaciones_mon_actuales_hoy.items() if c == "Mantener"]
                    if eliminar_mon:
                        with st.spinner(f"Eliminando {len(eliminar_mon)} órdenes (monitoreo hoy)..."):
                            h_completo_mon=st.session_state.historial_cambios[~st.session_state.historial_cambios['OrdenExterna'].isin(eliminar_mon)]
                            try: h_completo_mon.to_csv(ARCHIVO_HISTORIAL_CAMBIOS, sep=';', index=False)
                            except Exception as e: st.warning(f"⚠️ Error CSV {ARCHIVO_HISTORIAL_CAMBIOS}: {e}")
                            
                            st.session_state.historial_cambios = h_completo_mon
                            
                            if engine:
                                try:
                                    query_mon = text("DELETE FROM historial_cambios WHERE orden_externa IN :lista_ids")
                                    with engine.begin() as conn:
                                        conn.execute(query_mon, {"lista_ids": tuple(eliminar_mon)})
                                except Exception as e: st.warning(f"⚠️ Error Supabase (Eliminar Mon Hoy): {e}")
                                
                            st.success(f"🗑️ Eliminadas {len(eliminar_mon)} órdenes (monitoreo hoy).")
                    if mantener_mon: st.info(f"✅ {len(mantener_mon)} órdenes (monitoreo hoy) **mantenidas**.")
                    st.session_state.ordenes_monitoreo_no_encontradas_hoy = []
                    st.rerun()


# ------------------------------------------------------------------------------
# --- PESTAÑA 5: CORRECCIÓN MANUAL ---
# ------------------------------------------------------------------------------
with tab_correccion:
    st.header("🔧 Corrección Manual / Adición")
    st.warning("⚠️ **Precaución:** Añade registros directamente al historial completo con el Lote actual.")
    lote_actual_corr = st.session_state.get('lote_actual', 0)
    st.info(f"Registros añadidos aquí se guardarán con **Lote {lote_actual_corr}**.")
    tipo_evento_manual = st.selectbox( "**1. Selecciona Tipo de Evento:**", ['NUEVO', 'CAMBIO', 'ENCONTRADO', 'MONITOREO', 'ACTIVO'], key="tipo_evento_manual_corr", help="Define cómo se registrará.")
    col_c1, col_c2, col_c3 = st.columns([2, 2, 1])
    with col_c1:
        if st.button("📋 Pegar y Agregar Datos", type="primary", use_container_width=True, key="pegar_corr"):
            texto = pyperclip.paste()
            df_temp = procesar_texto_kunai_mejorado(texto)
            if not df_temp.empty:
                st.session_state.datos_correccion_acumulado = align_and_concat(st.session_state.datos_correccion_acumulado, df_temp).drop_duplicates(subset=['OrdenExterna'], keep='last').reset_index(drop=True)
                st.success(f"✅ Agregados {len(df_temp)}. Total pendientes: {len(st.session_state.datos_correccion_acumulado)}")
            else: st.warning("⚠️ No se procesaron datos válidos.")
    with col_c2:
        if st.button("⚡ Guardar Adición Manual", use_container_width=True, key="guardar_corr", disabled=st.session_state.datos_correccion_acumulado.empty or not tipo_evento_manual):
            with st.spinner(f"Guardando adición manual (Lote {lote_actual_corr})..."):
                df_correccion = st.session_state.datos_correccion_acumulado.copy()
                df_correccion['Fuente_Paso'] = "Corrección Manual"
                df_correccion['Tipo_Evento'] = tipo_evento_manual
                if 'Timestamp_Procesado' not in df_correccion.columns or df_correccion['Timestamp_Procesado'].isnull().all():
                    df_correccion['Timestamp_Procesado'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                df_correccion = normalizar_timestamps(df_correccion)
                guardados = guardar_correccion_manual(df_correccion)
                if guardados > 0:
                    st.success(f"✅ Adición manual guardada. Se **añadieron {guardados}** eventos al Historial Completo (Lote {lote_actual_corr}).")
                    st.session_state.datos_correccion_acumulado = pd.DataFrame()
                    st.rerun()
                else: st.error("❌ No se pudo guardar la adición manual.")
    with col_c3:
        if st.button("🗑️ Limpiar Acum. Corrección", use_container_width=True, key="limpiar_corr", disabled=st.session_state.datos_correccion_acumulado.empty):
            st.session_state.datos_correccion_acumulado = pd.DataFrame()
            st.rerun()
    if not st.session_state.datos_correccion_acumulado.empty:
        st.markdown("---")
        st.subheader(f"Tickets pendientes ({len(st.session_state.datos_correccion_acumulado)}):")
        df_corr_acum_ordenado = reordenar_dataframe_para_salida(st.session_state.datos_correccion_acumulado)
        st.dataframe(df_corr_acum_ordenado, use_container_width=True, height=300)


# ------------------------------------------------------------------------------
# --- PESTAÑA 6: REABIERTOS ---
# ------------------------------------------------------------------------------
with tab_reabiertos:
    st.header("🔄 Cargar Casos Reabiertos")
    st.info("""
    Pega aquí los datos de reabiertos que limpias en Excel.
    - Asegúrate de copiar las **7 columnas** en este orden: 
    `caso`, `codigo`, `tarjeta`, `supervisor` (nombre), `fecha`, `condicion`, `tarjeta_supervisor` (ID).
    - El sistema guardará los datos tal cual los pegues.
    """)
    
    COLUMNAS_REABIERTOS = ['caso', 'codigo', 'tarjeta', 'supervisor', 'fecha', 'condicion', 'tarjeta_supervisor']
    
    col_r1, col_r2, col_r3 = st.columns([2, 2, 1])

    with col_r1:
        if st.button("📋 Pegar y Acumular Reabiertos", type="primary", use_container_width=True, key="pegar_reabiertos"):
            texto = pyperclip.paste()
            df_temp = procesar_pegado_simple(texto, COLUMNAS_REABIERTOS) 
            
            if not df_temp.empty:
                st.session_state.datos_reabiertos_acumulado = pd.concat(
                    [st.session_state.datos_reabiertos_acumulado, df_temp],
                    ignore_index=True
                ).drop_duplicates(keep='last')
                st.success(f"✅ Agregadas {len(df_temp)} filas. Total acumulado: {len(st.session_state.datos_reabiertos_acumulado)}")

    with col_r2:
        if st.button("⚡ Guardar Reabiertos en BD", use_container_width=True, key="guardar_reabiertos",
                    disabled=st.session_state.datos_reabiertos_acumulado.empty):
            with st.spinner("Guardando reabiertos en Supabase y CSV..."):
                df_para_guardar = st.session_state.datos_reabiertos_acumulado.copy()
                
                # --- v2.9.0: Usando la nueva función genérica ---
                guardados = guardar_datos_persistentes(
                    df_para_guardar,
                    'reabiertos',
                    ARCHIVO_REABIERTOS,
                    'reabiertos'
                    # No se pasa p_key para que se comporte como 'append' simple
                ) 
                
                if guardados > 0:
                    st.success(f"✅ ¡Guardado! Se **añadieron {guardados}** registros al historial 'reabiertos'.")
                    st.session_state.datos_reabiertos_acumulado = pd.DataFrame()
                    st.rerun()
                else:
                    st.error("❌ No se pudo guardar los datos de reabiertos.")

    with col_r3:
        if st.button("🗑️ Limpiar Acum. Reabiertos", use_container_width=True, key="limpiar_reabiertos",
                    disabled=st.session_state.datos_reabiertos_acumulado.empty):
            st.session_state.datos_reabiertos_acumulado = pd.DataFrame()
            st.rerun()
    
    if not st.session_state.datos_reabiertos_acumulado.empty:
        st.markdown("---")
        st.metric("Filas Acumuladas para Guardar", len(st.session_state.datos_reabiertos_acumulado))
        
        cols_display_reab = ['caso', 'codigo', 'tarjeta', 'supervisor', 'tarjeta_supervisor', 'fecha', 'condicion']
        cols_existentes = [col for col in cols_display_reab if col in st.session_state.datos_reabiertos_acumulado.columns]
        st.dataframe(st.session_state.datos_reabiertos_acumulado[cols_existentes], use_container_width=True, height=400)


# ------------------------------------------------------------------------------
# --- v2.9.0: PESTAÑA 7: HEAD COUNT TÉCNICOS ---
# ------------------------------------------------------------------------------
with tab_hc_tecnicos:
    st.header("🧑‍🔧 Head Count - Técnicos")
    
    COLUMNAS_HC_TECNICOS = ['ficha', 'tarjeta', 'nombre', 'telefono', 'funcion', 'supervisor']
    df_actual_tecnicos = st.session_state.get('head_count_tecnicos', pd.DataFrame())
    
    # Asegurar el orden de las columnas para mostrar
    if not df_actual_tecnicos.empty:
        df_actual_tecnicos = df_actual_tecnicos[COLUMNAS_HC_TECNICOS]

    tab_carga_rapida, tab_crud = st.tabs(["Carga Rápida (Pegar)", "Gestión Manual (CRUD)"])

    # --- Sub-pestaña 1: Carga Rápida ---
    with tab_carga_rapida:
        st.subheader("Carga Rápida (Copiar y Pegar)")
        st.info(f"""
        Pega aquí los datos de Excel. Asegúrate de copiar las **{len(COLUMNAS_HC_TECNICOS)} columnas** en este orden: 
        `{'`, `'.join(COLUMNAS_HC_TECNICOS)}`.
        
        **Importante:** La columna `tarjeta` es la **llave primaria (PRIMARY KEY)**. Si intentas
        pegar una 'tarjeta' que ya existe, la operación **fallará**. Esta pestaña es solo para
        **añadir nuevos** registros en bloque.
        """)
        
        col_r1_hc, col_r2_hc, col_r3_hc = st.columns([2, 2, 1])
        with col_r1_hc:
            if st.button("📋 Pegar y Acumular Técnicos", type="primary", use_container_width=True, key="pegar_hc_tecnicos"):
                texto = pyperclip.paste()
                df_temp = procesar_pegado_simple(texto, COLUMNAS_HC_TECNICOS) 
                
                if not df_temp.empty:
                    st.session_state.datos_hc_tecnicos_acumulado = pd.concat(
                        [st.session_state.datos_hc_tecnicos_acumulado, df_temp],
                        ignore_index=True
                    ).drop_duplicates(subset=['tarjeta'], keep='last') # Evitar duplicados en el lote
                    st.success(f"✅ Agregadas {len(df_temp)} filas. Total acumulado: {len(st.session_state.datos_hc_tecnicos_acumulado)}")

        with col_r2_hc:
            if st.button("⚡ Guardar Técnicos en BD", use_container_width=True, key="guardar_hc_tecnicos",
                        disabled=st.session_state.datos_hc_tecnicos_acumulado.empty):
                with st.spinner("Guardando técnicos en Supabase y CSV..."):
                    df_para_guardar = st.session_state.datos_hc_tecnicos_acumulado.copy()
                    
                    guardados = guardar_datos_persistentes(
                        df_para_guardar,
                        'head_count_tecnico',
                        ARCHIVO_HC_TECNICOS,
                        'head_count_tecnicos',
                        p_key='tarjeta'
                    ) 
                    
                    if guardados > 0:
                        st.success(f"✅ ¡Guardado! Se **añadieron {guardados}** registros a 'head_count_tecnico'.")
                        st.session_state.datos_hc_tecnicos_acumulado = pd.DataFrame()
                        st.rerun()
                    else:
                        st.error("❌ No se pudo guardar los datos. Revisa la consola de errores.")

        with col_r3_hc:
            if st.button("🗑️ Limpiar Acum. Técnicos", use_container_width=True, key="limpiar_hc_tecnicos",
                        disabled=st.session_state.datos_hc_tecnicos_acumulado.empty):
                st.session_state.datos_hc_tecnicos_acumulado = pd.DataFrame()
                st.rerun()
        
        if not st.session_state.datos_hc_tecnicos_acumulado.empty:
            st.markdown("---")
            st.metric("Filas Acumuladas para Guardar", len(st.session_state.datos_hc_tecnicos_acumulado))
            st.dataframe(st.session_state.datos_hc_tecnicos_acumulado, use_container_width=True, height=300)

    # --- Sub-pestaña 2: Gestión Manual (CRUD) ---
    with tab_crud:
        st.subheader("Gestión Manual (Añadir, Actualizar, Eliminar)")
        
        # --- 1. AÑADIR (INSERT) ---
        with st.expander("➕ Añadir Nuevo Técnico"):
            with st.form("form_add_tecnico", clear_on_submit=True):
                st.info("La 'Tarjeta' debe ser única.")
                c1, c2 = st.columns(2)
                with c1:
                    ficha_new = st.text_input("Ficha")
                    tarjeta_new = st.text_input("Tarjeta (Llave Primaria)")
                    nombre_new = st.text_input("Nombre")
                with c2:
                    telefono_new = st.text_input("Teléfono")
                    funcion_new = st.text_input("Función")
                    supervisor_new = st.text_input("Supervisor")
                
                submitted_add = st.form_submit_button("Añadir Técnico", use_container_width=True)
                if submitted_add:
                    if not tarjeta_new:
                        st.error("La 'Tarjeta' es obligatoria para añadir un registro.")
                    else:
                        query = """
                        INSERT INTO head_count_tecnico (ficha, tarjeta, nombre, telefono, funcion, supervisor)
                        VALUES (:ficha, :tarjeta, :nombre, :telefono, :funcion, :supervisor)
                        ON CONFLICT (tarjeta) DO NOTHING;
                        """
                        params = {
                            "ficha": ficha_new, "tarjeta": tarjeta_new, "nombre": nombre_new,
                            "telefono": telefono_new, "funcion": funcion_new, "supervisor": supervisor_new
                        }
                        if ejecutar_crud_sql(query, params, f"✅ Técnico '{nombre_new}' ({tarjeta_new}) añadido con éxito."):
                            recargar_datos_persistentes('head_count_tecnico', 'head_count_tecnicos')
                            st.rerun()

        # --- 2. ACTUALIZAR (UPDATE) ---
        with st.expander("✏️ Actualizar Técnico Existente"):
            if not df_actual_tecnicos.empty:
                tarjeta_to_edit = st.selectbox(
                    "Selecciona Técnico por Tarjeta:",
                    options=df_actual_tecnicos['tarjeta'],
                    index=None,
                    placeholder="Escribe o selecciona una tarjeta..."
                )
                
                if tarjeta_to_edit:
                    registro_actual = df_actual_tecnicos[df_actual_tecnicos['tarjeta'] == tarjeta_to_edit].iloc[0]
                    with st.form("form_edit_tecnico"):
                        st.info(f"Editando registro de: **{registro_actual['nombre']}** (`{registro_actual['tarjeta']}`)")
                        c1, c2 = st.columns(2)
                        with c1:
                            ficha_edit = st.text_input("Ficha", value=registro_actual['ficha'])
                            nombre_edit = st.text_input("Nombre", value=registro_actual['nombre'])
                            funcion_edit = st.text_input("Función", value=registro_actual['funcion'])
                        with c2:
                            telefono_edit = st.text_input("Teléfono", value=registro_actual['telefono'])
                            supervisor_edit = st.text_input("Supervisor", value=registro_actual['supervisor'])
                        
                        submitted_edit = st.form_submit_button("Actualizar Técnico", use_container_width=True)
                        if submitted_edit:
                            query = """
                            UPDATE head_count_tecnico
                            SET ficha = :ficha, nombre = :nombre, telefono = :telefono, funcion = :funcion, supervisor = :supervisor
                            WHERE tarjeta = :tarjeta;
                            """
                            params = {
                                "ficha": ficha_edit, "nombre": nombre_edit, "telefono": telefono_edit,
                                "funcion": funcion_edit, "supervisor": supervisor_edit, "tarjeta": tarjeta_to_edit
                            }
                            if ejecutar_crud_sql(query, params, f"✅ Técnico '{nombre_edit}' ({tarjeta_to_edit}) actualizado."):
                                recargar_datos_persistentes('head_count_tecnico', 'head_count_tecnicos')
                                st.rerun()
            else:
                st.info("No hay técnicos para actualizar.")

        # --- 3. ELIMINAR (DELETE) ---
        with st.expander("🗑️ Eliminar Técnico"):
            if not df_actual_tecnicos.empty:
                tarjeta_to_delete = st.selectbox(
                    "Selecciona Técnico por Tarjeta para ELIMINAR:",
                    options=df_actual_tecnicos['tarjeta'],
                    index=None,
                    placeholder="Escribe o selecciona una tarjeta...",
                    key="delete_tecnico_select"
                )
                
                if tarjeta_to_delete:
                    registro_a_borrar = df_actual_tecnicos[df_actual_tecnicos['tarjeta'] == tarjeta_to_delete].iloc[0]
                    st.warning(f"**PRECAUCIÓN:** Estás a punto de eliminar a **{registro_a_borrar['nombre']}** (`{registro_a_borrar['tarjeta']}`). Esta acción no se puede deshacer.")
                    
                    if st.button("Confirmar Eliminación", type="primary", use_container_width=True):
                        query = "DELETE FROM head_count_tecnico WHERE tarjeta = :tarjeta;"
                        params = {"tarjeta": tarjeta_to_delete}
                        if ejecutar_crud_sql(query, params, f"🗑️ Técnico ({tarjeta_to_delete}) eliminado."):
                            recargar_datos_persistentes('head_count_tecnico', 'head_count_tecnicos')
                            st.rerun()
            else:
                st.info("No hay técnicos para eliminar.")

        # --- 4. VER TABLA ---
        st.markdown("---")
        st.subheader("Listado Actual de Técnicos")
        filtro_hc_t = st.text_input("🔍 Buscar en Técnicos:", key="filtro_hc_tecnicos_crud")
        df_hc_t_filtrado = df_actual_tecnicos
        if filtro_hc_t:
            try:
                mask = df_actual_tecnicos.apply(lambda row: row.astype(str).str.contains(filtro_hc_t, case=False, regex=False).any(), axis=1)
                df_hc_t_filtrado = df_actual_tecnicos[mask]
            except Exception as e: st.warning(f"Error filtro: {e}")
        
        st.dataframe(df_hc_t_filtrado, use_container_width=True, height=400)
        excel_hc_t = convertir_a_excel_simple(df_hc_t_filtrado)
        if excel_hc_t:
            st.download_button("📥 Descargar Vista (Excel)", excel_hc_t, "head_count_tecnicos.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key='excel-hc-tecnicos', use_container_width=True)

# ------------------------------------------------------------------------------
# --- v2.9.0: PESTAÑA 8: HEAD COUNT SUPERVISORES ---
# ------------------------------------------------------------------------------
with tab_hc_supervisores:
    st.header("🧑‍💼 Head Count - Supervisores")
    
    COLUMNAS_HC_SUPERVISORES = ['ficha', 'tarjeta', 'nombre', 'telefono', 'rol']
    df_actual_supervisores = st.session_state.get('head_count_supervisores', pd.DataFrame())
    
    # Asegurar el orden de las columnas para mostrar
    if not df_actual_supervisores.empty:
        # Asegurarse de que todas las columnas esperadas existan
        for col in COLUMNAS_HC_SUPERVISORES:
            if col not in df_actual_supervisores.columns:
                df_actual_supervisores[col] = ''
        df_actual_supervisores = df_actual_supervisores[COLUMNAS_HC_SUPERVISORES]

    tab_carga_rapida_s, tab_crud_s = st.tabs(["Carga Rápida (Pegar)", "Gestión Manual (CRUD)"])

    # --- Sub-pestaña 1: Carga Rápida ---
    with tab_carga_rapida_s:
        st.subheader("Carga Rápida (Copiar y Pegar)")
        st.info(f"""
        Pega aquí los datos de Excel. Asegúrate de copiar las **{len(COLUMNAS_HC_SUPERVISORES)} columnas** en este orden: 
        `{'`, `'.join(COLUMNAS_HC_SUPERVISORES)}`.
        
        **Importante:** La columna `tarjeta` es la **llave primaria (PRIMARY KEY)**. Si intentas
        pegar una 'tarjeta' que ya existe, la operación **fallará**. Esta pestaña es solo para
        **añadir nuevos** registros en bloque.
        """)
        
        col_r1_hcs, col_r2_hcs, col_r3_hcs = st.columns([2, 2, 1])
        with col_r1_hcs:
            if st.button("📋 Pegar y Acumular Supervisores", type="primary", use_container_width=True, key="pegar_hc_supervisores"):
                texto = pyperclip.paste()
                df_temp = procesar_pegado_simple(texto, COLUMNAS_HC_SUPERVISORES) 
                
                if not df_temp.empty:
                    st.session_state.datos_hc_supervisores_acumulado = pd.concat(
                        [st.session_state.datos_hc_supervisores_acumulado, df_temp],
                        ignore_index=True
                    ).drop_duplicates(subset=['tarjeta'], keep='last')
                    st.success(f"✅ Agregadas {len(df_temp)} filas. Total acumulado: {len(st.session_state.datos_hc_supervisores_acumulado)}")

        with col_r2_hcs:
            if st.button("⚡ Guardar Supervisores en BD", use_container_width=True, key="guardar_hc_supervisores",
                        disabled=st.session_state.datos_hc_supervisores_acumulado.empty):
                with st.spinner("Guardando supervisores en Supabase y CSV..."):
                    df_para_guardar = st.session_state.datos_hc_supervisores_acumulado.copy()
                    
                    guardados = guardar_datos_persistentes(
                        df_para_guardar,
                        'head_count_supervisor',
                        ARCHIVO_HC_SUPERVISORES,
                        'head_count_supervisores',
                        p_key='tarjeta'
                    ) 
                    
                    if guardados > 0:
                        st.success(f"✅ ¡Guardado! Se **añadieron {guardados}** registros a 'head_count_supervisor'.")
                        st.session_state.datos_hc_supervisores_acumulado = pd.DataFrame()
                        st.rerun()
                    else:
                        st.error("❌ No se pudo guardar los datos. Revisa la consola de errores.")

        with col_r3_hcs:
            if st.button("🗑️ Limpiar Acum. Supervisores", use_container_width=True, key="limpiar_hc_supervisores",
                        disabled=st.session_state.datos_hc_supervisores_acumulado.empty):
                st.session_state.datos_hc_supervisores_acumulado = pd.DataFrame()
                st.rerun()
        
        if not st.session_state.datos_hc_supervisores_acumulado.empty:
            st.markdown("---")
            st.metric("Filas Acumuladas para Guardar", len(st.session_state.datos_hc_supervisores_acumulado))
            st.dataframe(st.session_state.datos_hc_supervisores_acumulado, use_container_width=True, height=300)

    # --- Sub-pestaña 2: Gestión Manual (CRUD) ---
    with tab_crud_s:
        st.subheader("Gestión Manual (Añadir, Actualizar, Eliminar)")
        
        # --- 1. AÑADIR (INSERT) ---
        with st.expander("➕ Añadir Nuevo Supervisor"):
            with st.form("form_add_supervisor", clear_on_submit=True):
                st.info("La 'Tarjeta' debe ser única.")
                c1, c2 = st.columns(2)
                with c1:
                    ficha_new_s = st.text_input("Ficha", key="s_ficha_new")
                    tarjeta_new_s = st.text_input("Tarjeta (Llave Primaria)", key="s_tarjeta_new")
                    nombre_new_s = st.text_input("Nombre", key="s_nombre_new")
                with c2:
                    telefono_new_s = st.text_input("Teléfono", key="s_telefono_new")
                    rol_new_s = st.text_input("Rol", key="s_rol_new")
                
                submitted_add_s = st.form_submit_button("Añadir Supervisor", use_container_width=True)
                if submitted_add_s:
                    if not tarjeta_new_s:
                        st.error("La 'Tarjeta' es obligatoria para añadir un registro.")
                    else:
                        query = """
                        INSERT INTO head_count_supervisor (ficha, tarjeta, nombre, telefono, rol)
                        VALUES (:ficha, :tarjeta, :nombre, :telefono, :rol)
                        ON CONFLICT (tarjeta) DO NOTHING;
                        """
                        params = {
                            "ficha": ficha_new_s, "tarjeta": tarjeta_new_s, "nombre": nombre_new_s,
                            "telefono": telefono_new_s, "rol": rol_new_s
                        }
                        if ejecutar_crud_sql(query, params, f"✅ Supervisor '{nombre_new_s}' ({tarjeta_new_s}) añadido con éxito."):
                            recargar_datos_persistentes('head_count_supervisor', 'head_count_supervisores')
                            st.rerun()

        # --- 2. ACTUALIZAR (UPDATE) ---
        with st.expander("✏️ Actualizar Supervisor Existente"):
            if not df_actual_supervisores.empty:
                tarjeta_to_edit_s = st.selectbox(
                    "Selecciona Supervisor por Tarjeta:",
                    options=df_actual_supervisores['tarjeta'],
                    index=None,
                    placeholder="Escribe o selecciona una tarjeta...",
                    key="edit_sup_select"
                )
                
                if tarjeta_to_edit_s:
                    registro_actual_s = df_actual_supervisores[df_actual_supervisores['tarjeta'] == tarjeta_to_edit_s].iloc[0]
                    with st.form("form_edit_supervisor"):
                        st.info(f"Editando registro de: **{registro_actual_s['nombre']}** (`{registro_actual_s['tarjeta']}`)")
                        c1, c2 = st.columns(2)
                        with c1:
                            ficha_edit_s = st.text_input("Ficha", value=registro_actual_s['ficha'], key="s_ficha_edit")
                            nombre_edit_s = st.text_input("Nombre", value=registro_actual_s['nombre'], key="s_nombre_edit")
                        with c2:
                            telefono_edit_s = st.text_input("Teléfono", value=registro_actual_s['telefono'], key="s_telefono_edit")
                            rol_edit_s = st.text_input("Rol", value=registro_actual_s['rol'], key="s_rol_edit")
                        
                        submitted_edit_s = st.form_submit_button("Actualizar Supervisor", use_container_width=True)
                        if submitted_edit_s:
                            query = """
                            UPDATE head_count_supervisor
                            SET ficha = :ficha, nombre = :nombre, telefono = :telefono, rol = :rol
                            WHERE tarjeta = :tarjeta;
                            """
                            params = {
                                "ficha": ficha_edit_s, "nombre": nombre_edit_s, "telefono": telefono_edit_s,
                                "rol": rol_edit_s, "tarjeta": tarjeta_to_edit_s
                            }
                            if ejecutar_crud_sql(query, params, f"✅ Supervisor '{nombre_edit_s}' ({tarjeta_to_edit_s}) actualizado."):
                                recargar_datos_persistentes('head_count_supervisor', 'head_count_supervisores')
                                st.rerun()
            else:
                st.info("No hay supervisores para actualizar.")

        # --- 3. ELIMINAR (DELETE) ---
        with st.expander("🗑️ Eliminar Supervisor"):
            if not df_actual_supervisores.empty:
                tarjeta_to_delete_s = st.selectbox(
                    "Selecciona Supervisor por Tarjeta para ELIMINAR:",
                    options=df_actual_supervisores['tarjeta'],
                    index=None,
                    placeholder="Escribe o selecciona una tarjeta...",
                    key="delete_supervisor_select"
                )
                
                if tarjeta_to_delete_s:
                    registro_a_borrar_s = df_actual_supervisores[df_actual_supervisores['tarjeta'] == tarjeta_to_delete_s].iloc[0]
                    st.warning(f"**PRECAUCIÓN:** Estás a punto de eliminar a **{registro_a_borrar_s['nombre']}** (`{registro_a_borrar_s['tarjeta']}`). Esta acción no se puede deshacer.")
                    
                    if st.button("Confirmar Eliminación", type="primary", use_container_width=True, key="delete_sup_confirm"):
                        query = "DELETE FROM head_count_supervisor WHERE tarjeta = :tarjeta;"
                        params = {"tarjeta": tarjeta_to_delete_s}
                        if ejecutar_crud_sql(query, params, f"🗑️ Supervisor ({tarjeta_to_delete_s}) eliminado."):
                            recargar_datos_persistentes('head_count_supervisor', 'head_count_supervisores')
                            st.rerun()
            else:
                st.info("No hay supervisores para eliminar.")

        # --- 4. VER TABLA ---
        st.markdown("---")
        st.subheader("Listado Actual de Supervisores")
        filtro_hc_s = st.text_input("🔍 Buscar en Supervisores:", key="filtro_hc_supervisores_crud")
        df_hc_s_filtrado = df_actual_supervisores
        if filtro_hc_s:
            try:
                mask = df_actual_supervisores.apply(lambda row: row.astype(str).str.contains(filtro_hc_s, case=False, regex=False).any(), axis=1)
                df_hc_s_filtrado = df_actual_supervisores[mask]
            except Exception as e: st.warning(f"Error filtro: {e}")
        
        st.dataframe(df_hc_s_filtrado, use_container_width=True, height=400)
        excel_hc_s = convertir_a_excel_simple(df_hc_s_filtrado)
        if excel_hc_s:
            st.download_button("📥 Descargar Vista (Excel)", excel_hc_s, "head_count_supervisores.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key='excel-hc-supervisores', use_container_width=True)

# ------------------------------------------------------------------------------
# --- PESTAÑA 9: HISTORIAL --- (Antes Pestaña 4, ahora 9)
# ------------------------------------------------------------------------------
with tab4:
    st.header("📊 Visualización de Historiales")

    subtab1, subtab2, subtab_reab = st.tabs([
        "📸 Snapshot de Hoy",
        "📚 Historial de Cambios",
        "🔄 Reabiertos (Historial)" 
    ])

    with subtab1:
        st.subheader("📸 Snapshot de Hoy")
        st.info("Muestra el estado actual de las órdenes 'Activo'/'Iniciado' del último Snapshot finalizado.")
        snapshot_hoy = st.session_state.snapshot_hoy 
        if not snapshot_hoy.empty:
            st.metric("Órdenes en Snapshot", len(snapshot_hoy))
            filtro_snap_hoy = st.text_input("🔍 Buscar en Snapshot:", key="filtro_snap_hoy_view")
            df_snap_hoy_filtrado = snapshot_hoy
            if filtro_snap_hoy:
                try:
                    mask = snapshot_hoy.apply(lambda row: row.astype(str).str.contains(filtro_snap_hoy, case=False, regex=False).any(), axis=1)
                    df_snap_hoy_filtrado = snapshot_hoy[mask]
                except Exception as e: st.warning(f"Error filtro: {e}")
            
            st.dataframe(df_snap_hoy_filtrado, use_container_width=True, height=500) 
            col_d1_s, col_d2_s = st.columns(2)
            with col_d1_s:
                csv_snap_hoy = df_snap_hoy_filtrado.to_csv(index=False, sep=';').encode('utf-8')
                st.download_button("📥 Descargar CSV", csv_snap_hoy, f"snapshot_hoy_vista.csv", mime='text/csv', key='csv-snapshot', use_container_width=True)
            with col_d2_s:
                excel_snap_hoy = convertir_a_excel(df_snap_hoy_filtrado, es_snapshot=True) 
                if excel_snap_hoy: st.download_button("📥 Descargar Excel", excel_snap_hoy, f"snapshot_hoy_vista.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key='excel-snapshot', use_container_width=True)
        else: st.info("📌 Snapshot vacío.")

    with subtab2:
        st.subheader("📚 Historial de Cambios")
        st.info("Muestra todos los registros de cambios (NUEVO y CAMBIO). Los tickets 'ACTIVO' sin cambios no se guardan aquí.")
        historial_completo = st.session_state.historial_cambios 
        
        if not historial_completo.empty:
            st.metric("Total Registros Históricos", len(historial_completo))
            tickets_unicos_hist = 0; dias_historial_str = "N/A" 
            if 'OrdenExterna' in historial_completo.columns: tickets_unicos_hist = historial_completo['OrdenExterna'].nunique()
            if 'Timestamp_Procesado' in historial_completo.columns:
                try:
                    timestamps_validos = pd.to_datetime(historial_completo['Timestamp_Procesado'], errors='coerce').dropna()
                    if not timestamps_validos.empty:
                        dias_historial = (timestamps_validos.max().date() - timestamps_validos.min().date()).days + 1; dias_historial_str = str(dias_historial)
                except Exception: pass
            col_stat1_hc, col_stat2_hc = st.columns(2);
            with col_stat1_hc: st.metric("🎫 Tickets Únicos", tickets_unicos_hist)
            with col_stat2_hc: st.metric("📅 Días de Historial", dias_historial_str)

            col_f1, col_f2, col_f3 = st.columns(3)
            df_hist_completo_filtrado = historial_completo
            lotes_hist = []; tipos_evento_unicos_hist = []; estados_unicos_hist = [] 
            if 'Lote_Procesado' in df_hist_completo_filtrado.columns: lotes_hist = sorted(pd.to_numeric(df_hist_completo_filtrado['Lote_Procesado'], errors='coerce').dropna().astype(int).unique(), reverse=True)
            if 'Tipo_Evento' in df_hist_completo_filtrado.columns: tipos_evento_unicos_hist = sorted(df_hist_completo_filtrado['Tipo_Evento'].dropna().unique())
            if 'Estado' in df_hist_completo_filtrado.columns: estados_unicos_hist = sorted(df_hist_completo_filtrado['Estado'].dropna().unique())

            with col_f1:
                if lotes_hist:
                    lote_seleccionado_hist = st.selectbox("🔢 Lote:", options=["Todos"] + lotes_hist, key="filtro_lote_hist")
                    if lote_seleccionado_hist != "Todos": df_hist_completo_filtrado = df_hist_completo_filtrado[pd.to_numeric(df_hist_completo_filtrado['Lote_Procesado'], errors='coerce') == lote_seleccionado_hist]
            with col_f2:
                if tipos_evento_unicos_hist:
                    default_eventos = [e for e in tipos_evento_unicos_hist if e != 'ACTIVO']
                    if not default_eventos: default_eventos = tipos_evento_unicos_hist
                    
                    tipo_evento_filtro_hist = st.multiselect("🏷️ Evento:", options=tipos_evento_unicos_hist, default=default_eventos, key="filtro_evento_hist")
                    if set(tipo_evento_filtro_hist) != set(tipos_evento_unicos_hist): df_hist_completo_filtrado = df_hist_completo_filtrado[df_hist_completo_filtrado['Tipo_Evento'].isin(tipo_evento_filtro_hist)]
            with col_f3:
                if estados_unicos_hist:
                    estado_filtro_hist = st.multiselect("🚦 Estado:", options=estados_unicos_hist, default=estados_unicos_hist, key="filtro_estado_hist")
                    if set(estado_filtro_hist) != set(estados_unicos_hist): df_hist_completo_filtrado = df_hist_completo_filtrado[df_hist_completo_filtrado['Estado'].isin(estado_filtro_hist)]
            
            filtro_hist_completo_texto = st.text_input("🔍 Buscar en Historial Filtrado:", key="filtro_hist_completo_view")
            if filtro_hist_completo_texto:
                try:
                    mask = df_hist_completo_filtrado.apply(lambda row: row.astype(str).str.contains(filtro_hist_completo_texto, case=False, regex=False).any(), axis=1)
                    df_hist_completo_filtrado = df_hist_completo_filtrado[mask]
                except Exception as e: st.warning(f"Error filtro texto: {e}")
            
            df_hist_completo_filtrado_sorted = normalizar_timestamps(df_hist_completo_filtrado).sort_values(['Lote_Procesado', 'Timestamp_Procesado'], ascending=[False, False])
            st.dataframe(df_hist_completo_filtrado_sorted, use_container_width=True, height=500) 
            
            col_d1_hc, col_d2_hc = st.columns(2)
            with col_d1_hc:
                csv_hist_completo = df_hist_completo_filtrado_sorted.to_csv(index=False, sep=';').encode('utf-8') 
                st.download_button("📥 Descargar CSV", csv_hist_completo, f"historial_completo_vista.csv", mime='text/csv', key='csv-hist-completo', use_container_width=True)
            with col_d2_hc:
                excel_hist_completo = convertir_a_excel(df_hist_completo_filtrado_sorted) 
                if excel_hist_completo: st.download_button("📥 Descargar Excel", excel_hist_completo, f"historial_completo_vista.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key='excel-hist-completo', use_container_width=True)
        else: st.info("📌 El historial de cambios está vacío.")

    with subtab_reab:
        st.subheader("🔄 Historial de Reabiertos")
        st.info("Muestra todos los registros de reabiertos cargados históricamente (no solo hoy).")
        
        df_reabiertos = st.session_state.get('reabiertos', pd.DataFrame())
        
        if not df_reabiertos.empty:
            st.metric("Total Registros Reabiertos (Histórico)", len(df_reabiertos))
            
            filtro_reab_texto = st.text_input("🔍 Buscar en Reabiertos:", key="filtro_reab_view")
            df_reab_filtrado = df_reabiertos
            if filtro_reab_texto:
                try:
                    mask = df_reab_filtrado.apply(lambda row: row.astype(str).str.contains(filtro_reab_texto, case=False, regex=False).any(), axis=1)
                    df_reab_filtrado = df_reab_filtrado[mask]
                except Exception as e: st.warning(f"Error filtro texto: {e}")
            
            cols_display_reab = ['caso', 'codigo', 'tarjeta', 'supervisor', 'tarjeta_supervisor', 'fecha', 'condicion']
            cols_existentes = [col for col in cols_display_reab if col in df_reab_filtrado.columns]
            df_reab_filtrado_display = df_reab_filtrado[cols_existentes]

            st.dataframe(df_reab_filtrado_display, use_container_width=True, height=500)
            
            col_d1_r, col_d2_r = st.columns(2)
            with col_d1_r:
                csv_reab = df_reab_filtrado_display.to_csv(index=False, sep=';').encode('utf-8')
                st.download_button("📥 Descargar CSV (Reabiertos)", csv_reab, f"reabiertos_vista.csv", mime='text/csv', key='csv-reabiertos', use_container_width=True)
            with col_d2_r:
                excel_reab = convertir_a_excel_simple(df_reab_filtrado_display)
                if excel_reab: 
                    st.download_button("📥 Descargar Excel (Reabiertos)", excel_reab, f"reabiertos_vista.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key='excel-reabiertos', use_container_width=True)
        else:
            st.info("📌 El historial de reabiertos está vacío.")

st.markdown("---")
st.caption("Sistema KUNAI v2.9.0 - CRUD Head Count Integrado")
