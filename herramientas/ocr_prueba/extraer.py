"""Extrae horarios de una carpeta de PDFs y guarda el resultado en JSON (Etapa 1b).

Uso (los PDFs deben estar en una carpeta FUERA del repositorio):
    uv run python herramientas/ocr_prueba/extraer.py CARPETA_PDFS SALIDA.json

La lógica de extracción vive en server/app/importers/ocr.py (la misma que usa el
importador de la aplicación); este script solo la aplica a una carpeta.
"""

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from app.importers.ocr import procesar_pdf


def main() -> None:
    carpeta, salida = Path(sys.argv[1]), Path(sys.argv[2])
    pdfs = sorted(carpeta.glob("*.pdf"))
    with ProcessPoolExecutor() as ejecutor:
        resultados = list(ejecutor.map(procesar_pdf, pdfs))
    salida.write_text(json.dumps(resultados, ensure_ascii=False, indent=1))
    print(f"{len(resultados)} PDFs procesados -> {salida}")


if __name__ == "__main__":
    main()
