from flask import Flask, send_file, render_template
import asyncio
from extraer_datos import extraer_datos, generar_pdf_final

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('visual.html')

@app.route('/generar_pdf')
def generar_pdf():
    try:
        # Extraer datos y generar PDF
        datos = asyncio.run(extraer_datos(playheadless=True))
        pdf_file = "Reporte_Supervision.pdf"
        generar_pdf_final(datos, archivo_pdf=pdf_file)

        return send_file(pdf_file, as_attachment=True)
    except Exception as e:
        print("Error al generar PDF:", e)
        return "Error al generar PDF", 500

if __name__ == "__main__":
    app.run(debug=True)
