"""Extrae horarios de PDFs escaneados (prueba de OCR, Etapa 1b).

Uso (los PDFs deben estar en una carpeta FUERA del repositorio):
    uv run --group ocr python herramientas/ocr_prueba/extraer.py CARPETA_PDFS SALIDA.json

Requiere Tesseract con idioma español instalado en el sistema.
Todo se procesa localmente; no se envía nada a servicios externos.
"""

import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytesseract

sys.path.insert(0, str(Path(__file__).parent))
from analisis import DIAS, leer_celda, leer_qr, normalizar, similitud  # noqa: E402

PRIMERA_HORA, ULTIMA_HORA = 7, 22  # filas de 07:00 a 23:00
MARGEN_FILA = 14  # píxeles entre el borde superior de la fila y su etiqueta de hora
_HORA = re.compile(r"^(\d{2})[:.,]\d{2}")


def paginas_de_pdf(ruta: Path) -> list[np.ndarray]:
    """Devuelve cada página como imagen en escala de grises."""
    imagenes = []
    with pymupdf.open(ruta) as doc:
        for pagina in doc:
            pix = pagina.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            imagenes.append(arr.copy())
    return imagenes


def leer_codigo_qr(img: np.ndarray) -> str:
    detector = cv2.QRCodeDetector()
    alto, ancho = img.shape
    for recorte in (img[: alto // 3, ancho // 2 :], img):  # primero la zona habitual
        for escala in (2, 1, 3):
            r = cv2.resize(recorte, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
            texto, *_ = detector.detectAndDecode(r)
            if texto:
                return texto
    return ""


def _palabras(img: np.ndarray) -> list[dict]:
    d = pytesseract.image_to_data(
        img, lang="spa", config="--psm 11", output_type=pytesseract.Output.DICT
    )
    return [
        {
            "t": t.strip(),
            "x": d["left"][i],
            "y": d["top"][i],
            "w": d["width"][i],
            "h": d["height"][i],
        }
        for i, t in enumerate(d["text"])
        if t.strip()
    ]


def ubicar_cuadricula(palabras: list[dict], ancho: int) -> tuple[dict, dict, float, float]:
    """Encuentra el centro de cada columna (día) y los límites de cada fila (hora)."""
    # Primero "HORAS"; los días se buscan solo en esa misma línea. (Antes se buscaban en
    # toda la página y un apellido parecido a "MARTES" desplazaba las columnas.)
    candidatos = [(similitud(normalizar(p["t"]), "horas"), p) for p in palabras]
    puntaje, horas = max(candidatos, key=lambda c: c[0], default=(0, None))
    if horas is None or puntaje < 0.8:
        raise ValueError("No se encontró el encabezado HORAS")
    encabezados: dict[str, dict] = {"horas": horas}
    linea = [p for p in palabras if abs(p["y"] - horas["y"]) < 30 and p["x"] > horas["x"]]
    for dia in DIAS:
        mejor = max(linea, key=lambda p: similitud(normalizar(p["t"]), dia), default=None)
        if mejor and similitud(normalizar(mejor["t"]), dia) >= 0.75:
            encabezados[dia] = mejor
    if len([d for d in DIAS if d in encabezados]) < 3:
        raise ValueError("No se encontraron los encabezados de la cuadrícula")

    centros = {d: p["x"] + p["w"] / 2 for d, p in encabezados.items() if d in DIAS}
    # Inclinación del escaneo, a partir de la altura de los encabezados de día.
    xs = np.array([encabezados[d]["x"] for d in centros])
    ys = np.array([encabezados[d]["y"] for d in centros])
    pendiente = float(np.polyfit(xs, ys, 1)[0]) if len(xs) >= 2 else 0.0

    # Columnas faltantes: se infieren con el espaciado promedio.
    conocidos = sorted((DIAS.index(d), c) for d, c in centros.items())
    paso = np.polyfit([i for i, _ in conocidos], [c for _, c in conocidos], 1)
    for i, d in enumerate(DIAS):
        centros.setdefault(d, float(np.polyval(paso, i)))

    # Filas: etiquetas de hora de inicio en la primera columna.
    limite_x = horas["x"] + horas["w"] / 2
    filas: dict[int, float] = {}
    for p in palabras:
        m = _HORA.match(p["t"])
        if m and p["x"] < limite_x and p["y"] > horas["y"]:
            h = int(m.group(1))
            if PRIMERA_HORA <= h <= ULTIMA_HORA and h not in filas:
                filas[h] = p["y"]  # la etiqueta está alineada arriba en su fila
    if len(filas) < 4:
        raise ValueError("No se encontraron suficientes etiquetas de hora")
    # Horas faltantes: interpolación lineal (o extrapolación con el paso promedio).
    hs = sorted(filas)
    paso_fila = (filas[hs[-1]] - filas[hs[0]]) / max(hs[-1] - hs[0], 1)
    for h in range(PRIMERA_HORA, ULTIMA_HORA + 1):
        if h not in filas:
            if h < hs[0]:
                filas[h] = filas[hs[0]] - (hs[0] - h) * paso_fila
            elif h > hs[-1]:
                filas[h] = filas[hs[-1]] + (h - hs[-1]) * paso_fila
            else:
                filas[h] = float(np.interp(h, hs, [filas[x] for x in hs]))
    # Cada fila empieza un poco arriba de su etiqueta y termina donde empieza la siguiente.
    limites: dict[int, tuple[float, float]] = {}
    for h in range(PRIMERA_HORA, ULTIMA_HORA + 1):
        siguiente = filas[h + 1] if h < ULTIMA_HORA else filas[h] + paso_fila
        limites[h] = (filas[h] - MARGEN_FILA, siguiente - MARGEN_FILA)
    return centros, limites, pendiente, limite_x


# Sin diccionario: evita que Tesseract "corrija" claves como M05 a la palabra MOS.
CONFIG_OCR = "--psm 6 -c load_system_dawg=0 -c load_freq_dawg=0"
IDIOMA_CELDAS = os.environ.get("OCR_IDIOMA_CELDAS", "eng")  # "eng" lee mejor las claves (ver docs)
ESCALA = 2


def _lineas_de_columna(
    img: np.ndarray, x0: int, x1: int, y0: int, y1: int
) -> list[tuple[float, str]]:
    """OCR de una columna completa. Devuelve (y superior en la página, texto) por línea."""
    recorte = img[max(y0, 0) : y1, max(x0, 0) : x1]
    grande = cv2.resize(recorte, None, fx=ESCALA, fy=ESCALA, interpolation=cv2.INTER_CUBIC)
    d = pytesseract.image_to_data(
        grande, lang=IDIOMA_CELDAS, config=CONFIG_OCR, output_type=pytesseract.Output.DICT
    )
    lineas: dict[tuple[int, int, int], list[int]] = {}
    for i, t in enumerate(d["text"]):
        if t.strip():
            lineas.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
    resultado = []
    for indices in lineas.values():
        indices.sort(key=lambda i: d["left"][i])
        arriba = min(d["top"][i] for i in indices) / ESCALA + max(y0, 0)
        resultado.append((arriba, " ".join(d["text"][i] for i in indices)))
    return sorted(resultado)


def nombre_en_encabezado(palabras: list[dict], ancho: int, y_cuadricula: float) -> str:
    etiqueta = next(
        (p for p in palabras if normalizar(p["t"]).startswith("DOCENTE") and p["y"] < y_cuadricula),
        None,
    )
    if not etiqueta:
        return ""
    linea = [
        p
        for p in palabras
        if abs(p["y"] - etiqueta["y"]) < 12
        and p["x"] > etiqueta["x"] + etiqueta["w"]
        and p["x"] < ancho * 0.46
    ]
    return " ".join(p["t"] for p in sorted(linea, key=lambda p: p["x"]))


def procesar_pagina(img: np.ndarray) -> dict:
    alto, ancho = img.shape
    resultado: dict = {"qr": leer_qr(leer_codigo_qr(img)), "error": None, "celdas": {}}
    if resultado["qr"]:
        resultado["qr"] = asdict(resultado["qr"])
    palabras = _palabras(img)
    try:
        centros, filas, pendiente, x_horas = ubicar_cuadricula(palabras, ancho)
    except ValueError as error:
        resultado["error"] = str(error)
        return resultado
    resultado["docente_ocr"] = nombre_en_encabezado(palabras, ancho, filas[PRIMERA_HORA][0])

    orden = [centros[d] for d in DIAS]
    medio = [(a + b) / 2 for a, b in zip(orden, orden[1:], strict=False)]
    bordes = [orden[0] - (medio[0] - orden[0])] + medio + [orden[-1] + (orden[-1] - medio[-1])]
    bordes[0] = max(bordes[0], x_horas + 60)
    for i, dia in enumerate(DIAS):
        x0, x1 = int(bordes[i]) + 6, int(bordes[i + 1]) - 6
        # Corrección por inclinación del escaneo en esta columna.
        desplazamiento = pendiente * ((x0 + x1) / 2 - x_horas)
        y0 = int(filas[PRIMERA_HORA][0] + desplazamiento)
        y1 = int(filas[ULTIMA_HORA][1] + desplazamiento)
        textos: dict[int, list[str]] = {}
        for arriba, texto in _lineas_de_columna(img, x0, x1, y0, y1):
            for h in range(PRIMERA_HORA, ULTIMA_HORA + 1):
                inicio, fin = filas[h]
                if inicio + desplazamiento <= arriba < fin + desplazamiento:
                    textos.setdefault(h, []).append(texto)
                    break
        for h, lineas in textos.items():
            texto = "\n".join(lineas)
            celda = leer_celda(texto)
            if celda:
                resultado["celdas"][f"{dia}-{h}"] = {**asdict(celda), "texto": texto}
    return resultado


def procesar_pdf(ruta: Path) -> dict:
    return {
        "archivo": ruta.name,
        "paginas": [procesar_pagina(img) for img in paginas_de_pdf(ruta)],
    }


def main() -> None:
    carpeta, salida = Path(sys.argv[1]), Path(sys.argv[2])
    pdfs = sorted(carpeta.glob("*.pdf"))
    with ProcessPoolExecutor() as ejecutor:
        resultados = list(ejecutor.map(procesar_pdf, pdfs))
    salida.write_text(json.dumps(resultados, ensure_ascii=False, indent=1))
    print(f"{len(resultados)} PDFs procesados -> {salida}")


if __name__ == "__main__":
    main()
