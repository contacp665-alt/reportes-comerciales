import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io
import gc

MAPEO_TRANSACCIONES = {
    'AEC': 'OTROS',
    'AIC': 'OTROS',
    'AJP': 'AJUSTE DE PRECIOS',
    'API': 'PRODUCCION',
    'ARO': 'COMPRA',
    'ATR': 'OTROS',
    'AVT': 'VENTA',
    'IAL': 'OTROS',
    'MIT': 'IMPORTACION',
    'MIE': 'IMPORTACION',
    'AEG': 'CONSUMO',
    'PRE': 'CONSUMO',
    'PRI': 'PRODUCCION',
    'ROC': 'COMPRA',
    'SAL': 'OTROS',
    'TIE': 'OTROS',
    'TRA': 'OTROS',
    'VTA': 'VENTA',
    'VTI': 'VENTA',
    'VTT': 'OTROS',
    'ZZZ': 'EXCLUIR',
    '___': 'SALDO INICIAL',
    'TFI': 'OTROS',
    'TFE': 'OTROS',
}

def clasificar_movimiento(df):
    cod = df['TransaccionCodigo'].astype(str).str.strip().str.upper()
    comp = df['CompaniaSocio'].astype(str).str.strip()

    tipo = cod.map(MAPEO_TRANSACCIONES).fillna('NO CLASIFICADO')
    tipo = np.where((cod == 'DVP') & (comp == '03000000'), 'CONSUMO',
           np.where((cod == 'DVP') & (comp != '03000000'), 'DEVOLUCION', tipo))
    tipo = np.where((cod == 'REQ') & (comp == '01000000'), 'CONSUMO',
           np.where((cod == 'REQ') & (comp != '01000000'), 'REQUERIMIENTO', tipo))
    return tipo

@st.cache_data(show_spinner="Procesando archivo Kardex...")
def cargar_kardex(archivo):
    if archivo.name.endswith('.parquet'):
        return pd.read_parquet(archivo)
    return pd.read_excel(archivo, dtype=str)

def exportar_excel_3_hojas(df_hoja1, nom1, df_hoja2, nom2, df_hoja3, nom3):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_hoja1.to_excel(writer, sheet_name=nom1[:31], index=False)
        df_hoja2.to_excel(writer, sheet_name=nom2[:31], index=False)
        df_hoja3.to_excel(writer, sheet_name=nom3[:31], index=False)
    return buffer.getvalue()
def ejecutar_cruce_ventas_kardex(df_k_all, df_v_all, df_tc, df_maestro, cols_m, empresa, moneda, p_ini, p_fin):
    mask_k = (
        (df_k_all['CompaniaSocio'] == empresa) &
        (df_k_all['Periodo'] >= str(p_ini)) &
        (df_k_all['Periodo'] <= str(p_fin)) &
        (df_k_all['TransaccionCodigo'].isin(['AVT', 'VTA', 'VTI']))
    )
    df_kv = df_k_all.loc[mask_k].copy()

    if df_kv.empty:
        return pd.DataFrame()

    df_kv['Cantidad'] = pd.to_numeric(df_kv['Cantidad'], errors='coerce').fillna(0)
    col_monto_k = 'MontoTotal' if moneda == 'SOLES' else 'MontoTotalDolares'
    df_kv['Monto_Kardex'] = pd.to_numeric(df_kv[col_monto_k], errors='coerce').fillna(0)
    
    df_kv['Doc_Cruce'] = df_kv['ReferenciaNumeroDocumento.1'].fillna('').astype(str).str.strip()
    df_kv['Costo_Positivo'] = df_kv['Monto_Kardex'] * -1

    kardex_agg = df_kv.groupby(['Doc_Cruce', 'Item'], as_index=False).agg(
        Cant_Kardex=('Cantidad', 'sum'),
        Costo=('Costo_Positivo', 'sum')
    )
    del df_kv

    df_v_emp = df_v_all.loc[df_v_all['CompaniaSocio'].astype(str).str.strip() == empresa].copy()
    df_v_emp['Doc_Cruce'] = df_v_emp['NumeroDocumento'].fillna('').astype(str).str.strip()
    df_v_emp['Item'] = df_v_emp['ItemCodigo'].astype(str).str.strip()

    llaves = set(zip(kardex_agg['Doc_Cruce'], kardex_agg['Item']))
    df_v_emp = df_v_emp[df_v_emp.set_index(['Doc_Cruce', 'Item']).index.isin(llaves)].copy()

    df_v_emp['Fecha_Clave'] = df_v_emp['FechaDocumento'].astype(str).str.slice(0, 10).str.strip()
    df_v_emp = pd.merge(
        df_v_emp, 
        df_tc[['Fecha_Clave_Busqueda', 'Oficial Venta']], 
        left_on='Fecha_Clave', 
        right_on='Fecha_Clave_Busqueda', 
        how='left'
    )
    df_v_emp['Oficial Venta'] = df_v_emp['Oficial Venta'].ffill()

    df_v_emp['Monto'] = pd.to_numeric(df_v_emp['Monto'], errors='coerce').fillna(0)
    df_v_emp['CantidadPedida'] = pd.to_numeric(df_v_emp['CantidadPedida'], errors='coerce').fillna(0)

    cond_ex_sol = (moneda == 'SOLES') & (df_v_emp['MonedaDocumento'] == 'EX')
    cond_lo_dol = (moneda == 'DÓLARES') & (df_v_emp['MonedaDocumento'] == 'LO')
    df_v_emp['Venta_Conv'] = np.where(
        cond_ex_sol, df_v_emp['Monto'] * df_v_emp['Oficial Venta'],
        np.where(cond_lo_dol, df_v_emp['Monto'] / df_v_emp['Oficial Venta'], df_v_emp['Monto'])
    )

    ventas_agg = df_v_emp.groupby(['Doc_Cruce', 'Item'], as_index=False).agg(
        Cant_Ventas=('CantidadPedida', 'sum'),
        Ventas=('Venta_Conv', 'sum')
    )
    del df_v_emp

    df_cruce = pd.merge(kardex_agg, ventas_agg, on=['Doc_Cruce', 'Item'], how='left').fillna({'Cant_Ventas': 0, 'Ventas': 0})
    del kardex_agg, ventas_agg
    gc.collect()

    df_cruce['Dif_Cant'] = (df_cruce['Cant_Kardex'] + df_cruce['Cant_Ventas']).round(2)
    df_cruce['Utilidad'] = df_cruce['Ventas'] - df_cruce['Costo']

    df_cruce = pd.merge(df_cruce, df_maestro[cols_m], on='Item', how='left')
    df_cruce['Tipo_Categoria'] = df_cruce['Tipo_Categoria'].fillna('SIN CATEGORÍA').str.strip()
    df_cruce['Marca_Descripcion'] = df_cruce['Marca_Descripcion'].fillna('SIN MARCA').str.strip()
    
    return df_cruce
def render(ctx):
    df_ventas_completo = ctx.get("df_ventas")
    df_tc = ctx["df_tc"]
    df_maestro = ctx["df_maestro"]
    empresa = ctx["empresa"]
    moneda = ctx["moneda"]
    p_inicio = ctx["p_inicio"]
    p_fin = ctx["p_fin"]
    simb = "S/" if moneda == 'SOLES' else "$"

    st.subheader(f"📦 Gestión de Kardex, Costos y Rentabilidad ({moneda})")

    uploaded_kardex = st.file_uploader(
        "Sube el archivo Kardex (.parquet o .xlsx):",
        type=["parquet", "xlsx"],
        key="uploader_kardex"
    )

    if not uploaded_kardex:
        st.info("👆 Sube tu archivo `kardex.parquet` o `kardex.xlsx` aquí arriba.")
        return

    if df_ventas_completo is None:
        st.error("⚠️ Falta agregar `'df_ventas': df_ventas` en el diccionario `contexto` de `app.py`.")
        return

    try:
        df_k = cargar_kardex(uploaded_kardex)

        df_k['CompaniaSocio'] = df_k['CompaniaSocio'].astype(str).str.strip()
        df_k['Periodo'] = df_k['Periodo'].astype(str).str.strip()
        df_k['TransaccionCodigo'] = df_k['TransaccionCodigo'].astype(str).str.strip().str.upper()
        df_k['Item'] = df_k['Item'].astype(str).str.strip()

        df_maestro['Item'] = df_maestro['Item'].astype(str).str.strip()
        cols_m = ['Item', 'Tipo_Categoria', 'Marca_Descripcion']
        if 'Descripcion' in df_maestro.columns:
            cols_m.append('Descripcion')
        if 'CuentaContable' in df_maestro.columns:
            cols_m.append('CuentaContable')

        df_k_filt = df_k[
            (df_k['CompaniaSocio'] == empresa) &
            (df_k['Periodo'] >= str(p_inicio)) &
            (df_k['Periodo'] <= str(p_fin))
        ].copy()

        if not df_k_filt.empty:
            df_k_filt['Tipo_Movimiento'] = clasificar_movimiento(df_k_filt)
            df_k_filt = df_k_filt[df_k_filt['Tipo_Movimiento'] != 'EXCLUIR'].copy()

            no_clasificados = df_k_filt[df_k_filt['Tipo_Movimiento'] == 'NO CLASIFICADO']['TransaccionCodigo'].unique()
            if len(no_clasificados) > 0:
                st.warning(f"⚠️ Códigos nuevos sin clasificar: **{', '.join(no_clasificados)}**")

            df_k_filt['Cantidad'] = pd.to_numeric(df_k_filt['Cantidad'], errors='coerce').fillna(0)
            col_monto_k = 'MontoTotal' if moneda == 'SOLES' else 'MontoTotalDolares'
            df_k_filt['Monto_Kardex'] = pd.to_numeric(df_k_filt[col_monto_k], errors='coerce').fillna(0)

            df_k_filt = pd.merge(df_k_filt, df_maestro[cols_m], on='Item', how='left')
            df_k_filt['Tipo_Categoria'] = df_k_filt['Tipo_Categoria'].fillna('SIN CATEGORÍA').str.strip()
            df_k_filt['Marca_Descripcion'] = df_k_filt['Marca_Descripcion'].fillna('SIN MARCA').str.strip()

        tab_rent, tab_comp, tab_cons, tab_prod = st.tabs([
            "💰 Ventas vs. Costo Kardex",
            "🛒 Compras e Importaciones",
            "🏭 Consumos",
            "⚙️ Producción"
        ])
        with tab_rent:
            modo_rent = st.radio(
                "Modo de visualización:",
                ["📅 Periodo Actual", "📊 Comparativo Interanual (Año Anterior vs. Actual)"],
                horizontal=True,
                key="modo_rent_radio"
            )
            st.markdown("---")

            c1, c2, c3 = st.columns(3)
            with c1:
                k_n1 = st.checkbox("Nivel 1: Categoría", value=True, key="k_n1")
            with c2:
                k_n2 = st.checkbox("Nivel 2: Marca", value=False, key="k_n2")
            with c3:
                k_n3 = st.checkbox("Nivel 3: Ítems", value=False, key="k_n3")

            cols_agrup = []
            if k_n1: cols_agrup.append('Tipo_Categoria')
            if k_n2: cols_agrup.append('Marca_Descripcion')
            if k_n3:
                cols_agrup.append('Item')
                if 'Descripcion' in df_maestro.columns: cols_agrup.append('Descripcion')

            if modo_rent == "📅 Periodo Actual":
                st.markdown(f"### Cruce de Despachos vs. Facturación ({p_inicio} - {p_fin} | {moneda})")
                df_cruce = ejecutar_cruce_ventas_kardex(
                    df_k, df_ventas_completo, df_tc, df_maestro, cols_m, empresa, moneda, p_inicio, p_fin
                )

                if df_cruce.empty:
                    st.warning(f"⚠️ No hay salidas por venta en el Kardex para {empresa} en el rango {p_inicio} - {p_fin}.")
                else:
                    tot_v = df_cruce['Ventas'].sum()
                    tot_c = df_cruce['Costo'].sum()
                    tot_u = tot_v - tot_c
                    margen = (tot_u / tot_v * 100) if tot_v != 0 else 0

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Ventas Cruzadas", f"{simb} {tot_v:,.2f}")
                    m2.metric("Costo Kardex", f"{simb} {tot_c:,.2f}")
                    m3.metric("Utilidad Bruta", f"{simb} {tot_u:,.2f}")
                    m4.metric("Margen Bruto", f"{margen:.2f}%")

                    if not cols_agrup:
                        st.info("💡 Activa al menos un nivel de agrupación arriba.")
                    else:
                        resumen_rent = df_cruce.groupby(cols_agrup, as_index=False, dropna=False).agg(
                            Ventas=('Ventas', 'sum'),
                            Costo=('Costo', 'sum'),
                            Utilidad=('Utilidad', 'sum'),
                            Cant_Kardex=('Cant_Kardex', 'sum'),
                            Cant_Ventas=('Cant_Ventas', 'sum'),
                            Dif_Cant=('Dif_Cant', 'sum')
                        ).sort_values(by='Ventas', ascending=False).reset_index(drop=True)

                        resumen_rent['Margen_%'] = np.where(resumen_rent['Ventas'] != 0, (resumen_rent['Utilidad'] / resumen_rent['Ventas']) * 100, 0)

                        fila_tot = {c: '' for c in cols_agrup}
                        fila_tot[next(iter(cols_agrup))] = 'TOTAL GENERAL'
                        fila_tot['Ventas'] = resumen_rent['Ventas'].sum()
                        fila_tot['Costo'] = resumen_rent['Costo'].sum()
                        fila_tot['Utilidad'] = resumen_rent['Utilidad'].sum()
                        fila_tot['Margen_%'] = margen
                        fila_tot['Cant_Kardex'] = resumen_rent['Cant_Kardex'].sum()
                        fila_tot['Cant_Ventas'] = resumen_rent['Cant_Ventas'].sum()
                        fila_tot['Dif_Cant'] = resumen_rent['Dif_Cant'].sum()

                        resumen_export = pd.concat([resumen_rent, pd.DataFrame([fila_tot])], ignore_index=True)

                        vista_rent = resumen_export.copy()
                        for c_mon in ['Ventas', 'Costo', 'Utilidad']:
                            vista_rent[c_mon] = vista_rent[c_mon].map(lambda x: f"{simb} {x:,.2f}")
                        for c_cnt in ['Cant_Kardex', 'Cant_Ventas', 'Dif_Cant']:
                            vista_rent[c_cnt] = vista_rent[c_cnt].map('{:,.2f}'.format)
                        vista_rent['Margen_%'] = vista_rent['Margen_%'].map('{:.2f}%'.format)

                        st.dataframe(vista_rent, use_container_width=True)

                        df_dif = df_cruce[df_cruce['Dif_Cant'] != 0].copy()
                        with st.expander(f"🔍 Auditoría de Diferencias en Cantidad ({len(df_dif)} documentos con saldo pendiente)"):
                            if df_dif.empty:
                                st.success("✅ Todas las cantidades despachadas cuadran al 100% con las facturadas.")
                            else:
                                st.dataframe(df_dif[['Doc_Cruce', 'Item', 'Tipo_Categoria', 'Cant_Kardex', 'Cant_Ventas', 'Dif_Cant', 'Costo', 'Ventas']], use_container_width=True)

                        excel_rent = exportar_excel_3_hojas(
                            resumen_export, "1. Resumen Gerencial",
                            df_dif, "2. Diferencias Cantidad",
                            df_cruce, "3. Detalle por Documento"
                        )
                        st.download_button(
                            label="📥 Descargar Ventas vs. Costo en Excel (3 Hojas)",
                            data=excel_rent,
                            file_name=f"Ventas_vs_Costo_{empresa}_{p_inicio}_{p_fin}_{moneda}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="dl_kardex_rent"
                        )
            else:
                p_inicio_ant = str(int(p_inicio) - 100)
                p_fin_ant    = str(int(p_fin) - 100)
                anio_act     = str(p_inicio)[:4]
                anio_ant     = p_inicio_ant[:4]

                st.markdown(f"### Comparativo Interanual: {anio_ant} (`{p_inicio_ant}-{p_fin_ant}`) vs. {anio_act} (`{p_inicio}-{p_fin}`)")

                df_cruce_ant = ejecutar_cruce_ventas_kardex(
                    df_k, df_ventas_completo, df_tc, df_maestro, cols_m, empresa, moneda, p_inicio_ant, p_fin_ant
                )
                df_cruce_act = ejecutar_cruce_ventas_kardex(
                    df_k, df_ventas_completo, df_tc, df_maestro, cols_m, empresa, moneda, p_inicio, p_fin
                )

                if df_cruce_ant.empty and df_cruce_act.empty:
                    st.warning("⚠️ No se encontraron datos de ventas en Kardex para ninguno de los dos periodos.")
                else:
                    v_ant = df_cruce_ant['Ventas'].sum() if not df_cruce_ant.empty else 0.0
                    c_ant = df_cruce_ant['Costo'].sum() if not df_cruce_ant.empty else 0.0
                    u_ant = v_ant - c_ant
                    m_ant = (u_ant / v_ant * 100) if v_ant != 0 else 0.0

                    v_act = df_cruce_act['Ventas'].sum() if not df_cruce_act.empty else 0.0
                    c_act = df_cruce_act['Costo'].sum() if not df_cruce_act.empty else 0.0
                    u_act = v_act - c_act
                    m_act = (u_act / v_act * 100) if v_act != 0 else 0.0

                    var_v_pct = ((v_act - v_ant) / abs(v_ant) * 100) if v_ant != 0 else 0.0
                    var_c_pct = ((c_act - c_ant) / abs(c_ant) * 100) if c_ant != 0 else 0.0
                    var_u_pct = ((u_act - u_ant) / abs(u_ant) * 100) if u_ant != 0 else 0.0

                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric(f"Ventas {anio_act} vs {anio_ant}", f"{simb} {v_act:,.2f}", f"{var_v_pct:+.2f}% ({simb} {v_act - v_ant:+,.0f})")
                    k2.metric(f"Costo {anio_act} vs {anio_ant}", f"{simb} {c_act:,.2f}", f"{var_c_pct:+.2f}% ({simb} {c_act - c_ant:+,.0f})", delta_color="inverse")
                    k3.metric(f"Utilidad {anio_act} vs {anio_ant}", f"{simb} {u_act:,.2f}", f"{var_u_pct:+.2f}% ({simb} {u_act - u_ant:+,.0f})")
                    k4.metric(f"Margen {anio_act} vs {anio_ant}", f"{m_act:.2f}%", f"{m_act - m_ant:+.2f} pp (Ant: {m_ant:.2f}%)")

                    agg_cat_ant = df_cruce_ant.groupby('Tipo_Categoria', as_index=False).agg(
                        Ventas_Ant=('Ventas', 'sum'), Utilidad_Ant=('Utilidad', 'sum')
                    ) if not df_cruce_ant.empty else pd.DataFrame(columns=['Tipo_Categoria', 'Ventas_Ant', 'Utilidad_Ant'])

                    agg_cat_act = df_cruce_act.groupby('Tipo_Categoria', as_index=False).agg(
                        Ventas_Act=('Ventas', 'sum'), Utilidad_Act=('Utilidad', 'sum')
                    ) if not df_cruce_act.empty else pd.DataFrame(columns=['Tipo_Categoria', 'Ventas_Act', 'Utilidad_Act'])

                    top5_cat = pd.merge(agg_cat_ant, agg_cat_act, on='Tipo_Categoria', how='outer').fillna(0)
                    top5_cat = top5_cat.sort_values(by='Ventas_Act', ascending=False).head(5).copy()

                    g1, g2 = st.columns(2)
                    with g1:
                        df_gv = pd.melt(top5_cat, id_vars=['Tipo_Categoria'], value_vars=['Ventas_Ant', 'Ventas_Act'], var_name='Periodo', value_name='Monto')
                        df_gv['Periodo'] = df_gv['Periodo'].replace({'Ventas_Ant': f'Ventas {anio_ant}', 'Ventas_Act': f'Ventas {anio_act}'})
                        fig_v = px.bar(
                            df_gv, x='Tipo_Categoria', y='Monto', color='Periodo', barmode='group', text_auto=',.0f',
                            title=f'Top 5 Categorías - Ventas ({anio_ant} vs {anio_act})',
                            labels={'Tipo_Categoria': '', 'Monto': f'Ventas ({simb})'},
                            color_discrete_sequence=['#85929E', '#1F618D']
                        )
                        fig_v.update_traces(textposition='outside')
                        fig_v.update_layout(height=400, margin=dict(t=40, b=20))
                        st.plotly_chart(fig_v, use_container_width=True)

                    with g2:
                        df_gu = pd.melt(top5_cat, id_vars=['Tipo_Categoria'], value_vars=['Utilidad_Ant', 'Utilidad_Act'], var_name='Periodo', value_name='Monto')
                        df_gu['Periodo'] = df_gu['Periodo'].replace({'Utilidad_Ant': f'Utilidad {anio_ant}', 'Utilidad_Act': f'Utilidad {anio_act}'})
                        fig_u = px.bar(
                            df_gu, x='Tipo_Categoria', y='Monto', color='Periodo', barmode='group', text_auto=',.0f',
                            title=f'Top 5 Categorías - Utilidad Bruta ({anio_ant} vs {anio_act})',
                            labels={'Tipo_Categoria': '', 'Monto': f'Utilidad ({simb})'},
                            color_discrete_sequence=['#A9DFBF', '#1E8449']
                        )
                        fig_u.update_traces(textposition='outside')
                        fig_u.update_layout(height=400, margin=dict(t=40, b=20))
                        st.plotly_chart(fig_u, use_container_width=True)
                    if not cols_agrup:
                        st.info("💡 Activa al menos un nivel de agrupación arriba para ver la tabla comparativa.")
                    else:
                        def construir_tabla_comparativa(keys_agrup):
                            g_ant = df_cruce_ant.groupby(keys_agrup, as_index=False, dropna=False).agg(
                                Ventas_Ant=('Ventas', 'sum'), Costo_Ant=('Costo', 'sum'), Utilidad_Ant=('Utilidad', 'sum')
                            ) if not df_cruce_ant.empty else pd.DataFrame(columns=keys_agrup + ['Ventas_Ant', 'Costo_Ant', 'Utilidad_Ant'])

                            g_act = df_cruce_act.groupby(keys_agrup, as_index=False, dropna=False).agg(
                                Ventas_Act=('Ventas', 'sum'), Costo_Act=('Costo', 'sum'), Utilidad_Act=('Utilidad', 'sum')
                            ) if not df_cruce_act.empty else pd.DataFrame(columns=keys_agrup + ['Ventas_Act', 'Costo_Act', 'Utilidad_Act'])

                            comp = pd.merge(g_ant, g_act, on=keys_agrup, how='outer').fillna(0)
                            comp['Var_Ventas_%'] = np.where(comp['Ventas_Ant'] != 0, ((comp['Ventas_Act'] - comp['Ventas_Ant']) / comp['Ventas_Ant'].abs()) * 100, 0)
                            comp['Var_Costo_%']  = np.where(comp['Costo_Ant'] != 0, ((comp['Costo_Act'] - comp['Costo_Ant']) / comp['Costo_Ant'].abs()) * 100, 0)
                            comp['Margen_Ant_%'] = np.where(comp['Ventas_Ant'] != 0, (comp['Utilidad_Ant'] / comp['Ventas_Ant']) * 100, 0)
                            comp['Margen_Act_%'] = np.where(comp['Ventas_Act'] != 0, (comp['Utilidad_Act'] / comp['Ventas_Act']) * 100, 0)
                            comp = comp.sort_values(by='Ventas_Act', ascending=False).reset_index(drop=True)

                            fila_t = {c: '' for c in keys_agrup}
                            fila_t[next(iter(keys_agrup))] = 'TOTAL GENERAL'
                            fila_t['Ventas_Ant']   = comp['Ventas_Ant'].sum()
                            fila_t['Ventas_Act']   = comp['Ventas_Act'].sum()
                            fila_t['Var_Ventas_%'] = var_v_pct
                            fila_t['Costo_Ant']    = comp['Costo_Ant'].sum()
                            fila_t['Costo_Act']    = comp['Costo_Act'].sum()
                            fila_t['Var_Costo_%']  = var_c_pct
                            fila_t['Utilidad_Ant'] = comp['Utilidad_Ant'].sum()
                            fila_t['Utilidad_Act'] = comp['Utilidad_Act'].sum()
                            fila_t['Margen_Ant_%'] = m_ant
                            fila_t['Margen_Act_%'] = m_act

                            comp_tot = pd.concat([comp, pd.DataFrame([fila_t])], ignore_index=True)
                            comp_tot = comp_tot.rename(columns={
                                'Ventas_Ant': f'Ventas_{anio_ant}', 'Ventas_Act': f'Ventas_{anio_act}',
                                'Costo_Ant': f'Costo_{anio_ant}',   'Costo_Act': f'Costo_{anio_act}',
                                'Utilidad_Ant': f'Utilidad_{anio_ant}', 'Utilidad_Act': f'Utilidad_{anio_act}',
                                'Margen_Ant_%': f'Margen_{anio_ant}_%', 'Margen_Act_%': f'Margen_{anio_act}_%'
                            })
                            return comp_tot

                        comp_gerencial = construir_tabla_comparativa(cols_agrup)

                        vista_comp = comp_gerencial.copy()
                        for col_m in [f'Ventas_{anio_ant}', f'Ventas_{anio_act}', f'Costo_{anio_ant}', f'Costo_{anio_act}', f'Utilidad_{anio_ant}', f'Utilidad_{anio_act}']:
                            vista_comp[col_m] = vista_comp[col_m].map(lambda x: f"{simb} {x:,.2f}")
                        for col_p in ['Var_Ventas_%', 'Var_Costo_%']:
                            vista_comp[col_p] = vista_comp[col_p].map('{:+.2f}%'.format)
                        for col_mg in [f'Margen_{anio_ant}_%', f'Margen_{anio_act}_%']:
                            vista_comp[col_mg] = vista_comp[col_mg].map('{:.2f}%'.format)

                        st.markdown(f"**Tabla Comparativa ({anio_ant} vs. {anio_act})**")
                        st.dataframe(vista_comp, use_container_width=True)

                        keys_item = ['Tipo_Categoria', 'Marca_Descripcion', 'Item']
                        if 'Descripcion' in df_maestro.columns: keys_item.append('Descripcion')
                        comp_por_item = construir_tabla_comparativa(keys_item)

                        dif_list = []
                        if not df_cruce_ant.empty:
                            d_ant = df_cruce_ant[df_cruce_ant['Dif_Cant'] != 0].copy()
                            d_ant['Ejercicio'] = anio_ant
                            dif_list.append(d_ant)
                        if not df_cruce_act.empty:
                            d_act = df_cruce_act[df_cruce_act['Dif_Cant'] != 0].copy()
                            d_act['Ejercicio'] = anio_act
                            dif_list.append(d_act)
                        df_dif_interanual = pd.concat(dif_list, ignore_index=True) if dif_list else pd.DataFrame()

                        excel_comp_int = exportar_excel_3_hojas(
                            comp_gerencial, "1. Comparativo Gerencial",
                            comp_por_item, "2. Comparativo por Item",
                            df_dif_interanual, "3. Auditoria Diferencias"
                        )
                        st.download_button(
                            label=f"📥 Descargar Comparativo {anio_ant} vs {anio_act} en Excel (3 Hojas)",
                            data=excel_comp_int,
                            file_name=f"Comparativo_{anio_ant}_vs_{anio_act}_{empresa}_{p_inicio}_{p_fin}_{moneda}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="dl_kardex_comp_int"
                        )
        with tab_comp:
            if df_k_filt.empty:
                st.info("No se encontraron compras ni importaciones en este periodo.")
            else:
                df_comp = df_k_filt[df_k_filt['Tipo_Movimiento'].isin(['COMPRA', 'IMPORTACION'])].copy()
                if df_comp.empty:
                    st.info("No se encontraron compras ni importaciones en este periodo.")
                else:
                    tot_comp_loc = df_comp[df_comp['Tipo_Movimiento'] == 'COMPRA']['Monto_Kardex'].sum()
                    tot_comp_imp = df_comp[df_comp['Tipo_Movimiento'] == 'IMPORTACION']['Monto_Kardex'].sum()
                    tot_comp_gen = df_comp['Monto_Kardex'].sum()

                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric(f"Total Compras e Importaciones ({moneda})", f"{simb} {tot_comp_gen:,.2f}")
                    mc2.metric("Compras Locales (ARO/ROC)", f"{simb} {tot_comp_loc:,.2f}")
                    mc3.metric("Importaciones (MIT/MIE)", f"{simb} {tot_comp_imp:,.2f}")

                    st.markdown("---")
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        comp_n1 = st.checkbox("Nivel 1: Categoría", value=True, key="comp_n1")
                    with cc2:
                        comp_n2 = st.checkbox("Nivel 2: Ítems", value=False, key="comp_n2")

                    col_desc_k = next((c for c in ['DescripcionLocal', 'Descripcion'] if c in df_comp.columns), None)
                    if col_desc_k:
                        df_comp[col_desc_k] = df_comp[col_desc_k].fillna('SIN DESCRIPCIÓN').astype(str).str.strip()

                    cols_agrup_comp = ['Tipo_Movimiento']
                    if comp_n1:
                        cols_agrup_comp.append('Tipo_Categoria')
                    if comp_n2:
                        cols_agrup_comp.append('Item')
                        if col_desc_k:
                            cols_agrup_comp.append(col_desc_k)

                    if not comp_n1 and not comp_n2:
                        st.info("💡 Activa al menos un nivel de agrupación (Categoría o Ítems) arriba.")
                    else:
                        resumen_comp = df_comp.groupby(cols_agrup_comp, as_index=False, dropna=False).agg(
                            Cantidad=('Cantidad', 'sum'),
                            Monto_Total=('Monto_Kardex', 'sum')
                        ).sort_values(by=['Tipo_Movimiento', 'Monto_Total'], ascending=[True, False]).reset_index(drop=True)

                        fila_tot_c = {c: '' for c in cols_agrup_comp}
                        fila_tot_c[next(iter(cols_agrup_comp))] = 'TOTAL GENERAL'
                        fila_tot_c['Cantidad'] = resumen_comp['Cantidad'].sum()
                        fila_tot_c['Monto_Total'] = resumen_comp['Monto_Total'].sum()
                        resumen_comp_tot = pd.concat([resumen_comp, pd.DataFrame([fila_tot_c])], ignore_index=True)

                        vista_cc = resumen_comp_tot.copy()
                        vista_cc['Cantidad'] = vista_cc['Cantidad'].map('{:,.2f}'.format)
                        vista_cc['Monto_Total'] = vista_cc['Monto_Total'].map(lambda x: f"{simb} {x:,.2f}")
                        st.dataframe(vista_cc, use_container_width=True)

                    comp_cat_xl = df_comp.groupby(['Tipo_Movimiento', 'Tipo_Categoria'], as_index=False, dropna=False).agg(
                        Cantidad=('Cantidad', 'sum'), Monto_Total=('Monto_Kardex', 'sum')
                    ).sort_values(by=['Tipo_Movimiento', 'Monto_Total'], ascending=[True, False])

                    cols_item_c = ['Tipo_Movimiento', 'Tipo_Categoria', 'Item'] + ([col_desc_k] if col_desc_k else [])
                    comp_item_xl = df_comp.groupby(cols_item_c, as_index=False, dropna=False).agg(
                        Cantidad=('Cantidad', 'sum'), Monto_Total=('Monto_Kardex', 'sum')
                    ).sort_values(by='Monto_Total', ascending=False)

                    excel_comp = exportar_excel_3_hojas(
                        comp_cat_xl, "1. Por Categoria",
                        comp_item_xl, "2. Por Item",
                        df_comp, "3. Detalle Documentos"
                    )
                    st.download_button(
                        label="📥 Descargar Compras en Excel (3 Hojas)",
                        data=excel_comp,
                        file_name=f"Compras_{empresa}_{p_inicio}_{p_fin}_{moneda}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="dl_kardex_comp"
                    )
        with tab_cons:
            if df_k_filt.empty:
                st.info("No se registran consumos en este periodo.")
            else:
                df_cons = df_k_filt[df_k_filt['Tipo_Movimiento'] == 'CONSUMO'].copy()
                if df_cons.empty:
                    st.info("No se registran consumos en este periodo.")
                else:
                    df_cons['Costo_Consumo'] = df_cons['Monto_Kardex'] * -1
                    st.metric(f"Total Consumos ({moneda})", f"{simb} {df_cons['Costo_Consumo'].sum():,.2f}")

                    st.markdown("---")
                    cs1, cs2 = st.columns(2)
                    with cs1:
                        cons_n1 = st.checkbox("Nivel 1: Categoría", value=True, key="cons_n1")
                    with cs2:
                        cons_n2 = st.checkbox("Nivel 2: Ítems", value=False, key="cons_n2")

                    col_desc_cs = next((c for c in ['DescripcionLocal', 'Descripcion'] if c in df_cons.columns), None)
                    if col_desc_cs:
                        df_cons[col_desc_cs] = df_cons[col_desc_cs].fillna('SIN DESCRIPCIÓN').astype(str).str.strip()

                    cols_agrup_cons = []
                    if cons_n1:
                        cols_agrup_cons.append('Tipo_Categoria')
                    if cons_n2:
                        cols_agrup_cons.append('Item')
                        if col_desc_cs:
                            cols_agrup_cons.append(col_desc_cs)

                    if not cols_agrup_cons:
                        st.info("💡 Activa al menos un nivel de agrupación (Categoría o Ítems) arriba.")
                    else:
                        resumen_cons = df_cons.groupby(cols_agrup_cons, as_index=False, dropna=False).agg(
                            Cantidad=('Cantidad', 'sum'),
                            Monto_Total=('Costo_Consumo', 'sum')
                        ).sort_values(by='Monto_Total', ascending=False).reset_index(drop=True)

                        fila_tot_cs = {c: '' for c in cols_agrup_cons}
                        fila_tot_cs[next(iter(cols_agrup_cons))] = 'TOTAL GENERAL'
                        fila_tot_cs['Cantidad'] = resumen_cons['Cantidad'].sum()
                        fila_tot_cs['Monto_Total'] = resumen_cons['Monto_Total'].sum()
                        resumen_cons_tot = pd.concat([resumen_cons, pd.DataFrame([fila_tot_cs])], ignore_index=True)

                        vista_cons = resumen_cons_tot.copy()
                        vista_cons['Cantidad'] = vista_cons['Cantidad'].map('{:,.2f}'.format)
                        vista_cons['Monto_Total'] = vista_cons['Monto_Total'].map(lambda x: f"{simb} {x:,.2f}")
                        st.dataframe(vista_cons, use_container_width=True)

                    cons_cat_xl = df_cons.groupby(['Tipo_Categoria'], as_index=False, dropna=False).agg(
                        Cantidad=('Cantidad', 'sum'), Monto_Total=('Costo_Consumo', 'sum')
                    ).sort_values(by='Monto_Total', ascending=False)

                    cols_item_cs = ['Tipo_Categoria', 'Item'] + ([col_desc_cs] if col_desc_cs else [])
                    cons_item_xl = df_cons.groupby(cols_item_cs, as_index=False, dropna=False).agg(
                        Cantidad=('Cantidad', 'sum'), Monto_Total=('Costo_Consumo', 'sum')
                    ).sort_values(by='Monto_Total', ascending=False)

                    excel_cons = exportar_excel_3_hojas(
                        cons_cat_xl, "1. Por Categoria",
                        cons_item_xl, "2. Por Item",
                        df_cons, "3. Detalle Movimientos"
                    )
                    st.download_button(
                        label="📥 Descargar Consumos en Excel (3 Hojas)",
                        data=excel_cons,
                        file_name=f"Consumos_{empresa}_{p_inicio}_{p_fin}_{moneda}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="dl_kardex_cons"
                    )

        with tab_prod:
            if df_k_filt.empty:
                st.info("No se registran movimientos de producción (API / PRI) en este periodo.")
            else:
                df_prod = df_k_filt[df_k_filt['Tipo_Movimiento'] == 'PRODUCCION'].copy()
                if df_prod.empty:
                    st.info("No se registran movimientos de producción (API / PRI) en este periodo.")
                else:
                    st.metric(f"Valorización Producción ({moneda})", f"{simb} {df_prod['Monto_Kardex'].sum():,.2f}")

                    st.markdown("---")
                    pr1, pr2 = st.columns(2)
                    with pr1:
                        prod_n1 = st.checkbox("Nivel 1: Categoría", value=True, key="prod_n1")
                    with pr2:
                        prod_n2 = st.checkbox("Nivel 2: Ítems", value=False, key="prod_n2")

                    col_desc_pr = next((c for c in ['DescripcionLocal', 'Descripcion'] if c in df_prod.columns), None)
                    if col_desc_pr:
                        df_prod[col_desc_pr] = df_prod[col_desc_pr].fillna('SIN DESCRIPCIÓN').astype(str).str.strip()

                    cols_agrup_prod = []
                    if prod_n1:
                        cols_agrup_prod.append('Tipo_Categoria')
                    if prod_n2:
                        cols_agrup_prod.append('Item')
                        if col_desc_pr:
                            cols_agrup_prod.append(col_desc_pr)

                    if not cols_agrup_prod:
                        st.info("💡 Activa al menos un nivel de agrupación (Categoría o Ítems) arriba.")
                    else:
                        resumen_prod = df_prod.groupby(cols_agrup_prod, as_index=False, dropna=False).agg(
                            Cantidad=('Cantidad', 'sum'),
                            Monto_Total=('Monto_Kardex', 'sum')
                        ).sort_values(by='Monto_Total', ascending=False).reset_index(drop=True)

                        fila_tot_pr = {c: '' for c in cols_agrup_prod}
                        fila_tot_pr[next(iter(cols_agrup_prod))] = 'TOTAL GENERAL'
                        fila_tot_pr['Cantidad'] = resumen_prod['Cantidad'].sum()
                        fila_tot_pr['Monto_Total'] = resumen_prod['Monto_Total'].sum()
                        resumen_prod_tot = pd.concat([resumen_prod, pd.DataFrame([fila_tot_pr])], ignore_index=True)

                        vista_prod = resumen_prod_tot.copy()
                        vista_prod['Cantidad'] = vista_prod['Cantidad'].map('{:,.2f}'.format)
                        vista_prod['Monto_Total'] = vista_prod['Monto_Total'].map(lambda x: f"{simb} {x:,.2f}")
                        st.dataframe(vista_prod, use_container_width=True)

                    prod_cat_xl = df_prod.groupby(['Tipo_Categoria'], as_index=False, dropna=False).agg(
                        Cantidad=('Cantidad', 'sum'), Monto_Total=('Monto_Kardex', 'sum')
                    ).sort_values(by='Monto_Total', ascending=False)

                    cols_item_pr = ['Tipo_Categoria', 'Item'] + ([col_desc_pr] if col_desc_pr else [])
                    prod_item_xl = df_prod.groupby(cols_item_pr, as_index=False, dropna=False).agg(
                        Cantidad=('Cantidad', 'sum'), Monto_Total=('Monto_Kardex', 'sum')
                    ).sort_values(by='Monto_Total', ascending=False)

                    excel_prod = exportar_excel_3_hojas(
                        prod_cat_xl, "1. Por Categoria",
                        prod_item_xl, "2. Por Item",
                        df_prod, "3. Detalle Produccion"
                    )
                    st.download_button(
                        label="📥 Descargar Producción en Excel (3 Hojas)",
                        data=excel_prod,
                        file_name=f"Produccion_{empresa}_{p_inicio}_{p_fin}_{moneda}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="dl_kardex_prod"
                    )

    except Exception as e:
        st.error(f"❌ Error al procesar el archivo Kardex: {e}")
