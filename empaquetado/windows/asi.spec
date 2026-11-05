# Construir en Windows: uv run --no-sync pyinstaller empaquetado/windows/asi.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

raiz = Path(SPECPATH).parents[1]
a = Analysis(
    [str(raiz / "client/asi_cliente/main.py")],
    pathex=[str(raiz / "client"), str(raiz / "shared")],
    binaries=[],
    datas=collect_data_files("certifi"),
    hiddenimports=["keyring.backends.Windows"],
    hookspath=[],
    excludes=["app", "psycopg", "sqlalchemy", "uvicorn", "pytesseract", "cv2", "numpy",
              "pymupdf", "PIL", "openpyxl", "reportlab", "pytest", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ASI-ARCHIVO", console=False,
          debug=False, strip=False, upx=False)
coleccion = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ASI-ARCHIVO")
