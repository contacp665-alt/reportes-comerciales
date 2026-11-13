import streamlit as st
import pandas as pd
import numpy as np
import importlib
from modulos import ventas_categorias, rankings, kardex, resumen_anual

importlib.reload(ventas_categorias)
importlib.reload(rankings)
importlib.reload(kardex)
importlib.reload(resumen_anual)


st.set_page_config(page_title="Sistema de Reportes Contables", page_icon="📊", layout="wide")

st.title("⚙️ PANEL INTERACTIVO DE CONTROL DE GESTIÓN")
st.markdown("---")

MODULOS_ACTIVOS = {
    "📊 Ventas por Categorías": ventas_categorias.render,
    "🏆 Top Productos y Clientes": rankings.render,
    "📦 Kardex y Rentabilidad": kardex.render,
    "📈 Resumen Anual Mensual": resumen_anual.render,
}

# Función con caché para lectura ultrarrápida (.parquet o .xlsx)
@st.cache_data(show_spinner="Cargando archivo en memoria...")
def leer_archivo(archivo):
    if archivo.name.endswith('.parquet'):
        return pd.read_parquet(archivo)
    return pd.read_excel(archivo, dtype=str)

# 1. ZONA DE CARGA DE ARCHIVOS BASE (Acepta .parquet y .xlsx)
st.sidebar.header("📂 1. ARCHIVOS BASE")
uploaded_ventas = st.sidebar.file_uploader("Ventas Histórico (.parquet / .xlsx)", type=["parquet", "xlsx"])
uploaded_tc = st.sidebar.file_uploader("Tipo de Cambio (.xlsx / .parquet)", type=["xlsx", "parquet"])
uploaded_maestro = st.sidebar.file_uploader("Maestro de Ítems (.xlsx / .parquet)", type=["xlsx", "parquet"])

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

# 3. PROCESAMIENTO CENTRAL
if uploaded_ventas and uploaded_tc and uploaded_maestro:
    try:
        df_ventas = leer_archivo(uploaded_ventas)
        df_tc = leer_archivo(uploaded_tc)
        df_maestro = leer_archivo(uploaded_maestro)

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
            
            # Conversión multimoneda ultrarrápida con NumPy
            cond_ex_sol = (moneda == 'SOLES') & (df_final['MonedaDocumento'] == 'EX')
            cond_lo_dol = (moneda == 'DÓLARES') & (df_final['MonedaDocumento'] == 'LO')
            df_final['Monto_Convertido'] = np.where(
                cond_ex_sol,
                df_final['Monto'] * df_final['Oficial Venta'],
                np.where(cond_lo_dol, df_final['Monto'] / df_final['Oficial Venta'], df_final['Monto'])
            )

            contexto = {
                "df_final": df_final,
                "df_ventas": df_ventas,  # <--- LÍNEA CLAVE PARA EL CRUCE DESFASADO DE KARDEX
                "df_tc": df_tc,
                "df_maestro": df_maestro,
                "empresa": empresa,
                "moneda": moneda,
                "p_inicio": p_inicio,
                "p_fin": p_fin
            }

            pestanas = st.tabs(list(MODULOS_ACTIVOS.keys()))
            for pestana, funcion_render in zip(pestanas, MODULOS_ACTIVOS.values()):
                with pestana:
                    funcion_render(contexto)

    except Exception as e:
        st.error(f"❌ Ocurrió un inconveniente al procesar las estructuras: {e}")
else:
    st.info("👋 Bienvenido. Sube los tres archivos base en la barra lateral izquierda para activar el sistema.")

