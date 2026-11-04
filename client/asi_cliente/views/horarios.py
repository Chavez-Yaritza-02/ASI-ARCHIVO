"""Pantalla de horarios: versiones por docente y periodo, y editor de cuadrícula semanal.

Flujo:
1. Elegir periodo y docente: se listan todas sus versiones (historial).
2. "Nueva versión" crea un borrador (copia de la vigente, si existe).
3. En el borrador se editan las celdas (doble clic) y se guarda.
4. Un administrador lo confirma como vigente; la versión anterior pasa a histórico.
"""

import hashlib
from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.cuadricula import (
    DIAS,
    HORAS,
    TITULOS_DIAS,
    Celda,
    CuadriculaNoCompatible,
    bloques_a_celdas,
    celdas_a_bloques,
)
from asi_cliente.views.comunes import (
    COLORES_ESTADO,
    NOMBRES_ESTADO,
    Campo,
    Columna,
    DialogoFormulario,
    Tabla,
    confirmar,
    encabezado,
    mostrar_error,
)


def _fecha_hora(texto: str | None) -> str:
    return datetime.fromisoformat(texto).astimezone().strftime("%d/%m/%y") if texto else ""


def _color_asignatura(asignatura_id: int) -> QColor:
    """Color pastel estable por asignatura, para distinguir materias en la cuadrícula."""
    tono = int(hashlib.md5(str(asignatura_id).encode()).hexdigest()[:2], 16) * 360 // 256
    return QColor.fromHsl(tono, 140, 225)


class DialogoCelda(QDialog):
    """Asignar actividad, grupo y aula a una o varias horas consecutivas."""

    VACIAR = 2

    def __init__(self, catalogos: dict, celda: Celda | None, dia: str, hora: int, padre=None):
        super().__init__(padre)
        self.setWindowTitle(f"{TITULOS_DIAS[DIAS.index(dia)]} {hora:02d}:00")
        self.asignatura = self._combo(catalogos["asignaturas"], "nombre", opcional=False)
        self.grupo = self._combo(catalogos["grupos"], "clave", opcional=True)
        # Una letra sola no identifica al grupo: se conserva como "pendiente" hasta elegirlo.
        if celda and celda.grupo_letra:
            self.grupo.insertItem(
                1,
                f"Letra «{celda.grupo_letra}» (pendiente de validar)",
                f"letra:{celda.grupo_letra}",
            )
        self.aula = self._combo(catalogos["aulas"], "clave", opcional=True)
        self.horas = QSpinBox(minimum=1, maximum=HORAS[-1] + 1 - hora, value=1)
        self.horas.setSuffix(" h")
        if celda:
            grupo = celda.grupo_id or (f"letra:{celda.grupo_letra}" if celda.grupo_letra else None)
            for combo, valor in (
                (self.asignatura, celda.asignatura_id),
                (self.grupo, grupo),
                (self.aula, celda.aula_id),
            ):
                combo.setCurrentIndex(max(combo.findData(valor), 0))

        formulario = QFormLayout()
        formulario.addRow("Asignatura / actividad", self.asignatura)
        formulario.addRow("Grupo", self.grupo)
        formulario.addRow("Aula", self.aula)
        formulario.addRow("Duración desde esta hora", self.horas)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Aplicar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        vaciar = botones.addButton("Vaciar celda", QDialogButtonBox.DestructiveRole)
        vaciar.clicked.connect(lambda: self.done(self.VACIAR))
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        capa.addLayout(formulario)
        capa.addWidget(botones)

    @staticmethod
    def _combo(registros: list[dict], campo: str, opcional: bool) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.completer().setFilterMode(Qt.MatchContains)
        combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        if opcional:
            combo.addItem("—", None)
        for r in registros:
            if r["activo"]:
                texto = r[campo] + (" (pendiente)" if r.get("pendiente_validacion") else "")
                combo.addItem(texto, r["id"])
        return combo

    def celda(self) -> Celda | None:
        if self.asignatura.currentData() is None:
            return None
        grupo = self.grupo.currentData()
        if isinstance(grupo, str) and grupo.startswith("letra:"):
            return Celda(
                self.asignatura.currentData(),
                None,
                self.aula.currentData(),
                grupo.removeprefix("letra:"),
            )
        return Celda(self.asignatura.currentData(), grupo, self.aula.currentData())


class VistaHorarios(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api = api
        self.puede_editar = usuario.puede("horarios.editar")
        self.puede_confirmar = usuario.puede("horarios.confirmar")
        self.horario: dict | None = None
        self.celdas: dict[tuple[str, int], Celda] = {}
        self.cambios_pendientes = False
        self.catalogos: dict[str, list[dict]] = {}
        self.nombres: dict[str, dict[int, dict]] = {}

        # --- selección ---
        self.periodo = QComboBox()
        self.docente = QComboBox()
        self.docente.setEditable(True)
        self.docente.setInsertPolicy(QComboBox.NoInsert)
        self.docente.completer().setFilterMode(Qt.MatchContains)
        self.docente.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.docente.setMinimumWidth(320)
        seleccion = QHBoxLayout()
        seleccion.addWidget(QLabel("Periodo"))
        seleccion.addWidget(self.periodo)
        seleccion.addSpacing(16)
        seleccion.addWidget(QLabel("Docente"))
        seleccion.addWidget(self.docente, 1)

        # --- versiones ---
        self.versiones = Tabla(
            [
                Columna("Versión", lambda h: h["version"]),
                Columna("Estado", lambda h: h["estado"], estado=True),
                Columna("Horas", lambda h: f"{h['horas']:g}"),
                Columna("Confirmado", lambda h: _fecha_hora(h["confirmado_en"])),
            ]
        )
        self.boton_nueva = QPushButton("Nueva versión", objectName="primario")
        self.boton_nueva.setVisible(self.puede_editar)
        cabecera = self.versiones.horizontalHeader()
        for col in range(3):
            cabecera.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        panel_versiones = QWidget()
        capa_v = QVBoxLayout(panel_versiones)
        capa_v.setContentsMargins(0, 0, 8, 0)
        capa_v.addWidget(QLabel("Versiones (historial)", objectName="suave"))
        capa_v.addWidget(self.versiones, 1)
        capa_v.addWidget(self.boton_nueva)

        # --- cuadrícula ---
        self.estado = QLabel("", objectName="estado")
        self.estado.setWordWrap(True)
        self.cuadricula = QTableWidget(len(HORAS), len(DIAS), objectName="cuadricula")
        self.cuadricula.setHorizontalHeaderLabels(TITULOS_DIAS)
        self.cuadricula.setVerticalHeaderLabels([f"{h:02d}:00–{h + 1:02d}:00" for h in HORAS])
        self.cuadricula.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cuadricula.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.cuadricula.verticalHeader().setDefaultSectionSize(42)
        self.cuadricula.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cuadricula.setWordWrap(True)
        self.advertencias = QLabel("", objectName="advertencia", wordWrap=True)
        self.boton_guardar = QPushButton("Guardar cambios", objectName="primario")
        self.boton_descartar = QPushButton("Descartar borrador")
        self.boton_confirmar = QPushButton("Confirmar como vigente")
        self.boton_guardar.setVisible(self.puede_editar)
        self.boton_descartar.setVisible(self.puede_editar)
        self.boton_confirmar.setVisible(self.puede_confirmar)
        acciones = QHBoxLayout()
        acciones.addWidget(
            QLabel("Doble clic en una celda para editarla; Supr para vaciar.", objectName="suave")
        )
        acciones.addStretch()
        for b in (self.boton_descartar, self.boton_guardar, self.boton_confirmar):
            acciones.addWidget(b)
        panel_cuadricula = QWidget()
        capa_c = QVBoxLayout(panel_cuadricula)
        capa_c.setContentsMargins(8, 0, 0, 0)
        capa_c.addWidget(self.estado)
        capa_c.addWidget(self.cuadricula, 1)
        capa_c.addWidget(self.advertencias)
        capa_c.addLayout(acciones)

        divisor = QSplitter()
        divisor.addWidget(panel_versiones)
        divisor.addWidget(panel_cuadricula)
        divisor.setSizes([340, 900])

        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 28, 32, 28)
        capa.addWidget(
            encabezado(
                "Horarios",
                "Cada cambio crea una nueva versión. Solo los borradores se editan; un "
                "administrador confirma la versión vigente y la anterior queda en el historial.",
            )
        )
        capa.addLayout(seleccion)
        capa.addWidget(divisor, 1)

        self.periodo.currentIndexChanged.connect(self.cargar_versiones)
        self.docente.activated.connect(self.cargar_versiones)
        self.versiones.itemSelectionChanged.connect(self._version_elegida)
        self.boton_nueva.clicked.connect(self.nueva_version)
        self.boton_guardar.clicked.connect(self.guardar)
        self.boton_descartar.clicked.connect(self.descartar)
        self.boton_confirmar.clicked.connect(self.confirmar_vigente)
        self.cuadricula.cellDoubleClicked.connect(self.editar_celda)
        QShortcut(QKeySequence.Delete, self.cuadricula, self.vaciar_seleccion)
        QShortcut(QKeySequence(Qt.Key_Backspace), self.cuadricula, self.vaciar_seleccion)

        self.recargar()

    # --- carga -------------------------------------------------------------------

    def recargar(self) -> None:
        try:
            periodos = self.api.get("/periodos")
            docentes = self.api.get("/docentes")
            for clave in ("asignaturas", "grupos", "aulas"):
                self.catalogos[clave] = self.api.get(f"/{clave}")
        except ErrorApi as error:
            mostrar_error(self, error, "No se pudo cargar la información")
            return
        self.nombres = {k: {r["id"]: r for r in v} for k, v in self.catalogos.items()}

        self.periodo.blockSignals(True)
        self.periodo.clear()
        for p in periodos:
            marca = (
                " (activo)"
                if p["estado"] == "activo"
                else (" (cerrado)" if p["estado"] == "cerrado" else "")
            )
            self.periodo.addItem(p["nombre"] + marca, p)
        activo = next((i for i, p in enumerate(periodos) if p["estado"] == "activo"), 0)
        self.periodo.setCurrentIndex(activo)
        self.periodo.blockSignals(False)

        self.docente.blockSignals(True)
        self.docente.clear()
        for d in docentes:
            self.docente.addItem(d["nombre"] + ("" if d["activo"] else " (inactivo)"), d)
        self.docente.blockSignals(False)
        self.cargar_versiones()

    def _periodo(self) -> dict | None:
        return self.periodo.currentData()

    def _docente(self) -> dict | None:
        return self.docente.currentData()

    def cargar_versiones(self, *_args, seleccionar: int | None = None) -> None:
        if not self._puede_salir():
            return
        periodo, docente = self._periodo(), self._docente()
        self.horario = None
        if not periodo or not docente:
            self.versiones.cargar([])
            self._mostrar()
            return
        try:
            versiones = self.api.get(
                "/horarios", docente_id=docente["id"], periodo_id=periodo["id"]
            )
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self.versiones.cargar(versiones)
        objetivo = seleccionar or next(
            (v["id"] for v in versiones if v["estado"] == "vigente"),
            versiones[0]["id"] if versiones else None,
        )
        self.versiones.blockSignals(True)
        if objetivo:
            self.versiones.seleccionar_id(objetivo)
        self.versiones.blockSignals(False)
        self._cargar_horario(objetivo)

    def _version_elegida(self) -> None:
        fila = self.versiones.seleccionado()
        if fila is None or (self.horario and fila["id"] == self.horario["id"]):
            return
        if not self._puede_salir():
            self.versiones.blockSignals(True)
            self.versiones.seleccionar_id(self.horario["id"])
            self.versiones.blockSignals(False)
            return
        self._cargar_horario(fila["id"])

    def _cargar_horario(self, id_: int | None) -> None:
        self.horario = None
        if id_ is not None:
            try:
                self.horario = self.api.get(f"/horarios/{id_}")
            except ErrorApi as error:
                mostrar_error(self, error)
        self._mostrar()

    # --- presentación ------------------------------------------------------------

    def _editable(self) -> bool:
        return bool(
            self.puede_editar
            and self.horario
            and self.horario["estado"] == "borrador"
            and self.horario["periodo"]["estado"] != "cerrado"
        )

    def _mostrar(self) -> None:
        self.cambios_pendientes = False
        self.celdas = {}
        self.advertencias.setText("")
        periodo = self._periodo()
        if self.horario:
            try:
                self.celdas = bloques_a_celdas(self.horario["bloques"])
            except CuadriculaNoCompatible as error:
                mostrar_error(
                    self, ErrorApi(f"Este horario no se puede mostrar en la cuadrícula: {error}")
                )
            avisos = self.horario.get("advertencias") or []
            if avisos:
                self.advertencias.setText("⚠ " + "\n⚠ ".join(avisos))
        self._pintar_cuadricula()
        self._actualizar_estado()
        self.boton_nueva.setEnabled(
            bool(
                self._docente()
                and periodo
                and periodo["estado"] != "cerrado"
                and self._docente()["activo"]
            )
        )

    def _pintar_cuadricula(self) -> None:
        self.cuadricula.clearContents()
        for (dia, hora), celda in self.celdas.items():
            asignatura = self.nombres["asignaturas"].get(celda.asignatura_id, {})
            grupo = self.nombres["grupos"].get(celda.grupo_id, {}).get("clave") or (
                f"{celda.grupo_letra}?" if celda.grupo_letra else None
            )
            aula = self.nombres["aulas"].get(celda.aula_id, {}).get("clave")
            # En la celda va lo esencial ("A · M01"); el detalle completo, al pasar el mouse.
            breve = " · ".join(x for x in (grupo, aula) if x)
            item = QTableWidgetItem(
                "\n".join(x for x in (asignatura.get("nombre", "?"), breve) if x)
            )
            item.setToolTip(
                f"{asignatura.get('nombre', '?')}\nGrupo: {grupo or '—'}\nAula: {aula or '—'}"
            )
            item.setTextAlignment(Qt.AlignCenter)
            item.setBackground(_color_asignatura(celda.asignatura_id))
            item.setForeground(QColor("#1f2937"))
            self.cuadricula.setItem(HORAS.index(hora), DIAS.index(dia), item)

    def _actualizar_estado(self) -> None:
        h = self.horario
        if h is None:
            docente = self._docente()
            self.estado.setText(
                "Sin horario registrado para este periodo." if docente else "Elige un docente."
            )
            self.estado.setStyleSheet("")
        else:
            nombre = NOMBRES_ESTADO.get(h["estado"], h["estado"])
            texto = f"Versión {h['version']} · {nombre} · {h['horas']:g} h por semana"
            if h["estado"] == "borrador" and self.cambios_pendientes:
                texto += " · cambios sin guardar"
            if h["periodo"]["estado"] == "cerrado":
                texto += " · periodo cerrado (solo lectura)"
            elif h["estado"] in ("vigente", "historico"):
                texto += " · para cambiarla crea una nueva versión"
            self.estado.setText(texto)
            self.estado.setStyleSheet(
                f"color: {COLORES_ESTADO.get(h['estado'], '')}; font-weight: 600;"
            )
        editable = self._editable()
        self.boton_guardar.setEnabled(editable and self.cambios_pendientes)
        self.boton_descartar.setEnabled(editable)
        self.boton_confirmar.setEnabled(
            bool(
                h
                and h["estado"] == "borrador"
                and h["periodo"]["estado"] != "cerrado"
                and self.puede_confirmar
                and not self.cambios_pendientes
                and h["bloques"]
            )
        )

    # --- edición -------------------------------------------------------------------

    def editar_celda(self, fila: int, columna: int) -> None:
        if not self._editable():
            return
        dia, hora = DIAS[columna], HORAS[fila]
        periodo = self._periodo() or {}
        catalogos = {
            **self.catalogos,
            "grupos": [
                g
                for g in self.catalogos["grupos"]
                if g.get("periodo_id") in (None, periodo.get("id"))
            ],
        }
        dialogo = DialogoCelda(catalogos, self.celdas.get((dia, hora)), dia, hora, self)
        resultado = dialogo.exec()
        if resultado == DialogoCelda.VACIAR:
            self.celdas.pop((dia, hora), None)
        elif resultado == QDialog.Accepted and dialogo.celda():
            for h in range(hora, hora + dialogo.horas.value()):
                self.celdas[(dia, h)] = dialogo.celda()
        else:
            return
        self._marcar_cambio()

    def vaciar_seleccion(self) -> None:
        if not self._editable():
            return
        indices = self.cuadricula.selectedIndexes()
        for i in indices:
            self.celdas.pop((DIAS[i.column()], HORAS[i.row()]), None)
        if indices:
            self._marcar_cambio()

    def _marcar_cambio(self) -> None:
        self.cambios_pendientes = True
        self._pintar_cuadricula()
        self._actualizar_estado()

    def _puede_salir(self) -> bool:
        if not self.cambios_pendientes:
            return True
        if confirmar(self, "Hay cambios sin guardar en el borrador.", "¿Descartarlos?"):
            self.cambios_pendientes = False
            return True
        return False

    # --- acciones --------------------------------------------------------------------

    def nueva_version(self) -> None:
        periodo, docente = self._periodo(), self._docente()
        if not periodo or not docente or not self._puede_salir():
            return
        vigente = next((v for v in self.versiones.filas if v["estado"] == "vigente"), None)
        datos = {"docente_id": docente["id"], "periodo_id": periodo["id"]}
        if vigente:
            datos["basado_en_id"] = vigente["id"]
        try:
            nuevo = self.api.post("/horarios", datos)
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self.cargar_versiones(seleccionar=nuevo["id"])

    def guardar(self) -> bool:
        if not self.horario:
            return False
        try:
            self.horario = self.api.put(
                f"/horarios/{self.horario['id']}/bloques", celdas_a_bloques(self.celdas)
            )
        except ErrorApi as error:
            mostrar_error(self, error, "El horario no se guardó")
            return False
        self.cambios_pendientes = False
        self.cargar_versiones(seleccionar=self.horario["id"])
        return True

    def descartar(self) -> None:
        if not self.horario or not confirmar(
            self,
            f"¿Descartar el borrador versión {self.horario['version']}?",
            "Quedará en el historial como descartado.",
        ):
            return
        try:
            self.api.post(f"/horarios/{self.horario['id']}/descartar")
        except ErrorApi as error:
            mostrar_error(self, error)
        self.cambios_pendientes = False
        self.cargar_versiones(seleccionar=self.horario["id"])

    def _pedir_vigencia(self) -> str | None | bool:
        """Si ya hay una versión vigente, pregunta desde cuándo rige la nueva.

        Devuelve la fecha (texto ISO), None si no hace falta preguntar, o False si se canceló.
        """
        if not any(v["estado"] == "vigente" for v in self.versiones.filas):
            return None
        dialogo = DialogoFormulario(
            "Fecha de vigencia",
            [Campo("vigente_desde", "La nueva versión rige desde", "fecha")],
            {"vigente_desde": date.today().isoformat()},
            padre=self,
        )
        return dialogo.valores()["vigente_desde"] if dialogo.exec() else False

    def confirmar_vigente(self, aceptar: bool = False, vigente_desde: str | None = None) -> None:
        if not self.horario:
            return
        if not aceptar:
            if not confirmar(
                self,
                f"¿Confirmar la versión {self.horario['version']} como vigente?",
                "La versión vigente actual pasará al historial. Los días anteriores de la "
                "bitácora seguirán usando el horario que regía entonces.",
            ):
                return
            vigente_desde = self._pedir_vigencia()
            if vigente_desde is False:
                return
        datos = {"aceptar_advertencias": aceptar}
        if vigente_desde:
            datos["vigente_desde"] = vigente_desde
        try:
            self.api.post(f"/horarios/{self.horario['id']}/confirmar", datos)
        except ErrorApi as error:
            if error.estado == 409 and error.problemas and not aceptar:
                detalle = "\n".join(f"• {p}" for p in error.problemas)
                if confirmar(self, "Hay advertencias. ¿Confirmar de todos modos?", detalle):
                    self.confirmar_vigente(aceptar=True, vigente_desde=vigente_desde)
                return
            mostrar_error(self, error)
            return
        self.cargar_versiones(seleccionar=self.horario["id"])
