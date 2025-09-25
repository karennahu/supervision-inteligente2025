import requests
import pandas as pd
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4

# ======================
# CONFIGURACIÓN
# ======================
URL = "https://lookerstudio.google.com/u/0/batchedDataV2?appVersion=20250825_0004"
OUTPUT_PDF = "Reporte_Automatico.pdf"

# Secciones a consultar (ajusta según corresponda en tu API)
SECCIONES = ["Terminado", "Revisión", "Retrabajo", "Detectado", "Terminado con Monitoreo Activo"]

# ======================
# FUNCIÓN PARA OBTENER DATOS DE LA API
# ======================
def obtener_datos(seccion: str):
    """
    Hace un POST a la API de LookerStudio y devuelve (conteo, metros²) para la sección indicada.
    """
    payload = {
        "dataRequest": [{
            "datasetSpec": {
                "dataset": [{
                    "datasourceId": "c7a2cd25-69b0-410c-92b4-51e6dafd1ad9",  # tu datasource id
                    "alias": seccion
                }]
            }
        }]
    }

    response = requests.post(URL, json=payload)
    data = response.json()

    try:
        subsets = data["dataResponse"]
        conteo = None
        metros = None

        for subset in subsets:
            for ds in subset.get("dataSubset", []):
                cols = ds["dataset"]["tableDataset"]["column"]
                if "longColumn" in cols[0]:
                    conteo = int(cols[0]["longColumn"]["values"][0])
                elif "doubleColumn" in cols[0]:
                    metros = float(cols[0]["doubleColumn"]["values"][0])

        return conteo, metros
    except Exception as e:
        print(f"⚠️ Error procesando sección {seccion}: {e}")
        return None, None

# ======================
# RECOLECTAR DATOS DE TODAS LAS SECCIONES
# ======================
datos = []
for seccion in SECCIONES:
    conteo, metros = obtener_datos(seccion)
    if conteo is not None and metros is not None:
        datos.append({"Sección": seccion, "Cantidad": conteo, "Metros²": metros})

df = pd.DataFrame(datos)
print("📊 Datos obtenidos:\n", df)

# ======================
# GENERAR GRÁFICAS
# ======================
plt.figure(figsize=(8, 5))
plt.bar(df["Sección"], df["Cantidad"])
plt.title("Cantidad por Sección")
plt.xticks(rotation=30, ha="right")
plt.tight_layout()
plt.savefig("grafico_cantidad.png")
plt.close()

plt.figure(figsize=(8, 5))
plt.bar(df["Sección"], df["Metros²"])
plt.title("Metros² por Sección")
plt.xticks(rotation=30, ha="right")
plt.tight_layout()
plt.savefig("grafico_metros.png")
plt.close()

# ======================
# GENERAR REPORTE PDF
# ======================
doc = SimpleDocTemplate(OUTPUT_PDF, pagesize=A4)
styles = getSampleStyleSheet()
story = []

story.append(Paragraph("📊 Reporte Automático de Producción", styles["Title"]))
story.append(Spacer(1, 12))

story.append(Paragraph("Datos Generales:", styles["Heading2"]))
story.append(Paragraph(df.to_html(index=False), styles["Normal"]))
story.append(Spacer(1, 12))

story.append(Paragraph("Cantidad por Sección", styles["Heading2"]))
story.append(Image("grafico_cantidad.png", width=400, height=250))
story.append(Spacer(1, 12))

story.append(Paragraph("Metros² por Sección", styles["Heading2"]))
story.append(Image("grafico_metros.png", width=400, height=250))

doc.build(story)

print(f"✅ Reporte generado automáticamente: {OUTPUT_PDF}")

