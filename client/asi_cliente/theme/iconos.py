"""Iconos de línea sencillos (SVG en el código, sin archivos externos).

Se dibujan con el color que se pida, así sirven en el menú oscuro y en fondos claros.
"""

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Trazos sobre una cuadrícula de 24×24.
_TRAZOS = {
    "inicio": '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
    "asistencias": (
        '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4h6v3H9z"/>'
        '<path d="m8.5 13 2.5 2.5 4.5-5"/>'
    ),
    "horarios": (
        '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>'
        '<path d="M8 14h3M13 14h3M8 17h3"/>'
    ),
    "docentes": (
        '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/>'
        '<circle cx="17" cy="9" r="2.5"/><path d="M16.5 14.6c2.6.2 4.4 1.9 5 4.9"/>'
    ),
    "reportes": (
        '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5"/><path d="M9 17v-3M12 17v-6M15 17v-2"/>'
    ),
    "administracion": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1'
        'M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>'
    ),
    "buscar": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    "importar": '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v3h16v-3"/>',
    "periodo": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "salir": '<path d="M10 4H5v16h5"/><path d="M14 8l4 4-4 4M18 12H9"/>',
    "tema": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "ayuda": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7"/><path d="M12 17h.01"/>'
    ),
}

NOMBRES = tuple(_TRAZOS)


def svg(nombre: str, color: str = "#ffffff") -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        f"{_TRAZOS[nombre]}</svg>"
    )


def icono(nombre: str, color: str = "#ffffff", tamano: int = 22) -> QIcon:
    """Icono nítido en pantallas normales y de alta densidad."""
    render = QSvgRenderer(QByteArray(svg(nombre, color).encode()))
    resultado = QIcon()
    for escala in (1, 2):
        pixmap = QPixmap(tamano * escala, tamano * escala)
        pixmap.fill(Qt.transparent)
        pintor = QPainter(pixmap)
        render.render(pintor)
        pintor.end()
        pixmap.setDevicePixelRatio(escala)
        resultado.addPixmap(pixmap)
    return resultado
