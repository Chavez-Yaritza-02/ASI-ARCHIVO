"""Captura independiente por hora, parciales, historial y reportes."""

from pathlib import Path

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ErrorApi
from asi_cliente.views.asistencia_lote import DialogoCapturaLote
from asi_cliente.views.bitacora import DialogoHistorial
from asi_cliente.views.comunes import Columna, Tabla, encabezado, mostrar_error

NOMBRES = {
    "pendiente": "Pendiente de verificar",
    "inhabil": "Suspendida / inhábil",
    "asistio": "Asistió",
    "falto": "Falta",
    "retardo": "Retardo",
    "justificado": "Justificado",
    "parcial": "Parcial",
}


class DialogoAsistenciaHora(QDialog):
    """Formulario horario propio: los cambios de estado no disparan señales recursivas."""

    def __init__(self, fila, padre=None):
        super().__init__(padre)
        self.fila = fila
        self.es_correccion = fila["asistencia"] is not None
        self.setWindowTitle("Asistencia de esta hora de clase")
        self.resize(600, 500)
        self.estado = QComboBox()
        for clave in ("asistio", "falto", "retardo", "justificado", "parcial"):
            self.estado.addItem(NOMBRES[clave], clave)
        self.entrada = QTimeEdit(displayFormat="HH:mm")
        self.salida = QTimeEdit(displayFormat="HH:mm")
        self.usar_entrada = QCheckBox("Hora real de entrada")
        self.usar_salida = QCheckBox("Hora real de salida")
        self.minutos_justificados = QSpinBox()
        self.minutos_justificados.setRange(0, fila["minutos"]["programadas"])
        self.justificacion = QLineEdit()
        self.observaciones = QPlainTextEdit()
        self.observaciones.setFixedHeight(65)
        self.motivo = QLineEdit()
        self.autorizar = QCheckBox("Excepción autorizada en día inhábil o suspendido")
        self.autorizar.setVisible(not fila["dia_habil"] and not self.es_correccion)
        self.aviso = QLabel("", wordWrap=True)
        self.mensaje = QLabel("", objectName="error", wordWrap=True)
        registro = fila["asistencia"] or {}
        for control, clave, programado in (
            (self.entrada, "hora_entrada", "programado_inicio"),
            (self.salida, "hora_salida", "programado_fin"),
        ):
            control.setTime(
                QTime.fromString((registro.get(clave) or fila[programado])[:5], "HH:mm")
            )
        self.estado.setCurrentIndex(max(0, self.estado.findData(registro.get("estado", "asistio"))))
        self.observaciones.setPlainText(registro.get("observaciones", ""))
        self.justificacion.setText(registro.get("justificacion", ""))
        if registro.get("estado") == "parcial":
            self.minutos_justificados.setValue(registro["minutos_justificados"])
        self.usar_entrada.setChecked(bool(registro.get("hora_entrada")))
        self.usar_salida.setChecked(bool(registro.get("hora_salida")))
        formulario = QFormLayout()
        etiqueta = QLabel(
            f"{fila['docente_nombre']} · {fila['fecha']}\n"
            f"{fila['programado_inicio'][:5]}–{fila['programado_fin'][:5]} · "
            f"{fila['asignatura']}",
            wordWrap=True,
        )
        etiqueta.setTextFormat(Qt.PlainText)
        formulario.addRow("Estado", self.estado)
        formulario.addRow(self.usar_entrada, self.entrada)
        formulario.addRow(self.usar_salida, self.salida)
        formulario.addRow("Minutos justificados (parcial)", self.minutos_justificados)
        formulario.addRow("Justificación", self.justificacion)
        formulario.addRow("Observaciones", self.observaciones)
        if self.es_correccion:
            formulario.addRow("Motivo de la corrección", self.motivo)
        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Save).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        capa.addWidget(etiqueta)
        capa.addLayout(formulario)
        for w in (self.autorizar, self.aviso, self.mensaje, botones):
            capa.addWidget(w)
        self.estado.currentIndexChanged.connect(self._actualizar)
        self.usar_entrada.toggled.connect(self.entrada.setEnabled)
        self.usar_salida.toggled.connect(self.salida.setEnabled)
        self.entrada.timeChanged.connect(self._aviso_retardo)
        self._actualizar()

    def _actualizar(self, *_):
        estado = self.estado.currentData()
        parcial = estado == "parcial"
        for usar, control in ((self.usar_entrada, self.entrada), (self.usar_salida, self.salida)):
            usar.blockSignals(True)
            if estado in ("falto", "justificado"):
                usar.setChecked(False)
            elif parcial or estado == "retardo":
                usar.setChecked(True)
            usar.setEnabled(estado not in ("falto", "justificado"))
            control.setEnabled(usar.isChecked())
            usar.blockSignals(False)
        self.minutos_justificados.setEnabled(parcial)
        self.justificacion.setEnabled(parcial or estado == "justificado")
        self._aviso_retardo()

    def _aviso_retardo(self, *_):
        self.aviso.clear()
        inicio = QTime.fromString(self.fila["programado_inicio"][:5], "HH:mm")
        tarde = inicio.secsTo(self.entrada.time()) // 60
        if self.usar_entrada.isChecked() and tarde > self.fila["tolerancia_minutos"]:
            self.aviso.setText(
                f"Entrada {tarde} min después del inicio; "
                f"tolerancia {self.fila['tolerancia_minutos']} min."
            )

    def datos(self):
        estado = self.estado.currentData()
        datos = {
            "estado": estado,
            "hora_entrada": self.entrada.time().toString("HH:mm")
            if self.usar_entrada.isChecked()
            else None,
            "hora_salida": self.salida.time().toString("HH:mm")
            if self.usar_salida.isChecked()
            else None,
            "minutos_justificados": self.minutos_justificados.value() if estado == "parcial" else 0,
            "justificacion": self.justificacion.text().strip(),
            "observaciones": self.observaciones.toPlainText().strip(),
        }
        if self.es_correccion:
            datos["motivo"] = self.motivo.text().strip()
        elif not self.fila["dia_habil"]:
            datos["autorizar_dia_inhabil"] = self.autorizar.isChecked()
        return datos

    def _aceptar(self):
        if self.es_correccion and len(self.motivo.text().strip()) < 5:
            self.mensaje.setText("Escribe el motivo de la corrección.")
            return
        self.accept()


class VistaAsistenciaHora(QWidget):
    def __init__(self, api, usuario):
        super().__init__()
        self.api, self.usuario = api, usuario
        self.datos = None
        self.fecha = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.fecha.setDisplayFormat("dd/MM/yyyy")
        self.docente = QComboBox()
        self.docente.addItem("Todos los docentes", None)
        self.turno = QComboBox()
        for texto, valor in [
            ("Ambos turnos", None),
            ("Matutino", "matutino"),
            ("Vespertino", "vespertino"),
        ]:
            self.turno.addItem(texto, valor)
        self.tipo = QComboBox()
        for texto, valor in [
            ("Clases y actividades", None),
            ("Solo clases", "materia"),
            ("Otras actividades", "actividad"),
        ]:
            self.tipo.addItem(texto, valor)
        self.estado = QComboBox()
        self.estado.addItem("Todos los estados", None)
        for k, v in NOMBRES.items():
            self.estado.addItem(v, k)
        self.boton_consultar = QPushButton("Consultar horas")
        self.aviso = QLabel("", wordWrap=True)
        self.resumen = QLabel("", wordWrap=True)
        columnas = [
            Columna("Docente", lambda f: f["docente_nombre"]),
            Columna("Hora", lambda f: f"{f['programado_inicio'][:5]}–{f['programado_fin'][:5]}"),
            Columna("Materia / actividad", lambda f: f["asignatura"]),
            Columna("Grupo / aula", lambda f: " · ".join(x for x in (f["grupo"], f["aula"]) if x)),
            Columna("Estado", lambda f: NOMBRES[f["estado"]]),
            Columna("Cumplidos min", lambda f: f["minutos"]["cumplidas"]),
            Columna("Faltantes min", lambda f: f["minutos"]["faltantes"]),
            Columna("Justificados min", lambda f: f["minutos"]["justificadas"]),
        ]
        self.tabla = Tabla(columnas)
        self.tabla.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.historicos = Tabla(columnas)
        self.pestanas = QTabWidget()
        self.pestanas.addTab(self.tabla, "Programa vigente en la fecha")
        self.pestanas.addTab(self.historicos, "Capturas fuera del programa actual")
        self.boton_registrar = QPushButton("Registrar / corregir esta hora")
        self.boton_registrar.setVisible(usuario.puede("asistencia.registrar"))
        self.boton_lote = QPushButton("Registrar horas seleccionadas")
        self.boton_lote.setVisible(usuario.puede("asistencia.registrar"))
        self.boton_lote.clicked.connect(self.registrar_lote)
        self.boton_documentos = QPushButton("Documentos de esta hora")
        self.boton_documentos.setVisible(usuario.puede("documentos.ver"))
        self.boton_documentos.clicked.connect(self.abrir_documentos)
        self.boton_historial = QPushButton("Historial de esta hora")
        self.boton_pdf = QPushButton("PDF del día")
        self.boton_excel = QPushButton("Excel del día")
        self.desde = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.hasta = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.boton_pdf_rango = QPushButton("PDF del rango")
        self.boton_excel_rango = QPushButton("Excel del rango")
        for b in (self.boton_pdf, self.boton_excel, self.boton_pdf_rango, self.boton_excel_rango):
            b.setVisible(usuario.puede("reportes.generar"))
        capa = QVBoxLayout(self)
        capa.addWidget(
            encabezado(
                "Asistencia por hora de clase",
                "Cada fila se registra independientemente. "
                "Una captura por turno no acredita horas.",
            )
        )
        barra = QHBoxLayout()
        for w in (
            self.fecha,
            self.docente,
            self.turno,
            self.tipo,
            self.estado,
            self.boton_consultar,
        ):
            barra.addWidget(w)
        capa.addLayout(barra)
        capa.addWidget(self.aviso)
        capa.addWidget(self.resumen)
        capa.addWidget(self.pestanas, 1)
        acciones = QHBoxLayout()
        for b in (
            self.boton_registrar,
            self.boton_lote,
            self.boton_historial,
            self.boton_documentos,
            self.boton_pdf,
            self.boton_excel,
        ):
            acciones.addWidget(b)
        capa.addLayout(acciones)
        rango = QHBoxLayout()
        for w in (
            QLabel("Reporte desde"),
            self.desde,
            QLabel("hasta"),
            self.hasta,
            self.boton_pdf_rango,
            self.boton_excel_rango,
        ):
            rango.addWidget(w)
        capa.addLayout(rango)
        self.boton_consultar.clicked.connect(self.cargar)
        self.fecha.dateChanged.connect(self.cargar)
        self.boton_registrar.clicked.connect(self.registrar)
        self.boton_historial.clicked.connect(self.historial)
        self.boton_pdf.clicked.connect(lambda: self.exportar("pdf"))
        self.boton_excel.clicked.connect(lambda: self.exportar("xlsx"))
        self.boton_pdf_rango.clicked.connect(lambda: self.exportar("pdf", rango=True))
        self.boton_excel_rango.clicked.connect(lambda: self.exportar("xlsx", rango=True))
        for tabla in (self.tabla, self.historicos):
            tabla.itemSelectionChanged.connect(self.botones)
            tabla.cellDoubleClicked.connect(lambda *_: self.registrar())
        self.pestanas.currentChanged.connect(self.botones)
        for combo in (self.docente, self.turno, self.tipo, self.estado):
            combo.currentIndexChanged.connect(self.cargar)
        self.cargar()

    def filtros(self):
        return {
            "docente_id": self.docente.currentData(),
            "turno": self.turno.currentData(),
            "estado": self.estado.currentData(),
            "tipo_actividad": self.tipo.currentData(),
        }

    def seleccionada(self):
        return self.pestanas.currentWidget().seleccionado()

    def cargar(self, *_):
        self.datos = None
        self.tabla.cargar([])
        self.historicos.cargar([])
        self.resumen.clear()
        try:
            datos = self.api.get(
                "/bitacora/horas", fecha=self.fecha.date().toPython().isoformat(), **self.filtros()
            )
        except ErrorApi as e:
            self.aviso.setText("No se pudo consultar; no se muestra información anterior.")
            mostrar_error(self, e)
            self.botones()
            return
        self.datos = datos
        self.tabla.cargar(datos["filas"])
        self.historicos.cargar(datos["registros_fuera_de_programacion"])
        if self.docente.currentData() is None:
            self.docente.blockSignals(True)
            self.docente.clear()
            self.docente.addItem("Todos los docentes", None)
            nombres = {
                f["docente_id"]: f["docente_nombre"]
                for f in datos["filas"] + datos["registros_fuera_de_programacion"]
            }
            for id_, nombre in sorted(nombres.items(), key=lambda p: p[1]):
                self.docente.addItem(nombre, id_)
            self.docente.blockSignals(False)
        t = datos["totales"]
        self.resumen.setText(
            " · ".join(
                f"{k.capitalize()}: {t['horas'][k]:g} h ({t['minutos'][k]} min)"
                for k in t["minutos"]
            )
        )
        aviso = datos["aviso"]
        if datos.get("horarios_sin_vigencia_confirmada"):
            aviso += " Hay horarios de vigencia desconocida: no se pueden determinar sus horas."
        if datos["registros_por_turno_sin_convertir"]:
            aviso += (
                f" Hay {len(datos['registros_por_turno_sin_convertir'])} "
                "registros por turno sin convertir."
            )
        if any(f.get("bloqueada_por_registro_previo") for f in datos["filas"]):
            aviso += (
                " Hay horas bloqueadas por capturas anteriores que se traslapan; "
                "revisa el historial."
            )
        self.aviso.setText(aviso)
        self.botones()

    def botones(self, *_):
        f = self.seleccionada()
        self.boton_registrar.setEnabled(
            bool(
                f
                and self.usuario.puede("asistencia.registrar")
                and (f["asistencia"] or not f.get("bloqueada_por_registro_previo"))
            )
        )
        self.boton_historial.setEnabled(bool(f and f["asistencia"]))
        self.boton_documentos.setEnabled(bool(f and f["asistencia"]))
        self.boton_lote.setEnabled(
            self.pestanas.currentWidget() is self.tabla
            and bool(self.tabla.selectionModel().selectedRows())
        )
        for b in (self.boton_pdf, self.boton_excel):
            b.setEnabled(self.datos is not None)

    def registrar(self):
        f = self.seleccionada()
        if not f or not self.usuario.puede("asistencia.registrar"):
            return
        dialogo = DialogoAsistenciaHora(f, self)
        while dialogo.exec():
            datos = dialogo.datos()
            try:
                if f["asistencia"]:
                    self.api.patch(f"/asistencias/horas/{f['asistencia']['id']}", datos)
                else:
                    self.api.post(
                        "/asistencias/horas",
                        {
                            **datos,
                            "docente_id": f["docente_id"],
                            "fecha": f["fecha"],
                            "bloque_id": f["bloque_id"],
                            "programado_inicio": f["programado_inicio"],
                        },
                    )
            except ErrorApi as e:
                mostrar_error(self, e)
                continue
            self.cargar()
            break

    def registrar_lote(self):
        if (
            not self.usuario.puede("asistencia.registrar")
            or self.pestanas.currentWidget() is not self.tabla
        ):
            return
        filas = [self.tabla.filas[i.row()] for i in self.tabla.selectionModel().selectedRows()]
        if not filas:
            return
        if len(filas) > 100 or any(
            f["asistencia"] or f.get("bloqueada_por_registro_previo") for f in filas
        ):
            mostrar_error(
                self, ErrorApi("Selecciona hasta 100 horas pendientes sin capturas previas.")
            )
            return
        dialogo = DialogoCapturaLote(filas, self)
        while dialogo.exec():
            try:
                self.api.post("/asistencias/horas/lote", dialogo.datos())
            except ErrorApi as e:
                mostrar_error(self, e)
                continue
            self.cargar()
            break

    def abrir_documentos(self):
        f = self.seleccionada()
        if not f or not f["asistencia"] or not self.usuario.puede("documentos.ver"):
            return
        from asi_cliente.views.documentos import DialogoDocumentosHora

        DialogoDocumentosHora(self.api, self.usuario, f["asistencia"], self).exec()

    def historial(self):
        f = self.seleccionada()
        if not f or not f["asistencia"]:
            return
        try:
            cambios = self.api.get(f"/asistencias/horas/{f['asistencia']['id']}/historial")
        except ErrorApi as e:
            mostrar_error(self, e)
            return
        DialogoHistorial(cambios, self).exec()

    def exportar(self, formato, rango=False):
        ruta, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar asistencia horaria",
            f"asistencia_horas.{formato}",
            f"Archivo (*.{formato})",
        )
        if ruta:
            self.exportar_a(Path(ruta), formato, rango)

    def exportar_a(self, ruta, formato, rango=False):
        if not self.usuario.puede("reportes.generar"):
            return False
        params = {**self.filtros(), "formato": formato}
        if rango:
            params.update(
                desde=self.desde.date().toPython().isoformat(),
                hasta=self.hasta.date().toPython().isoformat(),
            )
            endpoint = "/bitacora/horas/reporte"
        else:
            params["fecha"] = self.fecha.date().toPython().isoformat()
            endpoint = "/bitacora/horas/exportar"
        try:
            params = {k: v for k, v in params.items() if v is not None}
            Path(ruta).write_bytes(self.api.descargar(endpoint, **params))
        except (ErrorApi, OSError) as e:
            mostrar_error(self, ErrorApi(str(e)))
            return False
        return True
