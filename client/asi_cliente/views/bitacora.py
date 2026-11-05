"""Pantalla "Bitácora del día" (legado por turno): lo programado frente a lo registrado.

- La lista se arma con los horarios vigentes en la fecha elegida (uno por docente y turno).
- Un docente sin registro aparece "Pendiente de verificar": el sistema nunca marca faltas
  por su cuenta. En días inhábiles aparece "Día inhábil".
- Registrar: doble clic o botón. Corregir: exige motivo; días anteriores, autorización.
"""

from datetime import date, datetime, time
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtGui import QColor
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
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.views.comunes import Columna, Tabla, confirmar, encabezado, mostrar_error

ESTADOS = {
    "pendiente": ("Pendiente de verificar", "#d97706"),
    "inhabil": ("Día inhábil", "#6b7280"),
    "asistio": ("Asistió", "#16a34a"),
    "retardo": ("Retardo", "#ea580c"),
    "falto": ("Falta", "#dc2626"),
    "justificado": ("Justificado", "#2563eb"),
}
REGISTRABLES = ["asistio", "retardo", "falto", "justificado"]
TIPOS_INCIDENCIA = {
    "comision": "Comisión",
    "permiso": "Permiso",
    "salida_anticipada": "Salida anticipada",
    "cambio_aula": "Cambio de aula",
    "otra": "Otra",
}
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = [
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


def _hora(texto: str | None) -> str:
    return texto[:5] if texto else ""


def _a_time(texto: str | None) -> time | None:
    return time.fromisoformat(texto) if texto else None


def _texto_retardo(fila: dict) -> str:
    """Minutos tarde: en los retardos, o si una asistencia rebasa la tolerancia (aviso)."""
    minutos = fila.get("minutos_retardo") or 0
    if fila["estado"] == "retardo" and minutos:
        return f" (+{minutos} min)"
    if fila["estado"] == "asistio" and minutos > fila.get("tolerancia_minutos", 10):
        return f" (+{minutos} min, rebasa tolerancia)"
    return ""


def fecha_larga(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


class DialogoAsistencia(QDialog):
    """Registrar o corregir la asistencia de un docente en un turno."""

    def __init__(self, fila: dict, fecha: date, padre=None):
        super().__init__(padre)
        self.fila = fila
        registro = fila["asistencia"]
        self.es_correccion = registro is not None
        nombre = fila["docente"]["nombre"]
        self.setWindowTitle(("Corregir" if self.es_correccion else "Registrar") + " asistencia")
        self.setMinimumWidth(480)
        capa = QVBoxLayout(self)
        programado = f"{_hora(fila['programado_inicio'])}–{_hora(fila['programado_fin'])}"
        capa.addWidget(
            QLabel(
                f"<b>{nombre}</b><br>{fecha_larga(fecha)} · turno {fila['turno']} · "
                f"programado {programado}",
                wordWrap=True,
            )
        )
        if fila["actividades"]:
            capa.addWidget(
                QLabel(
                    "<br>".join(
                        f"{_hora(a['inicio'])}–{_hora(a['fin'])} {a['asignatura']}"
                        + (f" · {a['grupo']}" if a["grupo"] else "")
                        + (f" · {a['aula']}" if a["aula"] else "")
                        for a in fila["actividades"]
                    ),
                    objectName="suave",
                    wordWrap=True,
                )
            )
        if not fila["dia_habil"]:
            self.autorizar = QCheckBox(
                f"{fila['motivo_inhabil']}. Registrar por excepción autorizada"
            )
            capa.addWidget(self.autorizar)
        else:
            self.autorizar = None

        self.estado = QComboBox()
        for clave in REGISTRABLES:
            self.estado.addItem(ESTADOS[clave][0], clave)
        self.usar_entrada = QCheckBox("Hora real de entrada")
        self.entrada = QTimeEdit(displayFormat="HH:mm")
        self.usar_salida = QCheckBox("Hora real de salida")
        self.salida = QTimeEdit(displayFormat="HH:mm")
        self.aviso = QLabel("", objectName="advertencia", wordWrap=True)
        self.observaciones = QPlainTextEdit()
        self.observaciones.setFixedHeight(60)
        self.justificacion = QLineEdit(placeholderText="Motivo u oficio que lo justifica")
        self.motivo = QLineEdit(placeholderText="Obligatorio: por qué se corrige")

        inicio = _a_time(fila["programado_inicio"]) or time(7)
        fin = _a_time(fila["programado_fin"]) or time(8)
        self.entrada.setTime(QTime(inicio.hour, inicio.minute))
        self.salida.setTime(QTime(fin.hour, fin.minute))
        if registro:
            self.estado.setCurrentIndex(max(self.estado.findData(registro["estado"]), 0))
            for usar, control, valor in (
                (self.usar_entrada, self.entrada, registro["hora_entrada"]),
                (self.usar_salida, self.salida, registro["hora_salida"]),
            ):
                if valor:
                    t = _a_time(valor)
                    usar.setChecked(True)
                    control.setTime(QTime(t.hour, t.minute))
            self.observaciones.setPlainText(registro["observaciones"])
            self.justificacion.setText(registro["justificacion"])

        formulario = QFormLayout()
        formulario.addRow("Estado", self.estado)
        formulario.addRow(self.usar_entrada, self.entrada)
        formulario.addRow(self.usar_salida, self.salida)
        formulario.addRow("", self.aviso)
        formulario.addRow("Observaciones", self.observaciones)
        formulario.addRow("Justificación", self.justificacion)
        if self.es_correccion:
            formulario.addRow("Motivo de la corrección *", self.motivo)
        capa.addLayout(formulario)
        self.mensaje = QLabel("", objectName="error", wordWrap=True)
        capa.addWidget(self.mensaje)
        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Save).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        capa.addWidget(botones)

        self.inicio_programado = inicio
        self.tolerancia = fila.get("tolerancia_minutos", 10)
        for senal in (
            self.estado.currentIndexChanged,
            self.usar_entrada.toggled,
            self.usar_salida.toggled,
            self.entrada.timeChanged,
        ):
            senal.connect(self._actualizar)
        self._actualizar()

    def _actualizar(self) -> None:
        estado = self.estado.currentData()
        falta = estado == "falto"
        for usar, control in ((self.usar_entrada, self.entrada), (self.usar_salida, self.salida)):
            usar.setEnabled(not falta)
            control.setEnabled(usar.isChecked() and not falta)
        if estado == "retardo" and not self.usar_entrada.isChecked():
            self.usar_entrada.setChecked(True)
        self.justificacion.setEnabled(estado == "justificado" or bool(self.justificacion.text()))
        self.aviso.setText("")
        if self.usar_entrada.isChecked() and not falta:
            entrada = self.entrada.time().toPython()
            minutos = (entrada.hour * 60 + entrada.minute) - (
                self.inicio_programado.hour * 60 + self.inicio_programado.minute
            )
            if minutos > self.tolerancia and estado == "asistio":
                self.aviso.setText(
                    f"Llegó {minutos} min después de lo programado "
                    f"(tolerancia {self.tolerancia} min). ¿Es un retardo?"
                )

    def datos(self) -> dict:
        estado = self.estado.currentData()
        falta = estado == "falto"
        datos = {
            "estado": estado,
            "hora_entrada": None
            if falta or not self.usar_entrada.isChecked()
            else self.entrada.time().toString("HH:mm"),
            "hora_salida": None
            if falta or not self.usar_salida.isChecked()
            else self.salida.time().toString("HH:mm"),
            "observaciones": self.observaciones.toPlainText().strip(),
            "justificacion": self.justificacion.text().strip(),
        }
        if self.es_correccion:
            datos["motivo"] = self.motivo.text().strip()
        elif self.autorizar is not None:
            datos["autorizar_dia_inhabil"] = self.autorizar.isChecked()
        return datos

    def _aceptar(self) -> None:
        if self.es_correccion and len(self.motivo.text().strip()) < 5:
            self.mensaje.setText("Escribe el motivo de la corrección.")
            return
        if self.autorizar is not None and not self.autorizar.isChecked():
            self.mensaje.setText("Es día inhábil: marca la excepción autorizada para registrar.")
            return
        self.accept()


class DialogoIncidencia(QDialog):
    def __init__(self, docentes: list[dict], padre=None):
        super().__init__(padre)
        self.setWindowTitle("Nueva incidencia")
        self.setMinimumWidth(460)
        self.tipo = QComboBox()
        for clave, nombre in TIPOS_INCIDENCIA.items():
            self.tipo.addItem(nombre, clave)
        self.docente = QComboBox()
        self.docente.addItem("— (general)", None)
        for d in docentes:
            self.docente.addItem(d["nombre"], d["id"])
        self.turno = QComboBox()
        for texto, valor in (
            ("Todo el día", None),
            ("Matutino", "matutino"),
            ("Vespertino", "vespertino"),
        ):
            self.turno.addItem(texto, valor)
        self.descripcion = QPlainTextEdit()
        self.mensaje = QLabel("", objectName="error")
        formulario = QFormLayout()
        formulario.addRow("Tipo", self.tipo)
        formulario.addRow("Docente", self.docente)
        formulario.addRow("Turno", self.turno)
        formulario.addRow("Descripción", self.descripcion)
        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        capa.addLayout(formulario)
        capa.addWidget(self.mensaje)
        capa.addWidget(botones)

    def datos(self) -> dict:
        return {
            "tipo": self.tipo.currentData(),
            "docente_id": self.docente.currentData(),
            "turno": self.turno.currentData(),
            "descripcion": self.descripcion.toPlainText().strip(),
        }

    def _aceptar(self) -> None:
        if len(self.descripcion.toPlainText().strip()) < 3:
            self.mensaje.setText("Describe la incidencia.")
            return
        self.accept()


class DialogoHistorial(QDialog):
    def __init__(self, cambios: list[dict], padre=None):
        super().__init__(padre)
        self.setWindowTitle("Historial del registro")
        self.setMinimumSize(640, 320)
        tabla = Tabla(
            [
                Columna(
                    "Fecha",
                    lambda c: (
                        datetime.fromisoformat(c["fecha"]).astimezone().strftime("%d/%m/%Y %H:%M")
                    ),
                ),
                Columna("Usuario", lambda c: c["usuario"]),
                Columna("Acción", lambda c: c["accion"].capitalize()),
                Columna("Cambio", lambda c: _describir_cambio(c)),
            ]
        )
        tabla.cargar(cambios)
        tabla.setWordWrap(True)
        tabla.resizeRowsToContents()
        capa = QVBoxLayout(self)
        capa.addWidget(tabla)
        cerrar = QDialogButtonBox(QDialogButtonBox.Close)
        cerrar.rejected.connect(self.reject)
        capa.addWidget(cerrar)


def _describir_cambio(c: dict) -> str:
    despues = c["despues"] or {}
    antes = c["antes"] or {}
    if c["accion"] == "registrar":
        return (
            "Parcial"
            if despues.get("estado") == "parcial"
            else ESTADOS.get(despues.get("estado"), ("?",))[0]
        )
    partes = [
        f"{k}: {antes.get(k) or '—'} → {despues.get(k) or '—'}"
        for k in despues
        if k != "motivo" and antes.get(k) != despues.get(k)
    ]
    if despues.get("motivo"):
        partes.append(f"Motivo: {despues['motivo']}")
    return " · ".join(partes)


class VistaBitacora(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api = api
        self.puede_registrar = usuario.puede("asistencia.registrar")
        self.puede_exportar = usuario.puede("reportes.generar")
        self.datos: dict | None = None
        self.docentes: list[dict] = []

        self.fecha = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.fecha.setDate(QDate.currentDate())
        anterior, siguiente, hoy = QPushButton("◀"), QPushButton("▶"), QPushButton("Hoy")
        anterior.setFixedWidth(36)
        siguiente.setFixedWidth(36)
        self.turno = QComboBox()
        for texto, valor in (
            ("Ambos turnos", None),
            ("Matutino", "matutino"),
            ("Vespertino", "vespertino"),
        ):
            self.turno.addItem(texto, valor)
        self.estado = QComboBox()
        self.estado.addItem("Todos los estados", None)
        for clave, (nombre, _) in ESTADOS.items():
            self.estado.addItem(nombre, clave)
        self.buscar = QLineEdit(placeholderText="Buscar docente…")
        self.buscar.setClearButtonEnabled(True)
        barra = QHBoxLayout()
        for w in (anterior, self.fecha, siguiente, hoy):
            barra.addWidget(w)
        barra.addSpacing(16)
        for w in (self.turno, self.estado):
            barra.addWidget(w)
        barra.addWidget(self.buscar, 1)

        self.titulo_dia = QLabel("", objectName="estado")
        self.aviso_dia = QLabel("", objectName="advertencia", wordWrap=True)
        self.resumen = QLabel("", objectName="suave")
        self.tabla = Tabla(
            [
                Columna("Docente", lambda f: f["docente"]["nombre"]),
                Columna("Turno", lambda f: f["turno"].capitalize()),
                Columna(
                    "Programado",
                    lambda f: f"{_hora(f['programado_inicio'])}–{_hora(f['programado_fin'])}",
                ),
                Columna(
                    "Actividades",
                    lambda f: (
                        "; ".join(
                            a["asignatura"]
                            + (f" {a['grupo']}" if a["grupo"] else "")
                            + (f" ({a['aula']})" if a["aula"] else "")
                            for a in f["actividades"]
                        )
                        or "Sin actividades (el horario cambió)"
                    ),
                ),
                Columna("Entrada", lambda f: _hora((f["asistencia"] or {}).get("hora_entrada"))),
                Columna("Salida", lambda f: _hora((f["asistencia"] or {}).get("hora_salida"))),
                Columna(
                    "Estado",
                    lambda f: ESTADOS[f["estado"]][0] + _texto_retardo(f),
                ),
                Columna(
                    "Observaciones",
                    lambda f: " · ".join(
                        x
                        for x in (
                            (f["asistencia"] or {}).get("observaciones"),
                            (f["asistencia"] or {}).get("justificacion"),
                        )
                        if x
                    ),
                ),
            ]
        )
        self.tabla.setSelectionMode(QAbstractItemView.ExtendedSelection)
        cabecera = self.tabla.horizontalHeader()
        for col, modo in (
            (0, QHeaderView.ResizeToContents),
            (1, QHeaderView.ResizeToContents),
            (2, QHeaderView.ResizeToContents),
            (4, QHeaderView.ResizeToContents),
            (5, QHeaderView.ResizeToContents),
            (6, QHeaderView.ResizeToContents),
        ):
            cabecera.setSectionResizeMode(col, modo)

        self.boton_registrar = QPushButton("Registrar / corregir", objectName="primario")
        self.boton_asistieron = QPushButton("Marcar seleccionados: asistió")
        self.boton_historial = QPushButton("Historial")
        self.boton_incidencia = QPushButton("Nueva incidencia")
        self.boton_pdf = QPushButton("Exportar PDF")
        self.boton_excel = QPushButton("Exportar Excel")
        acciones = QHBoxLayout()
        for b in (
            self.boton_registrar,
            self.boton_asistieron,
            self.boton_historial,
            self.boton_incidencia,
        ):
            acciones.addWidget(b)
        acciones.addStretch()
        acciones.addWidget(self.boton_pdf)
        acciones.addWidget(self.boton_excel)
        for b in (self.boton_registrar, self.boton_asistieron, self.boton_incidencia):
            b.setVisible(self.puede_registrar)
        for b in (self.boton_pdf, self.boton_excel):
            b.setVisible(self.puede_exportar)

        self.incidencias = QLabel("", wordWrap=True, objectName="suave")
        self.incidencias.setTextInteractionFlags(Qt.TextSelectableByMouse)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 28, 32, 28)
        capa.addWidget(
            encabezado(
                "Bitácora por turno (legado)",
                "Docentes programados según el horario vigente en la fecha. Sin registro aparecen "
                "como pendientes: el sistema nunca marca faltas por su cuenta.",
            )
        )
        capa.addLayout(barra)
        capa.addWidget(self.titulo_dia)
        capa.addWidget(self.aviso_dia)
        capa.addWidget(self.resumen)
        capa.addWidget(self.tabla, 1)
        capa.addLayout(acciones)
        capa.addWidget(self.incidencias)

        anterior.clicked.connect(lambda: self.fecha.setDate(self.fecha.date().addDays(-1)))
        siguiente.clicked.connect(lambda: self.fecha.setDate(self.fecha.date().addDays(1)))
        hoy.clicked.connect(lambda: self.fecha.setDate(QDate.currentDate()))
        self.fecha.dateChanged.connect(self.recargar)
        self.turno.currentIndexChanged.connect(self.recargar)
        self.estado.currentIndexChanged.connect(self.recargar)
        self.buscar.textChanged.connect(self._filtrar)
        self.tabla.itemSelectionChanged.connect(self._actualizar_botones)
        if self.puede_registrar:
            self.tabla.doubleClicked.connect(self.registrar)
        self.boton_registrar.clicked.connect(self.registrar)
        self.boton_asistieron.clicked.connect(self.marcar_asistieron)
        self.boton_historial.clicked.connect(self.ver_historial)
        self.boton_incidencia.clicked.connect(self.nueva_incidencia)
        self.boton_pdf.clicked.connect(lambda: self.exportar("pdf"))
        self.boton_excel.clicked.connect(lambda: self.exportar("xlsx"))
        try:
            self.docentes = self.api.get("/docentes", activo="true")
        except ErrorApi:
            self.docentes = []
        self.recargar()

    def fecha_elegida(self) -> date:
        return self.fecha.date().toPython()

    # --- carga -----------------------------------------------------------------------

    def recargar(self, *_args, seleccionar: tuple[int, str] | None = None) -> None:
        fecha = self.fecha_elegida()
        try:
            self.datos = self.api.get(
                "/bitacora",
                fecha=fecha.isoformat(),
                turno=self.turno.currentData(),
                estado=self.estado.currentData(),
            )
        except ErrorApi as error:
            mostrar_error(self, error, "No se pudo cargar la bitácora")
            return
        d = self.datos
        periodo = f" · Periodo {d['periodo']['nombre']}" if d["periodo"] else " · Sin periodo"
        self.titulo_dia.setText(fecha_larga(fecha) + periodo)
        avisos = []
        if not d["dia_habil"]:
            avisos.append(f"{d['motivo']}: no se esperan registros (no se generan faltas).")
        if d["periodo"] and d["periodo"]["estado"] == "cerrado":
            avisos.append("El periodo está cerrado: solo consulta.")
        self.aviso_dia.setText("\n".join(avisos))
        self.resumen.setText(
            " · ".join(f"{ESTADOS[e][0]}: {n}" for e, n in d["resumen"].items() if n)
            or "No hay docentes programados en esta fecha."
        )
        self._filtrar()
        if seleccionar:
            for i, f in enumerate(self.tabla.filas):
                if (f["docente"]["id"], f["turno"]) == seleccionar:
                    self.tabla.selectRow(i)
        self._mostrar_incidencias()

    def _filtrar(self) -> None:
        if not self.datos:
            return
        texto = self.buscar.text().strip().upper()
        filas = [
            f for f in self.datos["filas"] if not texto or texto in f["docente"]["nombre"].upper()
        ]
        self.tabla.cargar(filas)
        for i, f in enumerate(filas):
            item = self.tabla.item(i, 6)
            item.setForeground(QColor(ESTADOS[f["estado"]][1]))
        self._actualizar_botones()

    def _mostrar_incidencias(self) -> None:
        lista = self.datos["incidencias"] if self.datos else []
        if not lista:
            self.incidencias.setText("")
            return
        self.incidencias.setText(
            "Incidencias del día:\n"
            + "\n".join(
                f"• {TIPOS_INCIDENCIA[i['tipo']]}"
                + (f" — {i['docente']['nombre']}" if i["docente"] else "")
                + (f" ({i['turno']})" if i["turno"] else "")
                + f": {i['descripcion']}"
                for i in lista
            )
        )

    def _seleccionadas(self) -> list[dict]:
        return [self.tabla.filas[i.row()] for i in self.tabla.selectionModel().selectedRows()]

    def _actualizar_botones(self) -> None:
        filas = self._seleccionadas()
        cerrado = bool(
            self.datos and self.datos["periodo"] and self.datos["periodo"]["estado"] == "cerrado"
        )
        editable = not cerrado and bool(self.datos and self.datos["periodo"])
        self.boton_registrar.setEnabled(editable and len(filas) == 1)
        self.boton_asistieron.setEnabled(
            editable and bool(filas) and all(f["estado"] == "pendiente" for f in filas)
        )
        self.boton_historial.setEnabled(len(filas) == 1 and filas[0]["asistencia"] is not None)
        self.boton_incidencia.setEnabled(editable)

    # --- acciones ---------------------------------------------------------------------

    def registrar(self, *_args) -> None:
        filas = self._seleccionadas()
        if len(filas) != 1 or not self.boton_registrar.isEnabled():
            return
        fila = filas[0]
        dialogo = DialogoAsistencia(fila, self.fecha_elegida(), self)
        while dialogo.exec():
            datos = dialogo.datos()
            try:
                if fila["asistencia"]:
                    self.api.patch(f"/asistencias/{fila['asistencia']['id']}", datos)
                else:
                    self.api.post(
                        "/asistencias",
                        {
                            "docente_id": fila["docente"]["id"],
                            "fecha": self.fecha_elegida().isoformat(),
                            "turno": fila["turno"],
                            **datos,
                        },
                    )
            except ErrorApi as error:
                mostrar_error(self, error, "No se guardó")
                continue
            self.recargar(seleccionar=(fila["docente"]["id"], fila["turno"]))
            return

    def marcar_asistieron(self) -> None:
        filas = self._seleccionadas()
        if not filas or not confirmar(
            self,
            f"¿Marcar {len(filas)} registro(s) como «Asistió»?",
            "Sin hora real de entrada ni salida. Puedes corregirlos después.",
        ):
            return
        errores = []
        for f in filas:
            try:
                self.api.post(
                    "/asistencias",
                    {
                        "docente_id": f["docente"]["id"],
                        "fecha": self.fecha_elegida().isoformat(),
                        "turno": f["turno"],
                        "estado": "asistio",
                    },
                )
            except ErrorApi as error:
                errores.append(f"{f['docente']['nombre']}: {error}")
        if errores:
            mostrar_error(self, ErrorApi("Algunos registros no se guardaron", errores))
        self.recargar()

    def ver_historial(self) -> None:
        filas = self._seleccionadas()
        if len(filas) != 1 or not filas[0]["asistencia"]:
            return
        try:
            cambios = self.api.get(f"/asistencias/{filas[0]['asistencia']['id']}/historial")
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        DialogoHistorial(cambios, self).exec()

    def nueva_incidencia(self) -> None:
        dialogo = DialogoIncidencia(self.docentes, self)
        while dialogo.exec():
            try:
                self.api.post(
                    "/incidencias", {"fecha": self.fecha_elegida().isoformat(), **dialogo.datos()}
                )
            except ErrorApi as error:
                mostrar_error(self, error)
                continue
            self.recargar()
            return

    def exportar(self, formato: str) -> None:
        fecha = self.fecha_elegida()
        sugerido = Path.home() / f"bitacora_{fecha.isoformat()}.{formato}"
        filtro = "PDF (*.pdf)" if formato == "pdf" else "Excel (*.xlsx)"
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar bitácora", str(sugerido), filtro)
        if ruta:
            self.exportar_a(Path(ruta), formato)

    def exportar_a(self, ruta: Path, formato: str) -> bool:
        contenido = self.api.obtener_bytes(
            f"/bitacora/exportar?fecha={self.fecha_elegida().isoformat()}&formato={formato}"
            + (f"&turno={self.turno.currentData()}" if self.turno.currentData() else "")
        )
        if contenido is None:
            mostrar_error(self, ErrorApi("No se pudo generar el archivo"))
            return False
        ruta.write_bytes(contenido)
        return True
