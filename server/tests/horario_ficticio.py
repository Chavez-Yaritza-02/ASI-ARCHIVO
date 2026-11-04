"""Generador de horarios en PDF **ficticios** con el formato institucional.

Las pruebas no pueden usar documentos reales (datos personales), así que este módulo
dibuja una hoja parecida: encabezado, código QR con los mismos campos y la cuadrícula
de 07:00 a 23:00. Luego la convierte en imagen, para que el PDF resultante no tenga
texto digital y se procese con OCR, igual que un escaneo.
"""

import io
import zipfile
from dataclasses import dataclass, field

import pymupdf
import segno

DIAS = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO"]
_X_DIAS = [136, 216, 295, 374, 455, 534]  # centro de cada columna (puntos)
_Y_PRIMERA_FILA, _ALTO_FILA = 206, 18


@dataclass
class Clase:
    dia: int  # 0 = lunes
    hora: int  # 7 = 07:00
    actividad: str
    grupo: str | None
    aula: str


@dataclass
class HorarioFicticio:
    docente: str
    nomina: str
    clases: list[Clase]
    version: int = 1
    fecha: str = "2026-06-28"
    periodo: str = "AGOSTO - DICIEMBRE 2026"
    con_qr: bool = True
    extra_horas_qr: int = 0  # para simular que el QR declara más horas de las leídas
    horas: dict = field(default_factory=dict)

    def texto_qr(self) -> str:
        total = len(self.clases) + self.extra_horas_qr
        return (
            f"ZAPOPAN,{self.periodo},{self.docente},{self.nomina},{self.fecha},"
            f"2026-07-01 AL 2026-12-31,{self.version},0GTUT[0],TEXT[0],"
            f"MAT[{total}],TOT[{total}],"
        )


def _pagina(doc: pymupdf.Document, h: HorarioFicticio) -> None:
    p = doc.new_page(width=612, height=792)
    fuente = "helv"
    p.insert_text((40, 118), "UNIDAD:", fontsize=8, fontname=fuente)
    p.insert_text((96, 118), "ZAPOPAN", fontsize=8, fontname=fuente)
    p.insert_text((40, 130), "DOCENTE:", fontsize=8, fontname=fuente)
    p.insert_text((96, 130), h.docente, fontsize=8, fontname=fuente)
    p.insert_text((300, 118), "PERIODO:", fontsize=8, fontname=fuente)
    p.insert_text((357, 118), h.periodo, fontsize=8, fontname=fuente)
    p.insert_text((300, 130), "VERSION:", fontsize=8, fontname=fuente)
    p.insert_text((357, 130), str(h.version), fontsize=8, fontname=fuente)
    if h.con_qr:
        png = io.BytesIO()
        segno.make(h.texto_qr(), error="m").save(png, kind="png", scale=4, border=2)
        p.insert_image(pymupdf.Rect(515, 92, 575, 152), stream=png.getvalue())

    y_titulos = _Y_PRIMERA_FILA - 14
    p.insert_text((48, y_titulos), "HORAS", fontsize=8, fontname="hebo")
    for x, dia in zip(_X_DIAS, DIAS, strict=True):
        ancho = pymupdf.get_text_length(dia, fontname="hebo", fontsize=8)
        p.insert_text((x - ancho / 2, y_titulos), dia, fontsize=8, fontname="hebo")
    for i, hora in enumerate(range(7, 23)):
        y = _Y_PRIMERA_FILA + i * _ALTO_FILA
        p.draw_line((38, y - 7), (575, y - 7), color=(0.75, 0.75, 0.75), width=0.4)
        etiqueta = f"{hora:02d}:00:00 - {hora + 1:02d}:00:00"
        p.insert_text((45, y), etiqueta, fontsize=5.5, fontname=fuente)
    for c in h.clases:
        y = _Y_PRIMERA_FILA + (c.hora - 7) * _ALTO_FILA
        segunda = f"Grupo: {c.grupo} Aula: {c.aula}" if c.grupo else f"Aula: {c.aula}"
        for linea, texto in enumerate((c.actividad, segunda)):
            ancho = pymupdf.get_text_length(texto, fontname=fuente, fontsize=5.5)
            p.insert_text(
                (_X_DIAS[c.dia] - ancho / 2, y + linea * 6.5), texto, fontsize=5.5, fontname=fuente
            )


def pdf_escaneado(*horarios: HorarioFicticio) -> bytes:
    """PDF de una página por horario, solo con imagen (sin texto digital)."""
    vectorial = pymupdf.open()
    for h in horarios:
        _pagina(vectorial, h)
    escaneado = pymupdf.open()
    for pagina in vectorial:
        imagen = pagina.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
        nueva = escaneado.new_page(width=612, height=792)
        nueva.insert_image(nueva.rect, stream=imagen.tobytes("png"))
    return escaneado.tobytes()


def zip_con(archivos: dict[str, bytes]) -> bytes:
    contenido = io.BytesIO()
    with zipfile.ZipFile(contenido, "w") as zf:
        for nombre, datos in archivos.items():
            zf.writestr(nombre, datos)
    return contenido.getvalue()


# Dos docentes ficticios con clases representativas.
UNO = HorarioFicticio(
    docente="DOCENTE PRUEBA UNO",
    nomina="ZZX0001",
    clases=[
        Clase(0, 7, "CALC. DIF.", "A", "M01"),
        Clase(0, 8, "CALC. DIF.", "A", "M01"),
        Clase(0, 9, "GESTION ACADEMICA", None, "SALA EM"),
        Clase(2, 7, "FIS. GRAL", "B", "M05"),
        Clase(4, 10, "TUTORIA INDIVIDUAL", None, "DOM-03"),
    ],
)
DOS = HorarioFicticio(
    docente="DOCENTE PRUEBA DOS",
    nomina="ZZX0002",
    clases=[
        Clase(1, 15, "DINAMICA", "N", "LMAC"),
        Clase(1, 16, "DINAMICA", "N", "LMAC"),
        Clase(3, 15, "CALC. DIF.", "N", "M02"),
    ],
)
