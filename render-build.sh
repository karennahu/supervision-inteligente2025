#!/usr/bin/env bash
# Archivo: render-build.sh

# Detener el proceso si ocurre algún error
set -o errexit

# Instalar dependencias de Python desde requirements.txt
pip install -r requirements.txt

# Instalar navegadores de Playwright con todas las dependencias
python -m playwright install --with-deps chromium
