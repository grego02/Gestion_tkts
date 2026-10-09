# -*- coding: utf-8 -*-
import psycopg2
import streamlit as st

def conectar_db():
    # Usamos las mismas credenciales que ya tenés guardadas de Render
    return psycopg2.connect(
        host=st.secrets["DB_HOST"],
        database=st.secrets["DB_NAME"],
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"],
        port=st.secrets["DB_PORT"]
    )

def inicializar_maestro_materiales():
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        
        # 1. Creamos la tabla simulando campos clave de MARA y MAKT
        st.write("Creando tabla maestro_materiales_sap en Render...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS maestro_materiales_sap (
                matnr SERIAL PRIMARY KEY,          -- Número de material (Autoincremental)
                maktx VARCHAR(40) NOT NULL,        -- Descripción corta de SAP (Máx 40 caracteres)
                matkl VARCHAR(9) NOT NULL,         -- Grupo de artículos (Sugerido por taxonomía)
                mtart VARCHAR(4) NOT NULL,         -- Tipo de material (ERSA, ROH, HALB, etc.)
                meins VARCHAR(3) NOT NULL,         -- Unidad de medida base (UN, KG, M, etc.)
                bklas VARCHAR(4) NOT NULL,         -- Categoría de valoración (Integración FI)
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 2. Verificamos si ya hay datos para no duplicar los de prueba
        cursor.execute("SELECT COUNT(*) FROM maestro_materiales_sap;")
        count = cursor.fetchone()[0]
        
        if count == 0:
            st.write("Poblando el maestro con materiales industriales de prueba...")
            
            # Insertamos datos típicos de repuestos mecánicos y eléctricos
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
            st.success(f"¡Maestro inicializado con éxito! Se cargaron {len(materiales_prueba)} materiales.")
        else:
            st.info(f"La tabla ya contiene {count} materiales. No se requería carga inicial.")
            
        cursor.close()
        conn.close()
        
    except Exception as e:
        st.error(f"Error al configurar el maestro de materiales: {e}")

# Ejecutor provisorio para Streamlit local si quisieras probarlo
if __name__ == "__main__":
    st.title("Instalador de Base de Datos SAP MM01")
    if st.button("Ejecutar Migración de Materiales en Render"):
        inicializar_maestro_materiales()
