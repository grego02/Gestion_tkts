# -*- coding: utf-8 -*-
import streamlit as st
import json
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field
from google import genai

# Configuración estética de la página web
st.set_page_config(
    page_title="Mesa de Ayuda Inteligente - SAP MVP",
    page_icon="⚙️",
    layout="wide"
)

# Base de datos de usuarios simulada para el MVP (Usuario: [Contraseña, Empresa])
# USUARIOS_MOCK = {
#     "carlos.logistica": ["sap123", "Logística S.A."],
#     "ana.fi": ["sap456", "Siderúrgica del Sur"],
#    "admin": ["admin", "Interno / Consultoría"]
# }

# Reemplazar la sección 3 del archivo app_sap.py con este bloque dinámico:

import psycopg2

def validar_credenciales_db(usuario, contrasena):
    """Consulta la base de datos en la nube para verificar el acceso."""
    try:
        conn = psycopg2.connect(
            host=st.secrets["DB_HOST"],
            database=st.secrets["DB_NAME"],
            user=st.secrets["DB_USER"],
            password=st.secrets["DB_PASSWORD"],
            port=st.secrets["DB_PORT"]
        )
        cursor = conn.cursor()
        cursor.execute(
            "SELECT contrasena, empresa FROM usuarios_sap WHERE usuario = %s", 
            (usuario,)
        )
        registro = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if registro and registro[0] == contrasena:
            return {"valido": True, "empresa": registro[1]}
    except Exception as e:
        st.error(f"Error de conexión con la base de datos: {e}")
    return {"valido": False, "empresa": None}

# Modificar la lógica del botón de login dentro de tu Pantalla 1:
if boton_login:
    resultado_auth = validar_credenciales_db(user_input, pass_input)
    if resultado_auth["valido"]:
        st.session_state["autenticado"] = True
        st.session_state["usuario_actual"] = user_input
        st.session_state["empresa_actual"] = resultado_auth["empresa"]
        st.rerun()
    else:
        st.error("Usuario o contraseña incorrectos. Intente nuevamente.")


# =====================================================================
# 1. ESQUEMA PYDANTIC PARA GEMINI
# =====================================================================
class SAPIncidentSchema(BaseModel):
    fecha: str = Field(description="Fecha actual en formato DD.MM.YYYY.")
    asunto: str = Field(description="Resumen corto de la solicitud (máximo 8 palabras).")
    cliente: str = Field(description="Nombre del cliente extraído o el provisto por el sistema.")
    detalle: str = Field(description="El texto intacto que ingresó el usuario.")
    prioridad: Literal["Muy Alta", "Alta", "Normal", "Baja"] = Field(
        description="Criticidad: Muy Alta (urgencia explícita/bloqueo total), Alta (error transaccional contable/facturación), Normal/Baja (consultas/configuraciones)."
    )
    modulo_sugerido: str = Field(description="Módulo SAP detectado (MM, SD, FI, CO, PP, ABAP, Desconocido).")
    informacion_adicional_requerida: Optional[str] = Field(
        description="Pregunta aclaratoria si el módulo es ambiguo o requiere datos adicionales del usuario. Si está todo claro, dejar vacío."
    )

# =====================================================================
# 2. FUNCIÓN DE PROCESAMIENTO CON LA API DE GEMINI
# =====================================================================
def procesar_con_gemini(texto_usuario: str, cliente_seleccionado: str) -> dict:
    # Intenta leer desde los secrets de Streamlit (para producción en la nube)
    # Si no existe, usa un fallback (para tu prueba local temporal)
    try:
        API_KEY = st.secrets["GEMINI_API_KEY"]
    except Exception:
        API_KEY = "" # Poné acá tu clave provisoria para probar en tu PC
        
    client = genai.Client(api_key=API_KEY)
    fecha_hoy = datetime.now().strftime("%d.%m.%Y")
    
    prompt_sistema = f"""
    Actúas como un Analista de Soporte SAP Senior. Analiza el incidente e inyecta la estructura JSON requerida.
    
    Reglas de Prioridad:
    - Muy Alta: Si exige resolución urgente, uso de palabras de desesperación o la operatoria está totalmente frenada.
    - Alta: Errores técnicos bloqueantes en cargas de documentos o validación (ej: saldo de material negativo, falla de contabilización).
    - Normal/Baja: Tareas administrativas o consultas estándar.

    Datos de control:
    - Fecha del Incidente: {fecha_hoy}
    - Cliente: {cliente_seleccionado}
    
    Texto del usuario: "{texto_usuario}"
    """
    
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt_sistema,
        config={
            "response_mime_type": "application/json",
            "response_schema": SAPIncidentSchema,
        }
    )
    return json.loads(response.text)

# =====================================================================
# 3. CONTROL DE FLUJO DE AUTENTICACIÓN
# =====================================================================
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False

# --- PANTALLA 1: LOGIN DE USUARIO ---
if not st.session_state["autenticado"]:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_login, _ = st.columns([1, 2]) # Centramos levemente a la izquierda
    
    with col_login:
        st.subheader("🔑 Acceso al Portal SAP MVP")
        st.info("Credenciales demo válidas:\n- Usuario: `carlos.logistica` / Clave: `sap123` \n- Usuario: `admin` / Clave: `admin`")
        
        user_input = st.text_input("Nombre de Usuario")
        pass_input = st.text_input("Contraseña", type="password")
        boton_login = st.button("Iniciar Sesión", use_container_width=True)
        
        if boton_login:
            if user_input in USUARIOS_MOCK and USUARIOS_MOCK[user_input][0] == pass_input:
                st.session_state["autenticado"] = True
                st.session_state["usuario_actual"] = user_input
                st.session_state["empresa_actual"] = USUARIOS_MOCK[user_input][1]
                st.rerun() # Recarga la app para pasar al panel
            else:
                st.error("Usuario o contraseña incorrectos. Intente nuevamente.")

# --- PANTALLA 2: PANEL DEL CLASIFICADOR (SOLO ACCESIBLE LOGUEADO) ---
else:
    # Encabezado superior con botón de cierre de sesión
    col_titulo, col_logout = st.columns([5, 1])
    with col_titulo:
        st.title("⚙️ Mesa de Ayuda Inteligente SAP — Prototipo MVP")
        st.markdown(f"Conectado como: **{st.session_state['usuario_actual']}** | Empresa asignada: **{st.session_state['empresa_actual']}**")
    with col_logout:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state["autenticado"] = False
            st.rerun()
            
    st.divider()

    # Estructura del clasificador web
    col_izquierda, col_derecha = st.columns(2, gap="large")

    with col_izquierda:
        st.subheader("📥 Ingreso del Incidente")
        
        # El campo cliente ya no es un selector suelto, se autocompleta con los datos de la sesión segura
        st.text_input("Cliente Autenticado", value=st.session_state["empresa_actual"], disabled=True)
        
        input_problema = st.text_area(
            "Describa el problema que presenta en SAP:",
            height=180,
            placeholder="Describa aquí el error transaccional de forma libre..."
        )
        
        boton_procesar = st.button("🚀 Analizar y Clasificar Incidente", use_container_width=True)

    with col_derecha:
        st.subheader("📊 Output del Sistema")
        
        if boton_procesar:
            if not input_problema.strip():
                st.warning("Por favor, ingrese el detalle del incidente antes de procesar.")
            else:
                with st.spinner("Gemini analizando impacto y estructura técnica..."):
                    try:
                        resultado_dict = procesar_con_gemini(input_problema, st.session_state["empresa_actual"])
                        st.session_state["resultado"] = resultado_dict
                    except Exception as e:
                        st.error(f"Error de conexión con la API: {e}")
        
        if "resultado" in st.session_state:
            res = st.session_state["resultado"]
            tab_humana, tab_json = st.tabs(["📋 Reporte Ordenado", "💻 JSON Estructurado para API"])
            
            with tab_humana:
                c1, c2, c3 = st.columns(3)
                prioridad_emoji = "🚨" if "Alta" in res.get('prioridad', 'Normal') else "ℹ️"
                c1.metric(label="Fecha Registro", value=res.get('fecha'))
                c2.metric(label="Módulo SAP", value=res.get('modulo_sugerido'))
                c3.metric(label=f"{prioridad_emoji} Prioridad", value=res.get('prioridad'))
                
                st.markdown(f"**🏢 Cliente:** {res.get('cliente')}")
                st.markdown(f"**📌 Asunto:** {res.get('asunto')}")
                
                if res.get('informacion_adicional_requerida'):
                    st.error(f"⚠️ **Información Adicional Requerida:** {res.get('informacion_adicional_requerida')}")
                else:
                    st.success("✅ Datos completos: No se requiere información adicional.")
                    
                st.info(f"**📝 Detalle del Ticket:**\n\n{res.get('detalle')}")
                
            with tab_json:
                st.markdown("Este objeto JSON está formateado de forma nativa para alimentar sistemas externos:")
                st.json(res)
        else:
            st.info("Complete el formulario de la izquierda y presione el botón para ver la clasificación inteligente.")
