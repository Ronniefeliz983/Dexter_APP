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
        raise ValueError("DATABASE_URL no encontrada.")
    
    # Ajuste para SQLAlchemy
    url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL.startswith("postgres://") else DB_URL
    engine = create_engine(url)
    
    with engine.connect() as conn:
        # Traemos todas las columnas
        query = text("SELECT * FROM historial_cambios")
        df_full = pd.read_sql(query, conn)
        
        if df_full.empty:
            return None

        df_full['timestamp_procesado'] = pd.to_datetime(df_full['timestamp_procesado'])
        
        # Lógica de tickets nuevos hoy
        df_full['Fecha_Nacimiento'] = df_full.groupby('orden_externa')['timestamp_procesado'].transform('min')
        fecha_hoy = datetime.now().date()
        df_nuevos_hoy = df_full[df_full['Fecha_Nacimiento'].dt.date == fecha_hoy].copy()
        
        if df_nuevos_hoy.empty:
            return None

        # Estado más reciente
        df_final = df_nuevos_hoy.sort_values('timestamp_procesado', ascending=False)
        df_final = df_final.drop_duplicates(subset=['orden_externa'], keep='first')
        
        # Limpiar columnas técnicas
        columnas_a_excluir = ['id', 'fecha_actualizacion', 'fecha_registro', 'Fecha_Nacimiento', 'timestamp_procesado']
        df_final = df_final.drop(columns=[c for c in columnas_a_excluir if c in df_final.columns])
        
        return df_final

def enviar_correo():
    df = obtener_reporte_completo()
    fecha_actual = datetime.now().strftime('%d-%m-%Y')
    
    if df is None:
        print(f"No hay tickets para el corte del {fecha_actual}")
        return

    # Nombre del archivo solicitado: corte + dia actual
    nombre_archivo = f"corte_{fecha_actual}.xlsx"
    df.to_excel(nombre_archivo, index=False)

    msg = MIMEMultipart()
    # Asunto con el día
    msg['Subject'] = f"Corte de Operaciones - {fecha_actual}"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_JEFE

    # Mensaje solicitado
    cuerpo_mensaje = f"saludo aqui el corte de las 5, hoy {fecha_actual}"
    msg.attach(MIMEText(cuerpo_mensaje, 'plain'))

    with open(nombre_archivo, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename={nombre_archivo}")
    msg.attach(part)

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        print(f"Corte del {fecha_actual} enviado correctamente.")
    finally:
        if os.path.exists(nombre_archivo):
            os.remove(nombre_archivo)

if __name__ == "__main__":
    enviar_correo()
