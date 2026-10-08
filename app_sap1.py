# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
import streamlit as st
import json
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field
from google import genai
import psycopg2

# Configuración estética de la página web
st.set_page_config(
    page_title="Mesa de Ayuda Inteligente - SAP MVP",
    page_icon="⚙️",
    layout="wide"
)

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
    try:
        API_KEY = st.secrets["GEMINI_API_KEY"]
    except Exception:
        API_KEY = "TU_API_KEY_REAL"
        
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
# 3. FUNCIONES DE BASE DE DATOS (RENDER)
# =====================================================================
def conectar_db():
    return psycopg2.connect(
        host=st.secrets["DB_HOST"],
        database=st.secrets["DB_NAME"],
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"],
        port=st.secrets["DB_PORT"]
    )

def validar_credenciales_db(usuario, contrasena):
    """Consulta la base de datos en la nube para verificar el acceso."""
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("SELECT contrasena, empresa FROM usuarios_sap WHERE usuario = %s", (usuario,))
        registro = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if registro and registro[0] == contrasena:
            return {"valido": True, "empresa": registro[1]}
    except Exception as e:
        st.error(f"Error de autenticación DB: {e}")
    return {"valido": False, "empresa": None}

def inicializar_tabla_tickets():
    """Crea la tabla de almacenamiento de tickets estructurados por IA si no existe."""
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets_sap (
                id SERIAL PRIMARY KEY,
                usuario VARCHAR(50) NOT NULL,
                empresa VARCHAR(100) NOT NULL,
                fecha VARCHAR(20) NOT NULL,
                asunto VARCHAR(200) NOT NULL,
                modulo VARCHAR(20) NOT NULL,
                prioridad VARCHAR(20) NOT NULL,
                detalle TEXT NOT NULL,
                info_adicional TEXT,
                fecha_servidor TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        st.error(f"Error al inicializar infraestructura de tickets: {e}")

def guardar_ticket_db(usuario, empresa, ticket_dict):
    """Persiste el análisis estructurado de Gemini y devuelve el ID único asignado."""
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tickets_sap (usuario, empresa, fecha, asunto, modulo, prioridad, detalle, info_adicional)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (
            usuario,
            empresa,
            ticket_dict.get("fecha"),
            ticket_dict.get("asunto"),
            ticket_dict.get("modulo_sugerido"),
            ticket_dict.get("prioridad"),
            ticket_dict.get("detalle"),
            ticket_dict.get("informacion_adicional_requerida")
        ))
        
        nuevo_id_row = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        
        if nuevo_id_row:
            return nuevo_id_row[0]
    except Exception as e:
        st.error(f"Error al guardar el ticket en el historial: {e}")
    return None

def obtener_historial_tickets_db(usuario):
    """Recupera únicamente los incidentes creados por el usuario logueado."""
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT fecha, asunto, modulo, prioridad, detalle, info_adicional, id 
            FROM tickets_sap 
            WHERE usuario = %s 
            ORDER BY id DESC
        """, (usuario,))
        registros = cursor.fetchall()
        cursor.close()
        conn.close()
        return registros
    except Exception as e:
        st.error(f"Error al leer el historial: {e}")
    return []

# =====================================================================
# 4. CONTROL DE FLUJO DE INTERFAZ Y PANTALLAS
# =====================================================================
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False

# --- PANTALLA 1: LOGIN DE USUARIO ---
if not st.session_state["autenticado"]:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_login, _ = st.columns(2)
    
    with col_login:
        st.subheader("🔑 Acceso al Portal SAP MVP")
        user_input = st.text_input("Nombre de Usuario")
        pass_input = st.text_input("Contraseña", type="password")
        boton_login = st.button("Iniciar Sesión", use_container_width=True)
        
        if boton_login:
            if not user_input or not pass_input:
                st.warning("Por favor complete ambos campos.")
            else:
                with st.spinner("Autenticando en la base de datos cloud..."):
                    resultado_auth = validar_credenciales_db(user_input, pass_input)
                    if resultado_auth["valido"]:
                        st.session_state["autenticado"] = True
                        st.session_state["usuario_actual"] = user_input
                        st.session_state["empresa_actual"] = resultado_auth["empresa"]
                        inicializar_tabla_tickets()
                        st.rerun()
                    else:
                        st.error("Usuario o contraseña incorrectos. Intente nuevamente.")

# --- PANTALLA 2: PANEL DEL CLASIFICADOR E HISTORIAL ---
else:
    col_titulo, col_logout = st.columns(2)
    with col_titulo:
        st.title("⚙️ Mesa de Ayuda Inteligente SAP — Prototipo MVP")
        st.markdown(f"Conectado como: **{st.session_state['usuario_actual']}** | Empresa asignada: **{st.session_state['empresa_actual']}**")
    with col_logout:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state["autenticado"] = False
            if "resultado" in st.session_state:
                del st.session_state["resultado"]
            st.rerun()
            
    st.divider()

    col_izquierda, col_derecha = st.columns(2, gap="large")

    with col_izquierda:
        st.subheader("📥 Ingreso del Incidente")
        st.text_input("Cliente Autenticado", value=st.session_state["empresa_actual"], disabled=True)
        
        input_problema = st.text_area(
            "Describa el problema que presenta en SAP:",
            height=180,
            placeholder="Escriba aquí el error transaccional de forma libre..."
        )
        
        boton_procesar = st.button("🚀 Analizar y Clasificar Incidente", use_container_width=True)

        with col_derecha:
        # 1. CREAMOS LAS PESTAÑAS (Siempre visibles en la columna derecha)
         tab_actual, tab_json, tab_historial = st.tabs([
            "📋 Último Análisis", 
            "💻 JSON Estructurado", 
            "⏳ Historial de Tickets"
        ])
        
        # 2. CAPTURA DEL PROCESAMIENTO (Ocurre al hacer clic en el botón)
        if boton_procesar:
            if not input_problema.strip():
                st.warning("Por favor, ingrese el detalle del incidente antes de procesar.")
            else:
                with st.spinner("Gemini analizando impacto y estructura técnica..."):
                    try:
                        # Ejecuta la consulta a la Inteligencia Artificial
                        resultado_dict = procesar_con_gemini(input_problema, st.session_state["empresa_actual"])
                        
                        # Guarda el registro en la base de datos de Render y obtiene el ID correlativo
                        ticket_id = guardar_ticket_db(st.session_state["usuario_actual"], st.session_state["empresa_actual"], resultado_dict)
                        
                        if ticket_id:
                            # Si la DB devolvió una tupla/lista, extraemos el primer elemento numérico
                            id_numerico = ticket_id[0] if isinstance(ticket_id, (tuple, list)) else ticket_id
                            
                            # Inyectamos el ID numérico real en la cabecera del JSON
                            resultado_dict = {"numero_ticket": id_numerico, **resultado_dict}
                            st.session_state["resultado"] = resultado_dict
                            st.toast(f"💾 Ticket #{id_numerico} guardado en el historial de forma exitosa.")
                        else:
                            st.session_state["resultado"] = resultado_dict
                            st.toast("⚠️ Ticket procesado pero no se pudo guardar en el historial.")
                            
                        # Forzamos a Streamlit a redibujar la pantalla para que las pestañas lean los datos nuevos
                        st.rerun()
                            
                    except Exception as e:
                        st.error(f"Error en procesamiento o guardado: {e}")
        
        # 3. RENDERIZADO DE LA PESTAÑA 1 (Último Análisis)
        with tab_actual:
            if "resultado" in st.session_state:
                res = st.session_state["resultado"]
                
                # Tarjetas métricas superiores
                c1, c2, c3 = st.columns(3)
                prioridad_emoji = "🚨" if "Alta" in res.get('prioridad', 'Normal') else "ℹ️"
                c1.metric(label="Número Ticket", value=f"#{res.get('numero_ticket', 'N/A')}")
                c2.metric(label="Módulo SAP", value=res.get('modulo_sugerido', 'N/A').upper())
                c3.metric(label=f"{prioridad_emoji} Prioridad", value=res.get('prioridad', 'Normal'))
                
                st.markdown(f"**📅 Fecha Registro:** {res.get('fecha')}")
                st.markdown(f"**📌 Asunto:** {res.get('asunto')}")
                
                # Alerta visual si Gemini detectó falta de contexto
                if res.get('informacion_adicional_requerida'):
                    st.error(f"⚠️ **Información Adicional Requerida:** {res.get('informacion_adicional_requerida')}")
                else:
                    st.success("✅ Datos completos: No se requiere información adicional.")
                    
                st.info(f"**📝 Detalle enviado:**\n\n{res.get('detalle')}")
            else:
                st.info("No se registran análisis en esta sesión. Cargue un incidente a la izquierda.")
                
        # 4. RENDERIZADO DE LA PESTAÑA 2 (JSON Puro)
        with tab_json:
            if "resultado" in st.session_state:
                st.markdown("Este objeto JSON está formateado de forma nativa para alimentar tus sistemas externos:")
                st.json(st.session_state["resultado"])
            else:
                st.info("El objeto JSON aparecerá aquí tras procesar el incidente.")
                
        # 5. RENDERIZADO DE LA PESTAÑA 3 (Historial desde Render)
        with tab_historial:
            st.markdown("A continuación se listan los incidentes históricos registrados por tu cuenta:")
            
            # Consultamos directamente a Render para traer los datos más frescos de este usuario
            tickets_guardados = obtener_historial_tickets_db(st.session_state["usuario_actual"])
            
            if not tickets_guardados:
                st.warning("Aún no has registrado ningún ticket en la base de datos.")
            else:
                for t_fecha, t_asunto, t_modulo, t_prioridad, t_detalle, t_info, t_id in tickets_guardados:
                    # Semáforo de color dinámico según la prioridad histórica
                    color_alerta = "🔴" if "Muy Alta" in t_prioridad else ("🟠" if "Alta" in t_prioridad else "🟢")
                    
                    with st.expander(f"{color_alerta} Ticket #{t_id} | {t_fecha} — {t_asunto}"):
                        st.markdown(f"**Módulo SAP:** `{t_modulo.upper()}` | **Prioridad:** `{t_prioridad}`")
                        st.markdown(f"**Detalle Histórico:** {t_detalle}")
                        if t_info:
                            st.markdown(f"❌ **Requerimiento pendiente:** *{t_info}*")
                        else:
                            st.markdown("✨ *Procesado con éxito completo sin datos faltantes.*")
