# extraer_datos.py
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from playwright.async_api import async_playwright
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib import colors
from PIL import Image

# ---------------------------
# COLORES (hex solicitados)
# ---------------------------
COLOR_MAP = {
    "Terminado": "#6CC24A",           # Verde claro
    "Revisión": "#FFD600",            # Amarillo
    "Retrabajo": "#9B3D64",           # Rojo violáceo
    "Detectados": "#E30613",          # Rojo
    "Monitoreo activo": "#004225"     # Verde oscuro
}

# ---------------------------
# URL y secciones a recorrer
# ---------------------------
URL = "https://lookerstudio.google.com/u/0/reporting/ea3fb237-17c6-49c6-956b-77b33774ce9a/page/X9kcE"

SECCIONES_ORDEN = [
    "General",
    "Terminado",
    "Revisión",
    "Retrabajo",
    "Detectados",
    "Monitoreo activo"
]

MAPA_METRICAS = {
    "qt_tsfhazuupd": "Baches reparados",
    "qt_r6axt0uupd": "M² Totales",
    "qt_yct2j9xupd": "Metros lineales aprox"
}

data_reporte = {s: {} for s in SECCIONES_ORDEN}

# ---------------------------
# Utils: conversión de strings numéricos
# ---------------------------
def text_to_int(s):
    if s is None:
        raise ValueError("None")
    if isinstance(s, (int, float)):
        return int(s)

    st = str(s).strip().lower()
    st = st.replace("(", "").replace(")", "").replace("%", "").replace("$", "").strip()

    if "mil" in st:
        st2 = _normalize_number_string(st.replace("mil", "").strip())
        return int(float(st2) * 1000)

    st = _normalize_number_string(st)
    if st == "":
        raise ValueError("Empty")
    return int(float(st))

def _normalize_number_string(s):
    s = s.strip().replace(" ", "")
    if "." in s and "," in s:
        if s.find(".") < s.find(","):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        if "." in s and s.count(".") == 1:
            pos = s.find(".")
            if len(s) - pos - 1 == 3:
                s = s.replace(".", "")
        if "," in s and s.count(",") == 1:
            pos = s.find(",")
            if len(s) - pos - 1 == 3:
                s = s.replace(",", "")
            else:
                s = s.replace(",", ".")
    return "".join(ch for ch in s if (ch.isdigit() or ch in ".-"))

# ---------------------------
# Scraper con Playwright
# ---------------------------
async def extraer_datos(playheadless=False, slow_mo=150):
    current_section = None
    indice_seccion = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,  # siempre en True en Render
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--single-process",
                "--disable-gpu"
            ]
        )
        page = await browser.new_page()

        async def handle_response(response):
            nonlocal indice_seccion, current_section
            if "batchedDataV2" not in response.url:
                return
            try:
                body = await response.text()
                if body.startswith(")]}'"):
                    body = body[4:]
                data = json.loads(body)
            except Exception:
                return

            metrics_by_name = {}
            for dr in data.get("dataResponse", []):
                for subset in dr.get("dataSubset", []):
                    td = subset.get("dataset", {}).get("tableDataset", {})
                    infos = td.get("columnInfo", []) or []
                    cols = td.get("column", []) or []
                    for i, info in enumerate(infos):
                        if i < len(cols):
                            col = cols[i]
                            val = None
                            if "longColumn" in col and col["longColumn"].get("values"):
                                val = col["longColumn"]["values"][0]
                            elif "doubleColumn" in col and col["doubleColumn"].get("values"):
                                val = col["doubleColumn"]["values"][0]
                            if val is not None:
                                metrics_by_name[info.get("name", "")] = val

            if current_section is None or indice_seccion >= len(SECCIONES_ORDEN):
                return

            seccion_actual = SECCIONES_ORDEN[indice_seccion]
            data_reporte[seccion_actual] = {}

            for clave, nombre in MAPA_METRICAS.items():
                if clave in metrics_by_name:
                    raw = metrics_by_name[clave]
                    try:
                        entero = text_to_int(raw)
                    except Exception:
                        try:
                            entero = int(float(str(raw).replace(",", "").replace(" ", "")))
                        except Exception:
                            entero = raw
                    data_reporte[seccion_actual][nombre] = entero

        page.on("response", handle_response)
        await page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(2500)

        text_variants = {
            "General": ["General"],
            "Terminado": ["Terminado"],
            "Revisión": ["Revisión", "Revision"],
            "Retrabajo": ["Retrabajo", "Re-Trabajo"],
            "Detectados": ["Detectados", "Detectado"],
            "Monitoreo activo": ["Monitoreo activo", "Monitoreo"]
        }

        for idx, seccion in enumerate(SECCIONES_ORDEN):
            current_section = seccion
            indice_seccion = idx

            if seccion != "General":
                clicked = False
                variants = text_variants.get(seccion, [seccion])
                for v in variants:
                    try:
                        locator = page.locator(f"text={v}", has_text=v)
                        if await locator.count() > 0:
                            await locator.first.click(timeout=6000)
                            clicked = True
                            break
                    except Exception:
                        pass
                if not clicked:
                    print(f"⚠️ No se pudo localizar '{seccion}', intentando continuar...")

            want = set(MAPA_METRICAS.values())
            deadline = time.time() + 12
            while time.time() < deadline:
                presentes = set(data_reporte[seccion].keys())
                if want.issubset(presentes):
                    break
                await asyncio.sleep(0.5)

            await page.wait_for_timeout(500)

        await browser.close()

    for s in SECCIONES_ORDEN:
        for nm in MAPA_METRICAS.values():
            val = data_reporte.get(s, {}).get(nm, 0)
            try:
                data_reporte[s][nm] = text_to_int(val)
            except Exception:
                try:
                    data_reporte[s][nm] = int(float(str(val).replace(",", "").replace(" ", "")))
                except Exception:
                    data_reporte[s][nm] = 0

    return data_reporte

# ---------------------------
# Gráficas y PDF
# ---------------------------
def generar_grafica_png(titulo, datos_por_seccion, salida_png):
    orden_barras = ["Monitoreo activo", "Detectados", "Retrabajo", "Revisión", "Terminado"]
    secciones = [s for s in orden_barras if s in datos_por_seccion]
    valores = [int(datos_por_seccion.get(s, 0)) for s in secciones]
    colores = [COLOR_MAP.get(s, "#999999") for s in secciones]

    plt.figure(figsize=(8, 3.2))
    bars = plt.bar(secciones, valores, color=colores)

    for bar, val in zip(bars, valores):
        h = bar.get_height()
        x = bar.get_x() + bar.get_width() / 2
        ymax = max(valores) if valores else 1
        if h >= ymax * 0.12:
            va, y, color_txt = 'center', h / 2, "white"
        else:
            va, y, color_txt = 'bottom', h + max(1, ymax * 0.02), "black"
        plt.text(x, y, str(int(val)), ha='center', va=va, fontsize=10, fontweight='bold', color=color_txt)

    plt.title(titulo, fontsize=12, fontweight='bold')
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(salida_png, dpi=150)
    plt.close()

def generar_pdf_final(data_reporte, archivo_pdf="Reporte_Supervision.pdf",
                      header_img="encabezado.png", footer_img="Toluca-logo-outline-blanco.png"):
    doc = SimpleDocTemplate(archivo_pdf, pagesize=A4,
                            rightMargin=36, leftMargin=36,
                            topMargin=36, bottomMargin=36)
    estilos = getSampleStyleSheet()
    estilo_centrado = ParagraphStyle("centrado", parent=estilos["Normal"],
                                     alignment=TA_CENTER, fontSize=10)

    elementos = []

    if os.path.exists(header_img):
        try:
            im = Image.open(header_img)
            w, h = im.size
            max_width = A4[0] - 72
            scale = min(1.0, max_width / w)
            elementos.append(RLImage(header_img, width=w*scale, height=h*scale))
        except Exception:
            elementos.append(RLImage(header_img, width=400, height=60))
    else:
        elementos.append(Paragraph("<b>SUPERVISIÓN INTELIGENTE - BACHEO</b>", estilos["Title"]))

    elementos.append(Spacer(1, 10))
    fecha = datetime.now().strftime("%d/%m/%Y")
    elementos.append(Paragraph(f"<b>Fecha de extracción:</b> {fecha}", estilo_centrado))
    elementos.append(Spacer(1, 10))

    datos_generales = data_reporte.get("General", {})
    if not any(datos_generales.values()):
        for m in MAPA_METRICAS.values():
            datos_generales[m] = sum(int(data_reporte.get(sec, {}).get(m, 0))
                                     for sec in SECCIONES_ORDEN if sec != "General")

    elementos.append(Paragraph("<b>DATOS GENERALES</b>", estilos["Heading2"]))
    tabla_data = [
        [Paragraph("<b>Baches reparados</b>", estilos["Normal"]),
         Paragraph("<b>M² Totales</b>", estilos["Normal"]),
         Paragraph("<b>Metros lineales aprox</b>", estilos["Normal"])],
        [str(int(datos_generales.get('Baches reparados',0))),
         str(int(datos_generales.get('M² Totales',0))),
         str(int(datos_generales.get('Metros lineales aprox',0)))]
    ]
    t = Table(tabla_data, colWidths=[160, 160, 160])
    t.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8)
    ]))
    elementos.append(t)
    elementos.append(Spacer(1, 14))

    metricas = {
        "Baches Reparados": {sec: data_reporte.get(sec, {}).get("Baches reparados", 0)
                             for sec in ["Monitoreo activo", "Detectados", "Retrabajo", "Revisión", "Terminado"]},
        "M² Totales": {sec: data_reporte.get(sec, {}).get("M² Totales", 0)
                       for sec in ["Monitoreo activo", "Detectados", "Retrabajo", "Revisión", "Terminado"]},
        "Metros Lineales Aprox": {sec: data_reporte.get(sec, {}).get("Metros lineales aprox", 0)
                                  for sec in ["Monitoreo activo", "Detectados", "Retrabajo", "Revisión", "Terminado"]}
    }

    imgs_temp = []
    for titulo, datos in metricas.items():
        png_name = f"tmp_graf_{titulo.replace(' ', '_')}.png"
        generar_grafica_png(titulo, datos, png_name)
        imgs_temp.append(png_name)
        elementos.append(Paragraph(f"<b>{titulo}</b>", estilos["Heading3"]))
        elementos.append(RLImage(png_name, width=480, height=170))
        elementos.append(Spacer(1, 12))

    elementos.append(Spacer(1, 24))
    if os.path.exists(footer_img):
        elementos.append(RLImage(footer_img, width=140, height=70))
    elementos.append(Spacer(1, 6))
    elementos.append(Paragraph("© 2025 Toluca - Capital de Oportunidades y Progreso", estilo_centrado))
    elementos.append(Paragraph("Sistema de Supervisión Inteligente", estilo_centrado))
    elementos.append(Paragraph("Datos extraídos automáticamente", estilo_centrado))

    doc.build(elementos)

    for f in imgs_temp:
        try:
            os.remove(f)
        except Exception:
            pass

    print(f"✅ PDF generado: {archivo_pdf}")

# ---------------------------
# MAIN (solo pruebas locales)
# ---------------------------
if __name__ == "__main__":
    datos = asyncio.run(extraer_datos(playheadless=False, slow_mo=120))
    print("\n=== DATOS EXTRAIDOS ===")
    for s, vals in datos.items():
        print(f"{s}: {vals}")
    generar_pdf_final(datos, archivo_pdf="Reporte_Supervision.pdf")