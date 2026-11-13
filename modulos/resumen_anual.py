import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io
import gc

MESES_NOMBRES = {
    '01': 'Ene', '02': 'Feb', '03': 'Mar', '04': 'Abr',
    '05': 'May', '06': 'Jun', '07': 'Jul', '08': 'Ago',
    '09': 'Sep', '10': 'Oct', '11': 'Nov', '12': 'Dic'
}

def cargar_kardex_anual(archivo):
    if archivo.name.endswith('.parquet'):
        return pd.read_parquet(archivo)
    return pd.read_excel(archivo, dtype=str)

def construir_matriz_anual(df_datos, cols_agrup, col_valor, anio, simb):
    """Genera tabla matricial Ene..Dic + Total Anual con fila de TOTAL GENERAL."""
    if df_datos.empty:
        return pd.DataFrame(), pd.DataFrame()

    df_tmp = df_datos.copy()
    df_tmp['Mes'] = df_tmp['Periodo_Mes'].str.slice(4, 6).map(MESES_NOMBRES).fillna('Otros')

    piv = df_tmp.pivot_table(
        index=cols_agrup,
        columns='Mes',
        values=col_valor,
        aggfunc='sum',
        fill_value=0
    ).reset_index()

    orden_meses = [m for m in MESES_NOMBRES.values() if m in piv.columns]
    cols_finales = cols_agrup + orden_meses
    piv = piv[cols_finales].copy()

    piv['Total Anual'] = piv[orden_meses].sum(axis=1)
    piv = piv.sort_values(by='Total Anual', ascending=False).reset_index(drop=True)

    # Fila Total General
    fila_tot = {c: '' for c in cols_agrup}
    fila_tot[cols_agrup[0]] = 'TOTAL GENERAL'
    for m in orden_meses:
        fila_tot[m] = piv[m].sum()
    fila_tot['Total Anual'] = piv['Total Anual'].sum()

    piv_export = pd.concat([piv, pd.DataFrame([fila_tot])], ignore_index=True)

    piv_vista = piv_export.copy()
    for col_num in orden_meses + ['Total Anual']:
        piv_vista[col_num] = piv_vista[col_num].map(lambda x: f"{simb} {x:,.2f}")

    return piv_vista, piv_export
def render(ctx):
    df_ventas_all = ctx.get("df_ventas")
    df_tc = ctx.get("df_tc")
    df_maestro = ctx.get("df_maestro")
    empresa = ctx["empresa"]
    moneda = ctx["moneda"]
    p_inicio = str(ctx["p_inicio"])
    anio = p_inicio[:4]
    simb = "S/" if moneda == 'SOLES' else "$"

    st.subheader(f"📈 Resumen Ejecutivo Anual {anio} - Mes a Mes ({moneda})")

    c1, c2 = st.columns(2)
    with c1:
        an_n1 = st.checkbox("Nivel 1: Categoría", value=True, key="an_n1")
    with c2:
        an_n2 = st.checkbox("Nivel 2: Ítems", value=False, key="an_n2")

    cols_agrup = []
    if an_n1: cols_agrup.append('Tipo_Categoria')
    if an_n2:
        cols_agrup.append('Item')
        if 'Descripcion' in df_maestro.columns:
            cols_agrup.append('Descripcion')

    if not cols_agrup:
        st.info("💡 Activa al menos un nivel de agrupación (Categoría o Ítems) arriba.")
        return

    # Preparar maestro limpio
    df_m = df_maestro.copy()
    df_m['Item'] = df_m['Item'].astype(str).str.strip()
    cols_m = ['Item', 'Tipo_Categoria'] + (['Descripcion'] if 'Descripcion' in df_m.columns else [])

    # Procesar Ventas de todo el año seleccionado (Ene a Dic)
    p_ini_anio = f"{anio}01"
    p_fin_anio = f"{anio}12"

    df_v_anio = df_ventas_all[
        (df_ventas_all['CompaniaSocio'].astype(str).str.strip() == empresa) &
        (df_ventas_all['VoucherPeriodo'].astype(str).str.strip() >= p_ini_anio) &
        (df_ventas_all['VoucherPeriodo'].astype(str).str.strip() <= p_fin_anio)
    ].copy()

    if not df_v_anio.empty:
        df_v_anio['Periodo_Mes'] = df_v_anio['VoucherPeriodo'].astype(str).str.strip()
        df_v_anio['Item'] = df_v_anio['ItemCodigo'].astype(str).str.strip()
        df_v_anio['Fecha_Clave'] = df_v_anio['FechaDocumento'].astype(str).str.slice(0, 10).str.strip()

        df_v_anio = pd.merge(df_v_anio, df_tc[['Fecha_Clave_Busqueda', 'Oficial Venta']], left_on='Fecha_Clave', right_on='Fecha_Clave_Busqueda', how='left')
        df_v_anio['Oficial Venta'] = df_v_anio['Oficial Venta'].ffill()

        df_v_anio['Monto'] = pd.to_numeric(df_v_anio['Monto'], errors='coerce').fillna(0)
        cond_ex_sol = (moneda == 'SOLES') & (df_v_anio['MonedaDocumento'] == 'EX')
        cond_lo_dol = (moneda == 'DÓLARES') & (df_v_anio['MonedaDocumento'] == 'LO')
        df_v_anio['Monto_Conv'] = np.where(
            cond_ex_sol, df_v_anio['Monto'] * df_v_anio['Oficial Venta'],
            np.where(cond_lo_dol, df_v_anio['Monto'] / df_v_anio['Oficial Venta'], df_v_anio['Monto'])
        )

        df_v_anio = pd.merge(df_v_anio, df_m[cols_m], on='Item', how='left')
        df_v_anio['Tipo_Categoria'] = df_v_anio['Tipo_Categoria'].fillna('SIN CATEGORÍA').str.strip()
        if 'Descripcion' in df_v_anio.columns:
            df_v_anio['Descripcion'] = df_v_anio['Descripcion'].fillna('SIN DESCRIPCIÓN').str.strip()

    tab_v_anual, tab_vc_anual, tab_p_anual = st.tabs([
        "💵 Ventas Mensuales",
        "💰 Ventas vs. Costo Kardex (Mensual)",
        "⚙️ Producción Mensual"
    ])
    with tab_v_anual:
        if df_v_anio.empty:
            st.warning(f"⚠️ No se encontraron ventas registradas para la empresa {empresa} en el año {anio}.")
        else:
            tot_v_anual = df_v_anio['Monto_Conv'].sum()
            st.metric(f"Total Ventas Acumuladas {anio} ({moneda})", f"{simb} {tot_v_anual:,.2f}")

            # Gráfico evolución mensual
            graf_v = df_v_anio.groupby('Periodo_Mes', as_index=False)['Monto_Conv'].sum().sort_values('Periodo_Mes')
            graf_v['Mes'] = graf_v['Periodo_Mes'].str.slice(4, 6).map(MESES_NOMBRES)

            fig_v = px.bar(
                graf_v, x='Mes', y='Monto_Conv', text_auto=',.0f',
                title=f'Evolución Mensual de Ventas {anio} ({moneda})',
                labels={'Mes': '', 'Monto_Conv': f'Ventas ({simb})'},
                color_discrete_sequence=['#1F618D']
            )
            fig_v.update_traces(textposition='outside')
            fig_v.update_layout(height=380, margin=dict(t=40, b=20))
            st.plotly_chart(fig_v, use_container_width=True)

            vista_v, export_v = construir_matriz_anual(df_v_anio, cols_agrup, 'Monto_Conv', anio, simb)
            st.dataframe(vista_v, use_container_width=True)

            buf_v = io.BytesIO()
            with pd.ExcelWriter(buf_v, engine='openpyxl') as writer:
                export_v.to_excel(writer, sheet_name=f'Ventas_{anio}', index=False)

            st.download_button(
                label=f"📥 Descargar Ventas Mensuales {anio} en Excel",
                data=buf_v.getvalue(),
                file_name=f"Ventas_Anual_{anio}_{empresa}_{moneda}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_anual_ventas"
            )
    # Control de carga de Kardex para las pestañas 2 y 3
    st.markdown("---")
    uploaded_k_anual = st.file_uploader(
        "📂 Sube el archivo Kardex (.parquet o .xlsx) para activar Ventas vs. Costo y Producción Anual:",
        type=["parquet", "xlsx"],
        key="uploader_kardex_anual"
    )

    df_k_anio = pd.DataFrame()
    if uploaded_k_anual is not None:
        df_k_raw = cargar_kardex_anual(uploaded_k_anual)
        df_k_raw['CompaniaSocio'] = df_k_raw['CompaniaSocio'].astype(str).str.strip()
        df_k_raw['Periodo'] = df_k_raw['Periodo'].astype(str).str.strip()

        df_k_anio = df_k_raw[
            (df_k_raw['CompaniaSocio'] == empresa) &
            (df_k_raw['Periodo'] >= p_ini_anio) &
            (df_k_raw['Periodo'] <= p_fin_anio)
        ].copy()
        del df_k_raw
        gc.collect()

        if not df_k_anio.empty:
            df_k_anio['Periodo_Mes'] = df_k_anio['Periodo']
            df_k_anio['TransaccionCodigo'] = df_k_anio['TransaccionCodigo'].astype(str).str.strip().str.upper()
            df_k_anio['Item'] = df_k_anio['Item'].astype(str).str.strip()
            col_monto_k = 'MontoTotal' if moneda == 'SOLES' else 'MontoTotalDolares'
            df_k_anio['Monto_Kardex'] = pd.to_numeric(df_k_anio[col_monto_k], errors='coerce').fillna(0)

            df_k_anio = pd.merge(df_k_anio, df_m[cols_m], on='Item', how='left')
            df_k_anio['Tipo_Categoria'] = df_k_anio['Tipo_Categoria'].fillna('SIN CATEGORÍA').str.strip()
            if 'Descripcion' in df_k_anio.columns:
                df_k_anio['Descripcion'] = df_k_anio['Descripcion'].fillna('SIN DESCRIPCIÓN').str.strip()

    with tab_vc_anual:
        if uploaded_k_anual is None:
            st.info("👆 Primero sube el archivo Kardex aquí abajo para visualizar el reporte cruzado de Ventas vs. Costo.")
        elif df_k_anio.empty:
            st.warning(f"⚠️ No hay movimientos en el Kardex para {empresa} en el año {anio}.")
        else:
            df_kv = df_k_anio[df_k_anio['TransaccionCodigo'].isin(['AVT', 'VTA', 'VTI'])].copy()
            if df_kv.empty:
                st.warning("⚠️ No se encontraron salidas por venta en el Kardex para este año.")
            else:
                df_kv['Doc_Cruce'] = df_kv['ReferenciaNumeroDocumento.1'].fillna('').astype(str).str.strip()
                df_kv['Costo'] = df_kv['Monto_Kardex'] * -1

                k_agg = df_kv.groupby(['Periodo_Mes', 'Doc_Cruce', 'Item'], as_index=False)['Costo'].sum()

                # Cruce contra todo el histórico de ventas de la empresa
                df_v_emp = df_ventas_all[df_ventas_all['CompaniaSocio'].astype(str).str.strip() == empresa].copy()
                df_v_emp['Doc_Cruce'] = df_v_emp['NumeroDocumento'].fillna('').astype(str).str.strip()
                df_v_emp['Item'] = df_v_emp['ItemCodigo'].astype(str).str.strip()

                llaves = set(zip(k_agg['Doc_Cruce'], k_agg['Item']))
                df_v_emp = df_v_emp[df_v_emp.set_index(['Doc_Cruce', 'Item']).index.isin(llaves)].copy()

                df_v_emp['Fecha_Clave'] = df_v_emp['FechaDocumento'].astype(str).str.slice(0, 10).str.strip()
                df_v_emp = pd.merge(df_v_emp, df_tc[['Fecha_Clave_Busqueda', 'Oficial Venta']], left_on='Fecha_Clave', right_on='Fecha_Clave_Busqueda', how='left')
                df_v_emp['Oficial Venta'] = df_v_emp['Oficial Venta'].ffill()

                df_v_emp['Monto'] = pd.to_numeric(df_v_emp['Monto'], errors='coerce').fillna(0)
                cond_ex_sol = (moneda == 'SOLES') & (df_v_emp['MonedaDocumento'] == 'EX')
                cond_lo_dol = (moneda == 'DÓLARES') & (df_v_emp['MonedaDocumento'] == 'LO')
                df_v_emp['Ventas'] = np.where(
                    cond_ex_sol, df_v_emp['Monto'] * df_v_emp['Oficial Venta'],
                    np.where(cond_lo_dol, df_v_emp['Monto'] / df_v_emp['Oficial Venta'], df_v_emp['Monto'])
                )

                v_agg = df_v_emp.groupby(['Doc_Cruce', 'Item'], as_index=False)['Ventas'].sum()
                del df_v_emp

                df_cruce_anual = pd.merge(k_agg, v_agg, on=['Doc_Cruce', 'Item'], how='left').fillna({'Ventas': 0})
                df_cruce_anual['Utilidad'] = df_cruce_anual['Ventas'] - df_cruce_anual['Costo']
                df_cruce_anual = pd.merge(df_cruce_anual, df_m[cols_m], on='Item', how='left')
                df_cruce_anual['Tipo_Categoria'] = df_cruce_anual['Tipo_Categoria'].fillna('SIN CATEGORÍA').str.strip()
                if 'Descripcion' in df_cruce_anual.columns:
                    df_cruce_anual['Descripcion'] = df_cruce_anual['Descripcion'].fillna('SIN DESCRIPCIÓN').str.strip()

                tv = df_cruce_anual['Ventas'].sum()
                tc = df_cruce_anual['Costo'].sum()
                tu = tv - tc
                mg = (tu / tv * 100) if tv != 0 else 0

                m1, m2, m3, m4 = st.columns(4)
                m1.metric(f"Ventas Cruzadas {anio}", f"{simb} {tv:,.2f}")
                m2.metric(f"Costo Kardex {anio}", f"{simb} {tc:,.2f}")
                m3.metric(f"Utilidad Bruta {anio}", f"{simb} {tu:,.2f}")
                m4.metric(f"Margen Bruto {anio}", f"{mg:.2f}%")

                # Gráfico comparativo mensual Ventas vs Costo vs Utilidad
                graf_vc = df_cruce_anual.groupby('Periodo_Mes', as_index=False)[['Ventas', 'Costo', 'Utilidad']].sum().sort_values('Periodo_Mes')
                graf_vc['Mes'] = graf_vc['Periodo_Mes'].str.slice(4, 6).map(MESES_NOMBRES)
                graf_vc_melt = pd.melt(graf_vc, id_vars=['Mes'], value_vars=['Ventas', 'Costo', 'Utilidad'], var_name='Indicador', value_name='Monto')

                fig_vc = px.bar(
                    graf_vc_melt, x='Mes', y='Monto', color='Indicador', barmode='group', text_auto=',.0f',
                    title=f'Ventas, Costo y Utilidad Bruta por Mes {anio} ({moneda})',
                    labels={'Mes': '', 'Monto': f'Monto ({simb})'},
                    color_discrete_map={'Ventas': '#1F618D', 'Costo': '#C0392B', 'Utilidad': '#1E8449'}
                )
                fig_vc.update_layout(height=380, margin=dict(t=40, b=20))
                st.plotly_chart(fig_vc, use_container_width=True)

                st.markdown("**1. Ventas Cruzadas por Mes**")
                vista_vc_v, exp_vc_v = construir_matriz_anual(df_cruce_anual, cols_agrup, 'Ventas', anio, simb)
                st.dataframe(vista_vc_v, use_container_width=True)

                st.markdown("**2. Costo Kardex por Mes**")
                vista_vc_c, exp_vc_c = construir_matriz_anual(df_cruce_anual, cols_agrup, 'Costo', anio, simb)
                st.dataframe(vista_vc_c, use_container_width=True)

                st.markdown("**3. Utilidad Bruta por Mes**")
                vista_vc_u, exp_vc_u = construir_matriz_anual(df_cruce_anual, cols_agrup, 'Utilidad', anio, simb)
                st.dataframe(vista_vc_u, use_container_width=True)

                buf_vc = io.BytesIO()
                with pd.ExcelWriter(buf_vc, engine='openpyxl') as writer:
                    exp_vc_v.to_excel(writer, sheet_name='1. Ventas Cruzadas', index=False)
                    exp_vc_c.to_excel(writer, sheet_name='2. Costo Kardex', index=False)
                    exp_vc_u.to_excel(writer, sheet_name='3. Utilidad Bruta', index=False)

                st.download_button(
                    label=f"📥 Descargar Ventas vs Costo {anio} en Excel (3 Hojas)",
                    data=buf_vc.getvalue(),
                    file_name=f"Ventas_vs_Costo_Anual_{anio}_{empresa}_{moneda}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_anual_vc"
                )
    with tab_p_anual:
        if uploaded_k_anual is None:
            st.info("👆 Primero sube el archivo Kardex aquí abajo para visualizar el reporte mensual de Producción.")
        elif df_k_anio.empty:
            st.warning(f"⚠️ No hay movimientos en el Kardex para {empresa} en el año {anio}.")
        else:
            df_prod = df_k_anio[df_k_anio['TransaccionCodigo'].isin(['API', 'PRI'])].copy()
            if df_prod.empty:
                st.warning(f"⚠️ No se registran movimientos de producción (API / PRI) en el año {anio}.")
            else:
                tot_prod = df_prod['Monto_Kardex'].sum()
                st.metric(f"Valorización Producción Acumulada {anio} ({moneda})", f"{simb} {tot_prod:,.2f}")

                graf_p = df_prod.groupby('Periodo_Mes', as_index=False)['Monto_Kardex'].sum().sort_values('Periodo_Mes')
                graf_p['Mes'] = graf_p['Periodo_Mes'].str.slice(4, 6).map(MESES_NOMBRES)

                fig_p = px.bar(
                    graf_p, x='Mes', y='Monto_Kardex', text_auto=',.0f',
                    title=f'Evolución Mensual de Producción {anio} ({moneda})',
                    labels={'Mes': '', 'Monto_Kardex': f'Producción ({simb})'},
                    color_discrete_sequence=['#D35400']
                )
                fig_p.update_traces(textposition='outside')
                fig_p.update_layout(height=380, margin=dict(t=40, b=20))
                st.plotly_chart(fig_p, use_container_width=True)

                vista_p, exp_p = construir_matriz_anual(df_prod, cols_agrup, 'Monto_Kardex', anio, simb)
                st.dataframe(vista_p, use_container_width=True)

                buf_p = io.BytesIO()
                with pd.ExcelWriter(buf_p, engine='openpyxl') as writer:
                    exp_p.to_excel(writer, sheet_name=f'Produccion_{anio}', index=False)

                st.download_button(
                    label=f"📥 Descargar Producción Mensual {anio} en Excel",
                    data=buf_p.getvalue(),
                    file_name=f"Produccion_Anual_{anio}_{empresa}_{moneda}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_anual_prod"
                )

