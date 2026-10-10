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
# 1. ESQUEMAS PYDANTIC PARA GEMINI
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

class SAPMaterialSchema(BaseModel):
    texto_breve_sap: str = Field(
        description="Descripción corta normalizada para SAP (máximo 40 caracteres, EN MAYÚSCULAS). Estructura estándar: SUSTANTIVO + CARACTERÍSTICA PRINCIPAL + MARCA/MODELO + MEDIDAS."
    )
    grupo_articulos: Literal["SELE-RODA", "SMEC-BULON", "SHID-VALV", "SELE-CAB", "SINDS-VARI"] = Field(
        description="Categoría taxonómica del material: SELE-RODA (Rodamientos), SMEC-BULON (Bulonería/Tornillos), SHID-VALV (Válvulas/Hidráulica), SELE-CAB (Cables/Electricidad), SINDS-VARI (Otros repuestos industriales)."
    )
    tipo_material: Literal["ERSA", "ROH", "HALB"] = Field(
        description="Tipo de material SAP: ERSA (Repuestos/Refacciones), ROH (Materia Prima), HALB (Semielaborado). Si es un componente industrial para mantenimiento, asignar ERSA."
    )
    unidad_medida_base: Literal["UN", "KG", "M", "L"] = Field(
        description="Unidad de medida base en formato SAP: UN (Unidad), KG (Kilogramo), M (Metro), L (Litro)."
    )
    categoria_valoracion: Literal["3000", "3001", "3040"] = Field(
        description="Categoría de valoración para integración MM-FI: '3000' para repuestos estándar/materias primas, '3040' para materiales de consumo o herramientas."
    )
    justificacion_tecnica: str = Field(
        description="Explicación concisa (máximo 15 palabras) de por qué se asignó ese Grupo de Artículos y Categoría de Valoración."
    )

# =====================================================================
# 2. FUNCIONES DE PROCESAMIENTO CON LA API DE GEMINI
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
    
    Texto del usuario: "{texto_usuario}"
    Cliente de control: {cliente_seleccionado}
    Fecha: {fecha_hoy}
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

def procesar_material_con_gemini(texto_usuario: str) -> dict:
    """Analiza la solicitud de alta del usuario y genera la estructura de Datos Maestros MM01."""
    try:
        API_KEY = st.secrets["GEMINI_API_KEY"]
    except Exception:
        API_KEY = "TU_API_KEY_REAL"
        
    client = genai.Client(api_key=API_KEY)
    
    prompt_sistema = f"""
    Actúas como un Consultor Senior de Datos Maestros SAP MM (MDM Architect).
    Tu tarea es procesar una solicitud de alta de material ingresada en lenguaje libre e informal, y transformarla en un registro maestro de materiales estructurado listo para SAP (BAPI_MATERIAL_SAVEDATA).
    
    Reglas de Negocio Estrictas:
    1. Texto Breve (MAKTX): Debe ser descriptivo, en MAYÚSCULAS y no superar NUNCA los 40 caracteres. Estructura: [PRODUCTO] [ESPECIFICACIÓN] [MARCA] [DIMENSIÓN]. Evita palabras como 'necesito', 'un', 'para la máquina'.
    2. Taxonomía: Clasifica correctamente el material dentro de los Grupos de Artículos (MATKL) permitidos.
    3. Integración FI (BKLAS): Asegura coherencia contable.
    
    Texto ingresado por el usuario de planta: "{texto_usuario}"
    """
    
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt_sistema,
        config={
            "response_mime_type": "application/json",
            "response_schema": SAPMaterialSchema,
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
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tickets_sap (usuario, empresa, fecha, asunto, modulo, prioridad, detalle, info_adicional)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (
            usuario, empresa, ticket_dict.get("fecha"), ticket_dict.get("asunto"),
            ticket_dict.get("modulo_sugerido"), ticket_dict.get("prioridad"),
            ticket_dict.get("detalle"), ticket_dict.get("informacion_adicional_requerida")
        ))
        nuevo_id_row = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        return nuevo_id_row[0] if nuevo_id_row else None
    except Exception as e:
        st.error(f"Error al guardar el ticket: {e}")
    return None

def obtener_historial_tickets_db(usuario):
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT fecha, asunto, modulo, prioridad, detalle, info_adicional, id 
            FROM tickets_sap 
            WHERE usuario = %s 
            ORDER BY id DESC;
        """, (usuario,))
        registros = cursor.fetchall()
        cursor.close()
        conn.close()
        return registros
    except Exception as e:
        st.error(f"Error al leer el historial: {e}")
    return []

# --- FUNCIONES ADICIONALES PARA MAESTRO DE MATERIALES (MM01/MM60) ---

def inicializar_maestro_materiales():
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS maestro_materiales_sap (
                matnr SERIAL PRIMARY KEY,
                maktx VARCHAR(40) NOT NULL,
                matkl VARCHAR(20) NOT NULL,
                mtart VARCHAR(4) NOT NULL,
                meins VARCHAR(3) NOT NULL,
                bklas VARCHAR(4) NOT NULL,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cursor.execute("ALTER TABLE maestro_materiales_sap ALTER COLUMN matkl TYPE VARCHAR(20);")
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
    try:
        inicializar_maestro_materiales()
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("SELECT matnr, maktx, matkl, mtart, meins, bklas, fecha_creacion FROM maestro_materiales_sap ORDER BY matnr DESC")
        registros = cursor.fetchall()
        cursor.close()
        conn.close()
        return registros
    except Exception as e:
        st.error(f"Error al recuperar el reporte MM60: {e}")
    return

def buscar_similares_maestro_db(texto_breve: str):
    """Busca coincidencias exactas o similitudes por primer palabra en la DB para auditar duplicados."""
    coincidencia_exacta = False
    materiales_similares = []
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        
        # 1. Validar si ya existe idéntico
        cursor.execute("SELECT matnr, maktx FROM maestro_materiales_sap WHERE maktx = %s", (texto_breve.strip(),))
        if cursor.fetchone():
            coincidencia_exacta = True
            
        # 2. Buscar similitud por palabra clave (primer palabra del sustantivo)
        primer_palabra = texto_breve.split(" ")[0] if " " in texto_breve else texto_breve
        cursor.execute("SELECT matnr, maktx, matkl FROM maestro_materiales_sap WHERE maktx LIKE %s LIMIT 4", (f"{primer_palabra}%",))
        materiales_similares = cursor.fetchall()
        
        cursor.close()
        conn.close()
    except Exception as e:
        st.error(f"Error en auditoría de duplicados: {e}")
    return coincidencia_exacta, materiales_similares

def guardar_material_db(material_dict):
    """Inserta el material normalizado por la IA dentro del maestro en Render."""
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO maestro_materiales_sap (maktx, matkl, mtart, meins, bklas)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING matnr;
        """, (
            material_dict.get("texto_breve_sap"),
            material_dict.get("grupo_articulos"),
            material_dict.get("tipo_material"),
            material_dict.get("unidad_medida_base"),
            material_dict.get("categoria_valoracion")
        ))
        nuevo_matnr = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        return nuevo_matnr[0] if nuevo_matnr else None
    except Exception as e:
        st.error(f"Error al impactar material en DB: {e}")
    return None

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
            for k in ["resultado", "analisis_temporal", "ticket_guardado_exitoso", "mat_temporal", "mat_guardado_exitoso"]:
                if k in st.session_state: del st.session_state[k]
            st.rerun()

    st.title("⚙️ SAP AI Suite — Prototipo MVP Cloud")
    st.divider()

    # =====================================================================
    # MÓDULO OPTION 1: MESA DE AYUDA INTELIGENTE
    # =====================================================================
    if modulo_seleccionado == "📋 Mesa de Ayuda Inteligente":
        if "analisis_temporal" not in st.session_state: st.session_state["analisis_temporal"] = None
        if "ticket_guardado_exitoso" not in st.session_state: st.session_state["ticket_guardado_exitoso"] = False

        col_izquierda, col_derecha = st.columns(2, gap="large")

        with col_izquierda:
            st.subheader("📥 Ingreso del Incidente")
            st.text_input("Cliente Autenticado", value=st.session_state["empresa_actual"], disabled=True)
            input_problema = st.text_area("Describa el problema que presenta en SAP:", height=180, placeholder="Escriba aquí...", disabled=st.session_state["ticket_guardado_exitoso"])
            
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                boton_analizar = st.button("🔍 Analizar Incidente", use_container_width=True, disabled=st.session_state["ticket_guardado_exitoso"])
            with c_btn2:
                if st.button("🆕 Nuevo Ticket", use_container_width=True):
                    st.session_state["analisis_temporal"] = None
                    st.session_state["ticket_guardado_exitoso"] = False
                    if "resultado" in st.session_state: del st.session_state["resultado"]
                    st.rerun()

            if boton_analizar and input_problema.strip():
                with st.spinner("Gemini analizando impacto..."):
                    try:
                        res = procesar_con_gemini(input_problema, st.session_state["empresa_actual"])
                        res["numero_ticket"] = "PENDIENTE"
                        st.session_state["analisis_temporal"] = res
                        st.session_state["ticket_guardado_exitoso"] = False
                    except Exception as e: st.error(f"Error: {e}")

            st.divider()
            if st.session_state["analisis_temporal"] and not st.session_state["ticket_guardado_exitoso"]:
                st.markdown("### 🛠️ ¿El análisis es correcto?")
                if st.button("✅ Confirmar y Registrar Ticket", use_container_width=True, type="primary"):
                    tid = guardar_ticket_db(st.session_state["usuario_actual"], st.session_state["empresa_actual"], st.session_state["analisis_temporal"])
                    if tid:
                        st.session_state["analisis_temporal"]["numero_ticket"] = tid[0] if isinstance(tid, (tuple, list)) else tid
                        st.session_state["ticket_guardado_exitoso"] = True
                        st.toast("💾 Ticket guardado.")
                        st.rerun()

        with col_derecha:
            tab_actual, tab_json, tab_historial = st.tabs(["📋 Último Análisis", "💻 JSON Estructurado", "⏳ Historial de Tickets"])
            datos_en_pantalla = st.session_state["analisis_temporal"]
            
            with tab_actual:
                if datos_en_pantalla:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Estado / Número", f"#{datos_en_pantalla.get('numero_ticket')}" if datos_en_pantalla.get('numero_ticket') != "PENDIENTE" else "PENDIENTE")
                    c2.metric("Módulo SAP", datos_en_pantalla.get('modulo_sugerido', '').upper())
                    c3.metric("Prioridad", datos_en_pantalla.get('prioridad'))
                    st.markdown(f"**📌 Asunto:** {datos_en_pantalla.get('asunto')}")
                    if datos_en_pantalla.get('informacion_adicional_requerida'): st.error(f"⚠️ {datos_en_pantalla.get('informacion_adicional_requerida')}")
                    else: st.success("✅ Datos completos.")
                else: st.info("No se registran análisis.")
            with tab_json:
                if datos_en_pantalla: st.json(datos_en_pantalla)
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
        if "mat_temporal" not in st.session_state: 
            st.session_state["mat_temporal"] = None
        if "mat_guardado_exitoso" not in st.session_state: 
            st.session_state["mat_guardado_exitoso"] = False

        st.subheader("📦 Hub de Gobernanza de Datos Maestros MM")
        col_m_izq, col_m_der = st.columns(2, gap="large")

        with col_m_izq:
            st.markdown("### 📥 Solicitud de Carga Cognitiva (Simulación MM01)")
            input_material_libre = st.text_area(
                "Describa informalmente el componente que necesita dar de alta:",
                height=110,
                placeholder="Ej: Necesito crear un rodamiento blindado skf para el motor de la cinta 1, mide 40mm...",
                disabled=st.session_state["mat_guardado_exitoso"]
            )

            c_mbtn1, c_mbtn2 = st.columns(2)
            with c_mbtn1:
                boton_validar_mat = st.button("🔍 Validar con IA (MM01)", use_container_width=True, disabled=st.session_state["mat_guardado_exitoso"])
            with c_mbtn2:
                if st.button("🆕 Limpiar y Nuevo Material", use_container_width=True):
                    st.session_state["mat_temporal"] = None
                    st.session_state["mat_guardado_exitoso"] = False
                    st.rerun()

            if boton_validar_mat and input_material_libre.strip():
                with st.spinner("Gemini normalizando taxonomía SAP..."):
                    try:
                        res_mat = procesar_material_con_gemini(input_material_libre)
                        exacto, similares = buscar_similares_maestro_db(res_mat["texto_breve_sap"])
                        res_mat["coincidencia_exacta"] = exacto
                        res_mat["similares"] = similares
                        st.session_state["mat_temporal"] = res_mat
                        st.session_state["mat_guardado_exitoso"] = False
                    except Exception as e: 
                        st.error(f"Error IA Materiales: {e}")

            if st.session_state["mat_temporal"] and not st.session_state["mat_guardado_exitoso"]:
                st.divider()
                st.markdown("### 🛠️ Panel de Control de Calidad de Datos")

                if st.session_state["mat_temporal"]["coincidencia_exacta"]:
                    st.error("🚨 BLOQUEADO: Este material ya existe de forma idéntica en el catálogo SAP (Evitamos Duplicación Basura).")
                else:
                    if st.session_state["mat_temporal"]["similares"]:
                        st.warning("⚠️ AUDITORÍA: Encontramos materiales similares en el catálogo. Verifica que no sea ninguno de ellos antes de confirmar.")

                    if st.button("💾 Confirmar y Registrar en Maestro SAP", use_container_width=True, type="primary"):
                        with st.spinner("Insertando en tabla maestro_materiales_sap..."):
                            nuevo_matnr = guardar_material_db(st.session_state["mat_temporal"])
                            if nuevo_matnr:
                                st.session_state["mat_guardado_exitoso"] = True
                                st.toast(f"✨ Material 00000000{nuevo_matnr}"[-8:] + " creado con éxito.")
                                st.rerun()

        with col_m_der:
            st.markdown("### 📊 Diagnóstico Taxonómico de la IA")
            tab_m_visual, tab_m_json = st.tabs(["📋 Vista SAP Extendida", "💻 JSON Estructurado BAPI"])

            mat_data = st.session_state["mat_temporal"]
            with tab_m_visual:
                if mat_data:
                    st.markdown(f"#### `{mat_data.get('texto_breve_sap')}`")
                    st.caption(f"💡 **Justificación Técnica:** *{mat_data.get('justificacion_tecnica')}*")
                    st.divider()

                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric("Grupo Art. (MATKL)", mat_data.get("grupo_articulos"))
                    mc2.metric("Tipo Mat. (MTART)", mat_data.get("tipo_material"))
                    mc3.metric("U.M. Base (MEINS)", mat_data.get("unidad_medida_base"))
                    st.metric("Categoría Valoración (BKLAS — Integración FI)", mat_data.get("categoria_valoracion"))

                    if mat_data.get("similares"):
                        st.markdown("**📋 Catálogo Existente Relacionado (Similitud Semántica):**")
                        for s_id, s_desc, s_kl in mat_data["similares"]:
                            st.markdown(f"- `Material #{s_id:08d}` | **{s_desc}** (Grupo: `{s_kl}`)")
                else:
                    st.info("El diagnóstico taxonómico aparecerá tras validar un texto libre.")

            with tab_m_json:
                if mat_data: 
                    st.json(mat_data)
                else: 
                    st.info("El objeto estructurado aparecerá aquí.")

        st.markdown("---")
        st.markdown("### 📊 Índice de Materiales Activos (Simulación MM60)")
        st.markdown("Listado en tiempo real directo desde la base de datos centralizada de Render:")

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
            st.dataframe(tabla_mm60, use_container_width=True, hide_index=True)
        else:
            st.warning("No se registran materiales.")




