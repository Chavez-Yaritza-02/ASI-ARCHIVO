"""Pantallas de docentes y catálogos (asignaturas, grupos, aulas).

Las cuatro funcionan igual: buscar, ver activos/inactivos, crear, editar,
activar y desactivar. Cada una se define con una `ConfigCatalogo`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.views.comunes import (
    Campo,
    Columna,
    DialogoFormulario,
    Tabla,
    confirmar,
    encabezado,
    mostrar_error,
)


@dataclass
class ConfigCatalogo:
    ruta: str
    singular: str  # "docente"
    permiso_editar: str
    columnas: list[Columna]
    campos: list[Campo]
    descripcion: str = ""
    nuevo: str = ""  # texto del botón, p. ej. "Nueva asignatura"
    # Datos auxiliares que se cargan de la API (p. ej. periodos para los grupos).
    cargar_contexto: Callable[[ClienteApi, dict], None] | None = None
    contexto: dict = field(default_factory=dict)
    # Campos cuyas opciones dependen del contexto: clave -> función(contexto) -> opciones.
    opciones: dict[str, Callable[[dict], list]] = field(default_factory=dict)


DOCENTES = ConfigCatalogo(
    ruta="/docentes",
    singular="docente",
    nuevo="Nuevo docente",
    permiso_editar="docentes.editar",
    descripcion="Personal docente de la Jefatura. Los docentes no se borran: se desactivan.",
    columnas=[
        Columna("Nombre", lambda d: d["nombre"]),
        Columna("Nómina", lambda d: d["nomina"] or ""),
        Columna("Correo", lambda d: d["correo"] or ""),
        Columna("Estado", lambda d: "Activo" if d["activo"] else "Inactivo"),
    ],
    campos=[
        Campo("nombre", "Nombre (apellidos y nombres)", obligatorio=True),
        Campo("nomina", "Nómina"),
        Campo("correo", "Correo"),
    ],
)

ASIGNATURAS = ConfigCatalogo(
    ruta="/asignaturas",
    singular="asignatura",
    nuevo="Nueva asignatura",
    permiso_editar="horarios.editar",
    columnas=[
        Columna("Nombre", lambda d: d["nombre"]),
        Columna("Tipo", lambda d: "Materia" if d["tipo"] == "materia" else "Actividad"),
        Columna("Estado", lambda d: "Activa" if d["activo"] else "Inactiva"),
    ],
    campos=[
        Campo("nombre", "Nombre", obligatorio=True),
        Campo(
            "tipo",
            "Tipo",
            "opciones",
            [("Materia (con grupo)", "materia"), ("Actividad (gestión, tutoría…)", "actividad")],
        ),
    ],
)


def _config_clave(ruta: str, singular: str, nuevo: str) -> ConfigCatalogo:
    return ConfigCatalogo(
        ruta=ruta,
        singular=singular,
        nuevo=nuevo,
        permiso_editar="horarios.editar",
        columnas=[
            Columna("Clave", lambda d: d["clave"]),
            Columna("Descripción", lambda d: d["descripcion"]),
            Columna("Estado", lambda d: "Activo" if d["activo"] else "Inactivo"),
        ],
        campos=[Campo("clave", "Clave", obligatorio=True), Campo("descripcion", "Descripción")],
    )


def _cargar_periodos(api: ClienteApi, contexto: dict) -> None:
    contexto["periodos"] = {p["id"]: p["nombre"] for p in api.get("/periodos")}


def _opciones_periodo(contexto: dict) -> list:
    return [("— (pendiente)", None)] + [(n, i) for i, n in contexto.get("periodos", {}).items()]


GRUPOS = ConfigCatalogo(
    ruta="/grupos",
    singular="grupo",
    nuevo="Nuevo grupo",
    permiso_editar="horarios.editar",
    descripcion="Un grupo se identifica por periodo, carrera, semestre y letra. "
    "Si falta alguno queda pendiente de validación.",
    cargar_contexto=_cargar_periodos,
    columnas=[],  # se definen abajo (usan el contexto)
    campos=[
        Campo("letra", "Letra", obligatorio=True),
        Campo("carrera", "Carrera (p. ej. IEM)"),
        Campo(
            "semestre", "Semestre", "opciones", [("—", None)] + [(f"{n}º", n) for n in range(1, 13)]
        ),
        Campo("periodo_id", "Periodo", "opciones"),
        Campo("descripcion", "Descripción"),
    ],
    opciones={"periodo_id": _opciones_periodo},
)
GRUPOS.columnas = [
    Columna("Grupo", lambda d: d["clave"]),
    Columna("Carrera", lambda d: d["carrera"] or "—"),
    Columna("Semestre", lambda d: f"{d['semestre']}º" if d["semestre"] else "—"),
    Columna("Periodo", lambda d: GRUPOS.contexto.get("periodos", {}).get(d["periodo_id"], "—")),
    Columna("Validación", lambda d: "Pendiente" if d["pendiente_validacion"] else "Completo"),
    Columna("Estado", lambda d: "Activo" if d["activo"] else "Inactivo"),
]
AULAS = _config_clave("/aulas", "aula", "Nueva aula")


class VistaCatalogo(QWidget):
    def __init__(
        self,
        api: ClienteApi,
        usuario: UsuarioSesion,
        config: ConfigCatalogo,
        titulo: str | None = None,
    ):
        super().__init__()
        self.api, self.config = api, config
        self.puede_editar = usuario.puede(config.permiso_editar)

        self.buscar = QLineEdit(placeholderText=f"Buscar {config.singular}…")
        self.buscar.setClearButtonEnabled(True)
        self.inactivos = QCheckBox("Mostrar inactivos")
        self.tabla = Tabla(config.columnas)
        self.boton_nuevo = QPushButton(
            config.nuevo or f"Nuevo {config.singular}", objectName="primario"
        )
        self.boton_editar = QPushButton("Editar")
        self.boton_estado = QPushButton("Desactivar")

        barra = QHBoxLayout()
        barra.addWidget(self.buscar, 1)
        barra.addWidget(self.inactivos)
        for boton in (self.boton_nuevo, self.boton_editar, self.boton_estado):
            boton.setVisible(self.puede_editar)
            barra.addWidget(boton)

        capa = QVBoxLayout(self)
        if titulo:
            capa.setContentsMargins(32, 28, 32, 28)
            capa.addWidget(encabezado(titulo, config.descripcion))
        capa.addLayout(barra)
        capa.addWidget(self.tabla, 1)

        self.buscar.textChanged.connect(self.recargar)
        self.inactivos.toggled.connect(self.recargar)
        self.boton_nuevo.clicked.connect(self.nuevo)
        self.boton_editar.clicked.connect(self.editar)
        self.boton_estado.clicked.connect(self.cambiar_estado)
        self.tabla.itemSelectionChanged.connect(self._actualizar_botones)
        if self.puede_editar:
            self.tabla.doubleClicked.connect(self.editar)
        self.recargar()

    def _campos(self) -> list[Campo]:
        """Campos del formulario, con las opciones que dependen de datos de la API."""
        return [
            replace(c, opciones=self.config.opciones[c.clave](self.config.contexto))
            if c.clave in self.config.opciones
            else c
            for c in self.config.campos
        ]

    def recargar(self) -> None:
        try:
            if self.config.cargar_contexto:
                self.config.cargar_contexto(self.api, self.config.contexto)
            filas = self.api.get(
                self.config.ruta,
                buscar=self.buscar.text().strip() or None,
                activo=None if self.inactivos.isChecked() else "true",
            )
        except ErrorApi as error:
            mostrar_error(self, error, "No se pudo cargar la información")
            return
        self.tabla.cargar(filas)
        self._actualizar_botones()

    def _actualizar_botones(self) -> None:
        fila = self.tabla.seleccionado()
        self.boton_editar.setEnabled(fila is not None)
        self.boton_estado.setEnabled(fila is not None)
        self.boton_estado.setText("Activar" if fila and not fila["activo"] else "Desactivar")

    def nuevo(self) -> None:
        dialogo = DialogoFormulario(self.boton_nuevo.text(), self._campos(), padre=self)
        while dialogo.exec():
            try:
                creado = self.api.post(self.config.ruta, _sin_vacios(dialogo.valores()))
            except ErrorApi as error:
                mostrar_error(self, error)
                continue
            self.recargar()
            self.tabla.seleccionar_id(creado["id"])
            return

    def editar(self) -> None:
        fila = self.tabla.seleccionado()
        if fila is None:
            return
        dialogo = DialogoFormulario(
            f"Editar {self.config.singular}", self._campos(), fila, padre=self
        )
        while dialogo.exec():
            try:
                self.api.patch(f"{self.config.ruta}/{fila['id']}", dialogo.valores())
            except ErrorApi as error:
                mostrar_error(self, error)
                continue
            self.recargar()
            self.tabla.seleccionar_id(fila["id"])
            return

    def cambiar_estado(self) -> None:
        fila = self.tabla.seleccionado()
        if fila is None:
            return
        accion = "desactivar" if fila["activo"] else "activar"
        nombre = fila.get("nombre") or fila.get("clave")
        detalle = (
            "Seguirá apareciendo en los horarios e historial anteriores, pero no podrá "
            "usarse en horarios nuevos."
            if accion == "desactivar"
            else ""
        )
        if not confirmar(self, f"¿{accion.capitalize()} {nombre}?", detalle):
            return
        try:
            self.api.post(f"{self.config.ruta}/{fila['id']}/{accion}")
        except ErrorApi as error:
            mostrar_error(self, error)
        self.recargar()
        self.tabla.seleccionar_id(fila["id"])


def _sin_vacios(datos: dict) -> dict:
    return {k: v for k, v in datos.items() if v is not None}


class VistaCatalogos(QWidget):
    """Asignaturas, grupos y aulas en pestañas."""

    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        pestanas = QTabWidget()
        self.vistas = {
            "Asignaturas": VistaCatalogo(api, usuario, ASIGNATURAS),
            "Grupos": VistaCatalogo(api, usuario, GRUPOS),
            "Aulas": VistaCatalogo(api, usuario, AULAS),
        }
        for nombre, vista in self.vistas.items():
            pestanas.addTab(vista, nombre)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 28, 32, 28)
        capa.addWidget(
            encabezado(
                "Catálogos",
                "Asignaturas, grupos y aulas que se usan al capturar horarios. "
                "Los registros no se borran: se desactivan.",
            )
        )
        capa.addWidget(pestanas, 1)
