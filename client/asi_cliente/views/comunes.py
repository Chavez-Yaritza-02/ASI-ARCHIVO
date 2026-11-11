"""Componentes reutilizables de la interfaz: tabla, formulario y mensajes."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ErrorApi

# Colores de estado, legibles en tema claro y oscuro.
COLORES_ESTADO = {
    "vigente": "#16a34a",
    "activo": "#16a34a",
    "borrador": "#d97706",
    "historico": "#6b7280",
    "cerrado": "#6b7280",
    "descartado": "#b91c1c",
    "inactivo": "#b91c1c",
}
NOMBRES_ESTADO = {
    "vigente": "Vigente",
    "activo": "Activo",
    "borrador": "Borrador",
    "historico": "Histórico",
    "cerrado": "Cerrado",
    "descartado": "Descartado",
}


def mostrar_error(padre: QWidget | None, error: ErrorApi, titulo: str = "No se pudo completar"):
    caja = QMessageBox(padre)
    caja.setIcon(QMessageBox.Warning)
    caja.setWindowTitle(titulo)
    caja.setText(str(error))
    if error.problemas:
        caja.setInformativeText("\n".join(f"• {p}" for p in error.problemas))
    caja.exec()


def confirmar(padre: QWidget | None, pregunta: str, detalle: str = "") -> bool:
    caja = QMessageBox(padre)
    caja.setIcon(QMessageBox.Question)
    caja.setWindowTitle("Confirmar")
    caja.setText(pregunta)
    if detalle:
        caja.setInformativeText(detalle)
    caja.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    caja.setDefaultButton(QMessageBox.No)
    return caja.exec() == QMessageBox.Yes


def encabezado(titulo: str, subtitulo: str = "") -> QWidget:
    caja = QWidget()
    capa = QVBoxLayout(caja)
    capa.setContentsMargins(0, 0, 0, 8)
    capa.addWidget(QLabel(titulo, objectName="titulo"))
    if subtitulo:
        capa.addWidget(QLabel(subtitulo, objectName="subtitulo", wordWrap=True))
    return caja


@dataclass
class Columna:
    titulo: str
    valor: Callable[[dict], object]
    estado: bool = False  # colorea el texto según COLORES_ESTADO


class Tabla(QTableWidget):
    """Tabla de solo lectura que recuerda el registro (dict) de cada fila."""

    def __init__(self, columnas: list[Columna]):
        super().__init__(0, len(columnas))
        self.columnas = columnas
        self.filas: list[dict] = []
        self.setHorizontalHeaderLabels([c.titulo for c in columnas])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def cargar(self, filas: list[dict]) -> None:
        self.filas = filas
        self.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            for j, col in enumerate(self.columnas):
                valor = col.valor(fila)
                texto = NOMBRES_ESTADO.get(str(valor), str(valor)) if col.estado else valor
                item = QTableWidgetItem("" if texto is None else str(texto))
                if col.estado and str(valor) in COLORES_ESTADO:
                    item.setForeground(QColor(COLORES_ESTADO[str(valor)]))
                self.setItem(i, j, item)

    def seleccionado(self) -> dict | None:
        filas = self.selectionModel().selectedRows()
        return self.filas[filas[0].row()] if filas else None

    def seleccionar_id(self, id_: int) -> None:
        for i, fila in enumerate(self.filas):
            if fila.get("id") == id_:
                self.selectRow(i)
                return


@dataclass
class Campo:
    clave: str
    etiqueta: str
    tipo: str = "texto"  # texto | fecha | opciones
    opciones: list[tuple[str, object]] = field(default_factory=list)  # (texto, valor)
    obligatorio: bool = False


class DialogoFormulario(QDialog):
    """Formulario sencillo generado a partir de una lista de campos."""

    def __init__(self, titulo: str, campos: list[Campo], valores: dict | None = None, padre=None):
        super().__init__(padre)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(420)
        self.campos = campos
        self.controles: dict[str, QWidget] = {}
        valores = valores or {}
        formulario = QFormLayout()
        for campo in campos:
            control = self._crear_control(campo, valores.get(campo.clave))
            self.controles[campo.clave] = control
            etiqueta = campo.etiqueta + (" *" if campo.obligatorio else "")
            formulario.addRow(etiqueta, control)
        self.mensaje = QLabel("", objectName="error", wordWrap=True)
        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Save).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        capa.addLayout(formulario)
        capa.addWidget(self.mensaje)
        capa.addWidget(botones)

    @staticmethod
    def _crear_control(campo: Campo, valor) -> QWidget:
        if campo.tipo == "fecha":
            control = QDateEdit(calendarPopup=True)
            control.setDisplayFormat("dd/MM/yyyy")
            d = date.fromisoformat(valor) if isinstance(valor, str) else (valor or date.today())
            control.setDate(QDate(d.year, d.month, d.day))
            return control
        if campo.tipo == "opciones":
            control = QComboBox()
            for texto, dato in campo.opciones:
                control.addItem(texto, dato)
            if valor is not None:
                control.setCurrentIndex(max(control.findData(valor), 0))
            return control
        return QLineEdit("" if valor is None else str(valor))

    def valores(self) -> dict:
        datos = {}
        for campo in self.campos:
            control = self.controles[campo.clave]
            if isinstance(control, QDateEdit):
                datos[campo.clave] = control.date().toPython().isoformat()
            elif isinstance(control, QComboBox):
                datos[campo.clave] = control.currentData()
            else:
                texto = control.text().strip()
                datos[campo.clave] = texto or None
        return datos

    def _aceptar(self) -> None:
        faltan = [c.etiqueta for c in self.campos if c.obligatorio and not self.valores()[c.clave]]
        if faltan:
            self.mensaje.setText("Completa: " + ", ".join(faltan))
            return
        self.accept()


def alinear_centro(item: QTableWidgetItem) -> QTableWidgetItem:
    item.setTextAlignment(Qt.AlignCenter)
    return item
