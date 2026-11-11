# Construir en Windows: uv run --no-sync pyinstaller empaquetado/windows/asi.spec
#
# Modo local: el ejecutable lleva dentro la aplicación de escritorio, la API (`app`),
# la base SQLite y el lector de PDF (Tesseract, si existe la carpeta indicada en
# ASI_TESSERACT_DIR al construir; el flujo de GitHub Actions la prepara).
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

raiz = Path(SPECPATH).parents[1]

datos = (
    collect_data_files("certifi")
    + collect_data_files("reportlab")
    + collect_data_files("tzdata")
    + collect_data_files("pymupdf")
)
tesseract = os.environ.get("ASI_TESSERACT_DIR")
if tesseract and Path(tesseract, "tesseract.exe").is_file():
    datos.append((tesseract, "tesseract"))

a = Analysis(
    [str(raiz / "client/asi_cliente/main.py")],
    pathex=[str(raiz / "client"), str(raiz / "shared"), str(raiz / "server")],
    binaries=[],
    datas=datos,
    hiddenimports=[
        "keyring.backends.Windows",
        "sqlalchemy.dialects.sqlite",
        "argon2",
        "email_validator",
        "multipart",
        "python_multipart",
        *collect_submodules("app"),
        *collect_submodules("uvicorn"),
    ],
    hookspath=[],
    # psycopg solo se usa con el servidor central (PostgreSQL).
    excludes=["psycopg", "alembic", "pytest", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ASI-ARCHIVO", console=False,
          debug=False, strip=False, upx=False)
coleccion = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ASI-ARCHIVO")
