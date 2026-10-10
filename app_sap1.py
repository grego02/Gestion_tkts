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
# 1. ESQUEMA PYDANTIC PARA GEMINI (INCIDENTES)
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
        """)
        registros = cursor.fetchall()
        cursor.close()
        conn.close()
        return registros
    except Exception as e:
        st.error(f"Error al leer el historial: {e}")
    return []

# --- FUNCIONES ADICIONALES PARA MAESTRO DE MATERIALES (MM01/MM60) ---

def inicializar_maestro_materiales():
    """Crea la tabla e inyecta los repuestos de prueba si no existen en Render."""
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS maestro_materiales_sap (
                matnr SERIAL PRIMARY KEY,
                maktx VARCHAR(40) NOT NULL,
                matkl VARCHAR(9) NOT NULL,
                mtart VARCHAR(4) NOT NULL,
                meins VARCHAR(3) NOT NULL,
                bklas VARCHAR(4) NOT NULL,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM maestro_materiales_sap;")
        count = cursor.fetchone()
        
        if count and count[0] == 0:
            materiales_prueba = [
                ("RODAMIENTO RIGID BOLAS SKF 6204", "SELE-RODA", "ERSA", "UN", "3000"),
                ("RODAMIENTO RIGID BOLAS SKF 6308 BLIND", "SELE-RODA", "ERSA", "UN", "3000"),
                ("BULON ACERO HEXAGONAL 1/2 X 2 ZINC", "SMEC-BULON", "ROH", "UN", "3000"),
                ("VALVULA ESFERICA BRONCE 1 PASO TOTAL", "SHID-VALV", "ERSA", "UN", "3000"),
                ("CABLE SINTENAX SUBTERRANEO 4X6 MM2", "SELE-CAB", "ROH", "M", "3000"),
                ("CABLE UNIPOLAR FRAL 2.5 MM2 ROJO", "SELE-CAB", "ROH", "M", "3000"),
                ("RODAMIENTO RODILLOS OSCILANTES TIMKEN", "SELE-RODA", "ERSA", "UN", "3000")
            ]
            cursor.executemany("""
                INSERT INTO maestro_materiales_sap (maktx, matkl, mtart, meins, bklas)
                VALUES (%s, %s, %s, %s, %s);
            """, materiales_prueba)
            conn.commit()
            
        cursor.close()
        conn.close()
    except Exception as e:
        st.error(f"Error al inicializar maestro de materiales: {e}")

def obtener_listado_mm60_db():
    """Simula la MM60 trayendo todo el catálogo activo."""
    try:
        inicializar_maestro_materiales()
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT matnr, maktx, matkl, mtart, meins, bklas, fecha_creacion 
            FROM maestro_materiales_sap 
            ORDER BY matnr DESC
        """)
        registros = cursor.fetchall()
        cursor.close()
        conn.close()
        return registros
    except Exception as e:
        st.error(f"Error al recuperar el reporte MM60: {e}")
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

# --- PANTALLA 2: SUITE DE APLICACIONES SAP INTELIGENTES ---
else:
    # Barra Lateral de Navegación (Sidebar)
    with st.sidebar:
        st.markdown("### 🏢 Menú del Portal")
        st.markdown(f"**Usuario:** `{st.session_state['usuario_actual']}`\n**Empresa:** `{st.session_state['empresa_actual']}`")
        st.divider()
        
        modulo_seleccionado = st.selectbox(
            "Seleccione la aplicación SAP:",
            ["📋 Mesa de Ayuda Inteligente", "⚙️ Gestor de Materiales (MM01 / MM60)"]
        )
        
        st.markdown("<br><br>" * 3, unsafe_allow_html=True)
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state["autenticado"] = False
            if "resultado" in st.session_state:
                del st.session_state["resultado"]
            if "analisis_temporal" in st.session_state:
                del st.session_state["analisis_temporal"]
            st.rerun()

    # Encabezado Principal del Panel Central
    st.title("⚙️ SAP AI Suite — Prototipo MVP Cloud")
    st.divider()

    # =====================================================================
    # MODULO OPTION 1: MESA DE AYUDA INTELIGENTE
    # =====================================================================
    if modulo_seleccionado == "📋 Mesa de Ayuda Inteligente":
        if "analisis_temporal" not in st.session_state:
            st.session_state["analisis_temporal"] = None
        if "ticket_guardado_exitoso" not in st.session_state:
            st.session_state["ticket_guardado_exitoso"] = False

        col_izquierda, col_derecha = st.columns(2, gap="large")

        with col_izquierda:
            st.subheader("📥 Ingreso del Incidente")
            st.text_input("Cliente Autenticado", value=st.session_state["empresa_actual"], disabled=True)
            
            input_problema = st.text_area(
                "Describa el problema que presenta en SAP:",
                height=180,
                placeholder="Escriba aquí el error transaccional de forma libre...",
                disabled=st.session_state["ticket_guardado_exitoso"]
            )
            
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                boton_analizar = st.button(
                    "🔍 Analizar Incidente", 
                    use_container_width=True, 
                    disabled=st.session_state["ticket_guardado_exitoso"]
                )
            with c_btn2:
                if st.button("🆕 Nuevo Ticket", use_container_width=True):
                    st.session_state["analisis_temporal"] = None
                    st.session_state["ticket_guardado_exitoso"] = False
                    if "resultado" in st.session_state:
                        del st.session_state["resultado"]
                    st.rerun()

            if boton_analizar:
                if not input_problema.strip():
                    st.warning("Por favor, ingrese el detalle del incidente antes de procesar.")
                else:
                    with st.spinner("Gemini analizando impacto..."):
                        try:
                            resultado_ia = procesar_con_gemini(input_problema, st.session_state["empresa_actual"])
                            resultado_ia["numero_ticket"] = "PENDIENTE"
                            st.session_state["analisis_temporal"] = resultado_ia
                            st.session_state["ticket_guardado_exitoso"] = False
                        except Exception as e:
                            st.error(f"Error en el análisis cognitivo: {e}")

            st.divider()
            
            if st.session_state["analisis_temporal"] and not st.session_state["ticket_guardado_exitoso"]:
                st.markdown("### 🛠️ ¿El análisis es correcto?")
                st.markdown("Revisa el diagnóstico de la derecha. Si estás de acuerdo o ya corregiste los datos, confirma.")
                
                if st.button("✅ Confirmar y Registrar Ticket", use_container_width=True, type="primary"):
                    with st.spinner("Persistiendo registro en Render..."):
                        ticket_id = guardar_ticket_db(
                            st.session_state["usuario_actual"], 
                            st.session_state["empresa_actual"], 
                            st.session_state["analisis_temporal"]
                        )
                        if ticket_id:
                            st.session_state["analisis_temporal"]["numero_ticket"] = ticket_id
                            st.session_state["resultado"] = st.session_state["analisis_temporal"]
                            st.session_state["ticket_guardado_exitoso"] = True
                            st.toast(f"💾 Ticket #{ticket_id} guardado con éxito.")
                            st.rerun()
                        else:
                            st.error("No se pudo guardar el registro en Render.")

        with col_derecha:
            tab_actual, tab_json, tab_historial = st.tabs([
                "📋 Último Análisis", 
                "💻 JSON Estructurado", 
                "⏳ Historial de Tickets"
            ])
            
            datos_en_pantalla = st.session_state["analisis_temporal"]
            
            with tab_actual:
                if datos_en_pantaran := datos_en_pantalla:
                    c1, c2, c3 = st.columns(3)
                    prioridad_emoji = "🚨" if "Alta" in datos_en_pantalla.get('prioridad', 'Normal') else "ℹ️"
                    num_tkt = datos_en_pantalla.get('numero_ticket')
                    value_tkt = f"#{num_tkt}" if num_tkt != "PENDIENTE" else "PENDIENTE"
                    
                    c1.metric(label="Estado / Número", value=value_tkt)
                    c2.metric(label="Módulo SAP", value=datos_en_pantalla.get('modulo_sugerido', 'N/A').upper())
                    c3.metric(label=f"{prioridad_emoji} Prioridad", value=datos_en_pantalla.get('prioridad', 'Normal'))
                    
                    st.markdown(f"**📅 Fecha Registro:** {datos_en_pantalla.get('fecha')}")
                    st.markdown(f"**📌 Asunto:** {datos_en_pantalla.get('asunto')}")
                    
                    if datos_en_pantalla.get('informacion_adicional_requerida'):
                        st.error(f"⚠️ **Información Adicional Requerida:** {datos_en_pantalla.get('informacion_adicional_requerida')}")
                    else:
                        st.success("✅ Datos completos: No se requiere información adicional.")
                    st.info(f"**📝 Detalle enviado:**\n\n{datos_en_pantalla.get('detalle')}")
                else:
                    st.info("No se registran análisis en esta sesión. Cargue un incidente a la izquierda.")
                    
            with tab_json:
                if datos_en_pantalla:
                    st.json(datos_en_pantalla)
                else:
                    st.info("El objeto JSON aparecerá aquí.")
                    
            with tab_historial:
                st.markdown("Incidentes históricos registrados por tu cuenta:")
                tickets_guardados = obtener_historial_tickets_db(st.session_state["usuario_actual"])
                
                if tickets_guardados:
                    for t_fecha, t_asunto, t_modulo, t_prioridad, t_detalle, t_info, t_id in tickets_guardados:
                        color_alerta = "🔴" if "Muy Alta" in t_prioridad else ("🟠" if "Alta" in t_prioridad else "🟢")
                        with st.expander(f"{color_alerta} Ticket #{t_id} | {t_fecha} — {t_asunto}"):
                            st.markdown(f"**Módulo SAP:** `{t_modulo.upper()}` | **Prioridad:** `{t_prioridad}`")
                            st.markdown(f"**Detalle Histórico:** {t_detalle}")
                            if t_info:
                                st.markdown(f"❌ **Requerimiento:** *{t_info}*")
                else:
                    st.warning("Aún no has registrado ningún ticket.")

    # =====================================================================
    # MODULO OPTION 2: GESTOR DE MATERIALES (MM01 / MM60)
    # =====================================================================
    else:
        st.subheader("📦 Hub de Gobernanza de Datos Maestros MM")
        st.markdown("Este entorno simula el ciclo de alta guiado por IA y la auditoría del catálogo central de materiales.")
        
        st.markdown("---")
        st.markdown("### 📥 Solicitud de Carga Cognitiva (Simulación MM01)")
        st.info("Próximamente: Aquí integraremos el prompt de ingeniería con Gemini y RAG para clasificar tus materiales sin errores.")
        
        input_material_libre = st.text_input("Describa el material que desea crear (Ej: Bulón de acero de media pulgada):")
        st.button("🔍 Validar y Precalificar Material", disabled=True)
        
        st.markdown("---")
        st.markdown("### 📊 Índice de Materiales Activos (Simulación MM60)")
        st.markdown("Listado en tiempo real directo desde la base de datos centralizada de Render:")
        
        # Traemos las filas frescas de la base de datos
        materiales_totales = obtener_listado_mm60_db()
        
        if materiales_totales:
            tabla_mm60 = []
            for matnr, maktx, matkl, mtart, meins, bklas, fecha in materiales_totales:
                tabla_mm60.append({
                    "Nº Material (MATNR)": f"00000000{matnr}"[-8:],
                    "Texto Breve (MAKTX)": maktx,
                    "Grupo Art. (MATKL)": matkl,
                    "Tipo Mat. (MTART)": mtart,
                    "UM Base (MEINS)": meins,
                    "Cat. Valoración (BKLAS)": bklas,
                    "Fecha Alta": fecha.strftime("%d/%m/%Y %H:%M") if hasattr(fecha, 'strftime') else str(fecha)
                })
            
            # Renderizamos la tabla interactiva de SAP MM60
            st.dataframe(
                tabla_mm60,
                use_container_width=True,
                hide_index=True
            )
        else:
            st.warning("No se registran materiales cargados en el maestro actualmente.")


