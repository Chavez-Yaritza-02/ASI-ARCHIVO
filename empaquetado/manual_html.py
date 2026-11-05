"""Convierte docs/MANUAL_USUARIO.md en "Manual de uso.html" para el instalador de Windows.

Uso: uv run --no-sync python empaquetado/manual_html.py dist/"Manual de uso.html"
"""

import sys
from pathlib import Path

import markdown

RAIZ = Path(__file__).resolve().parents[1]
ESTILO = """
body { font-family: "Segoe UI", Arial, sans-serif; max-width: 860px; margin: 32px auto;
       padding: 0 20px; color: #1f2937; line-height: 1.55; }
h1, h2, h3 { color: #1f2a37; } h2 { border-bottom: 1px solid #d9dde3; padding-bottom: 4px; }
table { border-collapse: collapse; margin: 12px 0; } td, th { border: 1px solid #d9dde3;
       padding: 6px 10px; text-align: left; } th { background: #f5f6f8; }
code { background: #f5f6f8; padding: 1px 4px; border-radius: 4px; }
blockquote { border-left: 4px solid #d97706; margin: 12px 0; padding: 4px 14px;
       background: #fffbeb; }
"""


def main() -> None:
    destino = Path(sys.argv[1])
    texto = (RAIZ / "docs" / "MANUAL_USUARIO.md").read_text(encoding="utf-8")
    cuerpo = markdown.markdown(texto, extensions=["tables", "toc"])
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        f'<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
        f"<title>ASI-ARCHIVO — Manual de uso</title><style>{ESTILO}</style></head>"
        f"<body>{cuerpo}</body></html>",
        encoding="utf-8",
    )
    print(f"Manual generado: {destino}")


if __name__ == "__main__":
    main()
