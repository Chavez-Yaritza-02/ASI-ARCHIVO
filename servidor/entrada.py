"""Leer secretos montados; no quedan incrustados en imágenes o configuración de Docker."""

import os
import sys
from pathlib import Path
from urllib.parse import quote

usuario = os.environ.get("ASI_DB_USUARIO", "asi_app")
secreto = "db_admin" if usuario == "asi_admin" else "db_app"
clave = Path("/run/secrets", secreto).read_text().strip()
os.environ["ASI_DATABASE_URL"] = (
    f"postgresql+psycopg://{usuario}:{quote(clave, safe='')}@"
    f"{os.environ.get('ASI_DB_HOST', 'db')}:5432/{os.environ.get('ASI_DB_NOMBRE', 'asi_archivo')}"
)
os.environ["ASI_SECRET_KEY"] = Path("/run/secrets/api_jwt").read_text().strip()
os.execvp(sys.argv[1], sys.argv[1:])
