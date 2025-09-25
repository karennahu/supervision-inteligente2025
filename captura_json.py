import asyncio
from playwright.async_api import async_playwright
import json

URL = "https://lookerstudio.google.com/u/0/reporting/ea3fb237-17c6-49c6-956b-77b33774ce9a/page/X9kcE"

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # visible para ver si carga
        page = await browser.new_page()

        async def handle_response(response):
            if "batchedDataV2" in response.url:
                try:
                    data = await response.json()
                    print("\n===== 📊 DATOS CAPTURADOS =====\n")
                    print(json.dumps(data, indent=2))  # imprimir todo el JSON
                except Exception as e:
                    print("⚠️ Error al procesar:", e)

        page.on("response", handle_response)

        print("🌐 Abriendo el dashboard público...")
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        # esperar 15 segundos a que carguen datos
        await page.wait_for_timeout(15000)

        await browser.close()
        print("\n✅ Captura finalizada.")

asyncio.run(run())
