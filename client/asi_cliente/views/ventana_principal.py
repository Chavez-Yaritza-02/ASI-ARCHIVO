"""Ventana principal: menú lateral y área de contenido.

Cada módulo es una página de `SECCIONES`. Las pantallas ya construidas están en
`PANTALLAS`; el resto muestra una página provisional con la etapa en que llegará.
Cada pantalla se crea la primera vez que se abre.
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

from asi_cliente.api.cliente import ClienteApi, UsuarioSesion
from asi_cliente.views.asistencia_hora import VistaAsistenciaHora
from asi_cliente.views.bitacora import VistaBitacora
from asi_cliente.views.calendario import VistaCalendario
from asi_cliente.views.catalogos import DOCENTES, VistaCatalogo, VistaCatalogos
from asi_cliente.views.consultas import (
    VistaBuscador,
    VistaConfiguracionAsistencia,
    VistaGrupos,
    VistaUbicacion,
)
from asi_cliente.views.documentos import VistaDocumentos
from asi_cliente.views.gestion_horarios import VistaGestionHorarios

# (título del menú, permiso necesario para verlo, etapa en que se implementa)
SECCIONES = [
    ("Asistencia por hora", "asistencia.ver", 4),
    ("Bitácora del día", "asistencia.ver", 4),
    ("Calendario", "asistencia.ver", 4),
    ("Gestión de horarios", "horarios.ver", 2),
    ("Docentes", "docentes.ver", 2),
    ("Catálogos", "horarios.ver", 2),
    ("Buscador", "docentes.ver", 5),
    ("Horarios por grupo", "horarios.ver", 5),
    ("Ubicación programada", "horarios.ver", 5),
    ("Tolerancia de retardos", "asistencia.ver", 5),
    ("Documentos", "documentos.ver", 6),
]

PANTALLAS = {
    "Documentos": VistaDocumentos,
    "Asistencia por hora": VistaAsistenciaHora,
    "Bitácora del día": VistaBitacora,
    "Calendario": VistaCalendario,
    "Gestión de horarios": VistaGestionHorarios,
    "Buscador": VistaBuscador,
    "Horarios por grupo": VistaGrupos,
    "Ubicación programada": VistaUbicacion,
    "Tolerancia de retardos": VistaConfiguracionAsistencia,
    "Docentes": lambda api, u: VistaCatalogo(api, u, DOCENTES, "Docentes"),
    "Catálogos": VistaCatalogos,
}

# Nombres anteriores del menú: ahora son pestañas dentro de "Gestión de horarios".
PESTANAS_GESTION = {
    "Horarios": "Horarios",
    "Importar horarios": "Importar y revisar",
    "Periodos": "Periodos",
    "Registro de cambios": "Registro de cambios",
}

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
    return [
        s
        for s in SECCIONES
        if (usuario.puede(s[1]) or (s[0] == "Buscador" and usuario.puede("horarios.ver")))
        and (s[0] != "Horarios por grupo" or usuario.puede("asistencia.ver"))
        and (
            s[0] != "Ubicación programada"
            or all(usuario.puede(p) for p in ("asistencia.ver", "docentes.ver"))
        )
    ]


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

    def __init__(self, usuario: UsuarioSesion, api: ClienteApi | None = None):
        super().__init__()
        self.api, self.usuario = api, usuario
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
        self.secciones = secciones_visibles(usuario)
        self.creadas: set[int] = set()
        for titulo, _permiso, etapa in self.secciones:
            self.menu.addItem(titulo)
            self.paginas.addWidget(_pagina_provisional(titulo, etapa))
        self.menu.currentRowChanged.connect(self.abrir)
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

    def abrir(self, indice: int) -> None:
        """Muestra una sección; la primera vez crea su pantalla real, si ya existe."""
        titulo = self.secciones[indice][0]
        if indice not in self.creadas and titulo in PANTALLAS and self.api is not None:
            provisional = self.paginas.widget(indice)
            self.paginas.removeWidget(provisional)
            provisional.deleteLater()
            self.paginas.insertWidget(indice, PANTALLAS[titulo](self.api, self.usuario))
            self.creadas.add(indice)
        self.paginas.setCurrentIndex(indice)

    def abrir_seccion(self, titulo: str) -> QWidget:
        pestana = PESTANAS_GESTION.get(titulo)
        if pestana:
            gestion = self.abrir_seccion("Gestión de horarios")
            vista = gestion.mostrar(pestana)
            if vista is None:
                raise StopIteration(titulo)  # sin permiso para esa pestaña
            return vista
        indice = next(i for i, s in enumerate(self.secciones) if s[0] == titulo)
        self.menu.setCurrentRow(indice)
        return self.paginas.widget(indice)
