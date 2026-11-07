"""Reportes: un solo lugar para generar PDF y Excel, con filtros sencillos.

Usa exactamente los mismos servicios del servidor que las pantallas de asistencia,
bitácora y horarios por grupo (no calcula nada por su cuenta):
- Asistencia por hora de un día ........ /bitacora/horas/exportar
- Asistencia por hora de varios días ... /bitacora/horas/reporte
- Bitácora del día por turno ........... /bitacora/exportar
- Horario semanal de un grupo .......... /consultas/grupos/{id}/exportar
"""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.views.asistencia_hora import NOMBRES as ESTADOS_HORA
from asi_cliente.views.comunes import Desplegable, mostrar_error

# clave: (título, explicación, usa rango de fechas, nombre sugerido)
TIPOS = {
    "asistencia_dia": (
        "Asistencia por hora de un día",
        "Cada hora de clase del día con su estado: asistió, falta, retardo o justificada.",
        False,
        "asistencia_por_hora_{fecha}",
    ),
    "asistencia_rango": (
        "Asistencia por hora de varios días",
        "Resumen por docente de un rango de fechas (por ejemplo, una quincena o un mes).",
        True,
        "asistencia_{desde}_a_{hasta}",
    ),
    "bitacora": (
        "Bitácora del día por turno",
        "La bitácora tradicional: entrada y salida por docente y turno, con incidencias.",
        False,
        "bitacora_{fecha}",
    ),
    "grupo": (
        "Horario semanal de un grupo",
        "Todas las clases de un grupo en la semana de la fecha elegida.",
        False,
        "horario_grupo_{fecha}",
    ),
}


def _fecha_edit(valor: date | None = None) -> QDateEdit:
    d = valor or date.today()
    control = QDateEdit(QDate(d.year, d.month, d.day), calendarPopup=True)
    control.setDisplayFormat("dd/MM/yyyy")
    return control


class VistaReportes(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api, self.usuario = api, usuario
        self.ultimo: Path | None = None

        # --- 1. tipo de reporte ---
        self.tipos = QButtonGroup(self)
        panel_tipo = QFrame(objectName="panel")
        capa_tipo = QVBoxLayout(panel_tipo)
        capa_tipo.setContentsMargins(18, 14, 18, 14)
        capa_tipo.addWidget(QLabel("1. ¿Qué reporte necesitas?", objectName="estado"))
        self.opciones: dict[str, QRadioButton] = {}
        for clave, (titulo, explicacion, _r, _n) in TIPOS.items():
            if clave == "grupo" and not usuario.puede("horarios.ver"):
                continue
            opcion = QRadioButton(titulo)
            opcion.setToolTip(explicacion)
            self.tipos.addButton(opcion)
            self.opciones[clave] = opcion
            capa_tipo.addWidget(opcion)
            ayuda = QLabel(explicacion, objectName="ayuda", wordWrap=True)
            ayuda.setContentsMargins(26, 0, 0, 6)
            capa_tipo.addWidget(ayuda)
        capa_tipo.addStretch()
        self.opciones["asistencia_dia"].setChecked(True)

        # --- 2. datos del reporte ---
        self.fecha = _fecha_edit()
        self.desde = _fecha_edit(date.today().replace(day=1))
        self.hasta = _fecha_edit()
        self.grupo = QComboBox()
        self.grupo.setMinimumWidth(260)
        for control, nombre in (
            (self.fecha, "Fecha"),
            (self.desde, "Desde"),
            (self.hasta, "Hasta"),
            (self.grupo, "Grupo"),
        ):
            control.setAccessibleName(nombre)
        self.formulario = QFormLayout()
        self.formulario.setVerticalSpacing(10)
        self.formulario.setLabelAlignment(Qt.AlignLeft)
        self.formulario.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.formulario.addRow("Fecha", self.fecha)
        self.formulario.addRow("Desde", self.desde)
        self.formulario.addRow("Hasta", self.hasta)
        self.formulario.addRow("Grupo", self.grupo)

        # Filtros opcionales, ocultos para no saturar.
        self.docente = QComboBox()
        self.docente.addItem("Todos los docentes", None)
        self.turno = QComboBox()
        for texto, valor in (
            ("Ambos turnos", None),
            ("Matutino", "matutino"),
            ("Vespertino", "vespertino"),
        ):
            self.turno.addItem(texto, valor)
        self.tipo_actividad = QComboBox()
        for texto, valor in (
            ("Clases y actividades", None),
            ("Solo clases", "materia"),
            ("Otras actividades", "actividad"),
        ):
            self.tipo_actividad.addItem(texto, valor)
        self.estado = QComboBox()
        self.estado.addItem("Todos los estados", None)
        for clave, texto in ESTADOS_HORA.items():
            self.estado.addItem(texto, clave)
        filtros = QWidget()
        capa_filtros = QFormLayout(filtros)
        capa_filtros.setContentsMargins(0, 0, 0, 0)
        capa_filtros.addRow("Docente", self.docente)
        capa_filtros.addRow("Turno", self.turno)
        capa_filtros.addRow("Tipo", self.tipo_actividad)
        capa_filtros.addRow("Estado", self.estado)
        self.mas_filtros = Desplegable("Filtros opcionales", filtros)

        panel_datos = QFrame(objectName="panel")
        capa_datos = QVBoxLayout(panel_datos)
        capa_datos.setContentsMargins(18, 14, 18, 14)
        capa_datos.addWidget(QLabel("2. Elige las fechas", objectName="estado"))
        capa_datos.addLayout(self.formulario)
        capa_datos.addWidget(self.mas_filtros)

        # --- 3. formato y generar ---
        self.pdf = QRadioButton("PDF (para imprimir o enviar)")
        self.excel = QRadioButton("Excel (para revisar o calcular)")
        self.pdf.setChecked(True)
        formatos = QButtonGroup(self)
        formatos.addButton(self.pdf)
        formatos.addButton(self.excel)
        self.boton_generar = QPushButton("Generar reporte…", objectName="primario")
        self.boton_generar.setToolTip("Elegir dónde guardar el archivo y generarlo")
        self.resultado = QLabel("", objectName="exito", wordWrap=True)
        self.boton_abrir = QPushButton("Abrir el archivo")
        self.boton_abrir.hide()
        panel_formato = QFrame(objectName="panel")
        capa_formato = QVBoxLayout(panel_formato)
        capa_formato.setContentsMargins(18, 14, 18, 14)
        capa_formato.addWidget(QLabel("3. Formato", objectName="estado"))
        capa_formato.addWidget(self.pdf)
        capa_formato.addWidget(self.excel)
        fila = QHBoxLayout()
        fila.addWidget(self.boton_generar)
        fila.addWidget(self.boton_abrir)
        fila.addStretch()
        capa_formato.addLayout(fila)
        capa_formato.addWidget(self.resultado)

        derecha = QVBoxLayout()
        derecha.setSpacing(14)
        derecha.addWidget(panel_datos)
        derecha.addWidget(panel_formato)
        derecha.addStretch()
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(16)
        cuerpo.addWidget(panel_tipo, 1)
        cuerpo.addLayout(derecha, 1)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 24, 32, 24)
        capa.addWidget(
            QLabel(
                "Los reportes se generan con la información registrada en el servidor. "
                "Elige el tipo, las fechas y el formato.",
                objectName="subtitulo",
                wordWrap=True,
            )
        )
        capa.addSpacing(8)
        capa.addLayout(cuerpo, 1)

        self.tipos.buttonToggled.connect(lambda *_: self._ajustar())
        self.boton_generar.clicked.connect(self.generar)
        self.boton_abrir.clicked.connect(self.abrir_ultimo)
        self.recargar()
        self._ajustar()

    # --- datos ----------------------------------------------------------------------

    def recargar(self) -> None:
        try:
            docentes = self.api.get("/docentes", activo="true")
            grupos = self.api.get("/consultas/grupos") if "grupo" in self.opciones else []
        except ErrorApi as error:
            mostrar_error(self, error, "No se pudieron cargar los filtros")
            return
        actual = self.docente.currentData()
        self.docente.clear()
        self.docente.addItem("Todos los docentes", None)
        for d in docentes:
            self.docente.addItem(d["nombre"], d["id"])
        self.docente.setCurrentIndex(max(self.docente.findData(actual), 0))
        self.grupo.clear()
        for g in grupos:
            self.grupo.addItem(g["clave"], g["id"])
        if not grupos:
            self.grupo.addItem("(no hay grupos registrados)", None)

    def tipo(self) -> str:
        return next(clave for clave, opcion in self.opciones.items() if opcion.isChecked())

    def _ajustar(self) -> None:
        tipo = self.tipo()
        rango = TIPOS[tipo][2]
        for control, visible in (
            (self.fecha, not rango),
            (self.desde, rango),
            (self.hasta, rango),
            (self.grupo, tipo == "grupo"),
        ):
            self.formulario.setRowVisible(control, visible)
        self.mas_filtros.setVisible(tipo in ("asistencia_dia", "asistencia_rango", "bitacora"))
        for control in (self.docente, self.tipo_actividad, self.estado):
            control.setEnabled(tipo != "bitacora")

    def formato(self) -> str:
        return "pdf" if self.pdf.isChecked() else "xlsx"

    def solicitud(self) -> tuple[str, dict]:
        """Servicio y parámetros del reporte elegido. Lanza ErrorApi si falta algo."""
        tipo, formato = self.tipo(), self.formato()
        fecha = self.fecha.date().toPython().isoformat()
        filtros = {
            "docente_id": self.docente.currentData(),
            "turno": self.turno.currentData(),
            "tipo_actividad": self.tipo_actividad.currentData(),
            "estado": self.estado.currentData(),
        }
        if tipo == "asistencia_dia":
            return "/bitacora/horas/exportar", {**filtros, "fecha": fecha, "formato": formato}
        if tipo == "asistencia_rango":
            desde, hasta = self.desde.date().toPython(), self.hasta.date().toPython()
            if hasta < desde:
                raise ErrorApi(
                    "La fecha «Hasta» es anterior a «Desde»",
                    ["Corrige el rango: «Desde» debe ser el primer día del reporte."],
                )
            return "/bitacora/horas/reporte", {
                **filtros,
                "desde": desde.isoformat(),
                "hasta": hasta.isoformat(),
                "formato": formato,
            }
        if tipo == "bitacora":
            return "/bitacora/exportar", {
                "fecha": fecha,
                "formato": formato,
                "turno": filtros["turno"],
            }
        if self.grupo.currentData() is None:
            raise ErrorApi("Elige un grupo", ["No hay grupos registrados en el sistema."])
        return f"/consultas/grupos/{self.grupo.currentData()}/exportar", {
            "fecha": fecha,
            "formato": formato,
        }

    def nombre_sugerido(self) -> str:
        plantilla = TIPOS[self.tipo()][3]
        nombre = plantilla.format(
            fecha=self.fecha.date().toPython().isoformat(),
            desde=self.desde.date().toPython().isoformat(),
            hasta=self.hasta.date().toPython().isoformat(),
        )
        return f"{nombre}.{self.formato()}"

    # --- acciones -------------------------------------------------------------------

    def generar(self) -> None:
        try:
            self.solicitud()  # valida antes de preguntar dónde guardar
        except ErrorApi as error:
            mostrar_error(self, error, "Revisa los datos del reporte")
            return
        filtro = "PDF (*.pdf)" if self.formato() == "pdf" else "Excel (*.xlsx)"
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar reporte", str(Path.home() / self.nombre_sugerido()), filtro
        )
        if ruta:
            self.generar_a(Path(ruta))

    def generar_a(self, ruta: Path) -> bool:
        self.boton_abrir.hide()
        try:
            endpoint, params = self.solicitud()
            params = {k: v for k, v in params.items() if v is not None}
            ruta.write_bytes(self.api.descargar(endpoint, **params))
        except ErrorApi as error:
            self.resultado.setText("")
            mostrar_error(self, error, "No se pudo generar el reporte")
            return False
        except OSError as error:
            self.resultado.setText("")
            mostrar_error(
                self,
                ErrorApi(
                    "No se pudo guardar el archivo",
                    [f"Revisa que la carpeta exista y que el archivo no esté abierto. ({error})"],
                ),
            )
            return False
        self.ultimo = ruta
        self.resultado.setText(f"Reporte guardado en: {ruta}")
        self.boton_abrir.show()
        return True

    def abrir_ultimo(self) -> None:
        if self.ultimo is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ultimo)))
