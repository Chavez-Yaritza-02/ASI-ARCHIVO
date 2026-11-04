"""Ventana principal: menú lateral y área de contenido.

Cada módulo se agregará como una página en `SECCIONES` en su etapa
correspondiente. Por ahora solo hay páginas provisionales.
"""

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import UsuarioSesion

# (título del menú, permiso necesario para verlo, etapa en que se implementa)
SECCIONES = [
    ("Bitácora del día", "asistencia.ver", 4),
    ("Docentes", "docentes.ver", 2),
    ("Horarios", "horarios.ver", 2),
    ("Periodos", "periodos.gestionar", 2),
    ("Buscador", "docentes.ver", 5),
    ("Documentos", "documentos.ver", 6),
    ("Reportes", "reportes.ver", 7),
]

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def fecha_larga(d: date) -> str:
    return f"{_DIAS[d.weekday()].capitalize()} {d.day} de {_MESES[d.month - 1]} de {d.year}"


def secciones_visibles(usuario: UsuarioSesion) -> list[tuple[str, str, int]]:
    return [s for s in SECCIONES if usuario.puede(s[1])]


def _pagina_provisional(titulo: str, etapa: int) -> QWidget:
    pagina = QWidget()
    caja = QVBoxLayout(pagina)
    caja.setContentsMargins(32, 28, 32, 28)
    caja.addWidget(QLabel(titulo, objectName="titulo"))
    caja.addWidget(QLabel(fecha_larga(date.today()), objectName="subtitulo"))
    caja.addSpacing(16)
    caja.addWidget(QLabel(f"Este módulo se construirá en la Etapa {etapa}.", objectName="suave"))
    caja.addStretch()
    return pagina


class VentanaPrincipal(QMainWindow):
    cambiar_tema = Signal()
    cerrar_sesion = Signal()

    def __init__(self, usuario: UsuarioSesion):
        super().__init__()
        self.setWindowTitle("ASI-ARCHIVO")
        self.resize(1200, 760)

        lateral = QWidget(objectName="lateral")
        lateral.setFixedWidth(230)
        caja_lateral = QVBoxLayout(lateral)
        caja_lateral.setContentsMargins(0, 20, 0, 16)
        marca = QLabel("  ASI-ARCHIVO")
        marca.setStyleSheet("font-size: 17px; padding: 0 8px 12px 8px;")
        caja_lateral.addWidget(marca)

        self.menu = QListWidget(objectName="menu")
        self.paginas = QStackedWidget()
        for titulo, _permiso, etapa in secciones_visibles(usuario):
            self.menu.addItem(titulo)
            self.paginas.addWidget(_pagina_provisional(titulo, etapa))
        self.menu.currentRowChanged.connect(self.paginas.setCurrentIndex)
        self.menu.setCurrentRow(0)
        caja_lateral.addWidget(self.menu, 1)

        nombre = QLabel(f"  {usuario.nombre}")
        nombre.setStyleSheet("font-weight: 400; font-size: 13px;")
        boton_tema = QPushButton("Cambiar tema")
        boton_salir = QPushButton("Cerrar sesión")
        boton_tema.clicked.connect(self.cambiar_tema)
        boton_salir.clicked.connect(self.cerrar_sesion)
        caja_lateral.addWidget(nombre)
        for b in (boton_tema, boton_salir):
            fila = QHBoxLayout()
            fila.setContentsMargins(12, 4, 12, 0)
            fila.addWidget(b)
            caja_lateral.addLayout(fila)

        central = QWidget()
        caja = QHBoxLayout(central)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(0)
        caja.addWidget(lateral)
        caja.addWidget(self.paginas, 1)
        self.setCentralWidget(central)
