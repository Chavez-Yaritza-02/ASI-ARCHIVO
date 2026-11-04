"""Configuración común de pruebas: la interfaz gráfica se dibuja sin abrir ventanas."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ASI_ENTORNO"] = "pruebas"
sys.path.insert(0, str(Path(__file__).parent / "server"))

# Se instala antes de recoger cualquier módulo de pruebas, incluso del cliente.
from app.db import proteccion_pruebas  # noqa: E402, F401
