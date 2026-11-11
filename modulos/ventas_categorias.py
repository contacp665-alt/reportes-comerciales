import streamlit as st
import pandas as pd
import io

def render(ctx):
    df_final = ctx["df_final"]
    moneda = ctx["moneda"]
    empresa = ctx["empresa"]
    p_inicio = ctx["p_inicio"]

    st.subheader(f"📊 Reporte Comercial por Categorías ({moneda})")

    # Controles propios de este reporte
    col1, col2, col3 = st.columns(3)
    with col1:
        n1 = st.checkbox("Nivel 1: Categoría", value=True, key="cat_n1")
    with col2:
        n2 = st.checkbox("Nivel 2: Marca", value=False, key="cat_n2")
    with col3:
        n3 = st.checkbox("Nivel 3: Ítems", value=False, key="cat_n3")

    columnas_agrupacion = []
    if n1: columnas_agrupacion.append('Tipo_Categoria')
    if n2: columnas_agrupacion.append('Marca_Descripcion')
    if n3: 
        columnas_agrupacion.append('ItemCodigo')
        if 'Descripcion' in df_final.columns: columnas_agrupacion.append('Descripcion')

    if not columnas_agrupacion:
        st.info("💡 Activa al menos un nivel de estructura arriba para visualizar la tabla.")
        return

    reporte_dinamico = df_final.groupby(columnas_agrupacion).agg({
        'CantidadPedida': 'sum',
        'Monto_Convertido': 'sum'
    }).reset_index().sort_values(by='Monto_Convertido', ascending=False).reset_index(drop=True)

    total_cantidades = reporte_dinamico['CantidadPedida'].sum()
    total_ventas = reporte_dinamico['Monto_Convertido'].sum()

    simb = "S/" if moneda == 'SOLES' else "$"
    vista_tabla = reporte_dinamico.copy()
    vista_tabla['CantidadPedida'] = vista_tabla['CantidadPedida'].map('{:,.0f}'.format)
    vista_tabla['Monto_Convertido'] = vista_tabla['Monto_Convertido'].map(lambda x: f"{simb} {x:,.2f}")

    fila_total = {col: "" for col in columnas_agrupacion}
    fila_total[columnas_agrupacion[0]] = "TOTAL GENERAL"
    fila_total['CantidadPedida'] = f"{total_cantidades:,.0f}"
    fila_total['Monto_Convertido'] = f"{simb} {total_ventas:,.2f}"
    df_fila_total = pd.DataFrame([fila_total])

    st.dataframe(vista_tabla, use_container_width=True)
    st.dataframe(df_fila_total, use_container_width=True)

    fila_total_excel = {col: "" for col in columnas_agrupacion}
    fila_total_excel[columnas_agrupacion[0]] = "TOTAL GENERAL"
    fila_total_excel['CantidadPedida'] = total_cantidades
    fila_total_excel['Monto_Convertido'] = total_ventas
    reporte_excel_final = pd.concat([reporte_dinamico, pd.DataFrame([fila_total_excel])], ignore_index=True)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        reporte_excel_final.to_excel(writer, sheet_name='Reporte Dinamico', index=False)
    
    st.download_button(
        label="📥 Descargar Reporte en Excel",
        data=buffer.getvalue(),
        file_name=f"Reporte_Dinamico_{empresa}_{p_inicio}_{moneda}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="btn_descarga_cat"
    )

