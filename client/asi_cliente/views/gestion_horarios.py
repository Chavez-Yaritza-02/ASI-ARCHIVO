"""Registro de cambios de horarios y cambio de periodo activo.

- VistaCambios: quién cambió qué horario y cuándo (solo lectura, de la auditoría).
- cambiar_periodo_activo: cierra el periodo actual (queda como historial de solo
  lectura) y activa otro, con confirmación. Solo para quien gestiona periodos.
"""

from datetime import date, datetime

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.views.comunes import Columna, Tabla, busqueda_para, confirmar, mostrar_error


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
            ],
            "Este periodo todavía no tiene cambios de horarios registrados.",
        )
        self.buscar = busqueda_para(self.tabla, "Buscar por docente, usuario o cambio…")
        barra = QHBoxLayout()
        barra.addWidget(QLabel("Periodo"))
        barra.addWidget(self.periodo)
        barra.addWidget(self.buscar, 1)
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


def cambiar_periodo_activo(padre: QWidget, api: ClienteApi) -> bool:
    """Cierra el periodo activo (queda como historial) y activa otro. Pide confirmación."""
    try:
        periodos = api.get("/periodos")
    except ErrorApi as error:
        mostrar_error(padre, error)
        return False
    candidatos = [p for p in periodos if p["estado"] == "borrador"]
    if not candidatos:
        mostrar_error(
            padre,
            ErrorApi(
                "No hay periodos nuevos para activar",
                [
                    "Crea primero el periodo (por ejemplo ENERO - JUNIO 2027) en "
                    "Administración › Periodos, con el botón «Nuevo periodo»."
                ],
            ),
        )
        return False
    actual = next((p for p in periodos if p["estado"] == "activo"), None)
    dialogo = DialogoCambiarPeriodo(actual, candidatos, padre)
    if not dialogo.exec():
        return False
    nuevo = dialogo.elegido()
    if actual and not confirmar(
        padre,
        f"¿Cerrar {actual['nombre']} y activar {nuevo['nombre']}?",
        "El periodo cerrado ya no se podrá editar desde la aplicación; sus horarios y "
        "asistencias se conservan para consultas y reportes.",
        texto_si="Sí, cambiar de periodo",
    ):
        return False
    try:
        if actual:
            api.post(f"/periodos/{actual['id']}/cerrar")
        api.post(f"/periodos/{nuevo['id']}/activar")
    except ErrorApi as error:
        mostrar_error(padre, error)
    return True
