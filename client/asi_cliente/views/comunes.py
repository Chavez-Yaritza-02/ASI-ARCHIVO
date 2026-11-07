"""Componentes reutilizables de la interfaz: tabla, formulario, filtros y mensajes.

Todas las pantallas los usan, así que las mejoras de uso (mensajes claros, búsqueda,
estados vacíos, ayuda en formularios) llegan a toda la aplicación a la vez.
"""

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
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
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


def explicar_error(error: ErrorApi) -> tuple[str, str]:
    """Mensaje principal y sugerencia, en lenguaje sencillo, para cualquier error."""
    texto = str(error)
    estado = getattr(error, "estado", 0)
    if texto.startswith("No se pudo conectar"):
        return (
            "No hay conexión con el servidor.",
            "Revisa que la computadora tenga red e inténtalo de nuevo. "
            "Si el problema continúa, avisa al administrador.",
        )
    if estado == 401:
        return ("Tu sesión terminó.", "Cierra sesión y vuelve a entrar con tu correo.")
    if estado == 403:
        return (
            "Tu usuario no tiene permiso para esta acción.",
            "Si la necesitas, pídela al administrador del sistema.",
        )
    if estado == 413:
        return ("El archivo es demasiado grande.", "Elige un archivo más pequeño.")
    if estado >= 500:
        return (
            "El servidor tuvo un problema al hacer esta operación.",
            "No se guardó nada. Intenta de nuevo en unos minutos; si continúa, avisa al "
            "administrador.",
        )
    if texto == "Datos inválidos":
        return ("Algunos datos no son válidos.", "Revisa lo siguiente:")
    return (texto, "")


def mostrar_error(padre: QWidget | None, error: ErrorApi, titulo: str = "No se pudo completar"):
    caja = QMessageBox(padre)
    caja.setIcon(QMessageBox.Warning)
    caja.setWindowTitle(titulo)
    principal, sugerencia = explicar_error(error)
    caja.setText(principal)
    detalle = [sugerencia] if sugerencia else []
    if error.problemas:
        detalle.append("\n".join(f"• {p}" for p in error.problemas))
    if detalle:
        caja.setInformativeText("\n\n".join(detalle))
    caja.setStandardButtons(QMessageBox.Ok)
    caja.button(QMessageBox.Ok).setText("Entendido")
    caja.exec()


def confirmar(
    padre: QWidget | None, pregunta: str, detalle: str = "", texto_si: str = "Sí, continuar"
) -> bool:
    """Pregunta antes de una acción importante. Por omisión queda marcado «Cancelar»."""
    caja = QMessageBox(padre)
    caja.setIcon(QMessageBox.Question)
    caja.setWindowTitle("Confirmar")
    caja.setText(pregunta)
    if detalle:
        caja.setInformativeText(detalle)
    caja.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    caja.button(QMessageBox.Yes).setText(texto_si)
    caja.button(QMessageBox.No).setText("Cancelar")
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
    """Tabla de solo lectura que recuerda el registro (dict) de cada fila.

    Si no hay filas (o la búsqueda no encuentra nada) muestra un mensaje que explica
    qué hacer, en lugar de un recuadro en blanco.
    """

    def __init__(self, columnas: list[Columna], mensaje_vacio: str = ""):
        super().__init__(0, len(columnas))
        self.columnas = columnas
        self.filas: list[dict] = []
        self.mensaje_vacio = mensaje_vacio or "No hay registros para mostrar."
        self.setHorizontalHeaderLabels([c.titulo for c in columnas])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(36)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.horizontalHeader().setHighlightSections(False)
        self.vacio = QLabel(self.mensaje_vacio, self.viewport(), objectName="vacio")
        self.vacio.setAlignment(Qt.AlignCenter)
        self.vacio.setWordWrap(True)
        self.vacio.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._texto_filtro = ""
        # Si la pantalla no define anchos propios, las columnas se ajustan al contenido.
        self.ajuste_automatico = True
        modelo = self.model()
        for senal in (modelo.rowsInserted, modelo.rowsRemoved, modelo.modelReset):
            senal.connect(self._actualizar_vacio)
        self._actualizar_vacio()

    def resizeEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().resizeEvent(evento)
        self.vacio.setGeometry(self.viewport().rect())

    def _actualizar_vacio(self, *_args) -> None:
        visibles = sum(1 for i in range(self.rowCount()) if not self.isRowHidden(i))
        if self.rowCount() and not visibles:
            self.vacio.setText(f"Ningún resultado contiene «{self._texto_filtro}».")
        else:
            self.vacio.setText(self.mensaje_vacio)
        self.vacio.setGeometry(self.viewport().rect())
        self.vacio.setVisible(visibles == 0)

    def filtrar(self, texto: str) -> int:
        """Oculta las filas que no contienen el texto (sin distinguir mayúsculas)."""
        self._texto_filtro = texto.strip()
        buscado = self._texto_filtro.casefold()
        visibles = 0
        for i in range(self.rowCount()):
            celdas = (self.item(i, j) for j in range(self.columnCount()))
            contenido = " ".join(c.text() for c in celdas if c).casefold()
            oculta = bool(buscado) and buscado not in contenido
            self.setRowHidden(i, oculta)
            visibles += not oculta
        self._actualizar_vacio()
        return visibles

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
        if self._texto_filtro:
            self.filtrar(self._texto_filtro)
        self._ajustar_columnas()
        self._actualizar_vacio()

    def _ajustar_columnas(self) -> None:
        """Columnas al ancho de su contenido (sin cortar nombres); la última llena el resto.

        Solo si la pantalla dejó el modo por omisión: si eligió anchos propios, se respetan.
        """
        cabecera = self.horizontalHeader()
        if not self.ajuste_automatico or not self.columnCount():
            return
        modos = {cabecera.sectionResizeMode(i) for i in range(self.columnCount())}
        if modos - {QHeaderView.Stretch, QHeaderView.ResizeToContents}:
            self.ajuste_automatico = False
            return
        if modos == {QHeaderView.ResizeToContents} or (
            modos == {QHeaderView.Stretch} and not cabecera.stretchLastSection()
        ):
            cabecera.setSectionResizeMode(QHeaderView.ResizeToContents)
            cabecera.setStretchLastSection(True)

    def seleccionado(self) -> dict | None:
        filas = self.selectionModel().selectedRows()
        return self.filas[filas[0].row()] if filas else None

    def seleccionar_id(self, id_: int) -> None:
        for i, fila in enumerate(self.filas):
            if fila.get("id") == id_:
                self.selectRow(i)
                return


def busqueda_para(tabla: Tabla, texto: str = "Buscar en la tabla…") -> QLineEdit:
    """Campo de búsqueda que filtra la tabla mientras se escribe."""
    campo = QLineEdit(placeholderText=texto)
    campo.setClearButtonEnabled(True)
    campo.setAccessibleName(texto)
    campo.textChanged.connect(tabla.filtrar)
    return campo


class Desplegable(QWidget):
    """Sección que se muestra u oculta (p. ej. «Más filtros»). Empieza cerrada."""

    def __init__(self, titulo: str, contenido: QWidget, abierto: bool = False):
        super().__init__()
        self.titulo = titulo
        self.boton = QToolButton(objectName="desplegable")
        self.boton.setCheckable(True)
        self.boton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.boton.setArrowType(Qt.RightArrow)
        self.contenido = contenido
        capa = QVBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(6)
        fila = QHBoxLayout()
        fila.addWidget(self.boton)
        fila.addStretch()
        capa.addLayout(fila)
        capa.addWidget(contenido)
        self.boton.toggled.connect(self.abrir)
        self.boton.setChecked(abierto)
        self.abrir(abierto)

    def abrir(self, abierto: bool) -> None:
        self.contenido.setVisible(abierto)
        self.boton.setArrowType(Qt.DownArrow if abierto else Qt.RightArrow)
        self.boton.setText(("Ocultar " if abierto else "Mostrar ") + self.titulo.lower())
        if self.boton.isChecked() != abierto:
            self.boton.setChecked(abierto)


@dataclass
class Campo:
    clave: str
    etiqueta: str
    tipo: str = "texto"  # texto | fecha | opciones
    opciones: list[tuple[str, object]] = field(default_factory=list)  # (texto, valor)
    obligatorio: bool = False
    ayuda: str = ""  # texto breve bajo el campo


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
        formulario.setVerticalSpacing(10)
        for campo in campos:
            control = self._crear_control(campo, valores.get(campo.clave))
            control.setAccessibleName(campo.etiqueta)
            self.controles[campo.clave] = control
            etiqueta = campo.etiqueta + (" *" if campo.obligatorio else "")
            if campo.ayuda:
                control.setToolTip(campo.ayuda)
                caja = QWidget()
                capa_campo = QVBoxLayout(caja)
                capa_campo.setContentsMargins(0, 0, 0, 0)
                capa_campo.setSpacing(2)
                capa_campo.addWidget(control)
                capa_campo.addWidget(QLabel(campo.ayuda, objectName="ayuda", wordWrap=True))
                formulario.addRow(etiqueta, caja)
            else:
                formulario.addRow(etiqueta, control)
        nota = QLabel("Los campos con * son obligatorios.", objectName="ayuda")
        nota.setVisible(any(c.obligatorio for c in campos))
        self.mensaje = QLabel("", objectName="error", wordWrap=True)
        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Save).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        capa.addLayout(formulario)
        capa.addWidget(nota)
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
            self.mensaje.setText("Falta completar: " + ", ".join(faltan))
            return
        self.accept()


def alinear_centro(item: QTableWidgetItem) -> QTableWidgetItem:
    item.setTextAlignment(Qt.AlignCenter)
    return item


def indicador(titulo: str, valor: str = "—", ayuda: str = "") -> tuple[QWidget, QLabel]:
    """Recuadro con una cifra grande y su descripción. Devuelve (recuadro, etiqueta_valor)."""
    caja = QFrame(objectName="indicador")
    caja.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    capa = QVBoxLayout(caja)
    capa.setContentsMargins(16, 12, 16, 12)
    numero = QLabel(valor, objectName="indicador_valor")
    capa.addWidget(numero)
    capa.addWidget(QLabel(titulo, objectName="indicador_titulo", wordWrap=True))
    if ayuda:
        caja.setToolTip(ayuda)
    return caja, numero
