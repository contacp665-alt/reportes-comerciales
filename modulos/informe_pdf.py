# -*- coding: utf-8 -*-
"""Informe gerencial PDF: TS, IS y RS.

Reemplaza el módulo modulos/informe_pdf.py. Mantiene la interfaz render(ctx)
utilizada por la aplicación principal.
"""

import html
import io
import os
import re
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

try:
    from google import genai
except Exception:  # El informe debe seguir funcionando sin el SDK instalado.
    genai = None

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    PageBreak, KeepTogether
)


REGLAS_EMPRESAS = {
    "02000000": {
        "nombre": "TIRE SOL S.A.C. (TS)",
        "giro": "Empresa comercial e importadora dedicada a neumáticos, aros y ejes. Su línea principal son las llantas.",
        "tipos_venta": ["AROS Y EJES", "CAMARAS Y PROTECTORES", "LLANTAS"],
        "enfoque_ia": "Analizar ventas y márgenes por línea y marcas, dando prioridad a LLANTAS.",
        "es_rs": False, "destacar_marcas": True,
    },
    "01000000": {
        "nombre": "REENCAUCHADORA EL SOL S.A.C. (RS)",
        "giro": "Empresa mixta: comercialización de cámaras, parches y llantas, y prestación del servicio industrial de reencauche.",
        "tipos_venta": ["CAMARAS Y PROTECTORES", "LLANTAS", "PARCHES", "SERVICIO DE REENCAUCHE"],
        "tipos_mercaderia": ["CAMARAS Y PROTECTORES", "LLANTAS", "PARCHES"],
        "tipo_servicio": "SERVICIO DE REENCAUCHE",
        "enfoque_ia": "Separar MERCADERÍA (cámaras y protectores, llantas y parches) de SERVICIOS (servicio de reencauche). Analizar marcas solamente para mercadería; comparar la rentabilidad de ambas unidades.",
        "es_rs": True, "destacar_marcas": True,
    },
    "03000000": {
        "nombre": "INDUSTRIAL EL SOL S.A.C. (IS)",
        "giro": "Planta industrial dedicada a la fabricación y venta de bandas de rodamiento, goma cojín, cemento y tiras.",
        "tipos_venta": ["BANDAS", "GOMA COJIN", "CEMENTO", "TIRAS"],
        "enfoque_ia": "Evaluar las cuatro líneas industriales BANDAS, GOMA COJIN, CEMENTO y TIRAS.",
        "es_rs": False, "destacar_marcas": False,
    },
}

COLUMNAS_VENTAS = ["CompaniaSocio", "VoucherPeriodo", "ItemCodigo", "Monto", "CantidadPedida", "MonedaDocumento", "FechaDocumento", "NumeroDocumento"]
COLUMNAS_KARDEX = ["CompaniaSocio", "Periodo", "TransaccionCodigo", "Item", "MontoTotal", "MontoTotalDolares", "ReferenciaNumeroDocumento.1"]


def _texto_columna(df, columna, defecto=""):
    if columna not in df.columns:
        return pd.Series([defecto] * len(df), index=df.index, dtype="object")
    return df[columna].fillna(defecto).astype(str).str.strip()


def _numero_seguro(serie):
    return pd.to_numeric(serie, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _variacion(actual, anterior):
    if abs(float(anterior)) < 1e-12:
        return 100.0 if actual > 0 else (0.0 if actual == 0 else -100.0)
    return (float(actual) - float(anterior)) / abs(float(anterior)) * 100.0


def _porcentaje(parte, total):
    return float(parte) / float(total) * 100.0 if abs(float(total)) > 1e-12 else 0.0


def _tipo_cambio_por_fecha(df, df_tc):
    """Adjunta TC por fecha y completa faltantes con el último TC conocido."""
    if df.empty:
        return df
    out = df.copy()
    if df_tc is None or df_tc.empty or "Fecha" not in df_tc.columns or "Oficial Venta" not in df_tc.columns:
        out["Oficial Venta"] = np.nan
        return out
    tc = df_tc.copy()
    tc["Fecha_Clave_Busqueda"] = _texto_columna(tc, "Fecha").str.slice(0, 10)
    tc["Oficial Venta"] = _numero_seguro(tc["Oficial Venta"])
    tc = tc[["Fecha_Clave_Busqueda", "Oficial Venta"]].drop_duplicates("Fecha_Clave_Busqueda", keep="last")
    out["Fecha_Clave"] = _texto_columna(out, "FechaDocumento").str.slice(0, 10)
    out = out.merge(tc, left_on="Fecha_Clave", right_on="Fecha_Clave_Busqueda", how="left")
    out["Oficial Venta"] = out["Oficial Venta"].replace(0, np.nan)
    out = out.sort_values("Fecha_Clave", kind="stable")
    out["Oficial Venta"] = out["Oficial Venta"].ffill()
    return out


def _convertir_montos(df, moneda, columna_origen="Monto", columna_destino="Venta_Conv"):
    out = df.copy()
    monto = _numero_seguro(out[columna_origen]) if columna_origen in out.columns else pd.Series(0.0, index=out.index)
    doc_moneda = _texto_columna(out, "MonedaDocumento").str.upper()
    tc = _numero_seguro(out["Oficial Venta"]) if "Oficial Venta" in out.columns else pd.Series(0.0, index=out.index)
    a_soles = (moneda == "SOLES") & (doc_moneda == "EX")
    a_dolares = (moneda != "SOLES") & (doc_moneda == "LO")
    valores = monto.to_numpy(dtype=float, copy=True)
    tipos = doc_moneda.to_numpy()
    tasas = tc.to_numpy(dtype=float)
    if moneda == "SOLES":
        convertir = a_soles.to_numpy()
        valores[convertir] = valores[convertir] * tasas[convertir]
    else:
        convertir = a_dolares.to_numpy()
        validas = convertir & (tasas != 0)
        valores[validas] = valores[validas] / tasas[validas]
        valores[convertir & ~validas] = 0.0
    valores[~np.isfinite(valores)] = 0.0
    out[columna_destino] = valores
    out["_TC_FALTANTE"] = (a_soles | a_dolares) & (tc <= 0)
    return out


def _regla_empresa(empresa):
    return REGLAS_EMPRESAS.get(str(empresa), REGLAS_EMPRESAS["02000000"])


def obtener_datos_limpios_empresa(df_ventas_all, df_k_all, df_tc, df_maestro, empresa, moneda, p_ini, p_fin):
    """Devuelve ventas, cruce Kardex, top clientes y regla de la empresa.

    Para TS, IS y RS el campo TipoVenta del maestro es obligatorio: si falta,
    no se incluyen registros sin clasificar por error. La validación se comunica
    mediante regla['_error_validacion'] y no mediante un KeyError.
    """
    regla = dict(_regla_empresa(empresa))
    vacio = pd.DataFrame()
    if df_ventas_all is None or df_ventas_all.empty:
        regla["_error_validacion"] = "El archivo histórico de ventas está vacío."
        return vacio, vacio, vacio, regla
    if df_maestro is None or df_maestro.empty or "Item" not in df_maestro.columns:
        regla["_error_validacion"] = "El Maestro de Ítems debe contener la columna Item y registros válidos."
        return vacio, vacio, vacio, regla
    if "TipoVenta" not in df_maestro.columns:
        regla["_error_validacion"] = "Falta la columna TipoVenta en el Maestro de Ítems. Es necesaria para aplicar las reglas de TS, IS y para separar mercadería/servicios en RS."
        return vacio, vacio, vacio, regla

    requeridas = [c for c in ["CompaniaSocio", "VoucherPeriodo", "ItemCodigo", "Monto"] if c not in df_ventas_all.columns]
    if requeridas:
        regla["_error_validacion"] = "Faltan columnas obligatorias en Ventas: " + ", ".join(requeridas)
        return vacio, vacio, vacio, regla

    maestro = df_maestro.copy()
    maestro["Item"] = _texto_columna(maestro, "Item")
    maestro["TipoVenta"] = _texto_columna(maestro, "TipoVenta").str.upper()
    maestro["Tipo_Categoria"] = _texto_columna(maestro, "Tipo_Categoria", "SIN CATEGORÍA").replace("", "SIN CATEGORÍA")
    maestro["Marca_Descripcion"] = _texto_columna(maestro, "Marca_Descripcion", "SIN MARCA").replace("", "SIN MARCA")
    maestro = maestro.drop_duplicates("Item", keep="last")

    tipos_validos = set(regla["tipos_venta"])
    maestro = maestro[maestro["TipoVenta"].isin(tipos_validos)].copy()
    items_validos = set(maestro["Item"])
    if not items_validos:
        regla["_error_validacion"] = "El Maestro de Ítems no contiene ítems con los TipoVenta configurados para esta empresa: " + ", ".join(regla["tipos_venta"])
        return vacio, vacio, vacio, regla

    ventas = df_ventas_all.copy()
    ventas["_empresa"] = _texto_columna(ventas, "CompaniaSocio")
    ventas["_periodo"] = _texto_columna(ventas, "VoucherPeriodo")
    ventas = ventas[(ventas["_empresa"] == str(empresa)) & (ventas["_periodo"] >= str(p_ini)) & (ventas["_periodo"] <= str(p_fin))].copy()
    ventas["Item"] = _texto_columna(ventas, "ItemCodigo")
    ventas = ventas[ventas["Item"].isin(items_validos)].copy()
    if ventas.empty:
        return vacio, vacio, vacio, regla

    ventas = _tipo_cambio_por_fecha(ventas, df_tc)
    ventas["Monto"] = _numero_seguro(ventas["Monto"])
    ventas["CantidadPedida"] = _numero_seguro(ventas["CantidadPedida"]) if "CantidadPedida" in ventas.columns else 0.0
    ventas = _convertir_montos(ventas, moneda)
    columnas_maestro = ["Item", "TipoVenta", "Tipo_Categoria", "Marca_Descripcion"]
    ventas = ventas.merge(maestro[columnas_maestro], on="Item", how="left", validate="many_to_one")
    ventas["ClienteNombre"] = _texto_columna(ventas, "ClienteNombre", "SIN NOMBRE").replace("", "SIN NOMBRE")

    if regla["es_rs"]:
        ventas["Grupo_RS"] = np.where(ventas["TipoVenta"].isin(regla["tipos_mercaderia"]), "MERCADERÍA", "SERVICIOS")

    top_clientes = (ventas.groupby("ClienteNombre", as_index=False)
                    .agg(Unidades=("CantidadPedida", "sum"), Ventas=("Venta_Conv", "sum"))
                    .sort_values("Ventas", ascending=False).head(10))

    cruce = pd.DataFrame()
    if df_k_all is not None and not df_k_all.empty:
        faltantes_k = [c for c in ["CompaniaSocio", "Periodo", "TransaccionCodigo", "Item"] if c not in df_k_all.columns]
        col_costo = "MontoTotal" if moneda == "SOLES" else "MontoTotalDolares"
        if not faltantes_k and col_costo in df_k_all.columns and "ReferenciaNumeroDocumento.1" in df_k_all.columns:
            kardex = df_k_all.copy()
            kardex["_empresa"] = _texto_columna(kardex, "CompaniaSocio")
            kardex["_periodo"] = _texto_columna(kardex, "Periodo")
            kardex["_trans"] = _texto_columna(kardex, "TransaccionCodigo").str.upper()
            kardex["Item"] = _texto_columna(kardex, "Item")
            kardex = kardex[(kardex["_empresa"] == str(empresa)) & (kardex["_periodo"] >= str(p_ini)) & (kardex["_periodo"] <= str(p_fin)) & kardex["_trans"].isin(["AVT", "VTA", "VTI"]) & kardex["Item"].isin(items_validos)].copy()
            if not kardex.empty:
                kardex["Costo"] = _numero_seguro(kardex[col_costo]) * -1
                kardex["Doc_Cruce"] = _texto_columna(kardex, "ReferenciaNumeroDocumento.1")
                kardex = kardex[kardex["Doc_Cruce"] != ""]
                k_agg = kardex.groupby(["Doc_Cruce", "Item"], as_index=False)["Costo"].sum()
                ventas_hist = df_ventas_all.copy()
                if all(c in ventas_hist.columns for c in ["CompaniaSocio", "NumeroDocumento", "ItemCodigo", "Monto"]):
                    ventas_hist = ventas_hist[_texto_columna(ventas_hist, "CompaniaSocio") == str(empresa)].copy()
                    ventas_hist["Doc_Cruce"] = _texto_columna(ventas_hist, "NumeroDocumento")
                    ventas_hist["Item"] = _texto_columna(ventas_hist, "ItemCodigo")
                    llaves = set(zip(k_agg["Doc_Cruce"], k_agg["Item"]))
                    ventas_hist = ventas_hist[ventas_hist.set_index(["Doc_Cruce", "Item"]).index.isin(llaves)].copy()
                    ventas_hist = _tipo_cambio_por_fecha(ventas_hist, df_tc)
                    ventas_hist["Monto"] = _numero_seguro(ventas_hist["Monto"])
                    ventas_hist = _convertir_montos(ventas_hist, moneda, columna_destino="Ventas_Cruce")
                    v_agg = ventas_hist.groupby(["Doc_Cruce", "Item"], as_index=False)["Ventas_Cruce"].sum()
                    cruce = k_agg.merge(v_agg, on=["Doc_Cruce", "Item"], how="left")
                    cruce["Ventas_Cruce"] = _numero_seguro(cruce["Ventas_Cruce"])
                    cruce["Utilidad"] = cruce["Ventas_Cruce"] - cruce["Costo"]
                    cruce = cruce.merge(maestro[columnas_maestro], on="Item", how="left", validate="many_to_one")
                    if regla["es_rs"]:
                        cruce["Grupo_RS"] = np.where(cruce["TipoVenta"].isin(regla["tipos_mercaderia"]), "MERCADERÍA", "SERVICIOS")

    regla["_tc_faltante_ventas"] = int(ventas.get("_TC_FALTANTE", pd.Series(dtype=bool)).sum())
    return ventas, cruce, top_clientes, regla


def _limpiar_texto_ia(texto):
    texto = str(texto or "").strip()
    texto = re.sub(r"```(?:html)?|```", "", texto, flags=re.IGNORECASE)
    texto = texto.replace("**", "")
    return texto


def _resumen_local(datos):
    """Produce exactamente tres párrafos usando exclusivamente cifras calculadas."""
    r = datos["regla"]
    ant, act = datos["anio_ant"], datos["anio_act"]
    ventas_ant, ventas_act = datos["v_ant"], datos["v_act"]
    var_ventas = _variacion(ventas_act, ventas_ant)
    lineas = datos["comp_cat"]
    lider = lineas.sort_values("Ventas_Act", ascending=False).head(1)
    if lider.empty:
        lider_txt = "no se identifican líneas con ventas"
    else:
        lider_txt = f"{lider.iloc[0]['NombreLinea']} concentra {lider.iloc[0]['Ventas_Act']:,.2f} ({lider.iloc[0]['Part_%']:.1f}% del total)"
    if r["es_rs"]:
        grupo = datos["comp_grupo"]
        merc = grupo[grupo["Grupo_RS"] == "MERCADERÍA"]
        serv = grupo[grupo["Grupo_RS"] == "SERVICIOS"]
        merc_v = float(merc["Ventas_Act"].sum()) if not merc.empty else 0.0
        serv_v = float(serv["Ventas_Act"].sum()) if not serv.empty else 0.0
        p1_detalle = f"En RS, la mercadería representa {merc_v:,.2f} y los servicios {serv_v:,.2f} en {act}."
    else:
        p1_detalle = f"La principal línea es {lider_txt}."
    p1 = (f"<b>Diagnóstico Comercial y Crecimiento:</b> Las ventas comerciales pasaron de {ventas_ant:,.2f} en {ant} a {ventas_act:,.2f} en {act}, "
          f"con una variación de {var_ventas:+.2f}%. {p1_detalle}")

    vc_ant, vc_act = datos["vc_ant"], datos["vc_act"]
    c_ant, c_act = datos["c_ant"], datos["c_act"]
    u_ant, u_act = datos["u_ant"], datos["u_act"]
    m_ant, m_act = datos["m_ant"], datos["m_act"]
    p2 = (f"<b>Análisis de Rentabilidad y Costos Kardex:</b> Las ventas cruzadas del Kardex fueron {vc_ant:,.2f} en {ant} y {vc_act:,.2f} en {act}; "
          f"el costo pasó de {c_ant:,.2f} a {c_act:,.2f}, mientras que la utilidad bruta fue {u_ant:,.2f} y {u_act:,.2f}, respectivamente. "
          f"El margen bruto cambió de {m_ant:.2f}% a {m_act:.2f}% ({m_act-m_ant:+.2f} puntos porcentuales). "
          f"Las cifras corresponden al cruce disponible entre documentos de venta y salidas de Kardex.")

    if r["es_rs"]:
        grupo = datos["comp_grupo"]
        fila_m = grupo[grupo["Grupo_RS"] == "MERCADERÍA"]
        fila_s = grupo[grupo["Grupo_RS"] == "SERVICIOS"]
        util_m = float(fila_m["Util_Act"].sum()) if not fila_m.empty else 0.0
        util_s = float(fila_s["Util_Act"].sum()) if not fila_s.empty else 0.0
        p3_det = (f"En RS, conviene monitorear por separado la utilidad de mercadería ({util_m:,.2f}) y la del servicio de reencauche ({util_s:,.2f}); "
                  "las marcas se interpretan únicamente dentro de mercadería.")
    elif datos["empresa"] == "03000000":
        p3_det = "En IS, el seguimiento debe centrarse en el desempeño y margen de BANDAS, GOMA COJÍN, CEMENTO y TIRAS; no se presenta ranking de marcas porque no aporta diferenciación para esta operación."
    else:
        p3_det = "En TS, se recomienda priorizar el seguimiento de LLANTAS y contrastar su crecimiento con su margen y las marcas que concentran las ventas."
    p3 = (f"<b>Foco Estratégico y Recomendaciones:</b> {p3_det} "
          "Validar las variaciones relevantes con el detalle de documentos y revisar las líneas con crecimiento de ventas acompañado de reducción del margen. "
          "No se atribuyen causas operativas que no estén contenidas en los datos.")
    return "\n\n".join([p1, p2, p3])


def generar_analisis_gemini(resumen_texto, regla, datos_locales=None):
    """Intenta Gemini; ante cualquier fallo devuelve diagnóstico matemático local."""
    fallback = _resumen_local(datos_locales) if datos_locales is not None else (
        "<b>Diagnóstico Comercial y Crecimiento:</b> No se pudo generar un diagnóstico con IA y no se proporcionó un resumen local suficiente.\n\n"
        "<b>Análisis de Rentabilidad y Costos Kardex:</b> Revise los importes y márgenes mostrados en las tablas del informe.\n\n"
        "<b>Foco Estratégico y Recomendaciones:</b> Verifique la clasificación de los ítems y la conciliación entre ventas y Kardex."
    )
    try:
        api_key = None
        try:
            api_key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            api_key = None
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key or genai is None:
            return fallback, "Diagnóstico local (Gemini no configurado)"

        prompt = f"""Actúa como analista financiero y de control de gestión en Perú. Redacta exactamente TRES párrafos, en español, sin inventar causas ni cifras. Usa subtítulos HTML <b>...</b>.
Empresa: {regla['nombre']}
Contexto: {regla['giro']}
Enfoque: {regla['enfoque_ia']}
Reglas: compara periodos, interpreta porcentajes y puntos porcentuales; si el dato no existe, dilo. No confundas ventas comerciales con ventas cruzadas de Kardex.
Datos:
{resumen_texto}

Párrafo 1: <b>Diagnóstico Comercial y Crecimiento:</b> variación real de ventas y líneas/grupos líderes.
Párrafo 2: <b>Análisis de Rentabilidad y Costos Kardex:</b> ventas cruzadas, costos, utilidad bruta y margen.
Párrafo 3: <b>Foco Estratégico y Recomendaciones:</b> recomendaciones específicas para esta empresa.
Devuelve solo los tres párrafos separados por una línea en blanco."""
        client = genai.Client(api_key=api_key)
        ultimo_error = ""
        # Orden de preferencia: modelo Flash vigente y alternativas de menor costo.
        for modelo in ("gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash"):
            try:
                respuesta = client.models.generate_content(model=modelo, contents=prompt)
                texto = _limpiar_texto_ia(getattr(respuesta, "text", ""))
                cantidad_subtitulos = len(re.findall(r"<b>", texto, flags=re.I))
                cantidad_parrafos = len([p for p in re.split(r"\n\s*\n", texto) if p.strip()])
                if texto and cantidad_subtitulos == 3 and cantidad_parrafos == 3:
                    return texto, f"Diagnóstico generado con {modelo}"
                if texto:
                    ultimo_error = "La respuesta de Gemini no respetó exactamente los tres párrafos solicitados."
            except Exception as exc:
                ultimo_error = str(exc)[:300]
        return fallback, f"Diagnóstico local (Gemini no disponible: {ultimo_error or 'respuesta vacía'})"
    except Exception as exc:
        return fallback, f"Diagnóstico local (fallo de Gemini: {str(exc)[:200]})"


def crear_grafico_barras_png(df_comp, col_dim, col_ant, col_act, label_ant, label_act, titulo,
                             color_ant="#95A5A6", color_act="#1F618D", max_barras=8):
    if df_comp is None or df_comp.empty:
        return None
    datos = df_comp.head(max_barras).copy()
    fig, ax = plt.subplots(figsize=(8.0, 2.9), dpi=160)
    etiquetas = [str(x)[:25] for x in datos[col_dim]]
    x = np.arange(len(etiquetas))
    ancho = 0.36
    barras_a = ax.bar(x - ancho / 2, datos[col_ant], ancho, label=label_ant, color=color_ant)
    barras_b = ax.bar(x + ancho / 2, datos[col_act], ancho, label=label_act, color=color_act)
    ax.set_title(titulo, fontsize=10, fontweight="bold", color="#1C2833", pad=10)
    ax.set_xticks(x)
    ax.set_xticklabels(etiquetas, rotation=12, ha="right", fontsize=7.5)
    ax.tick_params(axis="y", labelsize=7.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=7.5, loc="best")
    for barras in (barras_a, barras_b):
        for barra in barras:
            h = barra.get_height()
            if h > 0:
                ax.annotate(f"{h:,.0f}", (barra.get_x() + barra.get_width()/2, h),
                            xytext=(0, 2), textcoords="offset points", ha="center", va="bottom", fontsize=6)
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return buffer


def _tabla_comparativa(df_ant, df_act, dimension, total_act=None):
    ant = (df_ant.groupby(dimension, as_index=False)["Venta_Conv"].sum().rename(columns={"Venta_Conv": "Ventas_Ant"})
           if not df_ant.empty else pd.DataFrame(columns=[dimension, "Ventas_Ant"]))
    act = (df_act.groupby(dimension, as_index=False)["Venta_Conv"].sum().rename(columns={"Venta_Conv": "Ventas_Act"})
           if not df_act.empty else pd.DataFrame(columns=[dimension, "Ventas_Act"]))
    comp = ant.merge(act, on=dimension, how="outer").fillna(0)
    comp["Var_%"] = [_variacion(a, b) for a, b in zip(comp["Ventas_Act"], comp["Ventas_Ant"])]
    base = float(total_act if total_act is not None else comp["Ventas_Act"].sum())
    comp["Part_%"] = comp["Ventas_Act"].map(lambda x: _porcentaje(x, base))
    return comp.sort_values("Ventas_Act", ascending=False).reset_index(drop=True)


def _tabla_pdf(filas, anchos, color="#1F618D", total=True, font_size=7.5, repetir=1):
    tabla = Table(filas, colWidths=anchos, repeatRows=repetir, hAlign="LEFT")
    estilos = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(color)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F7F9F9"), colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D5D8DC")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if total and len(filas) > 1:
        estilos.extend([("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF2F8"))])
    tabla.setStyle(TableStyle(estilos))
    return tabla


def construir_pdf_gerencial(regla, empresa, moneda, p_ini, p_fin, anio_ant, anio_act,
                             kpis, texto_ia, img_g1, filas_t1, img_g2, filas_t2,
                             img_g3, filas_t3, filas_cli, interpretaciones=None,
                             filas_detalle_kardex=None):
    """Construye PDF A4; tablas largas pueden continuar en páginas adicionales."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.25*cm, leftMargin=1.25*cm,
                            topMargin=1.2*cm, bottomMargin=1.2*cm)
    styles = getSampleStyleSheet()
    simb = "S/" if moneda == "SOLES" else "$"
    titulo = ParagraphStyle("TituloInforme", parent=styles["Heading1"], fontSize=14,
                            textColor=colors.HexColor("#1B4F72"), spaceAfter=4)
    subtitulo = ParagraphStyle("SubInforme", parent=styles["Normal"], fontSize=8.5,
                               textColor=colors.HexColor("#566573"), spaceAfter=7)
    seccion = ParagraphStyle("SeccionInforme", parent=styles["Heading2"], fontSize=10,
                             textColor=colors.HexColor("#1F618D"), spaceBefore=6, spaceAfter=4)
    cuerpo = ParagraphStyle("CuerpoInforme", parent=styles["BodyText"], fontSize=8.7,
                            leading=12.2, alignment=TA_JUSTIFY, textColor=colors.HexColor("#2C3E50"), spaceAfter=6)
    elementos = []

    # PÁGINA 1: portada, KPIs y diagnóstico.
    elementos.append(Paragraph("INFORME EJECUTIVO DE CONTROL DE GESTIÓN", titulo))
    elementos.append(Paragraph(
        f"<b>Empresa:</b> {html.escape(regla['nombre'])} &nbsp; | &nbsp; <b>Periodo:</b> {p_ini} - {p_fin} (vs. {anio_ant}) &nbsp; | &nbsp; <b>Moneda:</b> {moneda} &nbsp; | &nbsp; <b>Emisión:</b> {datetime.now().strftime('%d/%m/%Y')}",
        subtitulo))
    cab_kpi = ["INDICADOR CLAVE", f"PERIODO {anio_ant} ({simb})", f"PERIODO {anio_act} ({simb})", "VARIACIÓN"]
    filas_kpi = [cab_kpi]
    for etiqueta, clave, variacion in [
        ("Ventas Comerciales (Facturación)", "v", "var_v"),
        ("Ventas Cruzadas (Despachos Kardex)", "vc", "var_vc"),
        ("Costo de Ventas (Kardex)", "c", "var_c"),
        ("Utilidad Bruta (Kardex)", "u", "var_u"),
    ]:
        filas_kpi.append([etiqueta, f"{kpis[clave+'_ant']:,.2f}", f"{kpis[clave+'_act']:,.2f}", f"{kpis[variacion]:+.2f}%"])
    filas_kpi.append(["Margen Bruto (%)", f"{kpis['m_ant']:.2f}%", f"{kpis['m_act']:.2f}%", f"{kpis['m_act']-kpis['m_ant']:+.2f} pp"])
    elementos.append(_tabla_pdf(filas_kpi, [7.0*cm, 3.4*cm, 3.4*cm, 3.3*cm], "#1B4F72", False, 7.2))
    elementos.append(Spacer(1, 0.25*cm))
    elementos.append(Paragraph("DIAGNÓSTICO TÉCNICO E INTERPRETACIÓN", seccion))
    for parrafo in [p.strip() for p in texto_ia.split("\n\n") if p.strip()]:
        elementos.append(Paragraph(parrafo, cuerpo))
    elementos.append(PageBreak())

    # PÁGINA 2: ventas por línea/grupo y marcas.
    elementos.append(Paragraph("ANÁLISIS COMERCIAL: VENTAS POR LÍNEA Y MARCA", titulo))
    elementos.append(Paragraph(f"Comparativo interanual de facturación ({anio_ant} vs. {anio_act}) - {regla['nombre']}", subtitulo))
    if img_g1:
        elementos.append(Image(img_g1, width=17.2*cm, height=5.3*cm))
    if filas_t1:
        elementos.append(_tabla_pdf(filas_t1, [5.5*cm, 3.0*cm, 3.0*cm, 2.4*cm, 2.4*cm], "#1F618D", True, 7.0))
    if interpretaciones and interpretaciones.get("comercial"):
        elementos.append(Spacer(1, 0.12*cm))
        elementos.append(Paragraph("Interpretación comercial", seccion))
        elementos.append(Paragraph(interpretaciones["comercial"], cuerpo))
    if img_g2:
        elementos.append(Spacer(1, 0.18*cm))
        elementos.append(Image(img_g2, width=17.2*cm, height=4.8*cm))
    if filas_t2:
        elementos.append(_tabla_pdf(filas_t2, [5.5*cm, 3.0*cm, 3.0*cm, 2.4*cm, 2.4*cm], "#2874A6", False, 7.0))
    if interpretaciones and interpretaciones.get("marcas"):
        elementos.append(Paragraph(interpretaciones["marcas"], cuerpo))
    elementos.append(PageBreak())

    # PÁGINA 3: ventas cruzadas vs costo y detalle categoría/marca.
    elementos.append(Paragraph("KARDEX Y RENTABILIDAD", titulo))
    elementos.append(Paragraph(f"Comparación de ventas cruzadas y costo valorizado del Kardex ({anio_ant} vs. {anio_act})", subtitulo))
    if img_g3:
        elementos.append(Image(img_g3, width=17.2*cm, height=5.2*cm))
    if filas_t3:
        elementos.append(Paragraph("Resumen de rentabilidad por tipo de venta", seccion))
        elementos.append(_tabla_pdf(filas_t3, [4.1*cm, 2.6*cm, 2.6*cm, 2.6*cm, 2.3*cm, 2.1*cm], "#117864", True, 6.8))
    if interpretaciones and interpretaciones.get("kardex"):
        elementos.append(Paragraph(interpretaciones["kardex"], cuerpo))
    if filas_detalle_kardex:
        elementos.append(Spacer(1, 0.15*cm))
        elementos.append(Paragraph("Detalle de rentabilidad por categoría y marca", seccion))
        elementos.append(Paragraph("Ordenado primero por categoría y, dentro de cada categoría, de mayor a menor venta.", cuerpo))
        elementos.append(_tabla_pdf(filas_detalle_kardex,
                                    [4.2*cm, 3.7*cm, 2.5*cm, 2.5*cm, 2.5*cm, 1.8*cm],
                                    "#0E6655", True, 6.5))
    else:
        elementos.append(Paragraph("No hay datos de Kardex suficientes para construir el detalle de rentabilidad.", cuerpo))
    elementos.append(PageBreak())

    # PÁGINA 4: Top clientes.
    elementos.append(Paragraph("PRINCIPALES CLIENTES DEL PERIODO", titulo))
    elementos.append(Paragraph(f"Top 10 clientes en líneas válidas ({p_ini} - {p_fin} | {moneda})", subtitulo))
    if filas_cli and len(filas_cli) > 1:
        elementos.append(_tabla_pdf(filas_cli, [8.2*cm, 2.4*cm, 3.8*cm, 2.4*cm], "#1E8449", False, 7.5))
    else:
        elementos.append(Paragraph("No se registraron clientes para el periodo seleccionado.", cuerpo))
    if interpretaciones and interpretaciones.get("clientes"):
        elementos.append(Spacer(1, 0.2*cm))
        elementos.append(Paragraph("Interpretación del ranking", seccion))
        elementos.append(Paragraph(interpretaciones["clientes"], cuerpo))

    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()


def _filas_ventas(comp, nombre_col, anio_ant, anio_act, total_ant, total_act, var_total, simb):
    filas = [[nombre_col.upper(), f"VENTAS {anio_ant} ({simb})", f"VENTAS {anio_act} ({simb})", "VAR %", "PART. %"]]
    for _, row in comp.iterrows():
        filas.append([str(row["NombreLinea"])[:34], f"{row['Ventas_Ant']:,.2f}", f"{row['Ventas_Act']:,.2f}",
                      f"{row['Var_%']:+.1f}%", f"{row['Part_%']:.1f}%"])
    filas.append(["TOTAL GENERAL", f"{total_ant:,.2f}", f"{total_act:,.2f}", f"{var_total:+.1f}%", "100.0%"])
    return filas


def _resumen_kardex(df_ant, df_act, dimension, anio_ant, anio_act):
    cols = [dimension, "VC_Ant", "Costo_Ant", "Util_Ant", "VC_Act", "Costo_Act", "Util_Act"]
    ant = (df_ant.groupby(dimension, as_index=False).agg(VC_Ant=("Ventas_Cruce", "sum"), Costo_Ant=("Costo", "sum"), Util_Ant=("Utilidad", "sum"))
           if not df_ant.empty else pd.DataFrame(columns=cols[:4]))
    act = (df_act.groupby(dimension, as_index=False).agg(VC_Act=("Ventas_Cruce", "sum"), Costo_Act=("Costo", "sum"), Util_Act=("Utilidad", "sum"))
           if not df_act.empty else pd.DataFrame(columns=[dimension, "VC_Act", "Costo_Act", "Util_Act"]))
    comp = ant.merge(act, on=dimension, how="outer").fillna(0)
    comp["Mg_Ant_%"] = comp.apply(lambda x: _porcentaje(x["Util_Ant"], x["VC_Ant"]), axis=1)
    comp["Mg_Act_%"] = comp.apply(lambda x: _porcentaje(x["Util_Act"], x["VC_Act"]), axis=1)
    return comp.sort_values("VC_Act", ascending=False).reset_index(drop=True)


def _filas_detalle_rentabilidad(df_cruce, simb):
    if df_cruce is None or df_cruce.empty:
        return []
    datos = df_cruce.copy()
    for col in ["Tipo_Categoria", "Marca_Descripcion"]:
        if col not in datos.columns:
            datos[col] = "SIN CLASIFICAR"
        datos[col] = datos[col].fillna("SIN CLASIFICAR").astype(str).str.strip().replace("", "SIN CLASIFICAR")
    agrupado = datos.groupby(["Tipo_Categoria", "Marca_Descripcion"], as_index=False).agg(
        Ventas=("Ventas_Cruce", "sum"), Costo=("Costo", "sum"), Utilidad=("Utilidad", "sum"))
    agrupado["Mg_%"] = agrupado.apply(lambda x: _porcentaje(x["Utilidad"], x["Ventas"]), axis=1)
    agrupado = agrupado.sort_values(["Tipo_Categoria", "Ventas"], ascending=[True, False], kind="stable")
    filas = [["TIPO CATEGORÍA", "MARCA", f"VENTAS ({simb})", f"COSTO ({simb})", f"UTILIDAD ({simb})", "MG %"]]
    for _, row in agrupado.iterrows():
        filas.append([str(row["Tipo_Categoria"])[:30], str(row["Marca_Descripcion"])[:28],
                      f"{row['Ventas']:,.2f}", f"{row['Costo']:,.2f}", f"{row['Utilidad']:,.2f}", f"{row['Mg_%']:.1f}%"])
    total_v, total_c, total_u = agrupado["Ventas"].sum(), agrupado["Costo"].sum(), agrupado["Utilidad"].sum()
    filas.append(["TOTAL GENERAL", "", f"{total_v:,.2f}", f"{total_c:,.2f}", f"{total_u:,.2f}", f"{_porcentaje(total_u, total_v):.1f}%"])
    return filas


def _interpretaciones(regla, comp_lineas, comp_marcas, comp_grupo, top_clientes, v_act, kpis, anio_act):
    lider = comp_lineas.iloc[0] if not comp_lineas.empty else None
    if regla["es_rs"]:
        merc = comp_grupo[comp_grupo["Grupo_RS"] == "MERCADERÍA"]
        serv = comp_grupo[comp_grupo["Grupo_RS"] == "SERVICIOS"]
        v_m = float(merc["Ventas_Act"].sum()) if not merc.empty else 0.0
        v_s = float(serv["Ventas_Act"].sum()) if not serv.empty else 0.0
        txt_com = (f"En {anio_act}, la facturación se distribuyó entre mercadería por {v_m:,.2f} ({_porcentaje(v_m, v_act):.1f}%) "
                   f"y servicios por {v_s:,.2f} ({_porcentaje(v_s, v_act):.1f}%). Esta separación se deriva del campo TipoVenta del Maestro: "
                   "CAMARAS Y PROTECTORES, LLANTAS y PARCHES se clasifican como MERCADERÍA; SERVICIO DE REENCAUCHE se clasifica como SERVICIOS.")
    else:
        txt_com = (f"La línea de mayor facturación fue {lider['NombreLinea']} con {lider['Ventas_Act']:,.2f}, "
                   f"equivalente al {lider['Part_%']:.1f}% del total." if lider is not None else "No hay líneas con ventas para interpretar.")
    if not comp_marcas.empty:
        top = comp_marcas.iloc[0]
        txt_mar = f"La marca con mayor facturación dentro del universo analizado fue {top['NombreLinea']}, con {top['Ventas_Act']:,.2f}."
        if regla["es_rs"]:
            txt_mar += " El ranking de marcas considera exclusivamente los ítems clasificados como MERCADERÍA; el servicio de reencauche queda excluido de este bloque."
    else:
        txt_mar = "No se presenta ranking de marcas para esta empresa, conforme a la regla de análisis configurada."
    txt_k = (f"En el comparativo del Kardex, el margen bruto fue {kpis['m_ant']:.2f}% en el periodo anterior y "
             f"{kpis['m_act']:.2f}% en el actual, con una variación de {kpis['m_act']-kpis['m_ant']:+.2f} puntos porcentuales. "
             "La lectura de costos y utilidad se limita a las salidas de Kardex cruzadas con documentos de venta identificables.")
    if top_clientes is not None and not top_clientes.empty:
        cliente = top_clientes.iloc[0]
        txt_cli = (f"El principal cliente fue {cliente['ClienteNombre']}, con ventas por {cliente['Ventas']:,.2f} "
                   f"({ _porcentaje(cliente['Ventas'], v_act):.1f}% de la facturación del periodo). El ranking muestra los diez clientes con mayor venta.")
    else:
        txt_cli = "No se registraron ventas asociadas a clientes en el periodo seleccionado."
    return {"comercial": txt_com, "marcas": txt_mar, "kardex": txt_k, "clientes": txt_cli}


def render(ctx):
    df_ventas_all = ctx.get("df_ventas")
    df_tc = ctx.get("df_tc")
    df_maestro = ctx.get("df_maestro")
    empresa = str(ctx.get("empresa", "02000000")).strip()
    moneda = str(ctx.get("moneda", "SOLES")).strip().upper()
    p_inicio = str(ctx.get("p_inicio", "")).strip()
    p_fin = str(ctx.get("p_fin", p_inicio)).strip()
    regla = _regla_empresa(empresa)
    simb = "S/" if moneda == "SOLES" else "$"

    st.subheader(f"📄 Generador de Informe Gerencial PDF - {regla['nombre']}")
    st.info(f"**Tipos de venta incluidos:** {', '.join(regla['tipos_venta'])}")
    if regla["es_rs"]:
        st.caption("RS: MERCADERÍA = CAMARAS Y PROTECTORES + LLANTAS + PARCHES. SERVICIOS = SERVICIO DE REENCAUCHE. La clasificación se obtiene del campo TipoVenta del Maestro de Ítems.")
    elif empresa == "03000000":
        st.caption("IS: se analizan las cuatro líneas; no se genera ranking de marcas.")

    uploaded_k_pdf = st.file_uploader(
        "📂 Carga el Kardex (.parquet o .xlsx) para incluir costos y rentabilidad:",
        type=["parquet", "xlsx"], key="uploader_kardex_pdf"
    )
    if not st.button("🚀 Generar Informe Gerencial PDF", type="primary", key="btn_gen_pdf"):
        return

    try:
        if not re.fullmatch(r"\d{6}", p_inicio) or not re.fullmatch(r"\d{6}", p_fin):
            st.error("Los periodos deben tener formato AAAAMM, por ejemplo 202601.")
            return
        if int(p_inicio) > int(p_fin):
            st.error("El periodo inicial no puede ser mayor que el periodo final.")
            return
        df_k = None
        if uploaded_k_pdf is not None:
            uploaded_k_pdf.seek(0)
            df_k = (pd.read_parquet(uploaded_k_pdf) if uploaded_k_pdf.name.lower().endswith(".parquet")
                    else pd.read_excel(uploaded_k_pdf, dtype=str))

        p_ini_ant, p_fin_ant = str(int(p_inicio) - 100), str(int(p_fin) - 100)
        anio_act, anio_ant = p_inicio[:4], p_ini_ant[:4]
        with st.spinner("Validando información, calculando rentabilidad y preparando el informe..."):
            df_v_ant, df_c_ant, _, regla_ant = obtener_datos_limpios_empresa(df_ventas_all, df_k, df_tc, df_maestro, empresa, moneda, p_ini_ant, p_fin_ant)
            df_v_act, df_c_act, top_cli, regla_act = obtener_datos_limpios_empresa(df_ventas_all, df_k, df_tc, df_maestro, empresa, moneda, p_inicio, p_fin)
            if regla_act.get("_error_validacion"):
                st.error(regla_act["_error_validacion"])
                return
            if df_v_act.empty:
                st.warning(f"No hay ventas válidas para {regla['nombre']} entre {p_inicio} y {p_fin}, según los TipoVenta configurados.")
                return

            v_ant = float(df_v_ant["Venta_Conv"].sum()) if not df_v_ant.empty else 0.0
            v_act = float(df_v_act["Venta_Conv"].sum())
            vc_ant = float(df_c_ant["Ventas_Cruce"].sum()) if not df_c_ant.empty else 0.0
            vc_act = float(df_c_act["Ventas_Cruce"].sum()) if not df_c_act.empty else 0.0
            c_ant = float(df_c_ant["Costo"].sum()) if not df_c_ant.empty else 0.0
            c_act = float(df_c_act["Costo"].sum()) if not df_c_act.empty else 0.0
            u_ant, u_act = vc_ant - c_ant, vc_act - c_act
            m_ant, m_act = _porcentaje(u_ant, vc_ant), _porcentaje(u_act, vc_act)
            kpis = {
                "v_ant": v_ant, "v_act": v_act, "var_v": _variacion(v_act, v_ant),
                "vc_ant": vc_ant, "vc_act": vc_act, "var_vc": _variacion(vc_act, vc_ant),
                "c_ant": c_ant, "c_act": c_act, "var_c": _variacion(c_act, c_ant),
                "u_ant": u_ant, "u_act": u_act, "var_u": _variacion(u_act, u_ant),
                "m_ant": m_ant, "m_act": m_act,
            }

            # Página 2: comparativo de líneas. En RS se consolida en dos unidades.
            if regla["es_rs"]:
                df_v_act["Grupo_RS"] = np.where(df_v_act["TipoVenta"].isin(regla["tipos_mercaderia"]), "MERCADERÍA", "SERVICIOS")
                if not df_v_ant.empty:
                    df_v_ant["Grupo_RS"] = np.where(df_v_ant["TipoVenta"].isin(regla["tipos_mercaderia"]), "MERCADERÍA", "SERVICIOS")
                dim_linea = "Grupo_RS"
                comp_lineas = _tabla_comparativa(df_v_ant, df_v_act, dim_linea, v_act)
                comp_lineas["NombreLinea"] = comp_lineas[dim_linea]
                titulo_linea = "MERCADERÍA / SERVICIOS"
                comp_grupo = comp_lineas.copy()
                util_grupos = (df_c_act.groupby("Grupo_RS", as_index=False)["Utilidad"].sum()
                               .rename(columns={"Utilidad": "Util_Act"})
                               if not df_c_act.empty and "Grupo_RS" in df_c_act.columns
                               else pd.DataFrame(columns=["Grupo_RS", "Util_Act"]))
                comp_grupo = comp_grupo.merge(util_grupos, on="Grupo_RS", how="left")
                comp_grupo["Util_Act"] = comp_grupo["Util_Act"].fillna(0.0)
            else:
                dim_linea = "TipoVenta"
                comp_lineas = _tabla_comparativa(df_v_ant, df_v_act, dim_linea, v_act)
                comp_lineas["NombreLinea"] = comp_lineas[dim_linea]
                titulo_linea = "TIPO DE VENTA"
                comp_grupo = pd.DataFrame(columns=["Grupo_RS", "Ventas_Act", "Util_Act"])
            img1 = crear_grafico_barras_png(comp_lineas, "NombreLinea", "Ventas_Ant", "Ventas_Act",
                                            f"Ventas {anio_ant}", f"Ventas {anio_act}",
                                            f"Ventas por {titulo_linea} ({anio_ant} vs. {anio_act})")
            filas_t1 = _filas_ventas(comp_lineas, titulo_linea, anio_ant, anio_act, v_ant, v_act, kpis["var_v"], simb)

            # Marcas: TS todas las ventas válidas; RS solo mercadería; IS se omite.
            img2, filas_t2 = None, []
            comp_marcas = pd.DataFrame()
            if regla["destacar_marcas"]:
                if regla["es_rs"]:
                    ant_marcas = df_v_ant[df_v_ant["TipoVenta"].isin(regla["tipos_mercaderia"])] if not df_v_ant.empty else df_v_ant
                    act_marcas = df_v_act[df_v_act["TipoVenta"].isin(regla["tipos_mercaderia"])]
                    base_marcas = float(act_marcas["Venta_Conv"].sum())
                else:
                    ant_marcas, act_marcas = df_v_ant, df_v_act
                    base_marcas = v_act
                comp_marcas = _tabla_comparativa(ant_marcas, act_marcas, "Marca_Descripcion", base_marcas)
                comp_marcas["NombreLinea"] = comp_marcas["Marca_Descripcion"]
                comp_marcas = comp_marcas.head(8)
                img2 = crear_grafico_barras_png(comp_marcas, "NombreLinea", "Ventas_Ant", "Ventas_Act",
                                                f"Ventas {anio_ant}", f"Ventas {anio_act}",
                                                "Marcas principales (solo mercadería en RS)",
                                                color_ant="#AEB6BF", color_act="#2874A6", max_barras=8)
                filas_t2 = _filas_ventas(comp_marcas, "MARCA", anio_ant, anio_act,
                                         float(ant_marcas["Venta_Conv"].sum()) if not ant_marcas.empty else 0.0,
                                         base_marcas,
                                         _variacion(base_marcas, float(ant_marcas["Venta_Conv"].sum()) if not ant_marcas.empty else 0.0), simb)
                # La fila total de marcas debe ser el total del universo de marcas, no la suma del top 8.
                filas_t2[-1][1] = f"{(float(ant_marcas['Venta_Conv'].sum()) if not ant_marcas.empty else 0.0):,.2f}"
                filas_t2[-1][2] = f"{base_marcas:,.2f}"
                filas_t2[-1][4] = "100.0%"

            # Página 3: comparativo Kardex por tipo de venta y detalle categoría/marca.
            img3, filas_t3, filas_detalle = None, [], []
            dim_kardex = "TipoVenta"
            comp_k = _resumen_kardex(df_c_ant, df_c_act, dim_kardex, anio_ant, anio_act) if (not df_c_ant.empty or not df_c_act.empty) else pd.DataFrame()
            if not comp_k.empty:
                comp_k["NombreLinea"] = comp_k[dim_kardex]
                img3 = crear_grafico_barras_png(comp_k, "NombreLinea", "Costo_Act", "VC_Act",
                                                f"Costo {anio_act}", f"Venta cruzada {anio_act}",
                                                f"Venta cruzada vs. costo Kardex por TipoVenta ({anio_act})",
                                                color_ant="#C0392B", color_act="#117864")
                filas_t3 = [["TIPO DE VENTA", f"VENTA {anio_act} ({simb})", f"COSTO {anio_act} ({simb})",
                             f"UTILIDAD {anio_act} ({simb})", f"UTILIDAD {anio_ant} ({simb})", f"MG {anio_act}"]]
                for _, row in comp_k.iterrows():
                    filas_t3.append([str(row[dim_kardex]), f"{row['VC_Act']:,.2f}", f"{row['Costo_Act']:,.2f}",
                                     f"{row['Util_Act']:,.2f}", f"{row['Util_Ant']:,.2f}", f"{row['Mg_Act_%']:.1f}%"])
                filas_t3.append(["TOTAL GENERAL", f"{vc_act:,.2f}", f"{c_act:,.2f}", f"{u_act:,.2f}", f"{u_ant:,.2f}", f"{m_act:.1f}%"])
                filas_detalle = _filas_detalle_rentabilidad(df_c_act, simb)

            # Interpretaciones de cada bloque y resumen para IA.
            interpretaciones = _interpretaciones(regla, comp_lineas, comp_marcas, comp_grupo, top_cli, v_act, kpis, anio_act)
            top_lineas_texto = comp_lineas[["NombreLinea", "Ventas_Ant", "Ventas_Act", "Var_%", "Part_%"]].to_string(index=False)
            marcas_texto = comp_marcas[["NombreLinea", "Ventas_Ant", "Ventas_Act", "Var_%", "Part_%"]].to_string(index=False) if not comp_marcas.empty else "No aplica / no se presenta ranking de marcas."
            kardex_texto = comp_k[["NombreLinea", "VC_Act", "Costo_Act", "Util_Act", "Mg_Ant_%", "Mg_Act_%"]].to_string(index=False) if not comp_k.empty else "No hay cruce de Kardex disponible."
            resumen_ia = (f"Ventas {anio_ant}: {v_ant:,.2f}; ventas {anio_act}: {v_act:,.2f}; variación: {kpis['var_v']:+.2f}%.\n"
                          f"Líneas/grupos:\n{top_lineas_texto}\nMarcas:\n{marcas_texto}\n"
                          f"Ventas cruzadas Kardex {anio_ant}: {vc_ant:,.2f}; {anio_act}: {vc_act:,.2f}.\n"
                          f"Costo {anio_ant}: {c_ant:,.2f}; {anio_act}: {c_act:,.2f}.\n"
                          f"Utilidad {anio_ant}: {u_ant:,.2f}; {anio_act}: {u_act:,.2f}.\n"
                          f"Margen {anio_ant}: {m_ant:.2f}%; margen {anio_act}: {m_act:.2f}%.\nDetalle Kardex:\n{kardex_texto}")
            datos_locales = {
                "regla": regla, "empresa": empresa, "anio_ant": anio_ant, "anio_act": anio_act,
                "v_ant": v_ant, "v_act": v_act, "comp_cat": comp_lineas,
                "comp_grupo": comp_grupo, "vc_ant": vc_ant, "vc_act": vc_act,
                "c_ant": c_ant, "c_act": c_act, "u_ant": u_ant, "u_act": u_act,
                "m_ant": m_ant, "m_act": m_act,
            }
            texto_ia, estado_ia = generar_analisis_gemini(resumen_ia, regla, datos_locales)
            pdf_bytes = construir_pdf_gerencial(
                regla, empresa, moneda, p_inicio, p_fin, anio_ant, anio_act,
                kpis, texto_ia, img1, filas_t1, img2, filas_t2, img3, filas_t3,
                [["CLIENTE", "UNIDADES", f"VENTAS {anio_act} ({simb})", "PART. %"]] + [
                    [str(row["ClienteNombre"])[:48], f"{row['Unidades']:,.0f}", f"{row['Ventas']:,.2f}", f"{_porcentaje(row['Ventas'], v_act):.1f}%"]
                    for _, row in top_cli.iterrows()
                ], interpretaciones, filas_detalle)

        st.success("Informe gerencial PDF generado correctamente.")
        st.caption(f"Origen del diagnóstico: {estado_ia}.")
        with st.expander("Vista previa del diagnóstico"):
            st.markdown(texto_ia, unsafe_allow_html=True)
        st.download_button(
            label=f"📥 Descargar Informe Gerencial PDF ({regla['nombre']})",
            data=pdf_bytes,
            file_name=f"Informe_Gerencial_{empresa}_{p_inicio}_{p_fin}_{moneda}.pdf",
            mime="application/pdf", key="dl_pdf_gerencial_final"
        )
    except Exception as exc:
        st.error(f"No se pudo generar el informe. Detalle técnico: {exc}")
