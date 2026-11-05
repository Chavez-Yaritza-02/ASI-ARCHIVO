"""Gestión de horarios: un solo lugar para los horarios de cada semestre.

Reúne las pantallas que ya existían (sin duplicar su lógica):
- Horarios: versiones por docente y periodo, edición manual e historial.
- Importar y revisar: PDF o ZIP con OCR, revisión editable página por página.
- Periodos: crear periodos (Agosto–Diciembre, Enero–Junio...), activar y cerrar.
- Registro de cambios: quién cambió qué horario y cuándo (solo lectura).

Arriba siempre se ve el periodo activo. Solo el administrador ve "Importar horarios"
y "Cambiar periodo activo"; el rol de consulta solo visualiza.
"""

from datetime import date, datetime

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.views.comunes import Columna, Tabla, confirmar, encabezado, mostrar_error
from asi_cliente.views.horarios import VistaHorarios
from asi_cliente.views.importacion import VistaImportacion
from asi_cliente.views.periodos import VistaPeriodos


def _fecha(texto: str) -> str:
    return date.fromisoformat(texto).strftime("%d/%m/%Y")


def _fecha_hora(texto: str) -> str:
    return datetime.fromisoformat(texto).astimezone().strftime("%d/%m/%Y %H:%M")


class VistaCambios(QWidget):
    """Registro de cambios de los horarios de un periodo (de la auditoría del servidor)."""

    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api = api
        self.periodo = QComboBox()
        self.periodo.setMinimumWidth(260)
        self.boton_actualizar = QPushButton("Actualizar")
        self.tabla = Tabla(
            [
                Columna("Fecha", lambda c: _fecha_hora(c["fecha"])),
                Columna("Usuario", lambda c: c["usuario"]),
                Columna("Docente", lambda c: c["docente"]),
                Columna("Versión", lambda c: c["version"]),
                Columna("Cambio", lambda c: c["accion"]),
                Columna("Detalle", lambda c: c["detalle"]),
            ]
        )
        barra = QHBoxLayout()
        barra.addWidget(QLabel("Periodo"))
        barra.addWidget(self.periodo)
        barra.addStretch()
        barra.addWidget(self.boton_actualizar)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 12, 0, 0)
        capa.addWidget(
            QLabel(
                "Cada creación, edición, confirmación o paso al historial queda registrado. "
                "Los horarios anteriores nunca se sobrescriben.",
                objectName="suave",
                wordWrap=True,
            )
        )
        capa.addLayout(barra)
        capa.addWidget(self.tabla, 1)
        self.periodo.activated.connect(lambda *_: self.cargar())
        self.boton_actualizar.clicked.connect(self.recargar)
        self.recargar()

    def recargar(self) -> None:
        elegido = self.periodo.currentData()
        try:
            periodos = self.api.get("/periodos")
        except ErrorApi as error:
            mostrar_error(self, error, "No se pudieron cargar los periodos")
            return
        self.periodo.clear()
        for p in periodos:
            self.periodo.addItem(f"{p['nombre']} ({p['estado']})", p["id"])
        indice = self.periodo.findData(elegido) if elegido else -1
        if indice < 0:
            indice = next((i for i, p in enumerate(periodos) if p["estado"] == "activo"), 0)
        self.periodo.setCurrentIndex(indice)
        self.cargar()

    def cargar(self) -> None:
        periodo_id = self.periodo.currentData()
        if periodo_id is None:
            self.tabla.cargar([])
            return
        try:
            self.tabla.cargar(self.api.get("/horarios/cambios", periodo_id=periodo_id))
        except ErrorApi as error:
            mostrar_error(self, error, "No se pudo cargar el registro de cambios")


class DialogoCambiarPeriodo(QDialog):
    """Elige el periodo que pasará a ser el activo (solo periodos en borrador)."""

    def __init__(self, actual: dict | None, candidatos: list[dict], padre=None):
        super().__init__(padre)
        self.setWindowTitle("Cambiar periodo activo")
        self.combo = QComboBox()
        for p in candidatos:
            self.combo.addItem(
                f"{p['nombre']} ({_fecha(p['fecha_inicio'])} – {_fecha(p['fecha_fin'])})", p
            )
        texto = (
            f"Periodo activo: {actual['nombre']}.\n\nAl cambiar, ese periodo se CIERRA: sus "
            "horarios, asistencias y reportes se conservan como historial de solo lectura."
            if actual
            else "No hay periodo activo."
        )
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Activar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel(texto, wordWrap=True))
        capa.addWidget(QLabel("Nuevo periodo activo"))
        capa.addWidget(self.combo)
        capa.addWidget(botones)

    def elegido(self) -> dict | None:
        return self.combo.currentData()


class VistaGestionHorarios(QWidget):
    PESTANAS = ("Horarios", "Importar y revisar", "Periodos", "Registro de cambios")

    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api, self.usuario = api, usuario
        self.puede_importar = usuario.puede("horarios.editar")
        self.puede_periodos = usuario.puede("periodos.gestionar")
        self.activo: dict | None = None

        self.periodo_activo = QLabel("", objectName="estado")
        self.boton_importar = QPushButton("Importar horarios", objectName="primario")
        self.boton_importar.setToolTip(
            "Elegir un PDF o ZIP de horarios y revisarlo antes de guardar"
        )
        self.boton_cambiar = QPushButton("Cambiar periodo activo…")
        self.boton_importar.setVisible(self.puede_importar)
        self.boton_cambiar.setVisible(self.puede_periodos)
        barra = QHBoxLayout()
        barra.addWidget(self.periodo_activo, 1)
        barra.addWidget(self.boton_cambiar)
        barra.addWidget(self.boton_importar)

        # Las pantallas ya existentes, sin cambios en su lógica.
        self.horarios = VistaHorarios(api, usuario)
        self.importacion = VistaImportacion(api, usuario) if self.puede_importar else None
        self.periodos = VistaPeriodos(api, usuario)
        self.cambios = VistaCambios(api, usuario)
        self.pestanas = QTabWidget()
        for titulo, vista in zip(
            self.PESTANAS,
            (self.horarios, self.importacion, self.periodos, self.cambios),
            strict=True,
        ):
            if vista is not None:
                # Cada pantalla trae su propio margen; dentro de la pestaña sobra.
                vista.layout().setContentsMargins(0, 12, 0, 0)
                self.pestanas.addTab(vista, titulo)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 28, 32, 28)
        capa.addWidget(
            encabezado(
                "Gestión de horarios",
                "Cada semestre tiene su propio periodo. Los horarios de semestres anteriores se "
                "conservan para consulta y la asistencia usa solo los del periodo de cada fecha.",
            )
        )
        capa.addLayout(barra)
        capa.addWidget(self.pestanas, 1)

        self.boton_importar.clicked.connect(self.importar)
        self.boton_cambiar.clicked.connect(self.cambiar_periodo)
        self.pestanas.currentChanged.connect(lambda *_: self.actualizar_periodo())
        self.actualizar_periodo()

    def mostrar(self, titulo: str) -> QWidget | None:
        """Cambia a la pestaña indicada y devuelve su pantalla."""
        for i in range(self.pestanas.count()):
            if self.pestanas.tabText(i) == titulo:
                self.pestanas.setCurrentIndex(i)
                return self.pestanas.widget(i)
        return None

    def actualizar_periodo(self) -> None:
        try:
            self.activo = self.api.get("/periodos/activo")
        except ErrorApi:
            self.periodo_activo.setText("No se pudo consultar el periodo activo")
            return
        if self.activo:
            self.periodo_activo.setText(
                f"Periodo activo: {self.activo['nombre']}  ·  "
                f"{_fecha(self.activo['fecha_inicio'])} – {_fecha(self.activo['fecha_fin'])}"
            )
        else:
            self.periodo_activo.setText(
                "Sin periodo activo: crea uno en la pestaña Periodos y actívalo."
            )

    def importar(self) -> None:
        """Botón permanente: abre el selector de PDF o ZIP en la pestaña de importación."""
        vista = self.mostrar("Importar y revisar")
        if vista is not None:
            vista.importar()

    def cambiar_periodo(self) -> None:
        try:
            periodos = self.api.get("/periodos")
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        candidatos = [p for p in periodos if p["estado"] == "borrador"]
        if not candidatos:
            mostrar_error(
                self,
                ErrorApi(
                    "No hay periodos nuevos para activar",
                    ["Crea primero el periodo (por ejemplo ENERO - JUNIO 2027) con Nuevo periodo."],
                ),
            )
            self.mostrar("Periodos")
            return
        actual = next((p for p in periodos if p["estado"] == "activo"), None)
        dialogo = DialogoCambiarPeriodo(actual, candidatos, self)
        if not dialogo.exec():
            return
        nuevo = dialogo.elegido()
        if actual and not confirmar(
            self,
            f"¿Cerrar {actual['nombre']} y activar {nuevo['nombre']}?",
            "El periodo cerrado ya no se podrá editar desde la aplicación; sus horarios y "
            "asistencias se conservan para consultas y reportes.",
        ):
            return
        try:
            if actual:
                self.api.post(f"/periodos/{actual['id']}/cerrar")
            self.api.post(f"/periodos/{nuevo['id']}/activar")
        except ErrorApi as error:
            mostrar_error(self, error)
        self.recargar()

    def recargar(self) -> None:
        self.actualizar_periodo()
        for vista in (self.horarios, self.importacion, self.periodos, self.cambios):
            if vista is not None:
                vista.recargar()
