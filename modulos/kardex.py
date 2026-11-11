import streamlit as st
import pandas as pd
import numpy as np
import io

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

        df_k_filt = df_k[
            (df_k['CompaniaSocio'] == empresa) &
            (df_k['Periodo'] >= str(p_inicio)) &
            (df_k['Periodo'] <= str(p_fin))
        ].copy()

        if df_k_filt.empty:
            st.warning(f"⚠️ No hay movimientos en el Kardex para {empresa} en el rango {p_inicio} - {p_fin}.")
            return

        df_k_filt['Tipo_Movimiento'] = clasificar_movimiento(df_k_filt)
        df_k_filt = df_k_filt[df_k_filt['Tipo_Movimiento'] != 'EXCLUIR'].copy()

        no_clasificados = df_k_filt[df_k_filt['Tipo_Movimiento'] == 'NO CLASIFICADO']['TransaccionCodigo'].unique()
        if len(no_clasificados) > 0:
            st.warning(f"⚠️ Códigos nuevos sin clasificar: **{', '.join(no_clasificados)}**")

        df_k_filt['Cantidad'] = pd.to_numeric(df_k_filt['Cantidad'], errors='coerce').fillna(0)
        col_monto_k = 'MontoTotal' if moneda == 'SOLES' else 'MontoTotalDolares'
        df_k_filt['Monto_Kardex'] = pd.to_numeric(df_k_filt[col_monto_k], errors='coerce').fillna(0)

        df_maestro['Item'] = df_maestro['Item'].astype(str).str.strip()
        cols_m = ['Item', 'Tipo_Categoria', 'Marca_Descripcion']
        if 'Descripcion' in df_maestro.columns:
            cols_m.append('Descripcion')
        if 'CuentaContable' in df_maestro.columns:
            cols_m.append('CuentaContable')

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
            st.markdown(f"### Cruce de Despachos vs. Facturación ({moneda})")
            
            c1, c2, c3 = st.columns(3)
            with c1:
                k_n1 = st.checkbox("Nivel 1: Categoría", value=True, key="k_n1")
            with c2:
                k_n2 = st.checkbox("Nivel 2: Marca", value=False, key="k_n2")
            with c3:
                k_n3 = st.checkbox("Nivel 3: Ítems", value=False, key="k_n3")

            df_kv = df_k_filt[df_k_filt['Tipo_Movimiento'] == 'VENTA'].copy()
            df_kv['Doc_Cruce'] = df_kv['ReferenciaNumeroDocumento.1'].fillna('').astype(str).str.strip()
            df_kv['Costo_Positivo'] = df_kv['Monto_Kardex'] * -1

            kardex_agg = df_kv.groupby(['Doc_Cruce', 'Item'], as_index=False).agg(
                Cant_Kardex=('Cantidad', 'sum'),
                Costo=('Costo_Positivo', 'sum')
            )

            df_v_emp = df_ventas_completo[df_ventas_completo['CompaniaSocio'].astype(str).str.strip() == empresa].copy()
            df_v_emp['Doc_Cruce'] = df_v_emp['NumeroDocumento'].fillna('').astype(str).str.strip()
            df_v_emp['Item'] = df_v_emp['ItemCodigo'].astype(str).str.strip()

            llaves = set(zip(kardex_agg['Doc_Cruce'], kardex_agg['Item']))
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

            ventas_agg = df_v_emp.groupby(['Doc_Cruce', 'Item'], as_index=False).agg(
                Cant_Ventas=('CantidadPedida', 'sum'),
                Ventas=('Venta_Conv', 'sum')
            )

            df_cruce = pd.merge(kardex_agg, ventas_agg, on=['Doc_Cruce', 'Item'], how='left').fillna({'Cant_Ventas': 0, 'Ventas': 0})
            df_cruce['Dif_Cant'] = (df_cruce['Cant_Kardex'] + df_cruce['Cant_Ventas']).round(2)
            df_cruce['Utilidad'] = df_cruce['Ventas'] - df_cruce['Costo']

            df_cruce = pd.merge(df_cruce, df_maestro[cols_m], on='Item', how='left')
            df_cruce['Tipo_Categoria'] = df_cruce['Tipo_Categoria'].fillna('SIN CATEGORÍA').str.strip()
            df_cruce['Marca_Descripcion'] = df_cruce['Marca_Descripcion'].fillna('SIN MARCA').str.strip()
            tot_v = df_cruce['Ventas'].sum()
            tot_c = df_cruce['Costo'].sum()
            tot_u = tot_v - tot_c
            margen = (tot_u / tot_v * 100) if tot_v != 0 else 0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Ventas Cruzadas", f"{simb} {tot_v:,.2f}")
            m2.metric("Costo Kardex", f"{simb} {tot_c:,.2f}")
            m3.metric("Utilidad Bruta", f"{simb} {tot_u:,.2f}")
            m4.metric("Margen Bruto", f"{margen:.2f}%")

            cols_agrup = []
            if k_n1: cols_agrup.append('Tipo_Categoria')
            if k_n2: cols_agrup.append('Marca_Descripcion')
            if k_n3:
                cols_agrup.append('Item')
                if 'Descripcion' in df_cruce.columns: cols_agrup.append('Descripcion')

            if not cols_agrup:
                st.info("💡 Activa al menos un nivel de agrupación arriba.")
            else:
                resumen_rent = df_cruce.groupby(cols_agrup, as_index=False).agg(
                    Ventas=('Ventas', 'sum'),
                    Costo=('Costo', 'sum'),
                    Utilidad=('Utilidad', 'sum'),
                    Cant_Kardex=('Cant_Kardex', 'sum'),
                    Cant_Ventas=('Cant_Ventas', 'sum'),
                    Dif_Cant=('Dif_Cant', 'sum')
                ).sort_values(by='Ventas', ascending=False).reset_index(drop=True)

                resumen_rent['Margen_%'] = np.where(resumen_rent['Ventas'] != 0, (resumen_rent['Utilidad'] / resumen_rent['Ventas']) * 100, 0)

                fila_tot = {c: '' for c in cols_agrup}
                fila_tot[cols_agrup[0]] = 'TOTAL GENERAL'
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
        with tab_comp:
            df_comp = df_k_filt[df_k_filt['Tipo_Movimiento'].isin(['COMPRA', 'IMPORTACION'])].copy()
            if df_comp.empty:
                st.info("No se encontraron compras ni importaciones en este periodo.")
            else:
                st.metric(f"Total Compras e Importaciones ({moneda})", f"{simb} {df_comp['Monto_Kardex'].sum():,.2f}")
                
                comp_cat = df_comp.groupby(['Tipo_Movimiento', 'Tipo_Categoria'], as_index=False).agg(
                    Cantidad=('Cantidad', 'sum'),
                    Monto_Total=('Monto_Kardex', 'sum')
                ).sort_values(by=['Tipo_Movimiento', 'Monto_Total'], ascending=[True, False])

                comp_item = df_comp.groupby(['Tipo_Movimiento', 'Tipo_Categoria', 'Marca_Descripcion', 'Item', 'DescripcionLocal'], as_index=False).agg(
                    Cantidad=('Cantidad', 'sum'),
                    Monto_Total=('Monto_Kardex', 'sum')
                ).sort_values(by='Monto_Total', ascending=False)

                st.markdown("**Resumen por Tipo de Compra y Categoría**")
                vista_cc = comp_cat.copy()
                vista_cc['Cantidad'] = vista_cc['Cantidad'].map('{:,.2f}'.format)
                vista_cc['Monto_Total'] = vista_cc['Monto_Total'].map(lambda x: f"{simb} {x:,.2f}")
                st.dataframe(vista_cc, use_container_width=True)

                excel_comp = exportar_excel_3_hojas(
                    comp_cat, "1. Por Categoria",
                    comp_item, "2. Por Item",
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
            df_cons = df_k_filt[df_k_filt['Tipo_Movimiento'] == 'CONSUMO'].copy()
            if df_cons.empty:
                st.info("No se registran consumos en este periodo.")
            else:
                df_cons['Costo_Consumo'] = df_cons['Monto_Kardex'] * -1
                st.metric(f"Total Consumos ({moneda})", f"{simb} {df_cons['Costo_Consumo'].sum():,.2f}")

                cons_cat = df_cons.groupby(['AlmacenCodigo', 'TransaccionCodigo', 'Tipo_Categoria'], as_index=False).agg(
                    Cantidad=('Cantidad', 'sum'),
                    Costo_Total=('Costo_Consumo', 'sum')
                ).sort_values(by='Costo_Total', ascending=False)

                cons_item = df_cons.groupby(['AlmacenCodigo', 'TransaccionCodigo', 'Tipo_Categoria', 'Item', 'DescripcionLocal'], as_index=False).agg(
                    Cantidad=('Cantidad', 'sum'),
                    Costo_Total=('Costo_Consumo', 'sum')
                ).sort_values(by='Costo_Total', ascending=False)

                st.markdown("**Resumen de Consumos por Almacén, Transacción y Categoría**")
                vista_cons = cons_cat.copy()
                vista_cons['Cantidad'] = vista_cons['Cantidad'].map('{:,.2f}'.format)
                vista_cons['Costo_Total'] = vista_cons['Costo_Total'].map(lambda x: f"{simb} {x:,.2f}")
                st.dataframe(vista_cons, use_container_width=True)

                excel_cons = exportar_excel_3_hojas(
                    cons_cat, "1. Por Almacen y Categoria",
                    cons_item, "2. Por Item",
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
            df_prod = df_k_filt[df_k_filt['Tipo_Movimiento'] == 'PRODUCCION'].copy()
            if df_prod.empty:
                st.info("No se registran movimientos de producción (API / PRI) en este periodo.")
            else:
                st.metric(f"Valorización Producción ({moneda})", f"{simb} {df_prod['Monto_Kardex'].sum():,.2f}")

                prod_cat = df_prod.groupby(['TransaccionCodigo', 'AlmacenCodigo', 'Tipo_Categoria'], as_index=False).agg(
                    Cantidad=('Cantidad', 'sum'),
                    Monto_Total=('Monto_Kardex', 'sum')
                ).sort_values(by=['TransaccionCodigo', 'Monto_Total'], ascending=[True, False])

                prod_item = df_prod.groupby(['TransaccionCodigo', 'AlmacenCodigo', 'Tipo_Categoria', 'Item', 'DescripcionLocal'], as_index=False).agg(
                    Cantidad=('Cantidad', 'sum'),
                    Monto_Total=('Monto_Kardex', 'sum')
                ).sort_values(by='Monto_Total', ascending=False)

                st.markdown("**Resumen de Producción por Código (API / PRI) y Categoría**")
                vista_prod = prod_cat.copy()
                vista_prod['Cantidad'] = vista_prod['Cantidad'].map('{:,.2f}'.format)
                vista_prod['Monto_Total'] = vista_prod['Monto_Total'].map(lambda x: f"{simb} {x:,.2f}")
                st.dataframe(vista_prod, use_container_width=True)

                excel_prod = exportar_excel_3_hojas(
                    prod_cat, "1. Por Transaccion y Cat",
                    prod_item, "2. Por Item",
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
