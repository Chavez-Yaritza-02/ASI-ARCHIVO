"""Importar faltas y salidas anticipadas desde un Excel, con vista previa editable.

Flujo:
1. Elegir el archivo .xlsx: se leen fechas, docentes y tipos. NO se registra nada.
2. Revisar cada fila: docente del catálogo, fecha, tipo, hora de salida y las horas
   exactas que no se cumplieron (del horario del docente ese día). Motivo, observaciones
   y justificante son opcionales.
3. Marcar las filas confirmadas e importarlas. Se importan todas o ninguna; las demás
   quedan pendientes, sin inventar horas.
"""

from datetime import date, time
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.views.comunes import (
    Columna,
    Tabla,
    confirmar,
    encabezado,
    informar,
    mostrar_error,
)

TIPOS = {"falta": "Falta", "salida_anticipada": "Salida anticipada"}
ESTADOS_FILA = {"pendiente": "Pendiente", "importada": "Importada", "descartada": "Descartada"}
ESTADOS_HORA = {
    "pendiente": "pendiente",
    "inhabil": "día inhábil",
    "asistio": "ya registrada: asistió",
    "retardo": "ya registrada: retardo",
    "falto": "ya registrada: falta",
    "justificado": "ya registrada: justificada",
    "parcial": "ya registrada: parcial",
}
SIN_FECHA = QDate(2000, 1, 1)


def _fecha(texto: str | None) -> str:
    return date.fromisoformat(texto).strftime("%d/%m/%Y") if texto else ""


def _horas_texto(fila: dict) -> str:
    return ", ".join(h["programado_inicio"][:5] for h in fila["horas"]) or "—"


def _previsto(previsto: dict | None) -> str:
    if not previsto:
        return ""
    if "error" in previsto:
        return f"no aplica: {previsto['error']}"
    if previsto["estado"] == "parcial":
        return (
            f"se registrará parcial (presente {previsto['hora_entrada'][:5]}–"
            f"{previsto['hora_salida'][:5]})"
        )
    return {"falto": "se registrará falta", "justificado": "se registrará justificada"}.get(
        previsto["estado"], previsto["estado"]
    )


class DialogoIncidencia(QDialog):
    """Revisar una fila: docente, fecha, tipo, horas exactas, motivo y justificante."""

    def __init__(self, api: ClienteApi, fila: dict, docentes: list[dict], padre=None):
        super().__init__(padre)
        self.api = api
        self.fila = fila
        self.setWindowTitle(f"Revisar fila {fila['fila']} del Excel")
        self.setMinimumWidth(620)

        evidencia = QLabel(
            "<b>En el archivo:</b> "
            + " · ".join(
                x
                for x in (
                    fila["fecha_texto"],
                    fila["docente_texto"],
                    fila["tipo_texto"],
                    fila["detalle_texto"],
                )
                if x
            ),
            wordWrap=True,
        )
        evidencia.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.docente = QComboBox()
        self.docente.setEditable(True)
        self.docente.setInsertPolicy(QComboBox.NoInsert)
        self.docente.completer().setFilterMode(Qt.MatchContains)
        self.docente.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.docente.addItem("— no encontrado: elige del catálogo —", None)
        for d in docentes:
            self.docente.addItem(d["nombre"] + ("" if d["activo"] else " (inactivo)"), d["id"])
        self.estado_docente = QLabel("", objectName="ayuda")
        self.fecha = QDateEdit(calendarPopup=True)
        self.fecha.setDisplayFormat("dd/MM/yyyy")
        self.fecha.setMinimumDate(SIN_FECHA)
        self.fecha.setSpecialValueText("Sin fecha válida")
        self.tipo = QComboBox()
        self.tipo.addItem("— elegir —", None)
        for clave, texto in TIPOS.items():
            self.tipo.addItem(texto, clave)
        self.hora_salida = QTimeEdit()
        self.hora_salida.setDisplayFormat("HH:mm")
        self.boton_horas = QPushButton("Aplicar y ver sus horas")
        self.boton_horas.setToolTip("Guarda docente, fecha y tipo, y muestra el horario de ese día")

        self.horas = QListWidget()
        self.horas.setMinimumHeight(150)
        self.boton_sugeridas = QPushButton("Marcar las horas posteriores a la salida")
        self.justificada = QCheckBox("Justificada")
        self.motivo = QLineEdit(placeholderText="Motivo (obligatorio si está justificada)")
        self.observaciones = QLineEdit(placeholderText="Observaciones")
        self.justificante = QComboBox()
        self.problemas = QLabel("", objectName="error", wordWrap=True)
        self.avisos = QLabel("", objectName="advertencia", wordWrap=True)

        formulario = QFormLayout()
        formulario.addRow("Docente", self.docente)
        formulario.addRow("", self.estado_docente)
        formulario.addRow("Fecha", self.fecha)
        formulario.addRow("Tipo", self.tipo)
        formulario.addRow("Hora de salida", self.hora_salida)
        formulario.addRow("", self.boton_horas)
        detalle = QFormLayout()
        detalle.addRow("", self.justificada)
        detalle.addRow("Motivo", self.motivo)
        detalle.addRow("Observaciones", self.observaciones)
        detalle.addRow("Justificante", self.justificante)

        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        botones.button(QDialogButtonBox.Save).setText("Guardar revisión")
        botones.button(QDialogButtonBox.Close).setText("Cerrar")
        botones.accepted.connect(self.guardar)
        botones.rejected.connect(self.reject)

        capa = QVBoxLayout(self)
        capa.addWidget(evidencia)
        capa.addLayout(formulario)
        capa.addWidget(
            QLabel(
                "Horas que NO se cumplieron (elige solo las confirmadas; nada se marca solo):",
                objectName="suave",
                wordWrap=True,
            )
        )
        capa.addWidget(self.horas, 1)
        capa.addWidget(self.boton_sugeridas)
        capa.addLayout(detalle)
        capa.addWidget(self.problemas)
        capa.addWidget(self.avisos)
        capa.addWidget(botones)

        self.tipo.currentIndexChanged.connect(self._habilitar)
        self.boton_horas.clicked.connect(self.aplicar_y_ver_horas)
        self.boton_sugeridas.clicked.connect(self.marcar_sugeridas)
        self.disponibles: list[dict] = []
        self._mostrar(fila)
        self._cargar_horas()

    # --- presentación ----------------------------------------------------------------

    def _mostrar(self, fila: dict) -> None:
        self.fila = fila
        docente = (fila.get("docente") or {}).get("id")
        self.docente.setCurrentIndex(max(self.docente.findData(docente), 0))
        self.estado_docente.setText(
            {
                "coincide": "Coincide con el catálogo.",
                "sugerido": "Sugerido por parecido: confírmalo o elige otro.",
                "confirmado": "Confirmado.",
            }.get(fila["docente_estado"], f"No se encontró «{fila['docente_texto']}».")
        )
        if fila["fecha"]:
            d = date.fromisoformat(fila["fecha"])
            self.fecha.setDate(QDate(d.year, d.month, d.day))
        else:
            self.fecha.setDate(SIN_FECHA)
        self.tipo.setCurrentIndex(max(self.tipo.findData(fila["tipo"]), 0))
        salida = time.fromisoformat(fila["hora_salida"]) if fila["hora_salida"] else time(0)
        self.hora_salida.setTime(QTime(salida.hour, salida.minute))
        self.justificada.setChecked(fila["justificada"])
        self.motivo.setText(fila["motivo"])
        self.observaciones.setText(fila["observaciones"])
        self._cargar_justificantes(docente)
        self.problemas.setText("\n".join(f"• {p}" for p in fila["problemas"]))
        self.avisos.setText("\n".join(f"⚠ {a}" for a in fila["avisos"]))
        self._habilitar()

    def _habilitar(self) -> None:
        self.hora_salida.setEnabled(self.tipo.currentData() == "salida_anticipada")
        self.boton_sugeridas.setEnabled(
            self.tipo.currentData() == "salida_anticipada"
            and any(h["sugerida"] for h in self.disponibles)
        )

    def _cargar_justificantes(self, docente_id: int | None) -> None:
        self.justificante.clear()
        self.justificante.addItem("— ninguno —", None)
        if docente_id is None:
            return
        try:
            documentos = self.api.get("/documentos", docente_id=docente_id, limite=100)
        except ErrorApi:
            documentos = {"resultados": []}  # sin permiso de documentos: solo «ninguno»
        for d in documentos["resultados"]:
            if d["admite_justificantes"] and d["activo"]:
                self.justificante.addItem(f"{d['nombre']} ({_fecha(d['fecha'])})", d["id"])
        self.justificante.setCurrentIndex(
            max(self.justificante.findData(self.fila["documento_id"]), 0)
        )

    def _cargar_horas(self) -> None:
        self.horas.clear()
        self.disponibles = []
        try:
            respuesta = self.api.get(f"/incidencias-excel/filas/{self.fila['id']}/horas")
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self.disponibles = respuesta["horas"]
        if not self.disponibles:
            item = QListWidgetItem(
                "Elige docente y fecha válidos y pulsa «Aplicar y ver sus horas»."
                if not (self.fila.get("docente") and self.fila["fecha"])
                else "El docente no tiene horas programadas ese día."
            )
            item.setFlags(Qt.NoItemFlags)
            self.horas.addItem(item)
        for h in self.disponibles:
            partes = [
                f"{h['programado_inicio'][:5]}–{h['programado_fin'][:5]}",
                h["asignatura"],
                h["grupo"] or "",
                h["aula"] or "",
            ]
            texto = " · ".join(p for p in partes if p)
            texto += f" — {ESTADOS_HORA.get(h['estado'], h['estado'])}"
            if h["sugerida"]:
                texto += " (sugerida por la hora de salida)"
            if h["seleccionada"] and (previsto := _previsto(h["se_registrara"])):
                texto += f" → {previsto}"
            item = QListWidgetItem(texto)
            item.setData(Qt.UserRole, h)
            libre = not h["registrada"] and h["dia_habil"]
            item.setFlags(
                (Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                if libre or h["seleccionada"]
                else Qt.NoItemFlags
            )
            item.setCheckState(Qt.Checked if h["seleccionada"] else Qt.Unchecked)
            self.horas.addItem(item)
        self._habilitar()

    def marcar_sugeridas(self) -> None:
        for i in range(self.horas.count()):
            item = self.horas.item(i)
            h = item.data(Qt.UserRole)
            if h and h["sugerida"] and item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(Qt.Checked)

    # --- datos -----------------------------------------------------------------------------

    def _identificacion(self) -> dict:
        """Docente, fecha, tipo y hora de salida tal como están en la ventana."""
        fecha = self.fecha.date()
        return {
            "docente_id": self.docente.currentData(),
            "fecha": None if fecha == SIN_FECHA else fecha.toPython().isoformat(),
            "tipo": self.tipo.currentData(),
            "hora_salida": (
                self.hora_salida.time().toPython().strftime("%H:%M:%S")
                if self.tipo.currentData() == "salida_anticipada"
                else None
            ),
        }

    def horas_elegidas(self) -> list[dict]:
        elegidas = []
        for i in range(self.horas.count()):
            item = self.horas.item(i)
            h = item.data(Qt.UserRole)
            if h and item.checkState() == Qt.Checked:
                elegidas.append(
                    {"bloque_id": h["bloque_id"], "programado_inicio": h["programado_inicio"]}
                )
        return elegidas

    def _cambios(self, datos: dict) -> dict:
        """Solo lo que cambió respecto de lo guardado."""
        actual = {
            **self.fila,
            "docente_id": (self.fila.get("docente") or {}).get("id"),
        }
        cambios = {}
        for clave, valor in datos.items():
            guardado = actual.get(clave)
            if clave == "horas":
                guardado = [
                    {"bloque_id": h["bloque_id"], "programado_inicio": h["programado_inicio"]}
                    for h in guardado
                ]
            if (
                clave == "docente_id"
                and valor is not None
                and self.fila["docente_estado"] == "sugerido"
            ):
                cambios[clave] = valor  # confirmar el sugerido
            elif valor != guardado:
                cambios[clave] = valor
        return cambios

    def _enviar(self, cambios: dict) -> bool:
        if not cambios:
            return True
        try:
            fila = self.api.patch(f"/incidencias-excel/filas/{self.fila['id']}", cambios)
        except ErrorApi as error:
            mostrar_error(self, error, "La revisión no se guardó")
            return False
        self._mostrar(fila)
        return True

    def aplicar_y_ver_horas(self) -> None:
        if self._enviar(self._cambios(self._identificacion())):
            self._cargar_horas()

    def guardar(self) -> None:
        datos = {
            **self._identificacion(),
            "justificada": self.justificada.isChecked(),
            "motivo": self.motivo.text().strip(),
            "observaciones": self.observaciones.text().strip(),
            "documento_id": self.justificante.currentData(),
        }
        identificacion_cambia = any(
            k in self._cambios(self._identificacion()) for k in ("docente_id", "fecha")
        )
        if not identificacion_cambia:
            datos["horas"] = self.horas_elegidas()
        if self._enviar(self._cambios(datos)):
            self._cargar_horas()
            if identificacion_cambia:
                return  # cambió el día o el docente: elegir sus horas antes de cerrar
            self.accept()


class VistaIncidenciasExcel(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api = api
        self.puede_importar = usuario.puede("asistencia.corregir")
        self.importacion: dict | None = None
        self.docentes: list[dict] = []

        self.boton_archivo = QPushButton("Elegir archivo Excel…", objectName="primario")
        self.anteriores = QComboBox()
        self.anteriores.setMinimumWidth(320)
        arriba = QHBoxLayout()
        arriba.addWidget(self.boton_archivo)
        arriba.addSpacing(16)
        arriba.addWidget(QLabel("Importaciones anteriores"))
        arriba.addWidget(self.anteriores, 1)

        self.resumen = QLabel("", objectName="estado", wordWrap=True)
        self.tabla = Tabla(
            [
                Columna("Importar", lambda f: ""),
                Columna("Fila", lambda f: f["fila"]),
                Columna("Fecha", lambda f: _fecha(f["fecha"]) or f"¿{f['fecha_texto']}?"),
                Columna(
                    "Docente",
                    lambda f: (f.get("docente") or {}).get("nombre") or f"¿{f['docente_texto']}?",
                ),
                Columna("Tipo", lambda f: TIPOS.get(f["tipo"], "¿?")),
                Columna("Salida", lambda f: (f["hora_salida"] or "")[:5]),
                Columna("Horas elegidas", _horas_texto),
                Columna("Estado", lambda f: ESTADOS_FILA[f["estado"]]),
                Columna(
                    "Revisión",
                    lambda f: (
                        "Lista para importar"
                        if f["lista"]
                        else "; ".join(f["problemas"] + f["avisos"])
                    ),
                ),
            ],
            "Elige un archivo Excel (.xlsx) con las incidencias para ver la vista previa.",
        )
        self.boton_revisar = QPushButton("Revisar fila…")
        self.boton_descartar = QPushButton("Descartar fila…")
        self.boton_recuperar = QPushButton("Recuperar fila")
        self.boton_importar = QPushButton("Importar filas marcadas", objectName="primario")
        self.boton_importar.setVisible(self.puede_importar)
        acciones = QHBoxLayout()
        for b in (self.boton_revisar, self.boton_descartar, self.boton_recuperar):
            acciones.addWidget(b)
        acciones.addStretch()
        acciones.addWidget(self.boton_importar)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 28, 32, 28)
        capa.addWidget(
            encabezado(
                "Importar incidencias (Excel)",
                "Faltas y salidas anticipadas. Leer el archivo no registra nada: revisa cada "
                "fila, elige las horas exactas que no se cumplieron y marca las confirmadas. "
                "Se importan todas las marcadas o ninguna; las demás quedan pendientes.",
            )
        )
        capa.addLayout(arriba)
        capa.addWidget(self.resumen)
        capa.addWidget(self.tabla, 1)
        capa.addLayout(acciones)

        self.boton_archivo.clicked.connect(self.elegir_archivo)
        self.anteriores.activated.connect(self._abrir_anterior)
        self.boton_revisar.clicked.connect(self.revisar)
        self.tabla.cellDoubleClicked.connect(lambda *_: self.revisar())
        self.boton_descartar.clicked.connect(self.descartar)
        self.boton_recuperar.clicked.connect(self.recuperar)
        self.boton_importar.clicked.connect(self.importar)
        self.recargar()

    # --- carga ---------------------------------------------------------------------------

    def recargar(self) -> None:
        try:
            self.docentes = self.api.get("/docentes")
            anteriores = self.api.get("/incidencias-excel")
        except ErrorApi as error:
            mostrar_error(self, error, "No se pudo cargar la información")
            return
        self.anteriores.blockSignals(True)
        self.anteriores.clear()
        self.anteriores.addItem("—", None)
        for i in anteriores:
            self.anteriores.addItem(
                f"{i['nombre_archivo']} · {i['pendientes']} pendientes, "
                f"{i['importadas']} importadas",
                i["id"],
            )
        if self.importacion:
            self.anteriores.setCurrentIndex(
                max(self.anteriores.findData(self.importacion["id"]), 0)
            )
        self.anteriores.blockSignals(False)
        if self.importacion:
            self.abrir(self.importacion["id"])
        else:
            self._mostrar()

    def _abrir_anterior(self) -> None:
        if (id_ := self.anteriores.currentData()) is not None:
            self.abrir(id_)

    def abrir(self, id_: int) -> None:
        try:
            self.importacion = self.api.get(f"/incidencias-excel/{id_}")
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self._mostrar()

    def elegir_archivo(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Elegir Excel de incidencias", str(Path.home()), "Excel (*.xlsx)"
        )
        if ruta:
            self.cargar_archivo(Path(ruta))

    def cargar_archivo(self, ruta: Path) -> None:
        try:
            self.importacion = self.api.subir(
                "/incidencias-excel", ruta.name, ruta.read_bytes(), {}
            )
        except (ErrorApi, OSError) as error:
            if isinstance(error, OSError):
                error = ErrorApi(f"No se pudo leer el archivo: {error.strerror or error}")
            mostrar_error(self, error, "El archivo no se cargó (no se guardó nada)")
            return
        if self.importacion.get("ya_existia"):
            informar(
                self,
                "Este archivo ya se había cargado",
                "Se abre la revisión existente; no se duplicó ninguna incidencia.",
            )
        self.recargar()

    # --- presentación --------------------------------------------------------------------

    def _mostrar(self) -> None:
        i = self.importacion
        filas = i["filas"] if i else []
        self.tabla.cargar(filas)
        for n, f in enumerate(filas):
            item = QTableWidgetItem()
            if f["lista"] and self.puede_importar:
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setCheckState(Qt.Unchecked)
                item.setToolTip("Marca para confirmar e importar esta fila")
            else:
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.tabla.setItem(n, 0, item)
            revision = self.tabla.item(n, self.tabla.columnCount() - 1)
            if revision is not None and (f["problemas"] or f["avisos"]):
                revision.setToolTip("\n".join(f["problemas"] + f["avisos"]))
        if i:
            self.resumen.setText(
                f"{i['nombre_archivo']} (hoja {i['hoja']}): {i['total_filas']} filas · "
                f"{i['listas']} listas para importar · {i['pendientes']} pendientes · "
                f"{i['importadas']} importadas · {i['descartadas']} descartadas"
            )
        else:
            self.resumen.setText("")
        hay = bool(filas)
        for b in (self.boton_revisar, self.boton_descartar, self.boton_recuperar):
            b.setEnabled(hay)
        self.boton_importar.setEnabled(any(f["lista"] for f in filas))

    def marcadas(self) -> list[dict]:
        return [
            f
            for n, f in enumerate(self.tabla.filas)
            if (item := self.tabla.item(n, 0)) is not None and item.checkState() == Qt.Checked
        ]

    def marcar(self, fila_id: int, marcada: bool = True) -> None:
        for n, f in enumerate(self.tabla.filas):
            if f["id"] == fila_id:
                self.tabla.item(n, 0).setCheckState(Qt.Checked if marcada else Qt.Unchecked)

    def _elegida(self) -> dict | None:
        fila = self.tabla.seleccionado()
        if fila is None:
            informar(self, "Elige una fila", "Selecciónala en la tabla.")
        return fila

    # --- acciones ----------------------------------------------------------------------

    def revisar(self) -> None:
        fila = self._elegida()
        if fila is None:
            return
        if fila["estado"] != "pendiente":
            informar(
                self,
                f"Fila {fila['fila']}: {ESTADOS_FILA[fila['estado']].lower()}",
                "Solo se revisan filas pendientes. Las importadas se corrigen en Asistencia "
                "por hora (cada corrección queda en el historial).",
            )
            return
        dialogo = DialogoIncidencia(self.api, fila, self.docentes, self)
        dialogo.exec()
        self.abrir(self.importacion["id"])

    def descartar(self) -> None:
        fila = self._elegida()
        if fila is None:
            return
        motivo, ok = QInputDialog.getText(
            self,
            f"Descartar fila {fila['fila']}",
            "Motivo (la fila se conserva como evidencia y se puede recuperar):",
        )
        if not ok:
            return
        try:
            self.api.post(f"/incidencias-excel/filas/{fila['id']}/descartar", {"motivo": motivo})
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self.abrir(self.importacion["id"])

    def recuperar(self) -> None:
        fila = self._elegida()
        if fila is None:
            return
        try:
            self.api.post(f"/incidencias-excel/filas/{fila['id']}/recuperar")
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self.abrir(self.importacion["id"])

    def importar(self) -> None:
        marcadas = self.marcadas()
        if not marcadas:
            informar(
                self,
                "Marca las filas confirmadas",
                "Solo se importan las filas listas que marques en la columna «Importar».",
            )
            return
        horas = sum(len(f["horas"]) for f in marcadas)
        if not confirmar(
            self,
            f"¿Importar {len(marcadas)} incidencia(s), {horas} hora(s) en total?",
            "Se registran en la asistencia por hora y en los reportes. Si alguna falla no se "
            "guarda ninguna. Las filas no marcadas quedan pendientes.",
            "Importar",
        ):
            return
        try:
            resultado = self.api.post(
                f"/incidencias-excel/{self.importacion['id']}/importar",
                {"filas": [f["id"] for f in marcadas]},
            )
        except ErrorApi as error:
            mostrar_error(self, error, "No se importó nada")
            self.abrir(self.importacion["id"])
            return
        informar(
            self,
            "Incidencias importadas",
            f"{len(resultado['importadas'])} fila(s), {resultado['horas']} hora(s) registradas "
            "en la asistencia por hora.",
        )
        self.importacion = resultado["importacion"]
        self.recargar()
