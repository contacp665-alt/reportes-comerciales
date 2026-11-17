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

    # Filtrar Ventas del periodo
    df_v = df_ventas_all[
        (df_ventas_all['CompaniaSocio'].astype(str).str.strip() == empresa) &
        (df_ventas_all['VoucherPeriodo'].astype(str).str.strip() >= str(p_ini)) &
        (df_ventas_all['VoucherPeriodo'].astype(str).str.strip() <= str(p_fin))
    ].copy()

    df_v['Item'] = df_v['ItemCodigo'].astype(str).str.strip()
    if tiene_tv and regla["tipos_venta"]:
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
    df_v = pd.merge(df_v, df_m[cols_m], on='Item', how='left')

    # Top Clientes limpios
    df_v['ClienteNombre'] = df_v.get('ClienteNombre', pd.Series(['SIN NOMBRE']*len(df_v))).fillna('SIN NOMBRE').astype(str).str.strip()
    top_clientes = df_v.groupby('ClienteNombre', as_index=False).agg(
        Unidades=('CantidadPedida', 'sum'),
        Ventas=('Venta_Conv', 'sum')
    ).sort_values('Ventas', ascending=False).head(10)

    # Cruce con Kardex (si fue cargado)
    df_cruce = pd.DataFrame()
    if df_k_all is not None and not df_k_all.empty:
        df_kv = df_k_all[
            (df_k_all['CompaniaSocio'].astype(str).str.strip() == empresa) &
            (df_k_all['Periodo'].astype(str).str.strip() >= str(p_ini)) &
            (df_k_all['Periodo'].astype(str).str.strip() <= str(p_fin)) &
            (df_k_all['TransaccionCodigo'].astype(str).str.strip().str.upper().isin(['AVT', 'VTA', 'VTI']))
        ].copy()
        df_kv['Item'] = df_kv['Item'].astype(str).str.strip()
        if tiene_tv and regla["tipos_venta"]:
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
            df_cruce = pd.merge(df_cruce, df_m[cols_m], on='Item', how='left')

    return df_v, df_cruce, top_clientes, regla
def generar_analisis_gemini(resumen_texto, regla):
    api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY"))
    if not api_key:
        return "⚠️ No se encontró la clave GEMINI_API_KEY en Streamlit Secrets. Configúrala para activar el diagnóstico narrativo automático."

    prompt = f"""
    Eres un Gerente de Control de Gestión y Finanzas corporativas en Perú. Redacta un informe técnico ejecutivo breve, directo y profesional en español (sin saludos ni introducciones innecesarias) para la empresa {regla['nombre']}.
    Contexto de la empresa: {regla['giro']}
    Enfoque obligatorio de análisis: {regla['enfoque_ia']}

    Datos consolidados y auditados del periodo:
    {resumen_texto}

    Estructura tu análisis exactamente en 3 párrafos claros con subtítulos en negrita (usa etiquetas HTML <b>...</b> para negritas, no uses asteriscos markdown):
    1. <b>Diagnóstico Comercial y Crecimiento:</b> Evalúa la evolución de ventas frente al año anterior y qué líneas lideran.
    2. <b>Análisis de Rentabilidad y Márgenes:</b> Evalúa el comportamiento de costos, utilidad bruta y márgenes.
    3. <b>Foco Estratégico y Recomendaciones:</b> Señala alertas o oportunidades accionables según el giro de la empresa.
    """
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        return f"Análisis automático no disponible en este momento ({e}). Revisa las tablas adjuntas para el detalle numérico."

def crear_grafico_barras_png(df_comp, col_dim, anio_ant, anio_act, titulo, simb):
    fig, ax = plt.subplots(figsize=(7.5, 3.2), dpi=150)
    top = df_comp.head(6).copy()
    labels = [str(x)[:18] for x in top[col_dim]]
    x = np.arange(len(labels))
    width = 0.36

    rects1 = ax.bar(x - width/2, top['Ventas_Ant'], width, label=f'Ventas {anio_ant}', color='#95A5A6')
    rects2 = ax.bar(x + width/2, top['Ventas_Act'], width, label=f'Ventas {anio_act}', color='#1F618D')

    ax.set_title(titulo, fontsize=10, fontweight='bold', color='#1C2833', pad=12)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha='right', fontsize=8)
    ax.tick_params(axis='y', labelsize=8)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis='y', linestyle='--', alpha=0.4)
    ax.legend(frameon=False, fontsize=8)

    for rect in rects2:
        h = rect.get_height()
        if h > 0:
            ax.annotate(f"{h:,.0f}", xy=(rect.get_x() + rect.get_width()/2, h),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=7, fontweight='bold', color='#1F618D')

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return buf
def construir_pdf_gerencial(regla, empresa, moneda, p_ini, p_fin, anio_ant, anio_act, kpis, texto_ia, img_graf1, img_graf2, df_tabla_cat, df_tabla_esp, df_clientes):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    simb = "S/" if moneda == "SOLES" else "$"

    estilo_titulo = ParagraphStyle('TituloCorp', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#1B4F72'), spaceAfter=4)
    estilo_sub = ParagraphStyle('SubCorp', parent=styles['Normal'], fontSize=9.5, textColor=colors.HexColor('#566573'), spaceAfter=12)
    estilo_sec = ParagraphStyle('SecCorp', parent=styles['Heading2'], fontSize=11.5, textColor=colors.HexColor('#1F618D'), spaceBefore=10, spaceAfter=6)
    estilo_texto = ParagraphStyle('BodyCorp', parent=styles['Normal'], fontSize=9.5, leading=14, alignment=TA_JUSTIFY, textColor=colors.HexColor('#2C3E50'), spaceAfter=8)

    elementos = []

    # --- PÁGINA 1: PORTADA EJECUTIVA, KPIS Y DIAGNÓSTICO GEMINI ---
    elementos.append(Paragraph("INFORME EJECUTIVO DE CONTROL DE GESTIÓN", estilo_titulo))
    elementos.append(Paragraph(f"<b>Empresa:</b> {regla['nombre']}  |  <b>Periodo:</b> {p_ini} - {p_fin} (vs. {anio_ant})  |  <b>Moneda:</b> {moneda}  |  <b>Emisión:</b> {datetime.now().strftime('%d/%m/%Y')}", estilo_sub))
    elementos.append(Spacer(1, 0.2*cm))

    # Tabla de KPIs principales
    data_kpi = [
        ["INDICADOR CLAVE", f"PERIODO {anio_ant}", f"PERIODO {anio_act}", "VARIACIÓN"],
        ["Ventas Netas (Líneas Clave)", f"{simb} {kpis['v_ant']:,.2f}", f"{simb} {kpis['v_act']:,.2f}", f"{kpis['var_v']:+.2f}%"],
        ["Costo de Ventas (Kardex)", f"{simb} {kpis['c_ant']:,.2f}", f"{simb} {kpis['c_act']:,.2f}", f"{kpis['var_c']:+.2f}%"],
        ["Utilidad Bruta", f"{simb} {kpis['u_ant']:,.2f}", f"{simb} {kpis['u_act']:,.2f}", f"{kpis['var_u']:+.2f}%"],
        ["Margen Bruto (%)", f"{kpis['m_ant']:.2f}%", f"{kpis['m_act']:.2f}%", f"{kpis['m_act'] - kpis['m_ant']:+.2f} pp"],
    ]
    t_kpi = Table(data_kpi, colWidths=[6.2*cm, 3.8*cm, 3.8*cm, 3.8*cm])
    t_kpi.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B4F72')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#F8F9F9'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D5D8DC')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elementos.append(t_kpi)
    elementos.append(Spacer(1, 0.4*cm))

    elementos.append(Paragraph("DIAGNÓSTICO TÉCNICO E INTERPRETACIÓN (IA)", estilo_sec))
    for parrafo in texto_ia.split('\n'):
        if parrafo.strip():
            elementos.append(Paragraph(parrafo.strip(), estilo_texto))

    elementos.append(PageBreak())

    # --- PÁGINA 2: GRÁFICOS COMPARATIVOS Y TABLA DE RENTABILIDAD ---
    elementos.append(Paragraph("ANÁLISIS DE LÍNEAS DE NEGOCIO Y RENTABILIDAD", estilo_titulo))
    elementos.append(Paragraph(f"Comparativo interanual filtrado por líneas principales de {regla['nombre']}", estilo_sub))

    if img_graf1:
        elementos.append(Image(img_graf1, width=17.5*cm, height=7.2*cm))
        elementos.append(Spacer(1, 0.2*cm))

    if img_graf2:
        elementos.append(Image(img_graf2, width=17.5*cm, height=7.2*cm))
        elementos.append(Spacer(1, 0.3*cm))

    # Tabla alineada de Líneas Clave
    elementos.append(Paragraph("Detalle Comparativo por Línea / Categoría", estilo_sec))
    t_cat = Table(df_tabla_cat, colWidths=[5.4*cm, 3.1*cm, 3.1*cm, 2.0*cm, 2.2*cm, 1.8*cm])
    t_cat.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F618D')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#EBF5FB')),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#D5D8DC')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elementos.append(t_cat)

    elementos.append(PageBreak())

    # --- PÁGINA 3: DESGLOSE ESPECÍFICO (MARCAS / SERVICIOS) Y TOP 10 CLIENTES ---
    titulo_p3 = "DESGLOSE POR MARCAS Y TOP CLIENTES" if regla["destacar_marcas"] else ("MERCADERÍA VS. SERVICIOS Y TOP CLIENTES" if regla["es_rs"] else "DESGLOSE POR MARCAS Y TOP CLIENTES")
    elementos.append(Paragraph(titulo_p3, estilo_titulo))
    elementos.append(Spacer(1, 0.2*cm))

    if df_tabla_esp:
        sub_esp = "Top Marcas Principales" if not regla["es_rs"] else "Comparativo Mercadería vs. Servicio de Reencauche"
        elementos.append(Paragraph(sub_esp, estilo_sec))
        t_esp = Table(df_tabla_esp, colWidths=[6.2*cm, 3.3*cm, 3.3*cm, 2.3*cm, 2.5*cm])
        t_esp.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2874A6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#D5D8DC')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        elementos.append(t_esp)
        elementos.append(Spacer(1, 0.5*cm))

    elementos.append(Paragraph(f"Top 10 Clientes del Periodo ({p_ini} - {p_fin})", estilo_sec))
    t_cli = Table(df_clientes, colWidths=[9.6*cm, 2.6*cm, 3.2*cm, 2.2*cm])
    t_cli.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E8449')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#F8F9F9'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#D5D8DC')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
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
    st.info(f"**Reglas activas para esta empresa:** Se analizarán únicamente los tipos de venta **{', '.join(regla['tipos_venta'])}**.")

    uploaded_k_pdf = st.file_uploader(
        "📂 Sube el archivo Kardex (.parquet o .xlsx) para incluir Costos y Márgenes en el PDF (Opcional, pero recomendado):",
        type=["parquet", "xlsx"],
        key="uploader_kardex_pdf"
    )

    if st.button("🚀 Generar Informe Gerencial PDF con Análisis IA", type="primary", key="btn_gen_pdf"):
        with st.spinner("Auditando datos, aplicando reglas de empresa y redactando diagnóstico con Gemini..."):
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

            c_ant = df_c_ant['Costo'].sum() if not df_c_ant.empty else 0.0
            c_act = df_c_act['Costo'].sum() if not df_c_act.empty else 0.0

            u_ant = (df_c_ant['Ventas_Cruce'].sum() - c_ant) if not df_c_ant.empty else 0.0
            u_act = (df_c_act['Ventas_Cruce'].sum() - c_act) if not df_c_act.empty else 0.0

            m_ant = (u_ant / df_c_ant['Ventas_Cruce'].sum() * 100) if (not df_c_ant.empty and df_c_ant['Ventas_Cruce'].sum() != 0) else 0.0
            m_act = (u_act / df_c_act['Ventas_Cruce'].sum() * 100) if (not df_c_act.empty and df_c_act['Ventas_Cruce'].sum() != 0) else 0.0

            kpis = {
                "v_ant": v_ant, "v_act": v_act, "var_v": ((v_act - v_ant) / abs(v_ant) * 100) if v_ant != 0 else 0.0,
                "c_ant": c_ant, "c_act": c_act, "var_c": ((c_act - c_ant) / abs(c_ant) * 100) if c_ant != 0 else 0.0,
                "u_ant": u_ant, "u_act": u_act, "var_u": ((u_act - u_ant) / abs(u_ant) * 100) if u_act != 0 else 0.0,
                "m_ant": m_ant, "m_act": m_act
            }

            # Agrupación por TipoVenta / Categoría
            dim_p1 = 'TipoVenta' if 'TipoVenta' in df_v_act.columns else 'Tipo_Categoria'
            g1_ant = df_v_ant.groupby(dim_p1, as_index=False)['Venta_Conv'].sum().rename(columns={'Venta_Conv': 'Ventas_Ant'}) if not df_v_ant.empty else pd.DataFrame(columns=[dim_p1, 'Ventas_Ant'])
            g1_act = df_v_act.groupby(dim_p1, as_index=False)['Venta_Conv'].sum().rename(columns={'Venta_Conv': 'Ventas_Act'})
            comp_cat = pd.merge(g1_ant, g1_act, on=dim_p1, how='outer').fillna(0).sort_values('Ventas_Act', ascending=False)
            comp_cat['Var_%'] = np.where(comp_cat['Ventas_Ant'] != 0, ((comp_cat['Ventas_Act'] - comp_cat['Ventas_Ant']) / comp_cat['Ventas_Ant'].abs()) * 100, 0)

            # Márgenes por línea desde Kardex
            if not df_c_act.empty and dim_p1 in df_c_act.columns:
                mg_df = df_c_act.groupby(dim_p1, as_index=False)[['Ventas_Cruce', 'Costo', 'Utilidad']].sum()
                mg_df['Margen_%'] = np.where(mg_df['Ventas_Cruce'] != 0, (mg_df['Utilidad'] / mg_df['Ventas_Cruce']) * 100, 0)
                comp_cat = pd.merge(comp_cat, mg_df[[dim_p1, 'Utilidad', 'Margen_%']], on=dim_p1, how='left').fillna({'Utilidad': 0, 'Margen_%': 0})
            else:
                comp_cat['Utilidad'] = 0.0
                comp_cat['Margen_%'] = 0.0

            filas_cat = [["LÍNEA / CATEGORÍA", f"VENTAS {anio_ant}", f"VENTAS {anio_act}", "VAR %", f"UTILIDAD {anio_act}", "MARGEN"]]
            for _, r in comp_cat.iterrows():
                filas_cat.append([
                    str(r[dim_p1])[:26], f"{simb} {r['Ventas_Ant']:,.0f}", f"{simb} {r['Ventas_Act']:,.0f}",
                    f"{r['Var_%']:+.1f}%", f"{simb} {r['Utilidad']:,.0f}", f"{r['Margen_%']:.1f}%"
                ])
            filas_cat.append(["TOTAL GENERAL", f"{simb} {v_ant:,.0f}", f"{simb} {v_act:,.0f}", f"{kpis['var_v']:+.1f}%", f"{simb} {u_act:,.0f}", f"{m_act:.1f}%"])

            # Gráficos
            img1 = crear_grafico_barras_png(comp_cat, dim_p1, anio_ant, anio_act, f"Comparativo Ventas por Línea Clave ({anio_ant} vs {anio_act})", simb)

            # Agrupación específica (Marcas para TS/IS o Mercadería vs Servicio para RS)
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

            img2 = crear_grafico_barras_png(comp_esp, dim_p2, anio_ant, anio_act, f"{tit_g2} ({anio_ant} vs {anio_act})", simb)

            filas_esp = [[tit_g2.upper(), f"VENTAS {anio_ant}", f"VENTAS {anio_act}", "VAR %", "PART. %"]]
            for _, r in comp_esp.head(8).iterrows():
                filas_esp.append([str(r[dim_p2])[:30], f"{simb} {r['Ventas_Ant']:,.0f}", f"{simb} {r['Ventas_Act']:,.0f}", f"{r['Var_%']:+.1f}%", f"{r['Part_%']:.1f}%"])

            filas_cli = [["CLIENTE", "UNIDADES", f"VENTAS {anio_act}", "PART. %"]]
            for _, r in top_cli.iterrows():
                part_c = (r['Ventas'] / v_act * 100) if v_act != 0 else 0
                filas_cli.append([str(r['ClienteNombre'])[:42], f"{r['Unidades']:,.0f}", f"{simb} {r['Ventas']:,.2f}", f"{part_c:.1f}%"])

            # Resumen numérico limpio para Gemini
            resumen_ia = f"""
            - Ventas {anio_ant}: {simb} {v_ant:,.2f} | Ventas {anio_act}: {simb} {v_act:,.2f} (Variación: {kpis['var_v']:+.2f}%)
            - Costo Kardex {anio_act}: {simb} {c_act:,.2f} | Utilidad Bruta {anio_act}: {simb} {u_act:,.2f} | Margen Bruto {anio_act}: {m_act:.2f}% (vs {m_ant:.2f}% en {anio_ant})
            - Desglose por Línea Principal ({anio_act}):
            {comp_cat[[dim_p1, 'Ventas_Ant', 'Ventas_Act', 'Var_%', 'Margen_%']].to_string(index=False)}
            - Desglose Específico ({tit_g2}):
            {comp_esp[[dim_p2, 'Ventas_Ant', 'Ventas_Act', 'Var_%', 'Part_%']].head(6).to_string(index=False)}
            """

            texto_ia = generar_analisis_gemini(resumen_ia, regla)
            pdf_bytes = construir_pdf_gerencial(
                regla, empresa, moneda, p_inicio, p_fin, anio_ant, anio_act,
                kpis, texto_ia, img1, img2, filas_cat, filas_esp, filas_cli
            )

            st.success("✅ ¡Informe Gerencial PDF generado exitosamente!")
            with st.expander("👁️ Vista previa del Diagnóstico redactado por Gemini"):
                st.markdown(texto_ia, unsafe_allow_html=True)

            st.download_button(
                label=f"📥 Descargar Informe Gerencial PDF ({regla['nombre']})",
                data=pdf_bytes,
                file_name=f"Informe_Gerencial_{empresa}_{p_inicio}_{p_fin}_{moneda}.pdf",
                mime="application/pdf",
                key="dl_pdf_gerencial_final"
            )

