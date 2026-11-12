import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io

def obtener_ventas_periodo(df_ventas, df_tc, df_maestro, empresa, moneda, p_ini, p_fin):
    df_filt = df_ventas[
        (df_ventas['CompaniaSocio'].astype(str).str.strip() == empresa) &
        (df_ventas['VoucherPeriodo'].astype(str).str.strip() >= str(p_ini)) &
        (df_ventas['VoucherPeriodo'].astype(str).str.strip() <= str(p_fin))
    ].copy()

    if df_filt.empty:
        return pd.DataFrame()

    df_filt['Fecha_Clave_Busqueda'] = df_filt['FechaDocumento'].astype(str).str.slice(0, 10).str.strip()
    df_cruces = pd.merge(df_filt, df_tc[['Fecha_Clave_Busqueda', 'Oficial Venta']], on='Fecha_Clave_Busqueda', how='left')
    df_cruces['Oficial Venta'] = df_cruces['Oficial Venta'].ffill()

    cols_maestro = ['Item', 'Tipo_Categoria', 'Marca_Descripcion']
    if 'Descripcion' in df_maestro.columns:
        cols_maestro.append('Descripcion')

    df_res = pd.merge(df_cruces, df_maestro[cols_maestro], left_on='ItemCodigo', right_on='Item', how='left')
    df_res['Tipo_Categoria'] = df_res['Tipo_Categoria'].fillna('SIN CATEGORÍA').str.strip()
    df_res['Marca_Descripcion'] = df_res['Marca_Descripcion'].fillna('SIN MARCA').str.strip()
    if 'Descripcion' in df_res.columns:
        df_res['Descripcion'] = df_res['Descripcion'].fillna('SIN DESCRIPCIÓN').str.strip()

    df_res['Monto'] = pd.to_numeric(df_res['Monto'], errors='coerce').fillna(0)
    df_res['CantidadPedida'] = pd.to_numeric(df_res['CantidadPedida'], errors='coerce').fillna(0)

    cond_ex_sol = (moneda == 'SOLES') & (df_res['MonedaDocumento'] == 'EX')
    cond_lo_dol = (moneda == 'DÓLARES') & (df_res['MonedaDocumento'] == 'LO')
    df_res['Monto_Convertido'] = np.where(
        cond_ex_sol,
        df_res['Monto'] * df_res['Oficial Venta'],
        np.where(cond_lo_dol, df_res['Monto'] / df_res['Oficial Venta'], df_res['Monto'])
    )
    return df_res

def render(ctx):
    df_final = ctx["df_final"]
    df_ventas_all = ctx.get("df_ventas")
    df_tc = ctx.get("df_tc")
    df_maestro = ctx.get("df_maestro")
    moneda = ctx["moneda"]
    empresa = ctx["empresa"]
    p_inicio = ctx["p_inicio"]
    p_fin = ctx.get("p_fin", p_inicio)
    simb = "S/" if moneda == 'SOLES' else "$"

    st.subheader(f"📊 Reporte Comercial por Categorías ({moneda})")

    modo_cat = st.radio(
        "Modo de visualización:",
        ["📅 Periodo Actual", "📊 Comparativo Interanual (Año Anterior vs. Actual)"],
        horizontal=True,
        key="modo_cat_radio"
    )
    st.markdown("---")

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
        st.info("💡 Activa al menos un nivel de estructura arriba para visualizar el reporte.")
        return

    if modo_cat == "📅 Periodo Actual":
        reporte_dinamico = df_final.groupby(columnas_agrupacion).agg({
            'CantidadPedida': 'sum',
            'Monto_Convertido': 'sum'
        }).reset_index().sort_values(by='Monto_Convertido', ascending=False).reset_index(drop=True)

        total_cantidades = reporte_dinamico['CantidadPedida'].sum()
        total_ventas = reporte_dinamico['Monto_Convertido'].sum()

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
    else:
        if df_ventas_all is None or df_tc is None or df_maestro is None:
            st.error("⚠️ Faltan datos históricos en el contexto de `app.py` para calcular el comparativo.")
            return

        p_inicio_ant = str(int(p_inicio) - 100)
        p_fin_ant = str(int(p_fin) - 100)
        anio_act = str(p_inicio)[:4]
        anio_ant = p_inicio_ant[:4]

        st.markdown(f"### Comparativo Comercial: {anio_ant} (`{p_inicio_ant}-{p_fin_ant}`) vs. {anio_act} (`{p_inicio}-{p_fin}`)")

        df_ant = obtener_ventas_periodo(df_ventas_all, df_tc, df_maestro, empresa, moneda, p_inicio_ant, p_fin_ant)
        df_act = df_final.copy()

        if df_ant.empty and df_act.empty:
            st.warning("⚠️ No se encontraron transacciones de venta en ninguno de los dos periodos.")
            return

        v_ant = df_ant['Monto_Convertido'].sum() if not df_ant.empty else 0.0
        q_ant = df_ant['CantidadPedida'].sum() if not df_ant.empty else 0.0

        v_act = df_act['Monto_Convertido'].sum() if not df_act.empty else 0.0
        q_act = df_act['CantidadPedida'].sum() if not df_act.empty else 0.0

        var_v_pct = ((v_act - v_ant) / abs(v_ant) * 100) if v_ant != 0 else 0.0
        var_q_pct = ((q_act - q_ant) / abs(q_ant) * 100) if q_ant != 0 else 0.0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric(f"Ventas {anio_act}", f"{simb} {v_act:,.2f}", f"{var_v_pct:+.2f}% vs {anio_ant}")
        k2.metric(f"Ventas {anio_ant}", f"{simb} {v_ant:,.2f}")
        k3.metric(f"Unidades {anio_act}", f"{q_act:,.0f}", f"{var_q_pct:+.2f}% vs {anio_ant}")
        k4.metric(f"Unidades {anio_ant}", f"{q_ant:,.0f}")

        # Selección inteligente de dimensión para los gráficos Top 5
        if n2:
            dim_graf = 'Marca_Descripcion'
            titulo_dim = 'Marcas'
        elif n1:
            dim_graf = 'Tipo_Categoria'
            titulo_dim = 'Categorías'
        else:
            dim_graf = 'Descripcion' if 'Descripcion' in df_act.columns else 'ItemCodigo'
            titulo_dim = 'Ítems'

        g_ant = df_ant.groupby(dim_graf, as_index=False).agg(
            Ventas_Ant=('Monto_Convertido', 'sum'), Cant_Ant=('CantidadPedida', 'sum')
        ) if not df_ant.empty else pd.DataFrame(columns=[dim_graf, 'Ventas_Ant', 'Cant_Ant'])

        g_act = df_act.groupby(dim_graf, as_index=False).agg(
            Ventas_Act=('Monto_Convertido', 'sum'), Cant_Act=('CantidadPedida', 'sum')
        ) if not df_act.empty else pd.DataFrame(columns=[dim_graf, 'Ventas_Act', 'Cant_Act'])

        top5_graf = pd.merge(g_ant, g_act, on=dim_graf, how='outer').fillna(0)
        top5_graf = top5_graf.sort_values(by='Ventas_Act', ascending=False).head(5).copy()

        g1, g2 = st.columns(2)
        with g1:
            df_gv = pd.melt(top5_graf, id_vars=[dim_graf], value_vars=['Ventas_Ant', 'Ventas_Act'], var_name='Periodo', value_name='Monto')
            df_gv['Periodo'] = df_gv['Periodo'].replace({'Ventas_Ant': f'Ventas {anio_ant}', 'Ventas_Act': f'Ventas {anio_act}'})
            fig_v = px.bar(
                df_gv, x=dim_graf, y='Monto', color='Periodo', barmode='group', text_auto=',.0f',
                title=f'Top 5 {titulo_dim} - Ventas ({anio_ant} vs {anio_act})',
                labels={dim_graf: '', 'Monto': f'Ventas ({simb})'},
                color_discrete_sequence=['#85929E', '#1F618D']
            )
            fig_v.update_traces(textposition='outside')
            fig_v.update_layout(height=400, margin=dict(t=40, b=20))
            st.plotly_chart(fig_v, use_container_width=True)

        with g2:
            df_gq = pd.melt(top5_graf, id_vars=[dim_graf], value_vars=['Cant_Ant', 'Cant_Act'], var_name='Periodo', value_name='Unidades')
            df_gq['Periodo'] = df_gq['Periodo'].replace({'Cant_Ant': f'Unidades {anio_ant}', 'Cant_Act': f'Unidades {anio_act}'})
            fig_q = px.bar(
                df_gq, x=dim_graf, y='Unidades', color='Periodo', barmode='group', text_auto=',.0f',
                title=f'Top 5 {titulo_dim} - Unidades ({anio_ant} vs {anio_act})',
                labels={dim_graf: '', 'Unidades': 'Cantidad Pedida'},
                color_discrete_sequence=['#AEB6BF', '#2E86C1']
            )
            fig_q.update_traces(textposition='outside')
            fig_q.update_layout(height=400, margin=dict(t=40, b=20))
            st.plotly_chart(fig_q, use_container_width=True)
        agg_ant = df_ant.groupby(columnas_agrupacion, as_index=False).agg(
            Cant_Ant=('CantidadPedida', 'sum'),
            Ventas_Ant=('Monto_Convertido', 'sum')
        ) if not df_ant.empty else pd.DataFrame(columns=columnas_agrupacion + ['Cant_Ant', 'Ventas_Ant'])

        agg_act = df_act.groupby(columnas_agrupacion, as_index=False).agg(
            Cant_Act=('CantidadPedida', 'sum'),
            Ventas_Act=('Monto_Convertido', 'sum')
        ) if not df_act.empty else pd.DataFrame(columns=columnas_agrupacion + ['Cant_Act', 'Ventas_Act'])

        comp_df = pd.merge(agg_ant, agg_act, on=columnas_agrupacion, how='outer').fillna(0)
        comp_df['Var_Cant_%'] = np.where(comp_df['Cant_Ant'] != 0, ((comp_df['Cant_Act'] - comp_df['Cant_Ant']) / comp_df['Cant_Ant'].abs()) * 100, 0)
        comp_df['Var_Ventas_%'] = np.where(comp_df['Ventas_Ant'] != 0, ((comp_df['Ventas_Act'] - comp_df['Ventas_Ant']) / comp_df['Ventas_Ant'].abs()) * 100, 0)
        comp_df = comp_df.sort_values(by='Ventas_Act', ascending=False).reset_index(drop=True)

        fila_t = {col: "" for col in columnas_agrupacion}
        fila_t[columnas_agrupacion[0]] = "TOTAL GENERAL"
        fila_t['Cant_Ant'] = comp_df['Cant_Ant'].sum()
        fila_t['Cant_Act'] = comp_df['Cant_Act'].sum()
        fila_t['Var_Cant_%'] = var_q_pct
        fila_t['Ventas_Ant'] = comp_df['Ventas_Ant'].sum()
        fila_t['Ventas_Act'] = comp_df['Ventas_Act'].sum()
        fila_t['Var_Ventas_%'] = var_v_pct

        comp_export = pd.concat([comp_df, pd.DataFrame([fila_t])], ignore_index=True)

        cols_ordenadas = columnas_agrupacion + ['Cant_Ant', 'Cant_Act', 'Var_Cant_%', 'Ventas_Ant', 'Ventas_Act', 'Var_Ventas_%']
        comp_export = comp_export[cols_ordenadas].rename(columns={
            'Cant_Ant': f'Unidades_{anio_ant}',
            'Cant_Act': f'Unidades_{anio_act}',
            'Ventas_Ant': f'Ventas_{anio_ant}',
            'Ventas_Act': f'Ventas_{anio_act}'
        })

        vista_comp = comp_export.copy()
        for col_u in [f'Unidades_{anio_ant}', f'Unidades_{anio_act}']:
            vista_comp[col_u] = vista_comp[col_u].map('{:,.0f}'.format)
        for col_m in [f'Ventas_{anio_ant}', f'Ventas_{anio_act}']:
            vista_comp[col_m] = vista_comp[col_m].map(lambda x: f"{simb} {x:,.2f}")
        for col_p in ['Var_Cant_%', 'Var_Ventas_%']:
            vista_comp[col_p] = vista_comp[col_p].map('{:+.2f}%'.format)

        st.markdown(f"**Detalle Comparativo ({anio_ant} vs. {anio_act})**")
        st.dataframe(vista_comp, use_container_width=True)

        buffer_comp = io.BytesIO()
        with pd.ExcelWriter(buffer_comp, engine='openpyxl') as writer:
            comp_export.to_excel(writer, sheet_name='Comparativo Comercial', index=False)

        st.download_button(
            label=f"📥 Descargar Comparativo {anio_ant} vs {anio_act} en Excel",
            data=buffer_comp.getvalue(),
            file_name=f"Comparativo_Comercial_{anio_ant}_vs_{anio_act}_{empresa}_{p_inicio}_{p_fin}_{moneda}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="btn_descarga_cat_comp"
        )
