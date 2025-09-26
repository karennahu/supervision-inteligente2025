# reporte_auto.py
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
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib import colors
from PIL import Image

# ---------------------------
# CONFIG: rutas de las imágenes
# ---------------------------
HEADER_IMG = "encabezado.png"   # <- reemplaza con la ruta de tu imagen de encabezado (membrete)
FOOTER_IMG = "Toluca-logo-outline-blanco.png"  # <- logo del footer

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

# Mapeo de nombres internos en las respuestas a las etiquetas que queremos mostrar
MAPA_METRICAS = {
    "qt_tsfhazuupd": "Baches reparados",
    "qt_r6axt0uupd": "M² Totales",
    "qt_yct2j9xupd": "Metros lineales aprox"
}

# Diccionario final con los datos por sección
data_reporte = {s: {} for s in SECCIONES_ORDEN}


# ---------------------------
# Util: convertir strings numéricos a entero (truncando)
# Heurística para separar miles/decimales y manejar sufijos tipo "mil"
# ---------------------------
def text_to_int(s):
    """Convierte strings tipo '13.943', '49,2 mil', '120.630' a int truncando decimales.
       Si no es convertible, lanza ValueError."""
    if s is None:
        raise ValueError("None")
    if isinstance(s, (int,)):
        return int(s)
    if isinstance(s, float):
        return int(s)

    st = str(s).strip().lower()
    # reemplazar paréntesis, signos, etc
    st = st.replace("(", "").replace(")", "").replace("%", "").replace("$", "").strip()

    # manejar sufijo mil/k
    if "mil" in st:
        # eliminar la palabra mil y convertir multiplicando por 1000
        st2 = st.replace("mil", "").strip()
        # normalizar separadores
        st2 = _normalize_number_string(st2)
        val = float(st2)
        return int(val * 1000)

    # normalizar separadores y convertir
    st = _normalize_number_string(st)

    # si queda vacío -> 0
    if st == "":
        raise ValueError("Empty")

    val = float(st)
    return int(val)  # truncar decimales


def _normalize_number_string(s):
    """Heurística para convertir distintos formatos numéricos a 'python float string'."""
    s = s.strip()
    # quitar espacios
    s = s.replace(" ", "")
    # si contiene ambos '.' y ',' -> asumir '.' miles y ',' decimal si '.' aparece antes de ','
    if "." in s and "," in s:
        if s.find(".") < s.find(","):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        # solo '.' presente
        if "." in s and s.count(".") == 1:
            pos = s.find(".")
            # si después del punto hay 3 dígitos, es probable separador de miles -> quitar
            if len(s) - pos - 1 == 3:
                s = s.replace(".", "")
            # else: punto decimal
        # solo ',' presente
        if "," in s and s.count(",") == 1:
            pos = s.find(",")
            # si después de la coma hay 3 dígitos -> separador de miles
            if len(s) - pos - 1 == 3:
                s = s.replace(",", "")
            else:
                # coma decimal -> convertir a punto
                s = s.replace(",", ".")
    # eliminar cualquier caracter no numérico salvo el punto y el signo negativo
    cleaned = "".join(ch for ch in s if (ch.isdigit() or ch in ".-"))
    return cleaned


# ---------------------------
# Scraper + extracción con Playwright
# ---------------------------
async def extraer_datos(playheadless=False, slow_mo=150):
    """
    Abre el dashboard, recorre las secciones y llena data_reporte con los KPIs detectados.
    Retorna data_reporte con valores ya convertidos a int (si es posible).
    """
    current_section = None
    indice_seccion = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=playheadless, slow_mo=slow_mo)
        page = await browser.new_page()

        # handler de responses
        async def handle_response(response):
            nonlocal indice_seccion, current_section
            if "batchedDataV2" not in response.url:
                return
            try:
                body = await response.text()
            except Exception:
                return
            if not body or not body.strip():
                return
            if body.startswith(")]}'"):
                body = body[4:]
            try:
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
                        name = info.get("name", "")
                        if i < len(cols):
                            col = cols[i]
                        else:
                            continue
                        val = None
                        if "longColumn" in col and col["longColumn"].get("values"):
                            val = col["longColumn"]["values"][0]
                        elif "doubleColumn" in col and col["doubleColumn"].get("values"):
                            val = col["doubleColumn"]["values"][0]
                        if val is not None:
                            # intentar convertir a int con heurística, pero guardamos el raw por ahora
                            metrics_by_name[name] = val

            if current_section is None or indice_seccion >= len(SECCIONES_ORDEN):
                return

            seccion_actual = SECCIONES_ORDEN[indice_seccion]
            if not data_reporte[seccion_actual]:
                data_reporte[seccion_actual] = {}

            # Guardar métricas mapeadas
            for clave, nombre in MAPA_METRICAS.items():
                if clave in metrics_by_name:
                    # Convertir / truncar aquí si es posible
                    raw = metrics_by_name[clave]
                    try:
                        entero = text_to_int(raw)
                    except Exception:
                        # si falla la conversión, intentar forzar con float->int
                        try:
                            entero = int(float(str(raw).replace(",", "").replace(" ", "")))
                        except Exception:
                            entero = raw
                    data_reporte[seccion_actual][nombre] = entero

        page.on("response", handle_response)

        print("🌐 Abriendo el dashboard público...")
        await page.goto(URL, wait_until="domcontentloaded", timeout=120000)

        # Pausa breve para que cargue la UI
        await page.wait_for_timeout(2500)

        # Se intenta clickear por texto. Si no se encuentra, se hace reintento y se avisa.
        text_variants = {
            "General": ["General"],
            "Terminado": ["Terminado"],
            "Revisión": ["Revisión", "Revision", "Revisión "],
            "Retrabajo": ["Retrabajo", "ReTrabajo", "Re-Trabajo"],
            "Detectados": ["Detectados", "Detectado"],
            "Monitoreo activo": ["Monitoreo activo", "Terminado con Monitoreo Activo", "Monitoreo"]
        }

        for idx, seccion in enumerate(SECCIONES_ORDEN):
            current_section = seccion
            indice_seccion = idx
            print(f"\n🔄 Procesando sección: {seccion} ...")
            clicked = False

            # Skip click for "General" (normalemente datos generales ya cargados al inicio)
            if seccion != "General":
                variants = text_variants.get(seccion, [seccion])
                for v in variants:
                    try:
                        locator = page.locator(f"text={v}", has_text=v)
                        # si existe al menos 1 match, click
                        count = await locator.count()
                        if count > 0:
                            await locator.first.click(timeout=6000)
                            clicked = True
                            break
                    except Exception:
                        clicked = False

                if not clicked:
                    # Fallback: intentar clickear por botones role
                    try:
                        btns = page.locator('[role="button"]')
                        nbtns = await btns.count()
                        # intentar recorrer y clickear el que contiene texto parcial
                        for i in range(min(nbtns, 30)):
                            try:
                                txt = (await btns.nth(i).inner_text()).strip()
                                if any(v.lower() in txt.lower() for v in variants):
                                    await btns.nth(i).click(timeout=4000)
                                    clicked = True
                                    break
                            except Exception:
                                continue
                    except Exception:
                        clicked = False

                if not clicked:
                    print(f"⚠️ No se pudo localizar claramente el botón de '{seccion}' por texto. Intentando pasar igual y esperar datos...")

            # Esperar hasta que los 3 KPIs estén presentes para esta sección o hasta timeout
            want = set(MAPA_METRICAS.values())
            timeout = 12.0  # segundos por sección
            deadline = time.time() + timeout
            while time.time() < deadline:
                presentes = set(k for k in data_reporte[seccion].keys())
                if want.issubset(presentes):
                    print(f"✅ Datos capturados para {seccion}: {data_reporte[seccion]}")
                    break
                await asyncio.sleep(0.5)
            else:
                print(f"⏱ Timeout al esperar KPIs para {seccion}. Lo que hay: {data_reporte[seccion]}")

            # pequeña espera antes de la siguiente sección
            await page.wait_for_timeout(500)

        await browser.close()

    # Post-proceso: asegurar que todos los valores numéricos sean ints (truncados) y llenar ceros si falta
    for s in SECCIONES_ORDEN:
        for nm in MAPA_METRICAS.values():
            val = data_reporte.get(s, {}).get(nm, 0)
            try:
                val_int = text_to_int(val)
            except Exception:
                # si no convertible, forzar cero o int
                try:
                    val_int = int(float(str(val).replace(",", "").replace(" ", "")))
                except Exception:
                    val_int = 0
            data_reporte.setdefault(s, {})[nm] = val_int

    return data_reporte


# ---------------------------
# Generar gráficas y PDF usando los datos extraídos
# ---------------------------
def generar_grafica_png(titulo, datos_por_seccion, salida_png):
    # datos_por_seccion: dict {seccion: valor}
    # El orden que pides en las barras (de arriba a abajo): 5 Monitoreo activo, 4 Detectados, 3 Retrabajo, 2 Revisión, 1 Terminado
    orden_barras = ["Monitoreo activo", "Detectados", "Retrabajo", "Revisión", "Terminado"]
    secciones = [s for s in orden_barras if s in datos_por_seccion]
    valores = [int(datos_por_seccion.get(s, 0)) for s in secciones]
    colores = [COLOR_MAP.get(s, "#999999") for s in secciones]

    plt.figure(figsize=(8, 3.2))  # ancho x alto (en pulgadas)
    bars = plt.bar(secciones, valores, color=colores)

    # Poner texto (entero) en centro de cada barra si cabe, o encima si es pequeño
    for bar, val in zip(bars, valores):
        h = bar.get_height()
        x = bar.get_x() + bar.get_width() / 2
        # Si altura suficientemente grande (> 5% del max) colocamos dentro, else encima
        ymax = max(valores) if valores else 1
        if ymax == 0:
            ymax = 1
        if h >= ymax * 0.12:
            va = 'center'
            y = h / 2
            color_txt = "white"
        else:
            va = 'bottom'
            y = h + max(1, ymax * 0.02)
            color_txt = "black"
        plt.text(x, y, str(int(val)), ha='center', va=va, fontsize=10, fontweight='bold', color=color_txt)


    plt.title(titulo, fontsize=12, fontweight='bold')
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(salida_png, dpi=150)
    plt.close()


def generar_pdf_final(data_reporte, archivo_pdf="Reporte_Supervision.pdf"):
    doc = SimpleDocTemplate(archivo_pdf, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    estilos = getSampleStyleSheet()
    estilo_centrado = ParagraphStyle("centrado", parent=estilos["Normal"], alignment=TA_CENTER, fontSize=10)

    elementos = []

    # Encabezado - imagen (membrete)
    if os.path.exists(HEADER_IMG):
        # Escalar imagen para ancho de página si es muy grande
        try:
            im = Image.open(HEADER_IMG)
            w, h = im.size
            # ancho max en puntos (A4 width ~595.27 - margins 72 -> usamos ~520)
            max_width = A4[0] - 72
            scale = min(1.0, max_width / w)
            img_w = w * scale
            img_h = h * scale
            elementos.append(RLImage(HEADER_IMG, width=img_w, height=img_h))
        except Exception:
            elementos.append(RLImage(HEADER_IMG, width=400, height=60))
    else:
        elementos.append(Paragraph("<b>SUPERVISIÓN INTELIGENTE - BACHEO</b>", estilos["Title"]))

    elementos.append(Spacer(1, 10))

    # Fecha actual
    fecha = datetime.now().strftime("%d/%m/%Y")
    elementos.append(Paragraph(f"<b>Fecha de extracción:</b> {fecha}", estilo_centrado))
    elementos.append(Spacer(1, 10))

    # DATOS GENERALES - si existe sección "General" usala, si no, suma de las secciones
    datos_generales = {}
    if data_reporte.get("General") and any(data_reporte["General"].values()):
        datos_generales = data_reporte["General"]
    else:
        # sumar por métrica sobre secciones conocidas (excluimos "General")
        for m in MAPA_METRICAS.values():
            s = sum(int(data_reporte.get(sec, {}).get(m, 0)) for sec in SECCIONES_ORDEN if sec != "General")
            datos_generales[m] = s

    elementos.append(Paragraph("<b>DATOS GENERALES</b>", estilos["Heading2"]))
    # Mostrar 3 valores en una tabla con 3 columnas
    tabla_data = [
    [Paragraph("<b>Baches reparados</b>", estilos["Normal"]), Paragraph("<b>M² Totales</b>", estilos["Normal"]), Paragraph("<b>Metros lineales aprox</b>", estilos["Normal"])],
    [str(int(datos_generales.get('Baches reparados',0))),
     str(int(datos_generales.get('M² Totales',0))),
     str(int(datos_generales.get('Metros lineales aprox',0)))]
]

    
    t = Table(tabla_data, colWidths=[160, 160, 160])
    t.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8)
    ]))
    elementos.append(t)
    elementos.append(Spacer(1, 14))

    # Preparar datos por sección para graficar (usamos sólo las 5 secciones operativas)
    secciones_para_graf = ["Monitoreo activo", "Detectados", "Retrabajo", "Revisión", "Terminado"]

    # Armar dict por métrica
    metricas = {
        "Baches Reparados": {sec: data_reporte.get(sec, {}).get("Baches reparados", 0) for sec in secciones_para_graf},
        "M² Totales": {sec: data_reporte.get(sec, {}).get("M² Totales", 0) for sec in secciones_para_graf},
        "Metros Lineales Aprox": {sec: data_reporte.get(sec, {}).get("Metros lineales aprox", 0) for sec in secciones_para_graf}
    }

    # Generar cada grafica y agregarla al PDF
    imgs_temp = []
    for titulo, datos in metricas.items():
        png_name = f"tmp_graf_{titulo.replace(' ', '_')}.png"
        generar_grafica_png(titulo, datos, png_name)
        imgs_temp.append(png_name)
        elementos.append(Paragraph(f"<b>{titulo}</b>", estilos["Heading3"]))
        elementos.append(RLImage(png_name, width=480, height=170))
        elementos.append(Spacer(1, 12))

    # Pie de pagina con logo y texto centralizado
    elementos.append(Spacer(1, 24))
    if os.path.exists(FOOTER_IMG):
        elementos.append(RLImage(FOOTER_IMG, width=140, height=70))
    elementos.append(Spacer(1, 6))
    elementos.append(Paragraph("© 2025 Toluca - Capital de Oportunidades y Progreso", estilo_centrado))
    elementos.append(Paragraph("Sistema de Supervisión Inteligente", estilo_centrado))
    elementos.append(Paragraph("Datos extraídos automáticamente", estilo_centrado))

    # Build PDF
    doc.build(elementos)

    # eliminar png temporales
    for f in imgs_temp:
        try:
            os.remove(f)
        except Exception:
            pass

    print(f"✅ PDF generado: {archivo_pdf}")


# ---------------------------
# MAIN
# ---------------------------
if __name__ == "__main__":
    # Extraer datos
    datos = asyncio.run(extraer_datos(playheadless=False, slow_mo=120))
    print("\n=== DATOS EXTRAIDOS ===")
    for s, vals in datos.items():
        print(f"{s}: {vals}")
    # Generar PDF
    generar_pdf_final(datos, archivo_pdf="Reporte_Supervision.pdf")
    
    