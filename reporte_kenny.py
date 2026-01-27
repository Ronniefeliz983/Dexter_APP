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
# Aquí puedes poner el correo de Kenny o a quien se le envíe
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

            # 2. Obtener el historial SOLO de esos tickets
            # Usamos parámetros seguros (:ids) o formateo si la lista es segura
            # Para simplicidad y velocidad en pandas: traemos datos relevantes
            query_historia = text("""
                SELECT orden_externa, estado, cliente, supervisor, asignado_a, 
                       vence, timestamp_procesado, tipo_servicio, municipio
                FROM historial_cambios
            """)
            df_full = pd.read_sql(query_historia, conn)
            
            # 3. Filtrar en Pandas (cruce de datos)
            # Nos quedamos solo con las ordenes que están en la lista de puntuales
            df_kenny = df_full[df_full['orden_externa'].astype(str).isin(lista_ids)].copy()
            
            if df_kenny.empty:
                print("No se encontraron registros en el historial para los tickets de la lista.")
                return None

            # 4. Obtener solo el ÚLTIMO estado de cada ticket
            df_kenny = df_kenny.sort_values('timestamp_procesado', ascending=False)
            df_final = df_kenny.drop_duplicates(subset=['orden_externa'], keep='first')
            
            # (Opcional) Filtrar columnas para que el Excel se vea limpio
            cols_exportar = ['orden_externa', 'estado', 'cliente', 'supervisor', 'asignado_a', 'vence', 'tipo_servicio', 'municipio']
            # Seleccionamos solo las columnas que existen
            cols_finales = [c for c in cols_exportar if c in df_final.columns]
            
            return df_final[cols_finales]

    except Exception as e:
        print(f"Error conectando a la base de datos: {e}")
        return None

def enviar_correo():
    print("Iniciando proceso de reporte Kenny...")
    df = obtener_tickets_kenny()
    
    # Ajuste de hora para el nombre del archivo (UTC-4 aprox)
    fecha_hoy = (datetime.utcnow() - timedelta(hours=4)).strftime('%d-%m-%Y')
    
    if df is None or df.empty:
        print(f"No hay tickets de Kenny para reportar hoy ({fecha_hoy})")
        # Opcional: Podrías enviar un correo diciendo "No hay tickets pendientes"
        return

    # Generar Excel
    nombre_archivo = f"Reporte_Kenny_{fecha_hoy}.xlsx"
    df.to_excel(nombre_archivo, index=False)
    print(f"Excel generado: {nombre_archivo} con {len(df)} filas.")

    # Configurar Correo
    msg = MIMEMultipart()
    msg['Subject'] = f"🚀 Reporte Tickets Kenny - {fecha_hoy} (5:30 PM)"
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_DESTINATARIOS

    cuerpo = f"""
    Hola,
    
    Adjunto el reporte de los tickets puntuales (lista de Kenny) actualizado al corte de las 5:30 PM.
    
    Total de casos en seguimiento: {len(df)}
    
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
        # Limpieza
        if os.path.exists(nombre_archivo):
            os.remove(nombre_archivo)

if __name__ == "__main__":
    enviar_correo()
