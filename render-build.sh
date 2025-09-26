#!/usr/bin/env bash
# Instalar dependencias de Python
pip install -r requirements.txt
# Instalar navegadores de Playwright
python -m playwright install --with-deps chromium
