import streamlit as st
import pandas as pd
import io

# Configuración estética de la página web
st.set_page_config(page_title="Sistema de Reportes Contables", page_icon="📊", layout="wide")

st.title("⚙️ PANEL INTERACTIVO DE CONTROL DE VENTAS")
st.markdown("---")

# 1. ZONA DE CARGA DE ARCHIVOS (Barra Lateral)
st.sidebar.header("📂 SUBE TUS ARCHIVOS EXCEL")
uploaded_ventas = st.sidebar.file_uploader("1. Ventas Histórico (.xlsx)", type=["xlsx"])
uploaded_tc = st.sidebar.file_uploader("2. Tipo de Cambio (.xlsx)", type=["xlsx"])
uploaded_maestro = st.sidebar.file_uploader("3. Maestro de Ítems (.xlsx)", type=["xlsx"])

# 2. SELECCIÓN DE FILTROS Y PARÁMETROS
st.sidebar.header("🎛️ FILTROS DEL REPORTE")
empresa = st.sidebar.selectbox("Empresa:", [("TS (02000000)", "02000000"), ("IS (03000000)", "03000000"), ("RS (01000000)", "01000000")], format_func=lambda x: x[0])[1]
moneda = st.sidebar.selectbox("Moneda de Expresión:", ["SOLES", "DÓLARES"])

# Menú dinámico modular para futuros reportes
tipo_reporte = st.sidebar.selectbox("Seleccione el Tipo de Reporte:", ["Reporte Comercial por Categorías", "Reporte de Auditoría de Tasas (Próximamente)"])

p_inicio = st.sidebar.text_input("Periodo Inicio (AAAAMM):", value="202601")
p_fin = st.sidebar.text_input("Periodo Fin (AAAAMM):", value="202601")

st.sidebar.subheader("Estructura de la Tabla:")
n1 = st.sidebar.checkbox("Nivel 1: Categoría", value=True)
n2 = st.sidebar.checkbox("Nivel 2: Marca", value=False)
n3 = st.sidebar.checkbox("Nivel 3: Ítems", value=False)

# 3. LÓGICA DE PROCESAMIENTO
if uploaded_ventas and uploaded_tc and uploaded_maestro:
    try:
        # Carga rápida en memoria del servidor
        df_ventas = pd.read_excel(uploaded_ventas, dtype=str)
        df_tc = pd.read_excel(uploaded_tc, dtype=str)
        df_maestro = pd.read_excel(uploaded_maestro, dtype=str)

        # Normalización y Limpieza Contable
        df_ventas['VoucherPeriodo'] = df_ventas['VoucherPeriodo'].astype(str).str.strip()
        df_ventas['ItemCodigo'] = df_ventas['ItemCodigo'].astype(str).str.strip()
        df_maestro['Item'] = df_maestro['Item'].astype(str).str.strip()

        # Extracción segura de fechas (Formato Nativo AAAA-MM-DD)
        df_ventas['Fecha_Clave_Busqueda'] = df_ventas['FechaDocumento'].astype(str).str.slice(0, 10).str.strip()
        df_tc['Fecha_Clave_Busqueda'] = df_tc['Fecha'].astype(str).str.slice(0, 10).str.strip()
        df_tc['Oficial Venta'] = pd.to_numeric(df_tc['Oficial Venta'], errors='coerce')

        # Filtrado de Ventas
        df_filtrado = df_ventas[
            (df_ventas['CompaniaSocio'] == empresa) & 
            (df_ventas['VoucherPeriodo'] >= str(p_inicio)) & 
            (df_ventas['VoucherPeriodo'] <= str(p_fin))
        ].copy()

        if df_filtrado.empty:
            st.warning(f"⚠️ No se encontraron transacciones para la empresa seleccionada en el rango {p_inicio} - {p_fin}.")
        else:
            # Enlaces Relacionales (Mergings)
            df_cruces = pd.merge(df_filtrado, df_tc[['Fecha_Clave_Busqueda', 'Oficial Venta']], on='Fecha_Clave_Busqueda', how='left')
            df_cruces['Oficial Venta'] = df_cruces['Oficial Venta'].ffill()

            df_final = pd.merge(df_cruces, df_maestro[['Item', 'Tipo_Categoria', 'Marca_Descripcion']], left_on='ItemCodigo', right_on='Item', how='left')
            df_final['Tipo_Categoria'] = df_final['Tipo_Categoria'].fillna('SIN CATEGORÍA').str.strip()
            df_final['Marca_Descripcion'] = df_final['Marca_Descripcion'].fillna('SIN MARCA').str.strip()

            # Operaciones Numéricas y Conversión Multimoneda
            df_final['Monto'] = pd.to_numeric(df_final['Monto'], errors='coerce').fillna(0)
            df_final['CantidadPedida'] = pd.to_numeric(df_final['CantidadPedida'], errors='coerce').fillna(0)
            
            df_final['Monto_Convertido'] = df_final.apply(
                lambda f: f['Monto'] * f['Oficial Venta'] if (moneda == 'SOLES' and f['MonedaDocumento'] == 'EX')
                else (f['Monto'] / f['Oficial Venta'] if (moneda == 'DÓLARES' and f['MonedaDocumento'] == 'LO') else f['Monto']),
                axis=1
            )

            # Construcción de la Tabla Dinámica según niveles activos
            columnas_agrupacion = []
            if n1: columnas_agrupacion.append('Tipo_Categoria')
            if n2: columnas_agrupacion.append('Marca_Descripcion')
            if n3: 
                columnas_agrupacion.append('ItemCodigo')
                if 'Descripcion' in df_final.columns: columnas_agrupacion.append('Descripcion')

            if not columnas_agrupacion:
                st.info("💡 Por favor, activa al menos un nivel de estructura en la barra lateral.")
            else:
                # Agrupación y Cálculos
                reporte_dinamico = df_final.groupby(columnas_agrupacion).agg({
                    'CantidadPedida': 'sum',
                    'Monto_Convertido': 'sum'
                }).reset_index()

                reporte_dinamico = reporte_dinamico.sort_values(by='Monto_Convertido', ascending=False).reset_index(drop=True)

                total_cantidades = reporte_dinamico['CantidadPedida'].sum()
                total_ventas = reporte_dinamico['Monto_Convertido'].sum()

                # Formatear la tabla visual
                simb = "S/" if moneda == 'SOLES' else "$"
                vista_tabla = reporte_dinamico.copy()
                vista_tabla['CantidadPedida'] = vista_tabla['CantidadPedida'].map('{:,.0f}'.format)
                vista_tabla['Monto_Convertido'] = vista_tabla['Monto_Convertido'].map(lambda x: f"{simb} {x:,.2f}")

                # Fila de Totales
                fila_total = {col: "" for col in columnas_agrupacion}
                fila_total[columnas_agrupacion[0]] = "TOTAL GENERAL"
                fila_total['CantidadPedida'] = f"{total_cantidades:,.0f}"
                fila_total['Monto_Convertido'] = f"{simb} {total_ventas:,.2f}"
                df_fila_total = pd.DataFrame([fila_total])

                # Desplegar en la página web
                st.subheader(f"📊 Reporte Generado ({moneda})")
                st.dataframe(vista_tabla, use_container_width=True)
                st.dataframe(df_fila_total, use_container_width=True)

                # BOTÓN DE EXPORTACIÓN DIRECTA EN WEB
                fila_total_excel = {col: "" for col in columnas_agrupacion}
                fila_total_excel[columnas_agrupacion[0]] = "TOTAL GENERAL"
                fila_total_excel['CantidadPedida'] = total_cantidades
                fila_total_excel['Monto_Convertido'] = total_ventas
                reporte_excel_final = pd.concat([reporte_dinamico, pd.DataFrame([fila_total_excel])], ignore_index=True)

                # Generar el archivo Excel en la memoria del navegador
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    reporte_excel_final.to_excel(writer, sheet_name='Reporte Dinamico', index=False)
                
                st.download_button(
                    label="📥 Descargar Reporte en Excel",
                    data=buffer.getvalue(),
                    file_name=f"Reporte_Dinamico_{empresa}_{p_inicio}_{moneda}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    except Exception as e:
        st.error(f"❌ Ocurrió un inconveniente al procesar las estructuras: {e}")
else:
    st.info("👋 Bienvenido. Por favor, sube los tres archivos Excel solicitados en la barra lateral izquierda para activar el panel.")

