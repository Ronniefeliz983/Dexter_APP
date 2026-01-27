import pandas as pd
from sqlalchemy import create_engine, text
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.mime.text import MIMEText
import os
from datetime import datetime, timedelta

# --- VARIABLES DE ENTORNO ---
DB_URL = os.getenv("DATABASE_URL")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_DESTINATARIOS = os.getenv("EMAIL_JEFE") 

def obtener_tickets_kenny():
    if not DB_URL:
        print("Error: DATABASE_URL no encontrada.")
        return None
    
    # Ajuste para SQLAlchemy si la URL empieza con postgres://
    url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL.startswith("postgres://") else DB_URL
    
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            # 1. Obtener la lista de tickets puntuales (la lista de Kenny)
            query_puntuales = text("SELECT orden_externa FROM puntuales")
            df_puntuales = pd.read_sql(query_puntuales, conn)
            
            if df_puntuales.empty:
                print("La lista de 'puntuales' está vacía.")
                return None
            
            # Limpiamos los IDs para asegurar que sean strings sin espacios
            lista_ids = df_puntuales['orden_externa'].astype(str).str.strip().tolist()
            
            if not lista_ids:
                return None

            # 2. Obtener el historial COMPLETO de esos tickets (SELECT *)
            # Traemos TODAS las columnas
            query_historia = text("SELECT * FROM historial_cambios")
            df_full = pd.read_sql(query_historia, conn)
            
            if df_full.empty:
                return None

            # 3. Filtrar en Pandas (cruce de datos)
            # Nos quedamos solo con las ordenes que están en la lista de Kenny
            df_kenny = df_full[df_full['orden_externa'].astype(str).isin(lista_ids)].copy()
            
            if df_kenny.empty:
                print("No se encontraron registros en el historial para los tickets de la lista.")
                return None

            # 4. Obtener solo el ÚLTIMO estado de cada ticket
            # Ordenamos por fecha de proceso (descendente) y nos quedamos con el primero
            if 'timestamp_procesado' in df_kenny.columns:
                df_kenny['timestamp_procesado'] = pd.to_datetime(df_kenny['timestamp_procesado'])
                df_kenny = df_kenny.sort_values('timestamp_procesado', ascending=False)
            
            df_final = df_kenny.drop_duplicates(subset=['orden_externa'], keep='first')
            
            # 5. Limpieza final (Opcional)
            # Quitamos columnas técnicas que no le sirven a Kenny (como ids internos o fechas duplicadas)
            cols_a_borrar = ['id', 'fecha_actualizacion', 'fecha_registro'] 
            df_final = df_final.drop(columns=[c for c in cols_a_borrar if c in df_final.columns], errors='ignore')
            
            return df_final

    except Exception as e:
        print(f"Error conectando a la base de datos o procesando: {e}")
        return None

def enviar_correo():
    print("Iniciando proceso de reporte Kenny...")
    df = obtener_tickets_kenny()
    
    # Ajuste de hora para el nombre del archivo (UTC-4 aprox)
    fecha_hoy = (datetime.utcnow() - timedelta(hours=4)).strftime('%d-%m-%Y')
    
    if df is None or df.empty:
        print(f"No hay tickets de Kenny para reportar hoy ({fecha_hoy})")
        return

    # Generar Excel
    nombre_archivo = f"Reporte_Kenny_Completo_{fecha_hoy}.xlsx"
    df.to_excel(nombre_archivo, index=False)
    print(f"Excel generado: {nombre_archivo} con {len(df)} filas y todas las columnas.")

    # Configurar Correo
    msg = MIMEMultipart()
    msg['Subject'] = f"🚀 Reporte Tickets Kenny (Detalle Completo) - {fecha_hoy} (5:30 PM)"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_DESTINATARIOS

    cuerpo = f"""
    Hola,
    
    Adjunto el reporte de los tickets puntuales (lista de Kenny) actualizado al corte de las 5:30 PM.
    
    Este archivo contiene TODAS las columnas disponibles.
    
    Total de casos: {len(df)}
    
    Saludos,
    Tu Asistente Virtual 🤖
    """
    msg.attach(MIMEText(cuerpo, 'plain'))

    # Adjuntar Archivo
    with open(nombre_archivo, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename={nombre_archivo}")
    msg.attach(part)

    try:
        # Enviar
        lista_destinatarios = [e.strip() for e in EMAIL_DESTINATARIOS.split(',') if e.strip()]
        
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, lista_destinatarios, msg.as_string())
        server.quit()
        print(f"✅ Correo enviado exitosamente a: {lista_destinatarios}")
    except Exception as e:
        print(f"❌ Error enviando correo: {e}")
    finally:
        # Limpieza del archivo temporal
        if os.path.exists(nombre_archivo):
            os.remove(nombre_archivo)

if __name__ == "__main__":
    enviar_correo()
