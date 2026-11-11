import streamlit as st
import pandas as pd
import io

# Configuración estética de la página web
st.set_page_config(page_title="Sistema de Reportes Gerenciales", page_icon="📊", layout="wide")

st.title("⚙️ SISTEMA INTEGRADO DE REPORTES Y TABLAS DINÁMICAS")
st.markdown("---")

# 1. ZONA DE CARGA DE ARCHIVOS (Barra Lateral)
st.sidebar.header("📂 CARGA DE ARCHIVOS EXCEL")
uploaded_ventas = st.sidebar.file_uploader("1. Ventas Histórico (.xlsx)", type=["xlsx"])
uploaded_tc = st.sidebar.file_uploader("2. Tipo de Cambio (.xlsx)", type=["xlsx"])
uploaded_maestro = st.sidebar.file_uploader("3. Maestro de Ítems (.xlsx)", type=["xlsx"])

# 2. SELECCIÓN DE FILTROS GENERALES
st.sidebar.header("🎛️ FILTROS GENERALES")

# Configuración limpia de empresas
opciones_empresa = {
    "TS (02000000)": "02000000",
    "IS (03000000)": "03000000",
    "RS (01000000)": "01000000"
}
empresa_seleccionada = st.sidebar.selectbox("Empresa:", list(opciones_empresa.keys()))
empresa_codigo = opciones_empresa[empresa_seleccionada]

moneda = st.sidebar.selectbox("Moneda de Expresión:", ["SOLES", "DÓLARES"])

p_inicio = st.sidebar.text_input("Periodo Inicio (AAAAMM):", value="202601")
p_fin = st.sidebar.text_input("Periodo Fin (AAAAMM):", value="202601")

# Selector dinámico de rankings (¡SINTAXIS BLINDADA CORREGIDA!)
st.sidebar.markdown("---")
st.sidebar.header("🔝 AJUSTES DE RANKINGS")
opciones_top = (10, 25, 50)
top_n = st.sidebar.selectbox("Mostrar en rankings:", opciones_top, index=0)

# Parámetros del Reporte Comercial por Niveles
st.sidebar.subheader("Estructura - Matriz Dinámica:")
n1 = st.sidebar.checkbox("Nivel 1: Categoría", value=True)
n2 = st.sidebar.checkbox("Nivel 2: Marca", value=False)
n3 = st.sidebar.checkbox("Nivel 3: Ítems", value=False)
# 3. LÓGICA DE PROCESAMIENTO CENTRALIZADA
if uploaded_ventas and uploaded_tc and uploaded_maestro:
    try:
        # Carga rápida en memoria del servidor
        df_ventas = pd.read_excel(uploaded_ventas, dtype=str)
        df_tc = pd.read_excel(uploaded_tc, dtype=str)
        df_maestro = pd.read_excel(uploaded_maestro, dtype=str)

        # Normalización y Limpieza Contable
        df_ventas['VoucherPeriodo'] = df_ventas['VoucherPeriodo'].astype(str).str.strip()
        df_ventas['CompaniaSocio'] = df_ventas['CompaniaSocio'].astype(str).str.strip()
        df_ventas['ItemCodigo'] = df_ventas['ItemCodigo'].astype(str).str.strip()
        df_ventas['ClienteNombre'] = df_ventas['ClienteNombre'].fillna("CLIENTE INDETERMINADO").astype(str).str.strip()
        df_ventas['ClienteRUC'] = df_ventas['ClienteRUC'].fillna("-").astype(str).str.strip()
        df_maestro['Item'] = df_maestro['Item'].astype(str).str.strip()

        # Extracción segura de fechas (Formato Nativo AAAA-MM-DD)
        df_ventas['Fecha_Clave_Busqueda'] = df_ventas['FechaDocumento'].astype(str).str.slice(0, 10).str.strip()
        df_tc['Fecha_Clave_Busqueda'] = df_tc['Fecha'].astype(str).str.slice(0, 10).str.strip()
        df_tc['Oficial Venta'] = pd.to_numeric(df_tc['Oficial Venta'], errors='coerce')

        # Filtrado de Ventas Base por Empresa (Código completo) y Rango de Periodos
        df_filtrado = df_ventas[
            (df_ventas['CompaniaSocio'] == str(empresa_codigo)) & 
            (df_ventas['VoucherPeriodo'] >= str(p_inicio)) & 
            (df_ventas['VoucherPeriodo'] <= str(p_fin))
        ].copy()

        if df_filtrado.empty:
            st.warning(f"⚠️ No se encontraron transacciones para la empresa {empresa_codigo} en el rango {p_inicio} - {p_fin}.")
        else:
            # Enlaces Relacionales Básicos
            df_cruces = pd.merge(df_filtrado, df_tc[['Fecha_Clave_Busqueda', 'Oficial Venta']], on='Fecha_Clave_Busqueda', how='left')
            df_cruces['Oficial Venta'] = df_cruces['Oficial Venta'].ffill()

            df_final = pd.merge(df_cruces, df_maestro[['Item', 'Tipo_Categoria', 'Marca_Descripcion']], left_on='ItemCodigo', right_on='Item', how='left')
            df_final['Tipo_Categoria'] = df_final['Tipo_Categoria'].fillna('SIN CATEGORÍA').str.strip()
            df_final['Marca_Descripcion'] = df_final['Marca_Descripcion'].fillna('SIN MARCA').str.strip()

            # Operaciones Numéricas y Conversión Multimoneda Homologada
            df_final['Monto'] = pd.to_numeric(df_final['Monto'], errors='coerce').fillna(0)
            df_final['CantidadPedida'] = pd.to_numeric(df_final['CantidadPedida'], errors='coerce').fillna(0)
            
            df_final['Monto_Convertido'] = df_final.apply(
                lambda f: f['Monto'] * f['Oficial Venta'] if (moneda == 'SOLES' and f['MonedaDocumento'] == 'EX')
                else (f['Monto'] / f['Oficial Venta'] if (moneda == 'DÓLARES' and f['MonedaDocumento'] == 'LO') else f['Monto']),
                axis=1
            )

            simb = "S/" if moneda == 'SOLES' else "$"

            # --- PRESENTACIÓN EN PESTAÑAS WEB ---
            tab_matriz, tab_clientes, tab_productos = st.tabs([
                "📊 Matriz Dinámica por Niveles", 
                "🏆 Ranking Top Clientes", 
                "📦 Ranking Top Productos"
            ])

            # PESTAÑA 1: MATRIZ DINÁMICA
            with tab_matriz:
                columnas_agrupacion = []
                if n1: columnas_agrupacion.append('Tipo_Categoria')
                if n2: columnas_agrupacion.append('Marca_Descripcion')
                if n3: 
                    columnas_agrupacion.append('ItemCodigo')
                    if 'Descripcion' in df_final.columns: columnas_agrupacion.append('Descripcion')

                if not columnas_agrupacion:
                    st.info("💡 Por favor, activa al menos un nivel de estructura en la barra lateral para ver la Matriz.")
                    reporte_matriz_excel = pd.DataFrame()
                else:
                    rep_matriz = df_final.groupby(columnas_agrupacion).agg({
                        'CantidadPedida': 'sum',
                        'Monto_Convertido': 'sum'
                    }).reset_index()
                    rep_matriz = rep_matriz.sort_values(by='Monto_Convertido', ascending=False).reset_index(drop=True)

                    tot_cant_m = rep_matriz['CantidadPedida'].sum()
                    tot_vent_m = rep_matriz['Monto_Convertido'].sum()

                    v_matriz = rep_matriz.copy()
                    v_matriz['CantidadPedida'] = v_matriz['CantidadPedida'].map('{:,.0f}'.format)
                    v_matriz['Monto_Convertido'] = v_matriz['Monto_Convertido'].map(lambda x: f"{simb} {x:,.2f}")

                    fila_tot_m = {col: "" for col in columnas_agrupacion}
                    fila_tot_m[columnas_agrupacion] = "TOTAL GENERAL"
                    fila_tot_m['CantidadPedida'] = f"{tot_cant_m:,.0f}"
                    fila_tot_m['Monto_Convertido'] = f"{simb} {tot_vent_m:,.2f}"

                    st.subheader(f"📈 Matriz de Ventas por Segmentos ({moneda})")
                    st.dataframe(v_matriz, use_container_width=True)
                    st.dataframe(pd.DataFrame([fila_tot_m]), use_container_width=True)

                    f_tot_m_excel = {col: "" for col in columnas_agrupacion}
                    f_tot_m_excel[columnas_agrupacion] = "TOTAL GENERAL"
                    f_tot_m_excel['CantidadPedida'] = tot_cant_m
                    f_tot_m_excel['Monto_Convertido'] = tot_vent_m
                    reporte_matriz_excel = pd.concat([rep_matriz, pd.DataFrame([f_tot_m_excel])], ignore_index=True)

            # PESTAÑA 2: TOP CLIENTES
            with tab_clientes:
                rep_clientes = df_final.groupby(['ClienteRUC', 'ClienteNombre']).agg({
                    'Monto_Convertido': 'sum'
                }).reset_index()
                rep_clientes = rep_clientes.sort_values(by='Monto_Convertido', ascending=False).reset_index(drop=True)
                
                top_clientes_vista = rep_clientes.head(top_n).copy()
                top_clientes_vista.index = top_clientes_vista.index + 1
                top_clientes_vista['Monto_Convertido'] = top_clientes_vista['Monto_Convertido'].map(lambda x: f"{simb} {x:,.2f}")

                st.subheader(f"🏆 Top {top_n} Clientes con Mayor Facturación ({moneda})")
                st.dataframe(top_clientes_vista, use_container_width=True)
                
                reporte_clientes_excel = rep_clientes.copy()

            # PESTAÑA 3: TOP PRODUCTOS
            with tab_productos:
                columnas_prod = ['ItemCodigo']
                if 'Descripcion' in df_final.columns: columnas_prod.append('Descripcion')
                
                rep_productos = df_final.groupby(columnas_prod).agg({
                    'CantidadPedida': 'sum',
                    'Monto_Convertido': 'sum'
                }).reset_index()
                rep_productos = rep_productos.sort_values(by='CantidadPedida', ascending=False).reset_index(drop=True)

                top_productos_vista = rep_productos.head(top_n).copy()
                top_productos_vista.index = top_productos_vista.index + 1
                top_productos_vista['CantidadPedida'] = top_productos_vista['CantidadPedida'].map('{:,.0f}'.format)
                top_productos_vista['Monto_Convertido'] = top_productos_vista['Monto_Convertido'].map(lambda x: f"{simb} {x:,.2f}")

                st.subheader(f"📦 Top {top_n} Productos Más Vendidos por Volumen Físico")
                st.dataframe(top_productos_vista, use_container_width=True)
                
                reporte_productos_excel = rep_productos.copy()

            # --- EXPORTACIÓN UNIFICADA MULTI-PESTAÑA (DESCARGA WEB) ---
            st.markdown("---")
            st.subheader("💾 DESCARGA DE REPORTES PARA GERENCIA")
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                if not reporte_matriz_excel.empty:
                    reporte_matriz_excel.to_excel(writer, sheet_name='1. Matriz Ventas', index=False)
                reporte_clientes_excel.to_excel(writer, sheet_name='2. Ranking Clientes', index=False)
                reporte_productos_excel.to_excel(writer, sheet_name='3. Ranking Productos', index=False)
            
            st.download_button(
                label="📥 Descargar Libro Completo de Excel (3 Pestañas)",
                data=buffer.getvalue(),
                file_name=f"Reporte_Gerencial_{empresa_codigo}_{p_inicio}_{moneda}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    except Exception as e:
        st.error(f"❌ Ocurrió un inconveniente al computar las bases: {e}")
else:
    st.info("👋 Bienvenido. Por favor, carga los tres archivos Excel solicitados en la barra lateral izquierda para activar el procesamiento del sistema.")



