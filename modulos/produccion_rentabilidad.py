import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io
import gc

@st.cache_data(show_spinner="Procesando Kardex para Producción...")
def cargar_kardex_prod(archivo):
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

def cruzar_produccion_costo_venta(df_k_all, df_v_all, df_tc, df_maestro, cols_m, empresa, moneda, p_ini, p_fin):
    mask_base = (
        (df_k_all['CompaniaSocio'] == empresa) &
        (df_k_all['Periodo'] >= str(p_ini)) &
        (df_k_all['Periodo'] <= str(p_fin))
    )
    df_k_per = df_k_all.loc[mask_base].copy()
    if df_k_per.empty:
        return pd.DataFrame()

    df_k_per['Cantidad'] = pd.to_numeric(df_k_per['Cantidad'], errors='coerce').fillna(0)
    col_monto_k = 'MontoTotal' if moneda == 'SOLES' else 'MontoTotalDolares'
    df_k_per['Monto_Kardex'] = pd.to_numeric(df_k_per[col_monto_k], errors='coerce').fillna(0)

    # 1. Universo exclusivo de ítems con movimiento de PRODUCCIÓN (API / PRI)
    df_prod = df_k_per[df_k_per['TransaccionCodigo'].isin(['API', 'PRI'])].copy()
    if df_prod.empty:
        return pd.DataFrame()

    prod_agg = df_prod.groupby('Item', as_index=False).agg(
        Cant_Prod=('Cantidad', 'sum'),
        Monto_Prod=('Monto_Kardex', 'sum')
    )
    items_producidos = set(prod_agg['Item'])

    # 2. Costos de venta (Kardex) únicamente de los ítems producidos
    df_kv = df_k_per[
        (df_k_per['TransaccionCodigo'].isin(['AVT', 'VTA', 'VTI'])) &
        (df_k_per['Item'].isin(items_producidos))
    ].copy()
    del df_k_per, df_prod

    if df_kv.empty:
        df_res = prod_agg.copy()
        df_res['Cant_Desp'] = 0.0
        df_res['Costo_Venta'] = 0.0
        df_res['Cant_Vendida'] = 0.0
        df_res['Monto_Venta'] = 0.0
    else:
        df_kv['Doc_Cruce'] = df_kv['ReferenciaNumeroDocumento.1'].fillna('').astype(str).str.strip()
        df_kv['Costo_Pos'] = df_kv['Monto_Kardex'] * -1

        k_doc_agg = df_kv.groupby(['Doc_Cruce', 'Item'], as_index=False).agg(
            Cant_Desp=('Cantidad', 'sum'),
            Costo_Venta=('Costo_Pos', 'sum')
        )
        del df_kv

        # 3. Ventas cruzadas por documento sin restricción de periodo
        df_v_emp = df_v_all.loc[df_v_all['CompaniaSocio'].astype(str).str.strip() == empresa].copy()
        df_v_emp['Doc_Cruce'] = df_v_emp['NumeroDocumento'].fillna('').astype(str).str.strip()
        df_v_emp['Item'] = df_v_emp['ItemCodigo'].astype(str).str.strip()

        llaves = set(zip(k_doc_agg['Doc_Cruce'], k_doc_agg['Item']))
        df_v_emp = df_v_emp[df_v_emp.set_index(['Doc_Cruce', 'Item']).index.isin(llaves)].copy()

        df_v_emp['Fecha_Clave'] = df_v_emp['FechaDocumento'].astype(str).str.slice(0, 10).str.strip()
        df_v_emp = pd.merge(df_v_emp, df_tc[['Fecha_Clave_Busqueda', 'Oficial Venta']], left_on='Fecha_Clave', right_on='Fecha_Clave_Busqueda', how='left')
        df_v_emp['Oficial Venta'] = df_v_emp['Oficial Venta'].ffill()

        df_v_emp['Monto'] = pd.to_numeric(df_v_emp['Monto'], errors='coerce').fillna(0)
        df_v_emp['CantidadPedida'] = pd.to_numeric(df_v_emp['CantidadPedida'], errors='coerce').fillna(0)

        cond_ex_sol = (moneda == 'SOLES') & (df_v_emp['MonedaDocumento'] == 'EX')
        cond_lo_dol = (moneda == 'DÓLARES') & (df_v_emp['MonedaDocumento'] == 'LO')
        df_v_emp['Venta_Conv'] = np.where(
            cond_ex_sol, df_v_emp['Monto'] * df_v_emp['Oficial Venta'],
            np.where(cond_lo_dol, df_v_emp['Monto'] / df_v_emp['Oficial Venta'], df_v_emp['Monto'])
        )

        v_doc_agg = df_v_emp.groupby(['Doc_Cruce', 'Item'], as_index=False).agg(
            Cant_Vendida=('CantidadPedida', 'sum'),
            Monto_Venta=('Venta_Conv', 'sum')
        )
        del df_v_emp

        cruce_cv = pd.merge(k_doc_agg, v_doc_agg, on=['Doc_Cruce', 'Item'], how='left').fillna({'Cant_Vendida': 0, 'Monto_Venta': 0})
        cv_item = cruce_cv.groupby('Item', as_index=False).agg(
            Cant_Desp=('Cant_Desp', 'sum'),
            Costo_Venta=('Costo_Venta', 'sum'),
            Cant_Vendida=('Cant_Vendida', 'sum'),
            Monto_Venta=('Monto_Venta', 'sum')
        )
        del k_doc_agg, v_doc_agg, cruce_cv

        # Left join desde prod_agg para mantener ítems producidos sin ventas en el mes
        df_res = pd.merge(prod_agg, cv_item, on='Item', how='left').fillna({
            'Cant_Desp': 0.0, 'Costo_Venta': 0.0, 'Cant_Vendida': 0.0, 'Monto_Venta': 0.0
        })
        del cv_item

    gc.collect()
    df_res['Utilidad'] = df_res['Monto_Venta'] - df_res['Costo_Venta']
    df_res = pd.merge(df_res, df_maestro[cols_m], on='Item', how='left')
    df_res['Tipo_Categoria'] = df_res['Tipo_Categoria'].fillna('SIN CATEGORÍA').str.strip()
    df_res['Marca_Descripcion'] = df_res['Marca_Descripcion'].fillna('SIN MARCA').str.strip()
    if 'Descripcion' in df_res.columns:
        df_res['Descripcion'] = df_res['Descripcion'].fillna('SIN DESCRIPCIÓN').str.strip()

    return df_res
def render(ctx):
    df_ventas_all = ctx.get("df_ventas")
    df_tc = ctx.get("df_tc")
    df_maestro = ctx.get("df_maestro")
    empresa = ctx["empresa"]
    moneda = ctx["moneda"]
    p_inicio = str(ctx["p_inicio"]).strip()
    p_fin = str(ctx["p_fin"]).strip()
    simb = "S/" if moneda == 'SOLES' else "$"

    st.subheader(f"⚙️ Producción vs. Costo vs. Venta ({moneda})")

    uploaded_k_pr = st.file_uploader(
        "📂 Sube el archivo Kardex (.parquet o .xlsx) para cruzar Producción, Costos y Ventas:",
        type=["parquet", "xlsx"],
        key="uploader_kardex_prod_cv"
    )

    if not uploaded_k_pr:
        st.info("👆 Primero sube el archivo Kardex aquí arriba para analizar los ítems de producción.")
        return

    if df_ventas_all is None:
        st.error("⚠️ Falta `'df_ventas'` en el contexto de `app.py`.")
        return

    try:
        df_k = cargar_kardex_prod(uploaded_k_pr)
        df_k['CompaniaSocio'] = df_k['CompaniaSocio'].astype(str).str.strip()
        df_k['Periodo'] = df_k['Periodo'].astype(str).str.strip()
        df_k['TransaccionCodigo'] = df_k['TransaccionCodigo'].astype(str).str.strip().str.upper()
        df_k['Item'] = df_k['Item'].astype(str).str.strip()

        df_m = df_maestro.copy()
        df_m['Item'] = df_m['Item'].astype(str).str.strip()
        cols_m = ['Item', 'Tipo_Categoria', 'Marca_Descripcion']
        if 'Descripcion' in df_m.columns:
            cols_m.append('Descripcion')

        modo_pr = st.radio(
            "Modo de visualización:",
            ["📅 Periodo Actual", "📊 Comparativo Interanual (Año Anterior vs. Actual)"],
            horizontal=True,
            key="modo_prod_cv_radio"
        )
        st.markdown("---")

        c1, c2, c3 = st.columns(3)
        with c1:
            p_n1 = st.checkbox("Nivel 1: Categoría", value=True, key="pcv_n1")
        with c2:
            p_n2 = st.checkbox("Nivel 2: Marca", value=False, key="pcv_n2")
        with c3:
            p_n3 = st.checkbox("Nivel 3: Ítems", value=False, key="pcv_n3")

        cols_agrup = []
        if p_n1: cols_agrup.append('Tipo_Categoria')
        if p_n2: cols_agrup.append('Marca_Descripcion')
        if p_n3:
            cols_agrup.append('Item')
            if 'Descripcion' in df_m.columns:
                cols_agrup.append('Descripcion')
        if modo_pr == "📅 Periodo Actual":
            st.markdown(f"### Consolidado de Ítems Producidos ({p_inicio} - {p_fin} | {moneda})")
            df_pcv = cruzar_produccion_costo_venta(
                df_k, df_ventas_all, df_tc, df_m, cols_m, empresa, moneda, p_inicio, p_fin
            )

            if df_pcv.empty:
                st.warning(f"⚠️ No se encontraron movimientos de producción (API / PRI) para {empresa} en el rango {p_inicio} - {p_fin}.")
                return

            tot_prod = df_pcv['Monto_Prod'].sum()
            tot_cost = df_pcv['Costo_Venta'].sum()
            tot_vent = df_pcv['Monto_Venta'].sum()
            tot_util = tot_vent - tot_cost
            margen = (tot_util / tot_vent * 100) if tot_vent != 0 else 0.0

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Valor Producción", f"{simb} {tot_prod:,.2f}")
            k2.metric("Costo Venta (Prod.)", f"{simb} {tot_cost:,.2f}")
            k3.metric("Venta Cruzada (Prod.)", f"{simb} {tot_vent:,.2f}")
            k4.metric("Utilidad / Margen", f"{simb} {tot_util:,.2f}", f"Margen: {margen:.2f}%")

            if not cols_agrup:
                st.info("💡 Activa al menos un nivel de agrupación arriba.")
                return

            resumen = df_pcv.groupby(cols_agrup, as_index=False, dropna=False).agg(
                Cant_Prod=('Cant_Prod', 'sum'),
                Monto_Prod=('Monto_Prod', 'sum'),
                Cant_Vendida=('Cant_Vendida', 'sum'),
                Costo_Venta=('Costo_Venta', 'sum'),
                Monto_Venta=('Monto_Venta', 'sum'),
                Utilidad=('Utilidad', 'sum')
            ).sort_values(by='Monto_Prod', ascending=False).reset_index(drop=True)

            resumen['Margen_%'] = np.where(resumen['Monto_Venta'] != 0, (resumen['Utilidad'] / resumen['Monto_Venta']) * 100, 0)

            fila_tot = {c: '' for c in cols_agrup}
            fila_tot[next(iter(cols_agrup))] = 'TOTAL GENERAL'
            fila_tot['Cant_Prod'] = resumen['Cant_Prod'].sum()
            fila_tot['Monto_Prod'] = resumen['Monto_Prod'].sum()
            fila_tot['Cant_Vendida'] = resumen['Cant_Vendida'].sum()
            fila_tot['Costo_Venta'] = resumen['Costo_Venta'].sum()
            fila_tot['Monto_Venta'] = resumen['Monto_Venta'].sum()
            fila_tot['Utilidad'] = resumen['Utilidad'].sum()
            fila_tot['Margen_%'] = margen

            resumen_export = pd.concat([resumen, pd.DataFrame([fila_tot])], ignore_index=True)

            vista = resumen_export.copy()
            for col_c in ['Cant_Prod', 'Cant_Vendida']:
                vista[col_c] = vista[col_c].map('{:,.2f}'.format)
            for col_m in ['Monto_Prod', 'Costo_Venta', 'Monto_Venta', 'Utilidad']:
                vista[col_m] = vista[col_m].map(lambda x: f"{simb} {x:,.2f}")
            vista['Margen_%'] = vista['Margen_%'].map('{:.2f}%'.format)

            st.dataframe(vista, use_container_width=True)

            # Hoja 2 Excel: Nivel Categoría y Marca
            xl_cat_marca = df_pcv.groupby(['Tipo_Categoria', 'Marca_Descripcion'], as_index=False, dropna=False).agg(
                Cant_Prod=('Cant_Prod', 'sum'), Monto_Prod=('Monto_Prod', 'sum'),
                Cant_Vendida=('Cant_Vendida', 'sum'), Costo_Venta=('Costo_Venta', 'sum'),
                Monto_Venta=('Monto_Venta', 'sum'), Utilidad=('Utilidad', 'sum')
            ).sort_values(by='Monto_Prod', ascending=False)

            excel_data = exportar_excel_3_hojas(
                resumen_export, "1. Resumen Gerencial",
                xl_cat_marca, "2. Categoria y Marca",
                df_pcv, "3. Detalle por Item"
            )
            st.download_button(
                label="📥 Descargar Producción vs Costo vs Venta en Excel (3 Hojas)",
                data=excel_data,
                file_name=f"Prod_Costo_Venta_{empresa}_{p_inicio}_{p_fin}_{moneda}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_prod_cv_act"
            )
        else:
            p_inicio_ant = str(int(p_inicio) - 100)
            p_fin_ant    = str(int(p_fin) - 100)
            anio_act     = p_inicio[:4]
            anio_ant     = p_inicio_ant[:4]

            st.markdown(f"### Comparativo Interanual Producción: {anio_ant} (`{p_inicio_ant}-{p_fin_ant}`) vs. {anio_act} (`{p_inicio}-{p_fin}`)")

            df_ant = cruzar_produccion_costo_venta(
                df_k, df_ventas_all, df_tc, df_m, cols_m, empresa, moneda, p_inicio_ant, p_fin_ant
            )
            df_act = cruzar_produccion_costo_venta(
                df_k, df_ventas_all, df_tc, df_m, cols_m, empresa, moneda, p_inicio, p_fin
            )

            if df_ant.empty and df_act.empty:
                st.warning("⚠️ No se encontraron datos de producción en ninguno de los dos periodos.")
                return

            pr_ant = df_ant['Monto_Prod'].sum() if not df_ant.empty else 0.0
            co_ant = df_ant['Costo_Venta'].sum() if not df_ant.empty else 0.0
            ve_ant = df_ant['Monto_Venta'].sum() if not df_ant.empty else 0.0

            pr_act = df_act['Monto_Prod'].sum() if not df_act.empty else 0.0
            co_act = df_act['Costo_Venta'].sum() if not df_act.empty else 0.0
            ve_act = df_act['Monto_Venta'].sum() if not df_act.empty else 0.0

            var_pr = ((pr_act - pr_ant) / abs(pr_ant) * 100) if pr_ant != 0 else 0.0
            var_co = ((co_act - co_ant) / abs(co_ant) * 100) if co_ant != 0 else 0.0
            var_ve = ((ve_act - ve_ant) / abs(ve_ant) * 100) if ve_ant != 0 else 0.0

            k1, k2, k3 = st.columns(3)
            k1.metric(f"Producción {anio_act} vs {anio_ant}", f"{simb} {pr_act:,.2f}", f"{var_pr:+.2f}% ({simb} {pr_act - pr_ant:+,.0f})")
            k2.metric(f"Costo Venta {anio_act} vs {anio_ant}", f"{simb} {co_act:,.2f}", f"{var_co:+.2f}% ({simb} {co_act - co_ant:+,.0f})", delta_color="inverse")
            k3.metric(f"Venta Prod. {anio_act} vs {anio_ant}", f"{simb} {ve_act:,.2f}", f"{var_ve:+.2f}% ({simb} {ve_act - ve_ant:+,.0f})")

            # Gráficos Top 5 Categorías (Producción y Ventas)
            g_ant = df_ant.groupby('Tipo_Categoria', as_index=False).agg(
                Prod_Ant=('Monto_Prod', 'sum'), Venta_Ant=('Monto_Venta', 'sum')
            ) if not df_ant.empty else pd.DataFrame(columns=['Tipo_Categoria', 'Prod_Ant', 'Venta_Ant'])

            g_act = df_act.groupby('Tipo_Categoria', as_index=False).agg(
                Prod_Act=('Monto_Prod', 'sum'), Venta_Act=('Monto_Venta', 'sum')
            ) if not df_act.empty else pd.DataFrame(columns=['Tipo_Categoria', 'Prod_Act', 'Venta_Act'])

            top5 = pd.merge(g_ant, g_act, on='Tipo_Categoria', how='outer').fillna(0)
            top5 = top5.sort_values(by='Prod_Act', ascending=False).head(5).copy()

            g1, g2 = st.columns(2)
            with g1:
                df_gp = pd.melt(top5, id_vars=['Tipo_Categoria'], value_vars=['Prod_Ant', 'Prod_Act'], var_name='Periodo', value_name='Monto')
                df_gp['Periodo'] = df_gp['Periodo'].replace({'Prod_Ant': f'Prod. {anio_ant}', 'Prod_Act': f'Prod. {anio_act}'})
                fig_p = px.bar(
                    df_gp, x='Tipo_Categoria', y='Monto', color='Periodo', barmode='group', text_auto=',.0f',
                    title=f'Top 5 Categorías - Producción ({anio_ant} vs {anio_act})',
                    labels={'Tipo_Categoria': '', 'Monto': f'Producción ({simb})'},
                    color_discrete_sequence=['#E59866', '#D35400']
                )
                fig_p.update_traces(textposition='outside')
                fig_p.update_layout(height=400, margin=dict(t=40, b=20))
                st.plotly_chart(fig_p, use_container_width=True)

            with g2:
                df_gv = pd.melt(top5, id_vars=['Tipo_Categoria'], value_vars=['Venta_Ant', 'Venta_Act'], var_name='Periodo', value_name='Monto')
                df_gv['Periodo'] = df_gv['Periodo'].replace({'Venta_Ant': f'Venta {anio_ant}', 'Venta_Act': f'Venta {anio_act}'})
                fig_v = px.bar(
                    df_gv, x='Tipo_Categoria', y='Monto', color='Periodo', barmode='group', text_auto=',.0f',
                    title=f'Top 5 Categorías - Ventas de Prod. ({anio_ant} vs {anio_act})',
                    labels={'Tipo_Categoria': '', 'Monto': f'Ventas ({simb})'},
                    color_discrete_sequence=['#85929E', '#1F618D']
                )
                fig_v.update_traces(textposition='outside')
                fig_v.update_layout(height=400, margin=dict(t=40, b=20))
                st.plotly_chart(fig_v, use_container_width=True)
            if not cols_agrup:
                st.info("💡 Activa al menos un nivel de agrupación arriba para ver la tabla comparativa.")
                return

            def armar_comparativo_pcv(keys):
                a1 = df_ant.groupby(keys, as_index=False, dropna=False).agg(
                    Cant_Prod_Ant=('Cant_Prod', 'sum'), Prod_Ant=('Monto_Prod', 'sum'),
                    Costo_Ant=('Costo_Venta', 'sum'), Venta_Ant=('Monto_Venta', 'sum')
                ) if not df_ant.empty else pd.DataFrame(columns=keys + ['Cant_Prod_Ant', 'Prod_Ant', 'Costo_Ant', 'Venta_Ant'])

                a2 = df_act.groupby(keys, as_index=False, dropna=False).agg(
                    Cant_Prod_Act=('Cant_Prod', 'sum'), Prod_Act=('Monto_Prod', 'sum'),
                    Costo_Act=('Costo_Venta', 'sum'), Venta_Act=('Monto_Venta', 'sum')
                ) if not df_act.empty else pd.DataFrame(columns=keys + ['Cant_Prod_Act', 'Prod_Act', 'Costo_Act', 'Venta_Act'])

                comp = pd.merge(a1, a2, on=keys, how='outer').fillna(0)
                comp['Var_Prod_%'] = np.where(comp['Prod_Ant'] != 0, ((comp['Prod_Act'] - comp['Prod_Ant']) / comp['Prod_Ant'].abs()) * 100, 0)
                comp['Var_Venta_%'] = np.where(comp['Venta_Ant'] != 0, ((comp['Venta_Act'] - comp['Venta_Ant']) / comp['Venta_Ant'].abs()) * 100, 0)
                comp = comp.sort_values(by='Prod_Act', ascending=False).reset_index(drop=True)

                ft = {c: '' for c in keys}
                ft[next(iter(keys))] = 'TOTAL GENERAL'
                ft['Cant_Prod_Ant'] = comp['Cant_Prod_Ant'].sum()
                ft['Cant_Prod_Act'] = comp['Cant_Prod_Act'].sum()
                ft['Prod_Ant']      = comp['Prod_Ant'].sum()
                ft['Prod_Act']      = comp['Prod_Act'].sum()
                ft['Var_Prod_%']    = var_pr
                ft['Costo_Ant']     = comp['Costo_Ant'].sum()
                ft['Costo_Act']     = comp['Costo_Act'].sum()
                ft['Venta_Ant']     = comp['Venta_Ant'].sum()
                ft['Venta_Act']     = comp['Venta_Act'].sum()
                ft['Var_Venta_%']   = var_ve

                comp_tot = pd.concat([comp, pd.DataFrame([ft])], ignore_index=True)
                comp_tot = comp_tot.rename(columns={
                    'Cant_Prod_Ant': f'Cant_Prod_{anio_ant}', 'Cant_Prod_Act': f'Cant_Prod_{anio_act}',
                    'Prod_Ant': f'Prod_{anio_ant}', 'Prod_Act': f'Prod_{anio_act}',
                    'Costo_Ant': f'Costo_{anio_ant}', 'Costo_Act': f'Costo_{anio_act}',
                    'Venta_Ant': f'Venta_{anio_ant}', 'Venta_Act': f'Venta_{anio_act}'
                })
                return comp_tot

            comp_ger = armar_comparativo_pcv(cols_agrup)

            vista_c = comp_ger.copy()
            for col_q in [f'Cant_Prod_{anio_ant}', f'Cant_Prod_{anio_act}']:
                vista_c[col_q] = vista_c[col_q].map('{:,.2f}'.format)
            for col_m in [f'Prod_{anio_ant}', f'Prod_{anio_act}', f'Costo_{anio_ant}', f'Costo_{anio_act}', f'Venta_{anio_ant}', f'Venta_{anio_act}']:
                vista_c[col_m] = vista_c[col_m].map(lambda x: f"{simb} {x:,.2f}")
            for col_p in ['Var_Prod_%', 'Var_Venta_%']:
                vista_c[col_p] = vista_c[col_p].map('{:+.2f}%'.format)

            st.markdown(f"**Tabla Comparativa ({anio_ant} vs. {anio_act})**")
            st.dataframe(vista_c, use_container_width=True)

            keys_item = ['Tipo_Categoria', 'Marca_Descripcion', 'Item'] + (['Descripcion'] if 'Descripcion' in df_m.columns else [])
            comp_item = armar_comparativo_pcv(keys_item)

            excel_comp = exportar_excel_3_hojas(
                comp_ger, "1. Comparativo Gerencial",
                comp_item, "2. Comparativo por Item",
                df_act, f"3. Detalle {anio_act}"
            )
            st.download_button(
                label=f"📥 Descargar Comparativo {anio_ant} vs {anio_act} en Excel (3 Hojas)",
                data=excel_comp,
                file_name=f"Comparativo_Prod_Costo_Venta_{anio_ant}_vs_{anio_act}_{empresa}_{p_inicio}_{p_fin}_{moneda}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_prod_cv_comp"
            )

    except Exception as e:
        st.error(f"❌ Error al procesar Producción vs. Costo vs. Venta: {e}")

