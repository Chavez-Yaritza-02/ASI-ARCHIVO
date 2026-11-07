"""«Ver PDF original»: muestra la página del documento importado junto a la revisión.

El servidor no guarda el PDF (solo su huella sha256 y los recortes de cada celda). Se usa
el archivo que el usuario tiene en su computadora —el PDF o el ZIP que importó— y se
comprueba con la huella que sea exactamente el mismo documento. Nada se sube ni se copia:
el PDF se lee en memoria y solo durante la sesión se recuerda dónde estaba.
"""

import hashlib
import zipfile
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

# Ubicaciones encontradas en esta sesión: huella o nombre -> ruta local (PDF o ZIP).
_RUTAS: dict[str, Path] = {}


class ArchivoNoCoincide(ValueError):
    """El archivo elegido no contiene el documento que se importó."""


def recordar(ruta: Path) -> None:
    """Apunta un PDF o ZIP recién importado para poder mostrarlo después sin preguntar."""
    try:
        for nombre, datos in _pdfs_de(ruta):
            _RUTAS[hashlib.sha256(datos).hexdigest()] = ruta
            _RUTAS[nombre] = ruta
    except (OSError, zipfile.BadZipFile):
        pass


def _pdfs_de(ruta: Path):
    if ruta.suffix.lower() == ".zip":
        with zipfile.ZipFile(ruta) as zf:
            for info in zf.infolist():
                nombre = PurePosixPath(info.filename).name
                if nombre.lower().endswith(".pdf") and not nombre.startswith("._"):
                    yield nombre, zf.read(info)
    else:
        yield ruta.name, ruta.read_bytes()


def buscar_pdf(ruta: Path, sha256: str | None, nombre: str) -> tuple[bytes, bool]:
    """Devuelve (contenido, verificado). verificado=False si el servidor no dio huella.

    Lanza ArchivoNoCoincide si el archivo no contiene ese documento.
    """
    por_nombre = None
    for interno, datos in _pdfs_de(ruta):
        if sha256 and hashlib.sha256(datos).hexdigest() == sha256:
            return datos, True
        if interno == nombre:
            por_nombre = datos
    if por_nombre is not None and not sha256:
        return por_nombre, False
    raise ArchivoNoCoincide(
        f"{ruta.name} no contiene el documento importado «{nombre}» (la huella no coincide). "
        "Elige el PDF o ZIP que se importó."
    )


def ruta_conocida(sha256: str | None, nombre: str) -> Path | None:
    ruta = _RUTAS.get(sha256 or "") or _RUTAS.get(nombre)
    return ruta if ruta and ruta.exists() else None


class VisorPdf(QDialog):
    """Ventana aparte (no bloquea la revisión) con la página del PDF original."""

    def __init__(self, contenido: bytes, titulo: str, pagina: int, verificado: bool, padre=None):
        super().__init__(padre)
        self.setWindowTitle(f"PDF original · {titulo}")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(760, 900)
        self._datos = QByteArray(contenido)
        self._buffer = QBuffer(self._datos, self)
        self._buffer.open(QIODevice.ReadOnly)
        self.documento = QPdfDocument(self)
        self.documento.load(self._buffer)
        self.vista = QPdfView(self)
        self.vista.setDocument(self.documento)
        self.vista.setPageMode(QPdfView.PageMode.MultiPage)
        self.vista.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.pagina = max(0, min(pagina - 1, self.documento.pageCount() - 1))
        self.vista.pageNavigator().jump(self.pagina, QPointF(), 0)

        aviso = (
            f"Página {pagina} de {self.documento.pageCount()}. "
            + ("Documento verificado: es el mismo que se importó." if verificado else "")
            + (
                ""
                if verificado
                else "El servidor no informa la huella: se identificó por el nombre del archivo."
            )
        )
        mas = QPushButton("Acercar")
        menos = QPushButton("Alejar")
        ajustar = QPushButton("Ajustar al ancho")
        mas.clicked.connect(lambda: self._zoom(1.25))
        menos.clicked.connect(lambda: self._zoom(0.8))
        ajustar.clicked.connect(lambda: self.vista.setZoomMode(QPdfView.ZoomMode.FitToWidth))
        barra = QHBoxLayout()
        barra.addWidget(QLabel(aviso, objectName="suave", wordWrap=True), 1)
        for b in (menos, mas, ajustar):
            barra.addWidget(b)
        capa = QVBoxLayout(self)
        capa.addLayout(barra)
        capa.addWidget(self.vista, 1)

    def _zoom(self, factor: float) -> None:
        self.vista.setZoomMode(QPdfView.ZoomMode.Custom)
        self.vista.setZoomFactor(self.vista.zoomFactor() * factor)
