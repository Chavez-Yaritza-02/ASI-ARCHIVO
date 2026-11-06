"""Ventana principal: seis secciones claras, cada una con sus pantallas en pestañas.

    Inicio · Asistencias · Horarios · Docentes · Reportes · Administración

- Las pantallas son las que ya existían (se reutilizan sin cambiar su lógica); aquí solo
  se organizan. Cada una se crea la primera vez que se abre.
- Cada pantalla conserva su permiso: una sección aparece si el usuario puede ver al
  menos una de sus pantallas, y una pestaña solo si tiene el permiso de esa pantalla.
- La barra superior muestra siempre la sección, el periodo activo y el usuario.
- Teclado: Ctrl+1…Ctrl+6 cambia de sección; Ctrl+Tab cambia de pestaña.
"""

from datetime import date

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.servidor import describir_servidor
from asi_cliente.theme.iconos import icono
from asi_cliente.views.asistencia_hora import VistaAsistenciaHora
from asi_cliente.views.asistente_importacion import VistaAsistenteImportacion
from asi_cliente.views.bitacora import VistaBitacora
from asi_cliente.views.calendario import VistaCalendario
from asi_cliente.views.catalogos import DOCENTES, VistaCatalogo, VistaCatalogos
from asi_cliente.views.configuracion import VistaConfiguracion
from asi_cliente.views.consultas import (
    VistaBuscador,
    VistaConfiguracionAsistencia,
    VistaGrupos,
    VistaUbicacion,
)
from asi_cliente.views.documentos import VistaDocumentos
from asi_cliente.views.gestion_horarios import VistaCambios, cambiar_periodo_activo
from asi_cliente.views.horarios import VistaHorarios
from asi_cliente.views.inicio import VistaInicio
from asi_cliente.views.periodos import VistaPeriodos
from asi_cliente.views.reportes import VistaReportes

# Pantallas: (nombre interno, permiso necesario, etapa en que se construyó).
# El nombre interno se conserva para compatibilidad (pruebas, autoprueba del instalador).
SECCIONES = [
    ("Inicio", None, 1),
    ("Asistencia por hora", "asistencia.ver", 4),
    ("Bitácora del día", "asistencia.ver", 4),
    ("Calendario", "asistencia.ver", 4),
    ("Horarios", "horarios.ver", 2),
    ("Horarios por grupo", "horarios.ver", 5),
    ("Importar horarios", "horarios.editar", 3),
    ("Registro de cambios", "horarios.ver", 3),
    ("Docentes", "docentes.ver", 2),
    ("Buscador", "docentes.ver", 5),
    ("Reportes", "reportes.generar", 4),
    ("Periodos", "horarios.ver", 2),
    ("Catálogos", "horarios.ver", 2),
    ("Documentos", "documentos.ver", 6),
    ("Tolerancia de retardos", "asistencia.ver", 5),
    ("Ubicación programada", "horarios.ver", 5),
    ("Configuración", None, 1),
]

PANTALLAS = {
    "Inicio": VistaInicio,
    "Asistencia por hora": VistaAsistenciaHora,
    "Bitácora del día": VistaBitacora,
    "Calendario": VistaCalendario,
    "Horarios": VistaHorarios,
    "Horarios por grupo": VistaGrupos,
    "Importar horarios": VistaAsistenteImportacion,
    "Registro de cambios": VistaCambios,
    "Docentes": lambda api, u: VistaCatalogo(api, u, DOCENTES, "Docentes"),
    "Buscador": VistaBuscador,
    "Reportes": VistaReportes,
    "Periodos": VistaPeriodos,
    "Catálogos": VistaCatalogos,
    "Documentos": VistaDocumentos,
    "Tolerancia de retardos": VistaConfiguracionAsistencia,
    "Ubicación programada": VistaUbicacion,
    "Configuración": VistaConfiguracion,
}

# Secciones del menú: (título, icono, descripción, [(pantalla, texto de la pestaña)]).
GRUPOS = [
    ("Inicio", "inicio", "Resumen del día y accesos rápidos", [("Inicio", "Inicio")]),
    (
        "Asistencias",
        "asistencias",
        "Registrar y consultar la asistencia de los docentes",
        [
            ("Asistencia por hora", "Registro por hora"),
            ("Bitácora del día", "Bitácora del día"),
            ("Calendario", "Días inhábiles y eventos"),
        ],
    ),
    (
        "Horarios",
        "horarios",
        "Horarios por docente y por grupo, importación y cambios",
        [
            ("Horarios", "Por docente"),
            ("Horarios por grupo", "Por grupo"),
            ("Importar horarios", "Importar horarios"),
            ("Registro de cambios", "Registro de cambios"),
        ],
    ),
    (
        "Docentes",
        "docentes",
        "Catálogo de docentes y búsqueda",
        [("Docentes", "Catálogo de docentes"), ("Buscador", "Búsqueda general")],
    ),
    ("Reportes", "reportes", "Reportes en PDF y Excel", [("Reportes", "Reportes")]),
    (
        "Administración",
        "administracion",
        "Periodos, catálogos, documentos y configuración",
        [
            ("Periodos", "Periodos"),
            ("Catálogos", "Catálogos"),
            ("Documentos", "Documentos"),
            ("Tolerancia de retardos", "Tolerancia de retardos"),
            ("Ubicación programada", "Ubicación programada"),
            ("Configuración", "Configuración"),
        ],
    ),
]

# Nombres anteriores que ya no son pantallas propias.
ALIAS = {"Gestión de horarios": "Horarios"}

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
ANCHO_COMPACTO = 1100  # por debajo de este ancho el menú muestra solo iconos


def fecha_larga(d: date) -> str:
    return f"{_DIAS[d.weekday()].capitalize()} {d.day} de {_MESES[d.month - 1]} de {d.year}"


def secciones_visibles(usuario: UsuarioSesion) -> list[tuple[str, str | None, int]]:
    """Pantallas que el usuario puede abrir (cada una con su permiso de siempre)."""
    return [
        s
        for s in SECCIONES
        if (
            s[1] is None
            or usuario.puede(s[1])
            or (s[0] == "Buscador" and usuario.puede("horarios.ver"))
        )
        and (s[0] != "Horarios por grupo" or usuario.puede("asistencia.ver"))
        and (
            s[0] != "Ubicación programada"
            or all(usuario.puede(p) for p in ("asistencia.ver", "docentes.ver"))
        )
    ]


def nombre_rol(usuario: UsuarioSesion) -> str:
    if "administrador" in usuario.roles:
        return "Administrador"
    if "consulta" in usuario.roles:
        return "Consulta (solo lectura)"
    return ", ".join(r.capitalize() for r in usuario.roles) or "Sin rol"


def confirmar_salida(padre, accion: str, cambios: list[str]) -> bool:
    """Pregunta antes de perder cambios sin guardar. True = salir de todos modos."""
    caja = QMessageBox(padre)
    caja.setIcon(QMessageBox.Warning)
    caja.setWindowTitle("Cambios sin guardar")
    caja.setText(f"Hay cambios sin guardar. Si vas a {accion}, se perderán.")
    caja.setInformativeText(
        "Pendiente de guardar en:\n"
        + "\n".join(f"• {c}" for c in cambios)
        + "\n\nVuelve y pulsa «Guardar» en esa pantalla para conservarlos."
    )
    volver = caja.addButton("Volver y guardar", QMessageBox.RejectRole)
    salir = caja.addButton("Salir sin guardar", QMessageBox.DestructiveRole)
    caja.setDefaultButton(volver)
    caja.exec()
    return caja.clickedButton() is salir


class Seccion(QWidget):
    """Una sección del menú: sus pantallas en pestañas, creadas al abrirlas."""

    def __init__(self, ventana: "VentanaPrincipal", pantallas: list[tuple[str, str]]):
        super().__init__()
        self.ventana = ventana
        self.nombres = [p for p, _ in pantallas]
        self.creadas: dict[str, QWidget] = {}
        self.pestanas = QTabWidget(objectName="subsecciones")
        self.pestanas.setDocumentMode(True)
        for nombre, texto in pantallas:
            provisional = QWidget()
            provisional.setObjectName(f"pendiente:{nombre}")
            self.pestanas.addTab(provisional, texto)
        self.pestanas.tabBar().setVisible(len(pantallas) > 1)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(28, 8, 28, 20)
        capa.addWidget(self.pestanas)
        self.pestanas.currentChanged.connect(self._crear)
        self._crear(0)

    def _crear(self, indice: int) -> None:
        if indice < 0:
            return
        nombre = self.nombres[indice]
        if nombre in self.creadas or self.ventana.api is None:
            return
        vista = PANTALLAS[nombre](self.ventana.api, self.ventana.usuario)
        self._adaptar(vista)
        if hasattr(vista, "navegar"):
            vista.navegar = self.ventana.abrir_seccion
        if hasattr(vista, "ventana"):
            vista.ventana = self.ventana
        self.creadas[nombre] = vista
        actual = self.pestanas.currentIndex()
        self.pestanas.blockSignals(True)
        provisional = self.pestanas.widget(indice)
        texto = self.pestanas.tabText(indice)
        self.pestanas.removeTab(indice)
        provisional.deleteLater()
        self.pestanas.insertTab(indice, vista, texto)
        self.pestanas.setCurrentIndex(actual)
        self.pestanas.blockSignals(False)

    @staticmethod
    def _adaptar(vista: QWidget) -> None:
        """La sección ya muestra el título: la pantalla conserva solo su explicación."""
        capa = vista.layout()
        if capa is not None:
            capa.setContentsMargins(0, 0, 0, 0)
        for titulo in vista.findChildren(QLabel, "titulo"):
            titulo.hide()

    def mostrar(self, nombre: str) -> QWidget:
        indice = self.nombres.index(nombre)
        self.pestanas.setCurrentIndex(indice)
        self._crear(indice)
        return self.creadas[nombre]


class VentanaPrincipal(QMainWindow):
    cambiar_tema = Signal()
    cerrar_sesion = Signal()

    def __init__(self, usuario: UsuarioSesion, api: ClienteApi | None = None):
        super().__init__()
        self.api, self.usuario = api, usuario
        self.setWindowTitle("ASI-ARCHIVO · Jefatura de Electromecánica")
        # Franja con el servidor conectado: evita trabajar en uno creyendo que es otro.
        self.franja_servidor = QLabel("", objectName="franja_servidor")
        self.franja_servidor.setAlignment(Qt.AlignCenter)
        self.franja_servidor.setAttribute(Qt.WA_StyledBackground)
        self.franja_servidor.setAccessibleName("Servidor conectado")
        self.servidor = None
        if api is not None:
            self.servidor = describir_servidor(api.url, api.identidad())
            self.franja_servidor.setText(self.servidor.texto)
            self.franja_servidor.setProperty("tipo", self.servidor.tipo)
            self.franja_servidor.setToolTip(
                f"Esta ventana trabaja con {api.url}. Lo que guardes queda en ese servidor."
            )
            self.setWindowTitle(f"ASI-ARCHIVO · {self.servidor.titulo} · {self.servidor.direccion}")
        else:
            self.franja_servidor.hide()
        self.resize(1280, 800)
        self.setMinimumSize(960, 620)
        self.compacto = False

        # Pantallas permitidas y secciones que las contienen.
        self.secciones = secciones_visibles(usuario)
        permitidas = {s[0] for s in self.secciones}
        grupos = [
            (titulo, nombre_icono, descripcion, [p for p in pantallas if p[0] in permitidas])
            for titulo, nombre_icono, descripcion, pantallas in GRUPOS
        ]
        self.grupos = [g for g in grupos if g[3]]
        self.vistas_grupo: dict[int, Seccion] = {}

        # --- menú lateral ---
        self.lateral = QWidget(objectName="lateral")
        self.lateral.setFixedWidth(232)
        caja_lateral = QVBoxLayout(self.lateral)
        caja_lateral.setContentsMargins(0, 18, 0, 14)
        caja_lateral.setSpacing(4)
        self.marca = QLabel("ASI-ARCHIVO", objectName="marca")
        self.marca_sub = QLabel("Jefatura de Electromecánica", objectName="marca_sub")
        for etiqueta in (self.marca, self.marca_sub):
            etiqueta.setContentsMargins(22, 0, 12, 0)
        caja_lateral.addWidget(self.marca)
        caja_lateral.addWidget(self.marca_sub)
        caja_lateral.addSpacing(16)

        self.menu = QListWidget(objectName="menu")
        self.menu.setIconSize(QSize(22, 22))
        self.menu.setAccessibleName("Menú principal")
        self.menu.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.menu.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.paginas = QStackedWidget()
        for i, (titulo, nombre_icono, descripcion, _p) in enumerate(self.grupos):
            item = QListWidgetItem(icono(nombre_icono, "#d5deeb"), titulo)
            atajo = f"Ctrl+{i + 1}"
            item.setToolTip(f"{descripcion} ({atajo})")
            item.setData(Qt.UserRole, titulo)
            self.menu.addItem(item)
            self.paginas.addWidget(QWidget())
            QShortcut(QKeySequence(atajo), self, activated=lambda i=i: self.menu.setCurrentRow(i))
        self.menu.currentRowChanged.connect(self.abrir)
        caja_lateral.addWidget(self.menu, 1)

        self.usuario_lateral = QLabel(
            f"{usuario.nombre}\n{nombre_rol(usuario)}", objectName="usuario_lateral"
        )
        self.usuario_lateral.setContentsMargins(22, 0, 12, 6)
        self.boton_tema = QPushButton(icono("tema", "#d5deeb", 18), "  Cambiar tema")
        self.boton_salir = QPushButton(icono("salir", "#d5deeb", 18), "  Cerrar sesión")
        self.boton_tema.setToolTip("Alternar entre tema claro y oscuro")
        self.boton_salir.setToolTip("Salir de tu cuenta en esta computadora")
        self.boton_tema.clicked.connect(self.cambiar_tema)
        self.boton_salir.clicked.connect(self.pedir_cerrar_sesion)
        caja_lateral.addWidget(self.usuario_lateral)
        for b in (self.boton_tema, self.boton_salir):
            fila = QHBoxLayout()
            fila.setContentsMargins(12, 2, 12, 0)
            fila.addWidget(b)
            caja_lateral.addLayout(fila)

        # --- barra superior ---
        barra = QWidget(objectName="barra_superior")
        barra.setAttribute(Qt.WA_StyledBackground)
        caja_barra = QHBoxLayout(barra)
        caja_barra.setContentsMargins(28, 14, 28, 14)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        self.titulo_seccion = QLabel("", objectName="titulo_seccion")
        self.descripcion_seccion = QLabel("", objectName="subtitulo")
        textos.addWidget(self.titulo_seccion)
        textos.addWidget(self.descripcion_seccion)
        caja_barra.addLayout(textos, 1)
        self.fecha_hoy = QLabel(fecha_larga(date.today()), objectName="suave")
        self.periodo = QLabel("", objectName="chip_periodo")
        self.periodo.setAccessibleName("Periodo académico activo")
        self.boton_periodo = QPushButton("Cambiar periodo")
        self.boton_periodo.setToolTip("Cerrar el periodo actual y activar otro")
        self.boton_periodo.setVisible(usuario.puede("periodos.gestionar"))
        self.boton_periodo.clicked.connect(self.cambiar_periodo)
        for w in (self.fecha_hoy, self.periodo, self.boton_periodo):
            caja_barra.addWidget(w)

        derecha = QWidget()
        caja_derecha = QVBoxLayout(derecha)
        caja_derecha.setContentsMargins(0, 0, 0, 0)
        caja_derecha.setSpacing(0)
        caja_derecha.addWidget(barra)
        caja_derecha.addWidget(self.paginas, 1)

        cuerpo = QWidget()
        caja = QHBoxLayout(cuerpo)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(0)
        caja.addWidget(self.lateral)
        caja.addWidget(derecha, 1)
        central = QWidget()
        caja_central = QVBoxLayout(central)
        caja_central.setContentsMargins(0, 0, 0, 0)
        caja_central.setSpacing(0)
        caja_central.addWidget(self.franja_servidor)
        caja_central.addWidget(cuerpo, 1)
        self.setCentralWidget(central)

        self.actualizar_periodo()
        self.menu.setCurrentRow(0)
        self.menu.setFocus()

    # --- cambios sin guardar ------------------------------------------------------

    def cambios_sin_guardar(self) -> list[str]:
        """Pantallas abiertas con cambios que aún no se guardan en el servidor."""
        nombres = {
            "VistaImportacion": "Importar horarios: revisión de una página",
            "VistaHorarios": "Horarios: borrador en edición",
        }
        return sorted(
            {
                nombres.get(type(w).__name__, type(w).__name__)
                for w in self.findChildren(QWidget)
                if getattr(w, "cambios_pendientes", False) is True
            }
        )

    def puede_cerrar(self, accion: str) -> bool:
        cambios = self.cambios_sin_guardar()
        if not cambios:
            return True
        return confirmar_salida(self, accion, cambios)

    def pedir_cerrar_sesion(self) -> None:
        if self.puede_cerrar("cerrar sesión"):
            self.cerrar_sesion.emit()

    def closeEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        if self.puede_cerrar("cerrar la ventana"):
            evento.accept()
        else:
            evento.ignore()

    # --- navegación ---------------------------------------------------------------

    def abrir(self, indice: int) -> None:
        """Muestra una sección; la primera vez crea su contenido."""
        if indice < 0:
            return
        titulo, _icono, descripcion, pantallas = self.grupos[indice]
        if indice not in self.vistas_grupo and self.api is not None:
            vista = Seccion(self, pantallas)
            anterior = self.paginas.widget(indice)
            self.paginas.removeWidget(anterior)
            anterior.deleteLater()
            self.paginas.insertWidget(indice, vista)
            self.vistas_grupo[indice] = vista
        self.paginas.setCurrentIndex(indice)
        self.titulo_seccion.setText(titulo)
        self.descripcion_seccion.setText(descripcion)

    def abrir_grupo(self, titulo: str) -> Seccion:
        indice = next(i for i, g in enumerate(self.grupos) if g[0] == titulo)
        self.menu.setCurrentRow(indice)
        self.abrir(indice)
        return self.vistas_grupo[indice]

    def abrir_seccion(self, titulo: str) -> QWidget:
        """Abre una pantalla por su nombre (y la sección que la contiene)."""
        titulo = ALIAS.get(titulo, titulo)
        for i, (_t, _i, _d, pantallas) in enumerate(self.grupos):
            if titulo in [p for p, _ in pantallas]:
                self.menu.setCurrentRow(i)
                self.abrir(i)
                return self.vistas_grupo[i].mostrar(titulo)
        raise StopIteration(f"Sin acceso a {titulo}")

    # --- periodo y tamaño ---------------------------------------------------------

    def actualizar_periodo(self) -> None:
        if self.api is None:
            return
        try:
            activo = self.api.get("/periodos/activo")
        except ErrorApi:
            self.periodo.setText("Periodo: sin conexión")
            return
        if activo:
            self.periodo.setObjectName("chip_periodo")
            self.periodo.setText(f"Periodo: {activo['nombre']}")
            self.periodo.setToolTip(
                f"Del {activo['fecha_inicio']} al {activo['fecha_fin']}. "
                "Los horarios y la asistencia se registran en este periodo."
            )
        else:
            self.periodo.setObjectName("chip_alerta")
            self.periodo.setText("Sin periodo activo")
            self.periodo.setToolTip("Crea y activa un periodo en Administración › Periodos.")
        self.periodo.style().unpolish(self.periodo)
        self.periodo.style().polish(self.periodo)

    def cambiar_periodo(self) -> None:
        if cambiar_periodo_activo(self, self.api):
            self.actualizar_periodo()
            for seccion in self.vistas_grupo.values():
                for vista in seccion.creadas.values():
                    if hasattr(vista, "recargar"):
                        vista.recargar()

    def resizeEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().resizeEvent(evento)
        self.ajustar_menu(self.width() < ANCHO_COMPACTO)

    def ajustar_menu(self, compacto: bool) -> None:
        """En ventanas angostas el menú muestra solo iconos (el nombre queda en la ayuda)."""
        if compacto == self.compacto:
            return
        self.compacto = compacto
        self.lateral.setFixedWidth(76 if compacto else 232)
        self.marca.setText("ASI" if compacto else "ASI-ARCHIVO")
        self.marca_sub.setVisible(not compacto)
        self.usuario_lateral.setVisible(not compacto)
        self.fecha_hoy.setVisible(not compacto)
        for i in range(self.menu.count()):
            item = self.menu.item(i)
            item.setText("" if compacto else item.data(Qt.UserRole))
        self.boton_tema.setText("" if compacto else "  Cambiar tema")
        self.boton_salir.setText("" if compacto else "  Cerrar sesión")
