import pandas as pd
from sqlalchemy import create_engine, text
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.mime.text import MIMEText
import os
from datetime import datetime

# Credenciales desde Secrets de GitHub
DB_URL = os.getenv("DATABASE_URL")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_JEFE = os.getenv("EMAIL_JEFE")

def obtener_reporte_completo():
    if not DB_URL:
        raise ValueError("DATABASE_URL no encontrada en los Secrets.")
    
    # Ajuste de protocolo para SQLAlchemy
    url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL.startswith("postgres://") else DB_URL
    engine = create_engine(url)
    
    with engine.connect() as conn:
        # Seleccionamos TODAS las columnas de la tabla
        query = text("SELECT * FROM historial_cambios")
        df_full = pd.read_sql(query, conn)
        
        if df_full.empty:
            return None

        # Procesar fechas para identificar "Nuevos Hoy"
        df_full['timestamp_procesado'] = pd.to_datetime(df_full['timestamp_procesado'])
        
        # Identificar la primera vez que apareció cada orden (Fecha de Nacimiento)
        df_full['Fecha_Nacimiento'] = df_full.groupby('orden_externa')['timestamp_procesado'].transform('min')
        
        # Filtrar solo los tickets cuyo primer registro fue hoy
        fecha_hoy = datetime.now().date()
        df_nuevos_hoy = df_full[df_full['Fecha_Nacimiento'].dt.date == fecha_hoy].copy()
        
        if df_nuevos_hoy.empty:
            return None

        # Lógica de estado más reciente: Ordenar por tiempo y quitar duplicados
        df_final = df_nuevos_hoy.sort_values('timestamp_procesado', ascending=False)
        df_final = df_final.drop_duplicates(subset=['orden_externa'], keep='first')
        
        # Limpieza de columnas técnicas antes de enviar
        columnas_a_excluir = ['id', 'fecha_actualizacion', 'fecha_registro', 'Fecha_Nacimiento']
        df_final = df_final.drop(columns=[c for c in columnas_a_excluir if c in df_final.columns])

        # Opcional: Poner los nombres de las columnas en mayúsculas/formato bonito
        df_final.columns = [col.replace('_', ' ').title() for col in df_final.columns]
        
        return df_final

def enviar_correo():
    df = obtener_reporte_completo()
    if df is None:
        print("No se encontraron tickets nuevos hoy.")
        return

    archivo = f"Reporte_General_{datetime.now().strftime('%Y%m%d')}.xlsx"
    df.to_excel(archivo, index=False)

    msg = MIMEMultipart()
    msg['Subject'] = f"📊 Reporte Detallado de Trabajos - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_JEFE

    msg.attach(MIMEText(f"Saludos,\n\nSe adjunta el reporte completo con todas las columnas de los tickets nuevos procesados hoy.", 'plain'))

    with open(archivo, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename={archivo}")
    msg.attach(part)

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        print("Reporte enviado exitosamente con todas las columnas.")
    finally:
        if os.path.exists(archivo):
            os.remove(archivo)

if __name__ == "__main__":
    enviar_correo()
