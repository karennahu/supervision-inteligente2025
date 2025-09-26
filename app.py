import subprocess

# Instalar Chromium si no existe (solo primera vez en Render)
try:
    subprocess.run(["playwright", "install", "chromium"], check=True)
except Exception as e:
    print("⚠️ No se pudo instalar Chromium automáticamente:", e)

import os
import asyncio
from flask import Flask, send_file, render_template
from extraer_datos import extraer_datos, generar_pdf_final

# Crear la app Flask
app = Flask(__name__)

# Rutas de imágenes para reportlab (PDF), apuntando a /static/
HEADER_IMG = os.path.join(app.static_folder, "encabezado.png")
FOOTER_IMG = os.path.join(app.static_folder, "Toluca-logo-outline-blanco.png")

@app.route('/')
def index():
    """Página principal con el template visual.html"""
    return render_template('visual.html')

@app.route('/generar_pdf')
def generar_pdf():
    """Genera el PDF y lo envía como descarga"""
    try:
        # Extraer datos de Looker Studio con Playwright
        datos = asyncio.run(extraer_datos(playheadless=True))

        # Generar el PDF en la carpeta raíz del proyecto
        pdf_file = "Reporte_Supervision.pdf"
        generar_pdf_final(datos, archivo_pdf=pdf_file,
                          header_img=HEADER_IMG, footer_img=FOOTER_IMG)

        # Enviar PDF como archivo descargable
        return send_file(pdf_file, as_attachment=True)
    except Exception as e:
        print("❌ Error al generar PDF:", e)
        return f"Error al generar PDF: {e}", 500

if __name__ == "__main__":
    # En Render, el debug debe ser False
    app.run(host="0.0.0.0", port=5000, debug=True)

