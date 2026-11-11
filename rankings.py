import streamlit as st
import pandas as pd
import plotly.express as px
import io

def mostrar_rankings(df_final, moneda, empresa, p_inicio, p_fin):
    st.subheader(f"🏆 Análisis de Rankings ({moneda})")
    
    # Selector interactivo para elegir cuántos registros mostrar
    top_n = st.slider("Seleccione la cantidad de registros (Top N):", min_value=5, max_value=30, value=10, step=5)
    simb = "S/" if moneda == 'SOLES' else "$"

    # Limpieza preventiva de columnas de cliente
    df_trabajo = df_final.copy()
    df_trabajo['ClienteRUC'] = df_trabajo.get('ClienteRUC', pd.Series(['SIN RUC']*len(df_trabajo))).fillna('SIN RUC').astype(str).str.strip()
    df_trabajo['ClienteNombre'] = df_trabajo.get('ClienteNombre', pd.Series(['SIN NOMBRE']*len(df_trabajo))).fillna('SIN NOMBRE').astype(str).str.strip()
    df_trabajo['Descripcion'] = df_trabajo.get('Descripcion', pd.Series(['SIN DESCRIPCIÓN']*len(df_trabajo))).fillna('SIN DESCRIPCIÓN').astype(str).str.strip()

    # Cálculos agrupados
    productos_agg = df_trabajo.groupby(['ItemCodigo', 'Descripcion'], as_index=False).agg({
        'CantidadPedida': 'sum',
        'Monto_Convertido': 'sum'
    })

    clientes_agg = df_trabajo.groupby(['ClienteRUC', 'ClienteNombre'], as_index=False).agg({
        'CantidadPedida': 'sum',
        'Monto_Convertido': 'sum'
    })

    # Rankings ordenados
    top_prod_monto = productos_agg.sort_values(by='Monto_Convertido', ascending=False).head(top_n).reset_index(drop=True)
    top_prod_cant = productos_agg.sort_values(by='CantidadPedida', ascending=False).head(top_n).reset_index(drop=True)
    top_cli_monto = clientes_agg.sort_values(by='Monto_Convertido', ascending=False).head(top_n).reset_index(drop=True)
    top_cli_cant = clientes_agg.sort_values(by='CantidadPedida', ascending=False).head(top_n).reset_index(drop=True)

    # Subpestañas para mantener la pantalla ordenada
    subtab_prod, subtab_cli = st.tabs(["📦 Productos Más Vendidos", "🤝 Mejores Clientes"])

    # --- SUBPESTAÑA 1: PRODUCTOS ---
    with subtab_prod:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"**Top {top_n} Productos por Monto ({moneda})**")
            fig_pm = px.bar(
                top_prod_monto.sort_values(by='Monto_Convertido', ascending=True),
                x='Monto_Convertido',
                y='Descripcion',
                orientation='h',
                text_auto=',.2f',
                labels={'Monto_Convertido': f'Ventas ({simb})', 'Descripcion': ''}
            )
            fig_pm.update_layout(height=400, margin=dict(l=0, r=20, t=20, b=20))
            st.plotly_chart(fig_pm, use_container_width=True)

            tabla_pm = top_prod_monto.copy()
            tabla_pm['CantidadPedida'] = tabla_pm['CantidadPedida'].map('{:,.0f}'.format)
            tabla_pm['Monto_Convertido'] = tabla_pm['Monto_Convertido'].map(lambda x: f"{simb} {x:,.2f}")
            st.dataframe(tabla_pm, use_container_width=True)

        with col2:
            st.markdown(f"**Top {top_n} Productos por Cantidad Física**")
            fig_pc = px.bar(
                top_prod_cant.sort_values(by='CantidadPedida', ascending=True),
                x='CantidadPedida',
                y='Descripcion',
                orientation='h',
                text_auto=',.0f',
                labels={'CantidadPedida': 'Unidades', 'Descripcion': ''},
                color_discrete_sequence=['#2E86C1']
            )
            fig_pc.update_layout(height=400, margin=dict(l=0, r=20, t=20, b=20))
            st.plotly_chart(fig_pc, use_container_width=True)

            tabla_pc = top_prod_cant.copy()
            tabla_pc['CantidadPedida'] = tabla_pc['CantidadPedida'].map('{:,.0f}'.format)
            tabla_pc['Monto_Convertido'] = tabla_pc['Monto_Convertido'].map(lambda x: f"{simb} {x:,.2f}")
            st.dataframe(tabla_pc, use_container_width=True)

    # --- SUBPESTAÑA 2: CLIENTES ---
    with subtab_cli:
        col3, col4 = st.columns(2)

        with col3:
            st.markdown(f"**Top {top_n} Clientes por Monto ({moneda})**")
            fig_cm = px.bar(
                top_cli_monto.sort_values(by='Monto_Convertido', ascending=True),
                x='Monto_Convertido',
                y='ClienteNombre',
                orientation='h',
                text_auto=',.2f',
                labels={'Monto_Convertido': f'Ventas ({simb})', 'ClienteNombre': ''},
                color_discrete_sequence=['#1E8449']
            )
            fig_cm.update_layout(height=400, margin=dict(l=0, r=20, t=20, b=20))
            st.plotly_chart(fig_cm, use_container_width=True)

            tabla_cm = top_cli_monto.copy()
            tabla_cm['CantidadPedida'] = tabla_cm['CantidadPedida'].map('{:,.0f}'.format)
            tabla_cm['Monto_Convertido'] = tabla_cm['Monto_Convertido'].map(lambda x: f"{simb} {x:,.2f}")
            st.dataframe(tabla_cm, use_container_width=True)

        with col4:
            st.markdown(f"**Top {top_n} Clientes por Cantidad Física**")
            fig_cc = px.bar(
                top_cli_cant.sort_values(by='CantidadPedida', ascending=True),
                x='CantidadPedida',
                y='ClienteNombre',
                orientation='h',
                text_auto=',.0f',
                labels={'CantidadPedida': 'Unidades', 'ClienteNombre': ''},
                color_discrete_sequence=['#D35400']
            )
            fig_cc.update_layout(height=400, margin=dict(l=0, r=20, t=20, b=20))
            st.plotly_chart(fig_cc, use_container_width=True)

            tabla_cc = top_cli_cant.copy()
            tabla_cc['CantidadPedida'] = tabla_cc['CantidadPedida'].map('{:,.0f}'.format)
            tabla_cc['Monto_Convertido'] = tabla_cc['Monto_Convertido'].map(lambda x: f"{simb} {x:,.2f}")
            st.dataframe(tabla_cc, use_container_width=True)

    # --- EXPORTACIÓN A EXCEL DE LOS 4 RANKINGS ---
    st.markdown("---")
    buffer_rank = io.BytesIO()
    with pd.ExcelWriter(buffer_rank, engine='openpyxl') as writer:
        top_prod_monto.to_excel(writer, sheet_name='Top Productos Monto', index=False)
        top_prod_cant.to_excel(writer, sheet_name='Top Productos Cantidad', index=False)
        top_cli_monto.to_excel(writer, sheet_name='Top Clientes Monto', index=False)
        top_cli_cant.to_excel(writer, sheet_name='Top Clientes Cantidad', index=False)

    st.download_button(
        label="📥 Descargar Rankings en Excel (4 Hojas)",
        data=buffer_rank.getvalue(),
        file_name=f"Rankings_{empresa}_{p_inicio}_{p_fin}_{moneda}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

