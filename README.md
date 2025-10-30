# Dashboard Trabajos Claro

Dashboard de monitoreo para trabajos de Claro con Supabase.

## 🚀 Despliegue en Render

### Pasos para desplegar:

1. **Fork o clona este repositorio**

2. **Configura tu base de datos en Supabase**
   - Crea una cuenta en [Supabase](https://supabase.com)
   - Crea la tabla `historial_cambios_hoy`
   - Copia tu DATABASE_URL

3. **Despliega en Render**
   - Crea cuenta en [Render](https://render.com)
   - New > Web Service
   - Conecta tu repositorio de GitHub
   - Usa estas configuraciones:
     - Runtime: Python
     - Build Command: `pip install -r requirements.txt`
     - Start Command: `streamlit run app.py`
   
4. **Configura las variables de entorno**
   - En Render, ve a Environment
   - Agrega `DATABASE_URL` con tu URL de Supabase
   - Agrega las demás variables del archivo de configuración

5. **Listo!** Tu app estará en: `https://tu-app.onrender.com`

## 🔧 Desarrollo Local
```bash
# Instalar dependencias
pip install -r requirements.txt

# Crear archivo de secretos
mkdir .streamlit
echo '[postgres]\nDATABASE_URL = "tu_url_aqui"' > .streamlit/secrets.toml

# Ejecutar
streamlit run app.py
```

## 📊 Características

- Login con múltiples roles
- Dashboard en tiempo real
- Exportación a Excel
- Tracking de tickets
- Análisis de PYMEs
- Gráficos interactivos

## ⚡ Optimizaciones

- Carga 5x más rápida
- Cache inteligente
- Pool de conexiones
- Queries optimizadas
