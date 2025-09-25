# supervision_inteligente.py
import asyncio, json, os, re, time
from pathlib import Path
from playwright.async_api import async_playwright
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm

# -----------------------
# CONFIG / CONSTANTS
# -----------------------
URL = "https://lookerstudio.google.com/u/0/reporting/ea3fb237-17c6-49c6-956b-77b33774ce9a/page/X9kcE"

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# Secciones esperadas (display y etiquetas a buscar)
SECTIONS = [
    {"key":"term_mon", "display":"Terminado con monitoreo activo", "labels":["Terminado con monitoreo activo","Terminado con monitoreo","Monitoreo activo","MONITOREO ACTIVO"]},
    {"key":"detectados", "display":"Detectados", "labels":["Detectados","DETECTADOS"]},
    {"key":"retrabajo", "display":"Retrabajo", "labels":["Retrabajo","RETRABAJO"]},
    {"key":"revision", "display":"Revisión", "labels":["Revisión","Revision","REVISIÓN","REVISION"]},
    {"key":"terminado", "display":"Terminado", "labels":["Terminado","TERMINADO"]},
]

# Colores de las barras por display (hex)
SECTION_COLORS = {
    "Terminado con monitoreo activo": "#0B6623",  # verde oscuro
    "Detectados": "#D7263D",                     # rojo
    "Retrabajo": "#8B1E3F",                      # rojo-violáceo
    "Revisión": "#FFD166",                       # amarillo
    "Terminado": "#8BC34A",                      # verde claro
}

# Colores institucionales
COLOR_TITLE = "#612141"  # PANTONE 7421 C
COLOR_ACCENT = "#DDCBA4" # PANTONE 468
COLOR_TEXT = "#333333"   # 80% negro

# Nombre del reporte
REPORT_TITLE = "Supervisión Inteligente"

# -----------------------
# UTIL / PARSER
# -----------------------
def try_number_convert(v):
    """Intenta convertir strings a números (int o float)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace(" ", "")
        # manejar formatos con comas o puntos
        try:
            if re.fullmatch(r"-?\d+\.\d+", s):
                return float(s)
            if re.fullmatch(r"-?\d+", s):
                return int(s)
        except:
            pass
    return None

def parse_batched_data(data):
    """
    Extrae pares {col_name: valor} de la respuesta batchedDataV2.
    """
    out = {}
    try:
        for entry in data.get("dataResponse", []):
            for subset in entry.get("dataSubset", []):
                ds = subset.get("dataset", {})
                table = ds.get("tableDataset", {}) or {}
                cols = table.get("columnInfo", []) or []
                vals = table.get("column", []) or []
                for i, ci in enumerate(cols):
                    name = ci.get("name", f"col_{i}")
                    val = None
                    if i < len(vals):
                        cell = vals[i]
                        # Priorizar longColumn -> doubleColumn -> primitiveValue
                        if isinstance(cell, dict):
                            if "longColumn" in cell and cell["longColumn"].get("values"):
                                val = cell["longColumn"]["values"][0]
                            elif "doubleColumn" in cell and cell["doubleColumn"].get("values"):
                                val = cell["doubleColumn"]["values"][0]
                            elif "primitiveValue" in cell:
                                val = cell.get("primitiveValue")
                    val_conv = try_number_convert(val)
                    out[name] = val_conv if val_conv is not None else val
    except Exception as e:
        print("parse_batched_data error:", e)
    return out

def heuristics_map(keys):
    """
    Devuelve sugerencias de mapeo {metric_name: [candidate_keys]}
    """
    suggestions = {"Baches reparados": [], "M2 Totales": [], "Metros lineales aprox.": []}
    for k in keys:
        kl = k.lower()
        # baches
        if any(x in kl for x in ["bache","baches","reparad","reparados","count","qty"]):
            suggestions["Baches reparados"].append(k)
        # m2
        if any(x in kl for x in ["m2","m²","metro cuadr","metros cuadrados","area","superficie","sqm","metros_cuad"]):
            suggestions["M2 Totales"].append(k)
        # metros lineales
        if any(x in kl for x in ["metro lineal","metros lineales","metrol","lineal","ml","metros_lineales","metros_lineal"]):
            suggestions["Metros lineales aprox."].append(k)
        # fallback: qt_ prefix (common in Looker) - add to baches or M2 unsure, so include in all where none found
        if k.startswith("qt_") and not any(k in lst for lst in suggestions.values()):
            # place as potential for baches as first attempt
            suggestions["Baches reparados"].append(k)
    return suggestions

# -----------------------
# CAPTURA Y LOGICA
# -----------------------
async def capture_all_sections(timeout_initial=7000, click_timeout=7000):
    """
    Abre la página y captura batchedDataV2 para General y para cada sección definida.
    Devuelve dict raw por sección.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        captured = {}
        current_section = {"name":"General"}

        async def on_response(resp):
            try:
                if "batchedDataV2" in resp.url:
                    # intentar parse JSON
                    j = None
                    try:
                        j = await resp.json()
                    except:
                        return
                    ts = int(time.time()*1000)
                    sec = current_section["name"]
                    captured.setdefault(sec, []).append({"url":resp.url, "ts":ts, "json":j})
                    print(f"[capturado] sección={sec} ts={ts} url={resp.url}")
            except Exception as e:
                pass

        page.on("response", on_response)

        print("Cargando página (General)...")
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        
        # esperar para que los requests iniciales se hagan
        await page.wait_for_timeout(timeout_initial)

        # si no hay nada en General, esperar un poco más
        if not captured.get("General"):
            print("No se capturó General inmediatamente; esperando 3s más...")
            await page.wait_for_timeout(3000)

        # Iterar secciones e intentar clickear
        for s in SECTIONS:
            found = False
            print(f"\nIntentando sección: {s['display']}")
            for lbl in s["labels"]:
                try:
                    # Probamos literal text locator
                    loc = page.locator(f'text="{lbl}"')
                    cnt = await loc.count()
                    if cnt > 0:
                        current_section["name"] = s["display"]
                        try:
                            await loc.first.click(timeout=click_timeout)
                            print(f"  - Click exacto en '{lbl}'")
                            # esperar respuesta batchedDataV2
                            try:
                                await page.wait_for_response(lambda r: "batchedDataV2" in r.url, timeout=click_timeout)
                            except:
                                await page.wait_for_timeout(1200)
                            found = True
                            break
                        except Exception:
                            # si falla click exacto, seguimos intentando
                            pass
                except Exception:
                    pass

                # Si no se encontró con exact text, probamos contains con XPath (case-insensitive)
                try:
                    # preparar lower label
                    ll = lbl.lower()
                    xpath = f'xpath=//*[contains(translate(normalize-space(.), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{ll}")]'
                    # intentamos contar
                    cnt2 = await page.locator(xpath).count()
                    if cnt2 > 0:
                        current_section["name"] = s["display"]
                        try:
                            await page.click(xpath, timeout=click_timeout)
                            print(f"  - Click contains en '{lbl}'")
                            try:
                                await page.wait_for_response(lambda r: "batchedDataV2" in r.url, timeout=click_timeout)
                            except:
                                await page.wait_for_timeout(1200)
                            found = True
                            break
                        except Exception:
                            pass
                except Exception:
                    pass

            if not found:
                print(f"  ⚠️ No se encontró/ no se pudo clickear la sección: {s['display']}. Se omitirá.")
                current_section["name"] = "General"
            else:
                # darle un pequeño respiro entre clicks
                await page.wait_for_timeout(900)

        await browser.close()
        return captured

# -----------------------
# AGREGAR LOGICA DE 'GENERAL' POR SUMA SI FALTA
# -----------------------
def consolidate_parsed(captured_raw):
    """
    Desde captured_raw (dict sección -> list de responses) arma:
    - parsed per section: {section: {key: value}}
    - general: si existe se usa; si no, se genera sumando numéricos por campo entre secciones
    """
    parsed_sections = {}
    for sec, recs in captured_raw.items():
        merged = {}
        for r in recs:
            p = parse_batched_data(r["json"])
            merged.update(p)
        parsed_sections[sec] = merged

    # preparar resultado 'limpio' con heurística de mapeo
    all_keys = set()
    for v in parsed_sections.values():
        all_keys.update(v.keys())
    suggestions = heuristics_map(list(all_keys))

    # construir clean per section: buscar mejores candidatos para cada métrica
    clean = {}
    for sec, dd in parsed_sections.items():
        clean[sec] = {"Baches reparados": None, "M2 Totales": None, "Metros lineales aprox.": None}
        # usar suggestions preferentemente
        for metric, cands in suggestions.items():
            for cand in cands:
                if cand in dd and dd[cand] is not None:
                    clean[sec][metric] = dd[cand]
                    break
        # si aún faltan, buscar por heuristica en claves
        for metric in list(clean[sec].keys()):
            if clean[sec][metric] is None:
                for k,v in dd.items():
                    if v is None: continue
                    kl = k.lower()
                    if metric == "Baches reparados" and any(x in kl for x in ["bache","reparad","reparados","count","qt_"]):
                        clean[sec][metric] = v; break
                    if metric == "M2 Totales" and any(x in kl for x in ["m2","m²","metro cuadr","area","superficie","sqm"]):
                        clean[sec][metric] = v; break
                    if metric == "Metros lineales aprox." and any(x in kl for x in ["lineal","metros lineales","ml","m_lineal","lineales"]):
                        clean[sec][metric] = v; break

    # detectar 'General' explícito (si estaba capturado y has values)
    general_exists = "General" in clean and any(v is not None for v in clean["General"].values())
    if general_exists:
        general = clean["General"]
    else:
        # construir general por suma de secciones (ignorando None)
        general = {"Baches reparados": 0, "M2 Totales": 0.0, "Metros lineales aprox.": 0}
        found_any = {"Baches reparados": False, "M2 Totales": False, "Metros lineales aprox.": False}
        for sec, vals in clean.items():
            if sec == "General": continue
            for k in general.keys():
                val = vals.get(k)
                if isinstance(val, (int, float)):
                    general[k] = (general[k] or 0) + val
                    found_any[k] = True
        # si no se encontró nada para una métrica, dejar None
        for k in list(general.keys()):
            if not found_any[k]:
                general[k] = None

    # agregar general al resultado final (sobrescribir si existe)
    clean["General"] = general
    return parsed_sections, clean, suggestions

# -----------------------
# GRAFICAS y PDF
# -----------------------
def format_num(v):
    if v is None:
        return "—"
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")  # separador de miles con punto
    if isinstance(v, float):
        # formatear con 2 decimales, eliminar .00 si entero
        if abs(v - int(v)) < 1e-9:
            return f"{int(v):,}".replace(",", ".")
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(v)

def generate_bar_chart(metric_key, cleaned_results, filename_png):
    """
    metric_key: "Baches reparados" | "M2 Totales" | "Metros lineales aprox."
    cleaned_results: dict sections -> {metric: value}
    """
    # order de secciones: mostrar en el orden solicitado (5->1)
    order = [s["display"] for s in SECTIONS]  # already in desired order top->bottom
    # but user wants bars: 5 Terminado con monitoreo activo, 4 Detectados, 3 Retrabajo, 2 Revisión, 1 Terminado
    # ensure order is as SECTIONS above (we defined that order)
    labels = []
    values = []
    colors_bars = []
    for sec in order:
        labels.append(sec)
        val = cleaned_results.get(sec, {}).get(metric_key) if sec in cleaned_results else None
        if val is None and "General" in cleaned_results and metric_key in cleaned_results["General"]:
            # do not substitute per section with general
            pass
        values.append(val if isinstance(val, (int,float)) else 0)
        colors_bars.append(SECTION_COLORS.get(sec, "#888888"))

    # crear grafica
    plt.figure(figsize=(10,4))
    bars = plt.bar(labels, values, color=colors_bars)
    plt.title(metric_key, fontsize=14, color=COLOR_TITLE)
    plt.xticks(rotation=20, fontsize=10)
    plt.ylabel("")  # sin etiqueta extra
    # anotar valores en cada barra
    for bar, v in zip(bars, values):
        h = bar.get_height()
        label = format_num(v) if v != 0 else ""
        plt.text(bar.get_x() + bar.get_width()/2, h + max(0.01*max(values or [1]), 0.1), label, ha='center', va='bottom', fontsize=9)
    plt.tight_layout()
    plt.savefig(filename_png, dpi=150)
    plt.close()

def generate_pdf(cleaned_results, parsed_sections, ts):
    pdf_path = OUTPUT_DIR / f"Supervision_Inteligente_{ts}.pdf"
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    # Title
    title_style = ParagraphStyle('title', parent=styles['Title'], fontSize=20, textColor=COLOR_TITLE, alignment=1)
    story.append(Paragraph(REPORT_TITLE, title_style))
    story.append(Spacer(1, 6))
    subtitle_style = ParagraphStyle('subtitle', parent=styles['Normal'], fontSize=9, textColor=COLOR_TEXT, alignment=1)
    story.append(Paragraph("Datos extraídos en vivo de Google Looker Studio", subtitle_style))
    story.append(Spacer(1, 12))

    # DataTimestamp and generation
    ts_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    story.append(Paragraph(f"<b>Generado el:</b> {ts_text}", styles["Normal"]))
    # If JSON had dataTimestamp in General raw, include; else omit
    # show general metrics
    general = cleaned_results.get("General", {})
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Datos generales:</b>", styles["Heading3"]))
    table_data = [["Métrica", "Valor"]]
    table_data.append(["Baches reparados", format_num(general.get("Baches reparados"))])
    table_data.append(["M² Totales", format_num(general.get("M2 Totales"))])
    table_data.append(["Metros lineales aprox.", format_num(general.get("Metros lineales aprox."))])
    t = Table(table_data, colWidths=[9*cm, 6*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(1,0), colors.HexColor(COLOR_TITLE)),
        ('TEXTCOLOR',(0,0),(1,0), colors.white),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('GRID',(0,0),(-1,-1),0.3, colors.grey)
    ]))
    story.append(t)
    story.append(Spacer(1,12))

    # Generate charts images
    chart_files = []
    metrics = ["Baches reparados", "M2 Totales", "Metros lineales aprox."]
    for metric in metrics:
        png = OUTPUT_DIR / f"chart_{metric.replace(' ','_')}_{ts}.png"
        generate_bar_chart(metric, cleaned_results, str(png))
        chart_files.append(png)

    # Insert charts consecutivos
    for png in chart_files:
        story.append(Image(str(png), width=16*cm, height=7*cm))
        story.append(Spacer(1,12))

    # Footer: note about source
    story.append(Spacer(1,6))
    story.append(Paragraph("Fuente: Google Looker Studio (reporte público). Datos extraídos automáticamente.", styles["Normal"]))
    doc.build(story)
    return pdf_path

# -----------------------
# MAIN
# -----------------------
async def main():
    print("Iniciando captura en el dashboard...")
    captured_raw = await capture_all_sections()
    # guardar raw
    ts = int(time.time())
    raw_file = OUTPUT_DIR / f"raw_capture_{ts}.json"
    with raw_file.open("w", encoding="utf-8") as f:
        json.dump(captured_raw, f, ensure_ascii=False, indent=2)
    print(f"Raw guardado en {raw_file}")

    parsed_sections, cleaned_results, suggestions = consolidate_parsed(captured_raw)

    parsed_file = OUTPUT_DIR / f"parsed_sections_{ts}.json"
    with parsed_file.open("w", encoding="utf-8") as f:
        json.dump({"parsed_sections":parsed_sections, "cleaned_results":cleaned_results, "suggestions":suggestions}, f, ensure_ascii=False, indent=2)
    print(f"Parsed guardado en {parsed_file}")

    # advertir si falta mapeo
    missing = {}
    for sec, vals in cleaned_results.items():
        for k, v in vals.items():
            if v is None:
                missing.setdefault(sec, []).append(k)
    if missing:
        print("\n⚠️ Algunos valores no se pudieron mapear automáticamente. Revisa el archivo parsed_sections y raw_capture para ajustar el mapeo si hace falta.")
        print(json.dumps(missing, indent=2, ensure_ascii=False))

    # generar pdf
    pdf = generate_pdf(cleaned_results, parsed_sections, ts)
    print(f"\n✅ Reporte generado: {pdf.resolve()}")

if __name__ == "__main__":
    asyncio.run(main())


import asyncio
import json
from playwright.async_api import async_playwright

URL = "https://lookerstudio.google.com/u/0/reporting/ea3fb237-17c6-49c6-956b-77b33774ce9a/page/X9kcE"

# Secciones del dashboard
secciones = {
    "General": None,  # General no tiene botón, solo carga al inicio
    "Terminado": "text=Terminado",
    "Revisión": "text=Revisión",
    "Retrabajo": "text=Retrabajo",
    "Detectados": "text=Detectado",
    "Monitoreo activo": "text=Monitoreo activo"
}

data_reporte = {s: {} for s in secciones.keys()}

def mostrar_reporte():
    print("\n===== 📊 SUPERVISIÓN INTELIGENTE =====\n")
    for seccion, valores in data_reporte.items():
        print(f"▶ {seccion}")
        if valores:
            for k, v in valores.items():
                print(f"   {k}: {v}")
        else:
            print("   (sin datos)")
        print("")

def parse_number(x):
    if isinstance(x, (int, float)):
        return x
    if isinstance(x, str):
        s = x.strip()
        if s == "":
            return x
        s2 = s.replace(",", "").replace(" ", "")
        try:
            if s2.isdigit():
                return int(s2)
            return float(s2)
        except:
            return x
    return x

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=200)
        page = await browser.new_page()

        async def handle_response(response):
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
                            metrics_by_name[name] = parse_number(val)

            mapa_metricas = {
                "qt_tsfhazuupd": "Baches reparados",
                "qt_r6axt0uupd": "M² Totales",
                "qt_yct2j9xupd": "Metros lineales aprox"
            }

            # Guardar métricas en la sección actual
            if current_section not in data_reporte:
                data_reporte[current_section] = {}

            for clave, nombre in mapa_metricas.items():
                if clave in metrics_by_name:
                    data_reporte[current_section][nombre] = metrics_by_name[clave]

        page.on("response", handle_response)

        print("🌐 Abriendo el dashboard público...")
        await page.goto(URL, wait_until="domcontentloaded", timeout=120000)

        # Recorremos las secciones automáticamente
        for seccion, selector in secciones.items():
            global current_section
            current_section = seccion
            print(f"\n🔄 Cargando sección: {seccion}...")

            if selector:  # Si tiene botón, hacer click
                try:
                    await page.click(selector)
                except:
                    print(f"⚠ No se pudo hacer click en {seccion}, intentando continuar...")
            
            await page.wait_for_timeout(6000)  # esperar a que carguen datos

        await browser.close()
        print("\n✅ Captura finalizada.")
        mostrar_reporte()

if __name__ == "__main__":
    asyncio.run(run())
