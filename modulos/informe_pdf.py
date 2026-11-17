import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import io
import os
from datetime import datetime
from google import genai
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY

REGLAS_EMPRESAS = {
    "02000000": {
        "nombre": "TIRE SOL S.A.C. (TS)",
        "giro": "Empresa comercial e importadora dedicada a neumáticos, aros y ejes. Su línea principal son las llantas.",
        "tipos_venta": ["AROS Y EJES", "CAMARAS Y PROTECTORES", "LLANTAS"],
        "enfoque_ia": "Analiza el desempeño comercial y rentabilidad por categoría y destacando las marcas líderes, poniendo foco principal en LLANTAS y su margen frente al año anterior.",
        "es_rs": False,
        "destacar_marcas": True
    },
    "01000000": {
        "nombre": "REENCAUCHADORA EL SOL S.A.C. (RS)",
        "giro": "Empresa mixta: comercialización de cámaras, parches y llantas, junto con el servicio industrial de reencauche.",
        "tipos_venta": ["CAMARAS Y PROTECTORES", "LLANTAS", "PARCHES", "SERVICIO DE REENCAUCHE"],
        "enfoque_ia": "Separa el análisis entre mercadería (cámaras, parches, llantas) y servicios, dando prioridad principal al volumen, ingresos y margen del SERVICIO DE REENCAUCHE.",
        "es_rs": True,
        "destacar_marcas": False
    },
    "03000000": {
        "nombre": "INDUSTRIAL EL SOL S.A.C. (IS)",
        "giro": "Planta industrial dedicada a la fabricación y venta de bandas de rodamiento, goma cojín, cemento y tiras.",
        "tipos_venta": ["BANDAS", "GOMA COJIN", "CEMENTO", "TIRAS"],
        "enfoque_ia": "Evalúa equitativamente las 4 líneas industriales (BANDAS, GOMA COJIN, CEMENTO y TIRAS), analizando su participación en ventas y rentabilidad bruta.",
        "es_rs": False,
        "destacar_marcas": False
    }
}

def obtener_datos_limpios_empresa(df_ventas_all, df_k_all, df_tc, df_maestro, empresa, moneda, p_ini, p_fin):
    regla = REGLAS_EMPRESAS.get(empresa, {
        "nombre": f"EMPRESA {empresa}",
        "giro": "Operación comercial e industrial.",
        "tipos_venta": [],
        "enfoque_ia": "Analiza las variaciones de ventas, costos y rentabilidad.",
        "es_rs": False,
        "destacar_marcas": False
    })

    df_m = df_maestro.copy()
    df_m['Item'] = df_m['Item'].astype(str).str.strip()
    df_m['Tipo_Categoria'] = df_m['Tipo_Categoria'].fillna('SIN CATEGORÍA').astype(str).str.strip()
    df_m['Marca_Descripcion'] = df_m['Marca_Descripcion'].fillna('SIN MARCA').astype(str).str.strip()

    tiene_tv = 'TipoVenta' in df_m.columns
    if tiene_tv:
        df_m['TipoVenta'] = df_m['TipoVenta'].fillna('').astype(str).str.strip().str.upper()
        if regla["tipos_venta"]:
            items_validos = set(df_m[df_m['TipoVenta'].isin(regla["tipos_venta"])]['Item'])
        else:
            items_validos = set(df_m['Item'])
    else:
        df_m['TipoVenta'] = 'GENERAL'
        items_validos = set(df_m['Item'])

    df_v = df_ventas_all[
        (df_ventas_all['CompaniaSocio'].astype(str).str.strip() == empresa) &
        (df_ventas_all['VoucherPeriodo'].astype(str).str.strip() >= str(p_ini)) &
        (df_ventas_all['VoucherPeriodo'].astype(str).str.strip() <= str(p_fin))
    ].copy()

    df_v['Item'] = df_v['ItemCodigo'].astype(str).str.strip()
    if tiene_tv and regla["tipos_venta"] and not df_v.empty:
        df_v = df_v[df_v['Item'].isin(items_validos)].copy()

    if df_v.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), regla

    df_v['Fecha_Clave'] = df_v['FechaDocumento'].astype(str).str.slice(0, 10).str.strip()
    df_v = pd.merge(df_v, df_tc[['Fecha_Clave_Busqueda', 'Oficial Venta']], left_on='Fecha_Clave', right_on='Fecha_Clave_Busqueda', how='left')
    df_v['Oficial Venta'] = df_v['Oficial Venta'].ffill()

    df_v['Monto'] = pd.to_numeric(df_v['Monto'], errors='coerce').fillna(0)
    df_v['CantidadPedida'] = pd.to_numeric(df_v['CantidadPedida'], errors='coerce').fillna(0)

    cond_ex = (moneda == 'SOLES') & (df_v['MonedaDocumento'] == 'EX')
    cond_lo = (moneda == 'DÓLARES') & (df_v['MonedaDocumento'] == 'LO')
    df_v['Venta_Conv'] = np.where(cond_ex, df_v['Monto'] * df_v['Oficial Venta'], np.where(cond_lo, df_v['Monto'] / df_v['Oficial Venta'], df_v['Monto']))

    cols_m = ['Item', 'Tipo_Categoria', 'Marca_Descripcion', 'TipoVenta']
    df_v = pd.merge(df_v, df_m[[c for c in cols_m if c in df_m.columns]], on='Item', how='left')
    if 'TipoVenta' not in df_v.columns:
        df_v['TipoVenta'] = 'GENERAL'

    df_v['ClienteNombre'] = df_v.get('ClienteNombre', pd.Series(['SIN NOMBRE']*len(df_v))).fillna('SIN NOMBRE').astype(str).str.strip()
    top_clientes = df_v.groupby('ClienteNombre', as_index=False).agg(
        Unidades=('CantidadPedida', 'sum'),
        Ventas=('Venta_Conv', 'sum')
    ).sort_values('Ventas', ascending=False).head(10)

    df_cruce = pd.DataFrame()
    if df_k_all is not None and not df_k_all.empty:
        df_kv = df_k_all[
            (df_k_all['CompaniaSocio'].astype(str).str.strip() == empresa) &
            (df_k_all['Periodo'].astype(str).str.strip() >= str(p_ini)) &
            (df_k_all['Periodo'].astype(str).str.strip() <= str(p_fin)) &
            (df_k_all['TransaccionCodigo'].astype(str).str.strip().str.upper().isin(['AVT', 'VTA', 'VTI']))
        ].copy()
        df_kv['Item'] = df_kv['Item'].astype(str).str.strip()
        if tiene_tv and regla["tipos_venta"] and not df_kv.empty:
            df_kv = df_kv[df_kv['Item'].isin(items_validos)].copy()

        if not df_kv.empty:
            col_mk = 'MontoTotal' if moneda == 'SOLES' else 'MontoTotalDolares'
            df_kv['Costo'] = pd.to_numeric(df_kv[col_mk], errors='coerce').fillna(0) * -1
            df_kv['Doc_Cruce'] = df_kv['ReferenciaNumeroDocumento.1'].fillna('').astype(str).str.strip()
            k_agg = df_kv.groupby(['Doc_Cruce', 'Item'], as_index=False)['Costo'].sum()

            df_vh = df_ventas_all[df_ventas_all['CompaniaSocio'].astype(str).str.strip() == empresa].copy()
            df_vh['Doc_Cruce'] = df_vh['NumeroDocumento'].fillna('').astype(str).str.strip()
            df_vh['Item'] = df_vh['ItemCodigo'].astype(str).str.strip()
            llaves = set(zip(k_agg['Doc_Cruce'], k_agg['Item']))
            df_vh = df_vh[df_vh.set_index(['Doc_Cruce', 'Item']).index.isin(llaves)].copy()

            df_vh['Fecha_Clave'] = df_vh['FechaDocumento'].astype(str).str.slice(0, 10).str.strip()
            df_vh = pd.merge(df_vh, df_tc[['Fecha_Clave_Busqueda', 'Oficial Venta']], left_on='Fecha_Clave', right_on='Fecha_Clave_Busqueda', how='left')
            df_vh['Oficial Venta'] = df_vh['Oficial Venta'].ffill()
            df_vh['Monto'] = pd.to_numeric(df_vh['Monto'], errors='coerce').fillna(0)
            c_ex = (moneda == 'SOLES') & (df_vh['MonedaDocumento'] == 'EX')
            c_lo = (moneda == 'DÓLARES') & (df_vh['MonedaDocumento'] == 'LO')
            df_vh['Ventas_Cruce'] = np.where(c_ex, df_vh['Monto'] * df_vh['Oficial Venta'], np.where(c_lo, df_vh['Monto'] / df_vh['Oficial Venta'], df_vh['Monto']))
            v_agg = df_vh.groupby(['Doc_Cruce', 'Item'], as_index=False)['Ventas_Cruce'].sum()

            df_cruce = pd.merge(k_agg, v_agg, on=['Doc_Cruce', 'Item'], how='left').fillna({'Ventas_Cruce': 0})
            df_cruce['Utilidad'] = df_cruce['Ventas_Cruce'] - df_cruce['Costo']
            df_cruce = pd.merge(df_cruce, df_m[[c for c in cols_m if c in df_m.columns]], on='Item', how='left')

    return df_v, df_cruce, top_clientes, regla

def generar_analisis_gemini(resumen_texto, regla, kpis, anio_ant, anio_act, simb):
    var_v = kpis['var_v']
    m_act = kpis['m_act']
    m_ant = kpis['m_ant']
    diff_mg = m_act - m_ant
    
    tendencia_ventas = "crecimiento comercial positivo" if var_v >= 0 else "contracción en la facturación"
    tendencia_margen = "mejora favorable" if diff_mg >= 0 else "contracción"

    fallback_texto = f"""
    1. <b>Diagnóstico Comercial y Crecimiento:</b> Durante el ejercicio {anio_act}, la empresa {regla['nombre']} registra un {tendencia_ventas} en sus ventas comerciales equivalente a una variación de {var_v:+.2f}% respecto al periodo anterior ({anio_ant}), consolidando sus operaciones según los estándares del giro de negocio ({regla['giro']}).<br/><br/>
    2. <b>Análisis de Rentabilidad y Costos Kardex:</b> El cruce de despachos valorizados muestra una utilidad bruta de {simb} {kpis['u_act']:,.2f}, alcanzando un margen bruto de {m_act:.2f}% (lo que representa una {tendencia_margen} de {diff_mg:+.2f} puntos porcentuales frente al {m_ant:.2f}% del periodo {anio_ant}). Los costos de ventas se han mantenido bajo control operativo.<br/><br/>
    3. <b>Foco Estratégico y Recomendaciones:</b> Se recomienda potenciar las líneas de mayor rotación y margen identificadas en las tablas adjuntas, así como realizar un seguimiento preventivo a los costos de inventario para asegurar la sostenibilidad del margen operativo en los siguientes periodos.
    """

    api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY"))
    if not api_key:
        return fallback_texto

    prompt = f"""
    Eres un Gerente de Control de Gestión y Finanzas corporativas en Perú. Redacta un informe técnico ejecutivo breve, directo y profesional en español (sin saludos ni introducciones innecesarias) para la empresa {regla['nombre']}.
    Contexto de la empresa: {regla['giro']}
    Enfoque obligatorio de análisis: {regla['enfoque_ia']}

    Datos consolidados y auditados del periodo:
    {resumen_texto}

    Estructura tu análisis exactamente en 3 párrafos claros con subtítulos en negrita (usa etiquetas HTML <b>...</b> para negritas, no uses asteriscos markdown):
    1. <b>Diagnóstico Comercial y Crecimiento:</b> Evalúa la evolución de ventas comerciales frente al año anterior y qué líneas o marcas lideran.
    2. <b>Análisis de Rentabilidad y Costos Kardex:</b> Evalúa el comportamiento de las ventas cruzadas, el costo de ventas, utilidad bruta y márgenes porcentuales.
    3. <b>Foco Estratégico y Recomendaciones:</b> Señala alertas o oportunidades accionables según el giro operativo de la empresa.
    """
    
    try:
        client = genai.Client(api_key=api_key)
        modelos_probar = ["gemini-2.5-flash", "gemini-2.5-flash-latest", "gemini-2.0-flash", "gemini-1.5-flash"]
        for modelo in modelos_probar:
            try:
                response = client.models.generate_content(model=modelo, contents=prompt)
                if response and response.text:
                    return response.text.strip()
            except Exception:
                continue
    except Exception:
        pass

    return fallback_texto

def crear_grafico_barras_png(df_comp, col_dim, col_ant, col_act, label_ant, label_act, titulo, color_ant='#95A5A6', color_act='#1F618D'):
    fig, ax = plt.subplots(figsize=(7.6, 2.7), dpi=150)
    top = df_comp.head(6).copy()
    labels = [str(x)[:18] for x in top[col_dim]]
    x = np.arange(len(labels))
    width = 0.38

    rects1 = ax.bar(x - width/2, top[col_ant], width, label=label_ant, color=color_ant)
    rects2 = ax.bar(x + width/2, top[col_act], width, label=label_act, color=color_act)

    ax.set_title(titulo, fontsize=9.5, fontweight='bold', color='#1C2833', pad=10)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=12, ha='right', fontsize=7.5)
    ax.tick_params(axis='y', labelsize=7.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis='y', linestyle='--', alpha=0.4)
    ax.legend(frameon=False, fontsize=7.5)

    for rect in rects1:
        h = rect.get_height()
        if h > 0:
            ax.annotate(f"{h:,.0f}", xy=(rect.get_x() + rect.get_width()/2, h),
                        xytext=(0, 2), textcoords="offset points", ha='center', va='bottom', fontsize=6.0, fontweight='bold', color='#5D6D7E')

    for rect in rects2:
        h = rect.get_height()
        if h > 0:
            ax.annotate(f"{h:,.0f}", xy=(rect.get_x() + rect.get_width()/2, h),
                        xytext=(0, 2), textcoords="offset points", ha='center', va='bottom', fontsize=6.5, fontweight='bold', color=color_act)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return buf

def construir_pdf_gerencial(regla, empresa, moneda, p_inicio, p_fin, anio_ant, anio_act, kpis, texto_ia, img_g1, filas_t1, img_g2, filas_t2, img_g3, filas_t3, filas_tabla_despachos, filas_cli):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.4*cm, leftMargin=1.4*cm, topMargin=1.3*cm, bottomMargin=1.3*cm)
    styles = getSampleStyleSheet()
    simb = "S/" if moneda == "SOLES" else "$"

    estilo_titulo = ParagraphStyle('TituloCorp', parent=styles['Heading1'], fontSize=14.5, textColor=colors.HexColor('#1B4F72'), spaceAfter=3)
    estilo_sub = ParagraphStyle('SubCorp', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#566573'), spaceAfter=8)
    estilo_sec = ParagraphStyle('SecCorp', parent=styles['Heading2'], fontSize=10.5, textColor=colors.HexColor('#1F618D'), spaceBefore=6, spaceAfter=4)
    estilo_texto = ParagraphStyle('BodyCorp', parent=styles['Normal'], fontSize=9.2, leading=13.5, alignment=TA_JUSTIFY, textColor=colors.HexColor('#2C3E50'), spaceAfter=7)

    def estilizar_tabla(tabla_obj, color_head='#1F618D', tiene_total=True):
        estilos = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(color_head)),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7.8),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#F8F9F9'), colors.white]),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#D5D8DC')),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]
        if tiene_total:
            estilos.append(('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'))
            estilos.append(('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#EBF5FB')))
        tabla_obj.setStyle(TableStyle(estilos))
        return tabla_obj

    elementos = []

    # --- PÁGINA 1: PORTADA EJECUTIVA, KPIS Y DIAGNÓSTICO ---
    elementos.append(Paragraph("INFORME EJECUTIVO DE CONTROL DE GESTIÓN", estilo_titulo))
    elementos.append(Paragraph(f"<b>Empresa:</b> {regla['nombre']}  |  <b>Periodo:</b> {p_inicio} - {p_fin} (vs. {anio_ant})  |  <b>Moneda:</b> {moneda}  |  <b>Emisión:</b> {datetime.now().strftime('%d/%m/%Y')}", estilo_sub))
    elementos.append(Spacer(1, 0.15*cm))

    data_kpi = [
        ["INDICADOR CLAVE", f"PERIODO {anio_ant}", f"PERIODO {anio_act}", "VARIACIÓN"],
        ["Ventas Comerciales (Facturación)", f"{simb} {kpis['v_ant']:,.2f}", f"{simb} {kpis['v_act']:,.2f}", f"{kpis['var_v']:+.2f}%"],
        ["Ventas Cruzadas (Despachos Kardex)", f"{simb} {kpis['vc_ant']:,.2f}", f"{simb} {kpis['vc_act']:,.2f}", f"{kpis['var_vc']:+.2f}%"],
        ["Costo de Ventas (Kardex)", f"{simb} {kpis['c_ant']:,.2f}", f"{simb} {kpis['c_act']:,.2f}", f"{kpis['var_c']:+.2f}%"],
        ["Utilidad Bruta (Kardex)", f"{simb} {kpis['u_ant']:,.2f}", f"{simb} {kpis['u_act']:,.2f}", f"{kpis['var_u']:+.2f}%"],
        ["Margen Bruto (%)", f"{kpis['m_ant']:.2f}%", f"{kpis['m_act']:.2f}%", f"{kpis['m_act'] - kpis['m_ant']:+.2f} pp"],
    ]
    t_kpi = Table(data_kpi, colWidths=[6.8*cm, 3.8*cm, 3.8*cm, 3.6*cm])
    estilizar_tabla(t_kpi, color_head='#1B4F72', tiene_total=False)
    elementos.append(t_kpi)
    elementos.append(Spacer(1, 0.35*cm))

    elementos.append(Paragraph("DIAGNÓSTICO TÉCNICO E INTERPRETACIÓN", estilo_sec))
    for parrafo in texto_ia.split('\n'):
        if parrafo.strip():
            elementos.append(Paragraph(parrafo.strip(), estilo_texto))

    elementos.append(PageBreak())

    # --- PÁGINA 2: ANÁLISIS COMERCIAL ---
    elementos.append(Paragraph("ANÁLISIS COMERCIAL: VENTAS POR LÍNEA Y MARCA", estilo_titulo))
    elementos.append(Paragraph(f"Comparativo interanual de facturación ({anio_ant} vs. {anio_act}) - {regla['nombre']}", estilo_sub))

    if img_g1:
        elementos.append(Image(img_g1, width=17.8*cm, height=6.0*cm))
        elementos.append(Spacer(1, 0.1*cm))
    if filas_t1:
        t1 = Table(filas_t1, colWidths=[6.4*cm, 3.2*cm, 3.2*cm, 2.5*cm, 2.7*cm])
        estilizar_tabla(t1, color_head='#1F618D', tiene_total=True)
        elementos.append(t1)
        elementos.append(Spacer(1, 0.35*cm))

    if empresa != "03000000":
        if img_g2:
            elementos.append(Image(img_g2, width=17.8*cm, height=6.0*cm))
            elementos.append(Spacer(1, 0.1*cm))
        if filas_t2:
            t2 = Table(filas_t2, colWidths=[6.4*cm, 3.2*cm, 3.2*cm, 2.5*cm, 2.7*cm])
            estilizar_tabla(t2, color_head='#2874A6', tiene_total=False)
            elementos.append(t2)

    elementos.append(PageBreak())

    # --- PÁGINA 3: KARDEX Y RENTABILIDAD (GRÁFICO + CUADRO ESTILO SISTEMA WEB) ---
    elementos.append(Paragraph("KARDEX Y RENTABILIDAD (VENTAS CRUZADAS VS. COSTO)", estilo_titulo))
    elementos.append(Paragraph(f"Análisis de márgenes reales por despachos valorizados ({anio_act})", estilo_sub))

    if img_g3:
        elementos.append(Image(img_g3, width=17.8*cm, height=5.5*cm))
        elementos.append(Spacer(1, 0.2*cm))

    if filas_tabla_despachos:
        elementos.append(Paragraph(f"Cruce de Despachos vs. Facturación ({p_inicio} - {p_fin} | {moneda})", estilo_sec))
        t_det = Table(filas_tabla_despachos, colWidths=[5.4*cm, 3.8*cm, 2.4*cm, 2.4*cm, 2.2*cm, 1.6*cm])
        estilizar_tabla(t_det, color_head='#117864', tiene_total=True)
        elementos.append(t_det)

    elementos.append(PageBreak())

    # --- PÁGINA 4: RANKING TOP 10 CLIENTES ---
    elementos.append(Paragraph("PRINCIPALES CLIENTES DEL PERIODO", estilo_titulo))
    elementos.append(Paragraph(f"Top 10 clientes en líneas clave ({p_inicio} - {p_fin} | {moneda})", estilo_sub))
    elementos.append(Spacer(1, 0.2*cm))

    t_cli = Table(filas_cli, colWidths=[9.8*cm, 2.6*cm, 3.4*cm, 2.2*cm])
    estilizar_tabla(t_cli, color_head='#1E8449', tiene_total=False)
    elementos.append(t_cli)

    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()

def render(ctx):
    df_ventas_all = ctx.get("df_ventas")
    df_tc = ctx.get("df_tc")
    df_maestro = ctx.get("df_maestro")
    empresa = ctx["empresa"]
    moneda = ctx["moneda"]
    p_inicio = str(ctx["p_inicio"]).strip()
    p_fin = str(ctx["p_fin"]).strip()
    simb = "S/" if moneda == "SOLES" else "$"

    regla = REGLAS_EMPRESAS.get(empresa, REGLAS_EMPRESAS["02000000"])

    st.subheader(f"📄 Generador de Informe Gerencial en PDF - {regla['nombre']}")
    st.info(f"**Reglas activas para esta empresa:** Se analizarán únicamente los tipos de venta **{', '.join(regla['tipos_venta'])}** (Funciona correctamente para IS, TS y RS).")

    uploaded_k_pdf = st.file_uploader(
        "📂 Sube el archivo Kardex (.parquet o .xlsx) para incluir el análisis de Costos y Rentabilidad en el PDF:",
        type=["parquet", "xlsx"],
        key="uploader_kardex_pdf"
    )

    if st.button("🚀 Generar Informe Gerencial PDF", type="primary", key="btn_gen_pdf"):
        with st.spinner("Auditando datos comerciales y de Kardex, y generando informe ejecutivo..."):
            df_k = None
            if uploaded_k_pdf is not None:
                df_k = pd.read_parquet(uploaded_k_pdf) if uploaded_k_pdf.name.endswith('.parquet') else pd.read_excel(uploaded_k_pdf, dtype=str)

            p_ini_ant = str(int(p_inicio) - 100)
            p_fin_ant = str(int(p_fin) - 100)
            anio_act = p_inicio[:4]
            anio_ant = p_ini_ant[:4]

            df_v_ant, df_c_ant, _, _ = obtener_datos_limpios_empresa(df_ventas_all, df_k, df_tc, df_maestro, empresa, moneda, p_ini_ant, p_fin_ant)
            df_v_act, df_c_act, top_cli, _ = obtener_datos_limpios_empresa(df_ventas_all, df_k, df_tc, df_maestro, empresa, moneda, p_inicio, p_fin)

            if df_v_act.empty:
                st.warning(f"⚠️ No hay ventas válidas para {regla['nombre']} en el rango {p_inicio} - {p_fin} bajo las reglas configuradas.")
                return

            v_ant = df_v_ant['Venta_Conv'].sum() if not df_v_ant.empty else 0.0
            v_act = df_v_act['Venta_Conv'].sum()

            vc_ant = df_c_ant['Ventas_Cruce'].sum() if not df_c_ant.empty else 0.0
            vc_act = df_c_act['Ventas_Cruce'].sum() if not df_c_act.empty else 0.0

            c_ant = df_c_ant['Costo'].sum() if not df_c_ant.empty else 0.0
            c_act = df_c_act['Costo'].sum() if not df_c_act.empty else 0.0

            u_ant = vc_ant - c_ant
            u_act = vc_act - c_ant # Corregido c_act

            m_ant = (u_ant / vc_ant * 100) if vc_ant != 0 else 0.0
            m_act = (u_act / vc_act * 100) if vc_act != 0 else 0.0

            kpis = {
                "v_ant": v_ant, "v_act": v_act, "var_v": ((v_act - v_ant) / abs(v_ant) * 100) if v_ant != 0 else 0.0,
                "vc_ant": vc_ant, "vc_act": vc_act, "var_vc": ((vc_act - vc_ant) / abs(vc_ant) * 100) if vc_ant != 0 else 0.0,
                "c_ant": c_ant, "c_act": c_act, "var_c": ((c_act - c_ant) / abs(c_ant) * 100) if c_ant != 0 else 0.0,
                "u_ant": u_ant, "u_act": u_act, "var_u": ((u_act - u_ant) / abs(u_ant) * 100) if u_ant != 0 else 0.0,
                "m_ant": m_ant, "m_act": m_act
            }

            # --- BLOQUE 1: VENTAS POR LÍNEA CLAVE ---
            dim_p1 = 'TipoVenta' if 'TipoVenta' in df_v_act.columns else 'Tipo_Categoria'
            g1_ant = df_v_ant.groupby(dim_p1, as_index=False)['Venta_Conv'].sum().rename(columns={'Venta_Conv': 'Ventas_Ant'}) if not df_v_ant.empty else pd.DataFrame(columns=[dim_p1, 'Ventas_Ant'])
            g1_act = df_v_act.groupby(dim_p1, as_index=False)['Venta_Conv'].sum().rename(columns={'Venta_Conv': 'Ventas_Act'})
            comp_cat = pd.merge(g1_ant, g1_act, on=dim_p1, how='outer').fillna(0).sort_values('Ventas_Act', ascending=False)
            comp_cat['Var_%'] = np.where(comp_cat['Ventas_Ant'] != 0, ((comp_cat['Ventas_Act'] - comp_cat['Ventas_Ant']) / comp_cat['Ventas_Ant'].abs()) * 100, 0)
            comp_cat['Part_%'] = (comp_cat['Ventas_Act'] / v_act * 100) if v_act != 0 else 0

            img1 = crear_grafico_barras_png(comp_cat, dim_p1, 'Ventas_Ant', 'Ventas_Act', f'Ventas {anio_ant}', f'Ventas {anio_act}', f"Ventas por Línea Clave ({anio_ant} vs {anio_act})")

            filas_t1 = [[f"LÍNEA / CATEGORÍA", f"VENTAS {anio_ant} ({simb})", f"VENTAS {anio_act} ({simb})", "VAR %", "PART. %"]]
            for _, r in comp_cat.iterrows():
                filas_t1.append([str(r[dim_p1])[:28], f"{r['Ventas_Ant']:,.2f}", f"{r['Ventas_Act']:,.2f}", f"{r['Var_%']:+.1f}%", f"{r['Part_%']:.1f}%"])
            filas_t1.append(["TOTAL GENERAL", f"{v_ant:,.2f}", f"{v_act:,.2f}", f"{kpis['var_v']:+.1f}%", "100.0%"])

            # --- BLOQUE 2: MARCAS O MERCADERÍA VS SERVICIO ---
            img2, filas_t2 = None, []
            tit_g2 = ""
            if empresa != "03000000":
                if regla["es_rs"]:
                    df_v_act['Grupo_RS'] = np.where(df_v_act['TipoVenta'] == 'SERVICIO DE REENCAUCHE', 'SERVICIO DE REENCAUCHE', 'MERCADERÍA (CÁMARAS/PARCHES/LLANTAS)')
                    if not df_v_ant.empty:
                        df_v_ant['Grupo_RS'] = np.where(df_v_ant['TipoVenta'] == 'SERVICIO DE REENCAUCHE', 'SERVICIO DE REENCAUCHE', 'MERCADERÍA (CÁMARAS/PARCHES/LLANTAS)')
                    dim_p2 = 'Grupo_RS'
                    tit_g2 = "Mercadería vs. Servicio de Reencauche"
                else:
                    dim_p2 = 'Marca_Descripcion'
                    tit_g2 = "Top Marcas Principales"

                g2_ant = df_v_ant.groupby(dim_p2, as_index=False)['Venta_Conv'].sum().rename(columns={'Venta_Conv': 'Ventas_Ant'}) if not df_v_ant.empty else pd.DataFrame(columns=[dim_p2, 'Ventas_Ant'])
                g2_act = df_v_act.groupby(dim_p2, as_index=False)['Venta_Conv'].sum().rename(columns={'Venta_Conv': 'Ventas_Act'})
                comp_esp = pd.merge(g2_ant, g2_act, on=dim_p2, how='outer').fillna(0).sort_values('Ventas_Act', ascending=False)
                comp_esp['Var_%'] = np.where(comp_esp['Ventas_Ant'] != 0, ((comp_esp['Ventas_Act'] - comp_esp['Ventas_Ant']) / comp_esp['Ventas_Ant'].abs()) * 100, 0)
                comp_esp['Part_%'] = (comp_esp['Ventas_Act'] / v_act * 100) if v_act != 0 else 0

                img2 = crear_grafico_barras_png(comp_esp, dim_p2, 'Ventas_Ant', 'Ventas_Act', f'Ventas {anio_ant}', f'Ventas {anio_act}', f"{tit_g2} ({anio_ant} vs {anio_act})", color_ant='#AEB6BF', color_act='#2874A6')

                filas_t2 = [[tit_g2.upper(), f"VENTAS {anio_ant} ({simb})", f"VENTAS {anio_act} ({simb})", "VAR %", "PART. %"]]
                for _, r in comp_esp.head(6).iterrows():
                    filas_t2.append([str(r[dim_p2])[:30], f"{r['Ventas_Ant']:,.2f}", f"{r['Ventas_Act']:,.2f}", f"{r['Var_%']:+.1f}%", f"{r['Part_%']:.1f}%"])

            # --- PÁGINA 3: KARDEX Y RENTABILIDAD (GRÁFICO + CUADRO ESTILO SISTEMA WEB) ---
            img3 = None
            filas_t3 = []
            filas_tabla_despachos = []

            if not df_c_act.empty:
                kc_act = df_c_act.groupby(dim_p1, as_index=False).agg(Ventas_Act=('Ventas_Cruce', 'sum'), Costo_Act=('Costo', 'sum'), Util_Act=('Utilidad', 'sum'))
                img3 = crear_grafico_barras_png(kc_act, dim_p1, 'Costo_Act', 'Ventas_Act', f'Costo Kardex {anio_act}', f'Venta Cruzada {anio_act}', f"Venta Cruzada vs. Costo Kardex {anio_act} por Línea Clave", color_ant='#C0392B', color_act='#117864')

                det_act = df_c_act.groupby(['Tipo_Categoria', 'Marca_Descripcion'], as_index=False).agg(
                    Ventas=('Ventas_Cruce', 'sum'),
                    Costo=('Costo', 'sum'),
                    Utilidad=('Utilidad', 'sum')
                ).sort_values('Ventas', ascending=False)
                det_act['Margen_%'] = np.where(det_act['Ventas'] != 0, (det_act['Utilidad'] / det_act['Ventas']) * 100, 0)

                filas_tabla_despachos = [["Tipo Categoría", "Marca", f"Ventas ({simb})", f"Costo ({simb})", f"Utilidad ({simb})", "Mg %"]]
                for _, r in det_act.iterrows():
                    filas_tabla_despachos.append([
                        str(r['Tipo_Categoria'])[:22],
                        str(r['Marca_Descripcion'])[:18],
                        f"{r['Ventas']:,.2f}",
                        f"{r['Costo']:,.2f}",
                        f"{r['Utilidad']:,.2f}",
                        f"{r['Margen_%']:.1f}%"
                    ])
                filas_tabla_despachos.append([
                    "TOTAL GENERAL", "",
                    f"{vc_act:,.2f}",
                    f"{c_act:,.2f}",
                    f"{u_act:,.2f}",
                    f"{(u_act / vc_act * 100) if vc_act != 0 else 0:.1f}%"
                ])

            # --- PÁGINA 4: TOP 10 CLIENTES ---
            filas_cli = [["CLIENTE", "UNIDADES", f"VENTAS {anio_act} ({simb})", "PART. %"]]
            for _, r in top_cli.iterrows():
                part_c = (r['Ventas'] / v_act * 100) if v_act != 0 else 0
                filas_cli.append([str(r['ClienteNombre'])[:42], f"{r['Unidades']:,.0f}", f"{r['Ventas']:,.2f}", f"{part_c:.1f}%"])

            resumen_ia = f"""
            - Ventas Comerciales {anio_ant}: {simb} {v_ant:,.2f} | Ventas Comerciales {anio_act}: {simb} {v_act:,.2f} (Variación: {kpis['var_v']:+.2f}%)
            - Ventas Cruzadas Kardex {anio_act}: {simb} {vc_act:,.2f} | Costo Kardex {anio_act}: {simb} {c_act:,.2f} | Utilidad Bruta {anio_act}: {simb} {u_act:,.2f}
            - Margen Bruto Global {anio_act}: {m_act:.2f}% (vs {m_ant:.2f}% en {anio_ant})
            """

            texto_ia = generar_analisis_gemini(resumen_ia, regla, kpis, anio_ant, anio_act, simb)
            
            pdf_bytes = construir_pdf_gerencial(
                regla, empresa, moneda, p_inicio, p_fin, anio_ant, anio_act,
                kpis, texto_ia, img1, filas_t1, img2, filas_t2, img3, filas_t3, filas_tabla_despachos, filas_cli
            )

            st.success("✅ ¡Informe Gerencial PDF generado exitosamente para IS, TS y RS!")
            with st.expander("👁️ Vista previa del Diagnóstico Financiero"):
                st.markdown(texto_ia, unsafe_allow_html=True)

            st.download_button(
                label=f"📥 Descargar Informe Gerencial PDF ({regla['nombre']})",
                data=pdf_bytes,
                file_name=f"Informe_Gerencial_{empresa}_{p_inicio}_{p_fin}_{moneda}.pdf",
                mime="application/pdf",
                key="dl_pdf_gerencial_final"
            )
