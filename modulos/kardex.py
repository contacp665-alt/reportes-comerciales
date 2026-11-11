import streamlit as st
import pandas as pd

def render(ctx):
    df_ventas_final = ctx["df_final"]
    df_tc = ctx["df_tc"]
    df_maestro = ctx["df_maestro"]
    empresa = ctx["empresa"]
    moneda = ctx["moneda"]
    p_inicio = ctx["p_inicio"]
    p_fin = ctx["p_fin"]

    st.subheader("📦 Módulo de Kardex: Rentabilidad, Compras y Consumos")
    
    # Cargador exclusivo de este módulo (no ensucia app.py)
    uploaded_kardex = st.file_uploader("Sube el archivo Kardex (.xlsx) para activar este módulo:", type=["xlsx"], key="uploader_kardex")

    if not uploaded_kardex:
        st.info("👆 Sube tu libro `kardex.xlsx` aquí arriba para cruzar los costos con las ventas ya cargadas y calcular rentabilidad, compras y consumos.")
        return

    try:
        df_kardex = pd.read_excel(uploaded_kardex, dtype=str)
        st.success(f"✅ Archivo Kardex cargado correctamente ({len(df_kardex):,} registros).")
        
        # Vista previa de columnas para validar antes de programar las reglas de negocio
        with st.expander("🔍 Ver columnas detectadas en el Kardex"):
            st.write(list(df_kardex.columns))
            st.dataframe(df_kardex.head(5), use_container_width=True)

        # Subpestañas preparadas para los 3 reportes que solicitaste
        sub_rent, sub_comp, sub_cons = st.tabs([
            "💰 Rentabilidad (Ventas vs Costo)", 
            "🛒 Reporte de Compras", 
            "🏭 Reporte de Consumos"
        ])

        with sub_rent:
            st.info("Aquí cruzaremos `df_ventas_final` con los costos de salida del Kardex.")
        with sub_comp:
            st.info("Aquí filtraremos los movimientos de ingreso por compras del Kardex.")
        with sub_cons:
            st.info("Aquí filtraremos las salidas por consumo interno/producción del Kardex.")

    except Exception as e:
        st.error(f"❌ Error al leer el archivo Kardex: {e}")

