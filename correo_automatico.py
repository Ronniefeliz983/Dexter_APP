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

def obtener_reporte_formateado():
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        # 1. Traer todo el historial para identificar "Nuevos Hoy"
        query = text("SELECT * FROM historial_cambios")
        df_full = pd.read_sql(query, conn)
        
        if df_full.empty:
            return None

        # 2. Identificar la "Fecha de Nacimiento" del ticket (Lógica de tu Dashboard)
        df_full['timestamp_procesado'] = pd.to_datetime(df_full['timestamp_procesado'])
        df_full['Fecha_Nacimiento'] = df_full.groupby('orden_externa')['timestamp_procesado'].transform('min')
        
        # 3. Filtrar solo los que nacieron hoy
        fecha_hoy = datetime.now().date()
        df_nuevos_hoy = df_full[df_full['Fecha_Nacimiento'].dt.date == fecha_hoy].copy()
        
        if df_nuevos_hoy.empty:
            return None

        # 4. Quedarse con el estado MÁS RECIENTE (Lógica obtener_datos_unicos)
        df_final = df_nuevos_hoy.sort_values('timestamp_procesado', ascending=False)
        df_final = df_final.drop_duplicates(subset=['orden_externa'], keep='first')
        
        # 5. Seleccionar y renombrar columnas para que se vea limpio como en tu imagen
        columnas_visibles = {
            'trabajo': 'Trabajo',
            'orden_externa': 'OrdenExterna',
            'cliente': 'Cliente',
            'vence': 'Vence',
            'oe_creacion': 'OE_Creacion',
            'oe_vence': 'OE_Vence',
            'prioridad': 'Prioridad',
            'tipo_de_prioridad': 'Tipo_de_prioridad'
        }
        return df_final[list(columnas_visibles.keys())].rename(columns=columnas_visibles)

def enviar_correo():
    df = obtener_reporte_formateado()
    if df is None:
        print("No hay tickets nuevos hoy.")
        return

    archivo = f"Reporte_Nuevos_Hoy_{datetime.now().strftime('%Y%m%d')}.xlsx"
    df.to_excel(archivo, index=False)

    msg = MIMEMultipart()
    msg['Subject'] = f"📋 Tabla de Tickets: Nuevos Hoy (Estado Actual) - {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_JEFE

    msg.attach(MIMEText(f"Hola,\n\nAdjunto el reporte diario con los tickets nuevos detectados hoy y su estado más reciente procesado hasta las 5:30 PM.", 'plain'))

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
        print("Reporte enviado al jefe.")
    finally:
        if os.path.exists(archivo):
            os.remove(archivo)

if __name__ == "__main__":
    enviar_correo()
