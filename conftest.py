"""Configuración común de pruebas: la interfaz gráfica se dibuja sin abrir ventanas."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
