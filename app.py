import streamlit as st
import pandas as pd
from modulos import ventas_categorias, rankings, kardex

# Configuración estética de la página web
st.set_page_config(page_title="Sistema de Reportes Contables", page_icon="📊", layout="wide")

st.title("⚙️ PANEL INTERACTIVO DE CONTROL DE GESTIÓN")
st.markdown("---")

# ==============================================================================
# REGISTRO DE MÓDULOS (Aquí solo agregas una línea cuando crees un nuevo reporte)
# ==============================================================================
MODULOS_ACTIVOS = {
    "📊 Ventas por Categorías": ventas_categorias.render,
    "🏆 Top Productos y Clientes": rankings.render,
    "📦 Kardex y Rentabilidad": kardex.render,
}

# 1. ZONA DE CARGA DE ARCHIVOS BASE (Barra Lateral)
st.sidebar.header("📂 1. ARCHIVOS BASE")
uploaded_ventas = st.sidebar.file_uploader("Ventas Histórico (.xlsx)", type=["xlsx"])
uploaded_tc = st.sidebar.file_uploader("Tipo de Cambio (.xlsx)", type=["xlsx"])
uploaded_maestro = st.sidebar.file_uploader("Maestro de Ítems (.xlsx)", type=["xlsx"])

# 2. SELECCIÓN DE FILTROS GLOBALES
st.sidebar.header("🎛️ 2. FILTROS GLOBALES")
empresa = st.sidebar.selectbox(
    "Empresa:", 
    [("TS (02000000)", "02000000"), ("IS (03000000)", "03000000"), ("RS (01000000)", "01000000")], 
    format_func=lambda x: x[0]
)[1]
moneda = st.sidebar.selectbox("Moneda de Expresión:", ["SOLES", "DÓLARES"])
p_inicio = st.sidebar.text_input("Periodo Inicio (AAAAMM):", value="202601")
p_fin = st.sidebar.text_input("Periodo Fin (AAAAMM):", value="202601")

# 3. PROCESAMIENTO CENTRAL Y RENDERIZADO AUTOMÁTICO DE PESTAÑAS
if uploaded_ventas and uploaded_tc and uploaded_maestro:
    try:
        df_ventas = pd.read_excel(uploaded_ventas, dtype=str)
        df_tc = pd.read_excel(uploaded_tc, dtype=str)
        df_maestro = pd.read_excel(uploaded_maestro, dtype=str)

        # Limpieza y normalización
        df_ventas['VoucherPeriodo'] = df_ventas['VoucherPeriodo'].astype(str).str.strip()
        df_ventas['ItemCodigo'] = df_ventas['ItemCodigo'].astype(str).str.strip()
        df_maestro['Item'] = df_maestro['Item'].astype(str).str.strip()

        df_ventas['Fecha_Clave_Busqueda'] = df_ventas['FechaDocumento'].astype(str).str.slice(0, 10).str.strip()
        df_tc['Fecha_Clave_Busqueda'] = df_tc['Fecha'].astype(str).str.slice(0, 10).str.strip()
        df_tc['Oficial Venta'] = pd.to_numeric(df_tc['Oficial Venta'], errors='coerce')

        df_filtrado = df_ventas[
            (df_ventas['CompaniaSocio'] == empresa) & 
            (df_ventas['VoucherPeriodo'] >= str(p_inicio)) & 
            (df_ventas['VoucherPeriodo'] <= str(p_fin))
        ].copy()

        if df_filtrado.empty:
            st.warning(f"⚠️ No se encontraron transacciones para la empresa en el rango {p_inicio} - {p_fin}.")
        else:
            df_cruces = pd.merge(df_filtrado, df_tc[['Fecha_Clave_Busqueda', 'Oficial Venta']], on='Fecha_Clave_Busqueda', how='left')
            df_cruces['Oficial Venta'] = df_cruces['Oficial Venta'].ffill()

            df_final = pd.merge(df_cruces, df_maestro[['Item', 'Tipo_Categoria', 'Marca_Descripcion']], left_on='ItemCodigo', right_on='Item', how='left')
            df_final['Tipo_Categoria'] = df_final['Tipo_Categoria'].fillna('SIN CATEGORÍA').str.strip()
            df_final['Marca_Descripcion'] = df_final['Marca_Descripcion'].fillna('SIN MARCA').str.strip()

            df_final['Monto'] = pd.to_numeric(df_final['Monto'], errors='coerce').fillna(0)
            df_final['CantidadPedida'] = pd.to_numeric(df_final['CantidadPedida'], errors='coerce').fillna(0)
            
            df_final['Monto_Convertido'] = df_final.apply(
                lambda f: f['Monto'] * f['Oficial Venta'] if (moneda == 'SOLES' and f['MonedaDocumento'] == 'EX')
                else (f['Monto'] / f['Oficial Venta'] if (moneda == 'DÓLARES' and f['MonedaDocumento'] == 'LO') else f['Monto']),
                axis=1
            )

            # Contexto empaquetado que reciben todos los módulos
            contexto = {
                "df_final": df_final,
                "df_tc": df_tc,
                "df_maestro": df_maestro,
                "empresa": empresa,
                "moneda": moneda,
                "p_inicio": p_inicio,
                "p_fin": p_fin
            }

            # Creación automática de pestañas
            pestanas = st.tabs(list(MODULOS_ACTIVOS.keys()))
            for pestana, funcion_render in zip(pestanas, MODULOS_ACTIVOS.values()):
                with pestana:
                    funcion_render(contexto)

    except Exception as e:
        st.error(f"❌ Ocurrió un inconveniente al procesar las estructuras: {e}")
else:
    st.info("👋 Bienvenido. Sube los tres archivos Excel base en la barra lateral izquierda para activar el sistema.")
