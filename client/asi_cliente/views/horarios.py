"""Pantalla de horarios: versiones por docente y periodo, y editor de cuadrícula semanal.

Flujo:
1. Elegir periodo y docente: se listan todas sus versiones (historial).
2. "Nueva versión" crea un borrador (copia de la vigente, si existe).
3. En el borrador se agregan, corrigen o eliminan clases (botones o doble clic en la
   cuadrícula) y se guarda. Las horas ocupadas y las clases repetidas se avisan antes.
4. Un administrador lo confirma como vigente; la versión anterior pasa a histórico.

La captura manual y la importación por OCR trabajan sobre las mismas versiones: ninguna
crea un horario aparte. Cada semestre es otro periodo con sus propias versiones; la
asistencia ya registrada conserva su copia del horario que regía ese día.
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
    QTabWidget,
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
    mostrar_primera_clase,
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
    informar,
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


def _hora_texto(hora: int) -> str:
    return f"{hora:02d}:00"


class DialogoClase(QDialog):
    """Agregar o corregir una clase: día, hora de inicio y de fin, materia, grupo y aula."""

    def __init__(self, catalogos: dict, clase: dict | None = None, padre=None):
        super().__init__(padre)
        self.setWindowTitle("Corregir clase" if clase else "Agregar clase")
        self.setMinimumWidth(420)
        self.catalogos = catalogos
        self.dia = QComboBox()
        for dia, titulo in zip(DIAS, TITULOS_DIAS, strict=True):
            self.dia.addItem(titulo, dia)
        self.inicio, self.fin = QComboBox(), QComboBox()
        for h in HORAS:
            self.inicio.addItem(_hora_texto(h), h)
            self.fin.addItem(_hora_texto(h + 1), h + 1)
        self.asignatura = DialogoCelda._combo(catalogos["asignaturas"], "nombre", opcional=False)
        self.grupo = DialogoCelda._combo(catalogos["grupos"], "clave", opcional=True)
        self.aula = DialogoCelda._combo(catalogos["aulas"], "clave", opcional=True)
        celda = clase["celda"] if clase else None
        if celda and celda.grupo_letra:
            self.grupo.insertItem(
                1,
                f"Letra «{celda.grupo_letra}» (pendiente de validar)",
                f"letra:{celda.grupo_letra}",
            )
        if clase:
            self.dia.setCurrentIndex(DIAS.index(clase["dia"]))
            self.inicio.setCurrentIndex(self.inicio.findData(clase["inicio"]))
            self.fin.setCurrentIndex(self.fin.findData(clase["fin"]))
            grupo = celda.grupo_id or (f"letra:{celda.grupo_letra}" if celda.grupo_letra else None)
            for combo, valor in (
                (self.asignatura, celda.asignatura_id),
                (self.grupo, grupo),
                (self.aula, celda.aula_id),
            ):
                combo.setCurrentIndex(max(combo.findData(valor), 0))
        else:
            self.fin.setCurrentIndex(1)
        self.inicio.currentIndexChanged.connect(self._ajustar_fin)
        formulario = QFormLayout()
        formulario.addRow("Día", self.dia)
        formulario.addRow("Hora de inicio", self.inicio)
        formulario.addRow("Hora de fin", self.fin)
        formulario.addRow("Asignatura / actividad", self.asignatura)
        formulario.addRow("Grupo", self.grupo)
        formulario.addRow("Aula", self.aula)
        self.mensaje = QLabel("", objectName="error", wordWrap=True)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Aplicar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        capa.addLayout(formulario)
        capa.addWidget(
            QLabel(
                "Los cambios se aplican al borrador; usa «Guardar cambios» para guardarlos.",
                objectName="ayuda",
                wordWrap=True,
            )
        )
        capa.addWidget(self.mensaje)
        capa.addWidget(botones)

    def _ajustar_fin(self) -> None:
        if self.fin.currentData() <= self.inicio.currentData():
            self.fin.setCurrentIndex(self.fin.findData(self.inicio.currentData() + 1))

    def clase(self) -> dict | None:
        asignatura = self.asignatura.currentData()
        if asignatura is None:
            return None
        grupo = self.grupo.currentData()
        if isinstance(grupo, str) and grupo.startswith("letra:"):
            celda = Celda(asignatura, None, self.aula.currentData(), grupo.removeprefix("letra:"))
        else:
            celda = Celda(asignatura, grupo, self.aula.currentData())
        return {
            "dia": self.dia.currentData(),
            "inicio": self.inicio.currentData(),
            "fin": self.fin.currentData(),
            "celda": celda,
        }

    def problema(self) -> str:
        clase = self.clase()
        if clase is None:
            return "Elige la asignatura o actividad."
        if clase["fin"] <= clase["inicio"]:
            return "La hora de fin debe ser posterior a la de inicio."
        tipo = next(
            (
                a.get("tipo")
                for a in self.catalogos["asignaturas"]
                if a["id"] == clase["celda"].asignatura_id
            ),
            None,
        )
        if tipo == "materia" and not (clase["celda"].grupo_id or clase["celda"].grupo_letra):
            return "Una materia necesita grupo."
        return ""

    def _aceptar(self) -> None:
        problema = self.problema()
        if problema:
            self.mensaje.setText(problema)
            return
        self.accept()


class VistaHorarios(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api = api
        self.puede_editar = usuario.puede("horarios.editar")
        self.puede_confirmar = usuario.puede("horarios.confirmar")
        self.puede_docentes = usuario.puede("docentes.editar")
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
        self.boton_docente = QPushButton("Nuevo docente…")
        self.boton_docente.setToolTip("Agregar al catálogo un docente que todavía no existe")
        self.boton_docente.setVisible(self.puede_docentes)
        seleccion.addWidget(self.boton_docente)

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
        self.boton_vigencia = QPushButton("Fechas de vigencia…")
        self.boton_vigencia.setToolTip("Confirmar o corregir desde qué fecha aplica esta versión")
        self.boton_vigencia.setVisible(self.puede_confirmar)
        self.boton_guardar.setVisible(self.puede_editar)
        self.boton_descartar.setVisible(self.puede_editar)
        self.boton_confirmar.setVisible(self.puede_confirmar)
        self.ayuda_cuadricula = QLabel(
            "Agrega clases con su día y horas, o haz doble clic en una celda; tecla Supr "
            "para vaciarla. Recuerda «Guardar cambios».",
            objectName="ayuda",
            wordWrap=True,
        )
        self.boton_agregar = QPushButton("Agregar clase…")
        self.boton_editar_clase = QPushButton("Editar clase…")
        self.boton_eliminar_clase = QPushButton("Eliminar clase")
        for b in (self.boton_agregar, self.boton_editar_clase, self.boton_eliminar_clase):
            b.setVisible(self.puede_editar)
        self.lista = Tabla(
            [
                Columna("Día", lambda b: TITULOS_DIAS[DIAS.index(b["dia"])]),
                Columna("Inicio", lambda b: b["hora_inicio"]),
                Columna("Fin", lambda b: b["hora_fin"]),
                Columna("Asignatura / actividad", lambda b: b["asignatura"]),
                Columna("Grupo", lambda b: b["grupo"]),
                Columna("Aula", lambda b: b["aula"]),
                Columna("Horas", lambda b: b["horas"]),
            ],
            "Este horario no tiene clases. Usa «Agregar clase…».",
        )
        self.vistas = QTabWidget()
        self.vistas.addTab(self.cuadricula, "Semana")
        self.vistas.addTab(self.lista, "Lista de clases")
        self.ayuda_cuadricula.setVisible(self.puede_editar)
        acciones_clase = QHBoxLayout()
        for b in (self.boton_agregar, self.boton_editar_clase, self.boton_eliminar_clase):
            acciones_clase.addWidget(b)
        acciones_clase.addStretch()
        acciones = QHBoxLayout()
        acciones.addStretch()
        for b in (
            self.boton_vigencia,
            self.boton_descartar,
            self.boton_guardar,
            self.boton_confirmar,
        ):
            acciones.addWidget(b)
        panel_cuadricula = QWidget()
        capa_c = QVBoxLayout(panel_cuadricula)
        capa_c.setContentsMargins(8, 0, 0, 0)
        capa_c.addWidget(self.estado)
        capa_c.addWidget(self.vistas, 1)
        capa_c.addLayout(acciones_clase)
        capa_c.addWidget(self.ayuda_cuadricula)
        capa_c.addWidget(self.advertencias)
        capa_c.addLayout(acciones)

        divisor = QSplitter()
        divisor.addWidget(panel_versiones)
        divisor.addWidget(panel_cuadricula)
        divisor.setSizes([300, 900])
        panel_versiones.setMinimumWidth(280)

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
        self.boton_vigencia.clicked.connect(self.confirmar_fechas)
        self.cuadricula.cellDoubleClicked.connect(self.editar_celda)
        self.boton_docente.clicked.connect(self.nuevo_docente)
        self.boton_agregar.clicked.connect(self.agregar_clase)
        self.boton_editar_clase.clicked.connect(self.editar_clase)
        self.boton_eliminar_clase.clicked.connect(self.eliminar_clase)
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
        mostrar_primera_clase(self.cuadricula, [h for _d, h in self.celdas])
        self.lista.cargar(self._clases())

    def _clases(self) -> list[dict]:
        """Las clases del horario (bloques continuos), para la lista y para editarlas."""
        clases = []
        for b in celdas_a_bloques(self.celdas):
            celda = Celda(b["asignatura_id"], b["grupo_id"], b["aula_id"], b["grupo_letra"])
            grupo = self.nombres["grupos"].get(b["grupo_id"], {}).get("clave") or (
                f"{b['grupo_letra']} (pendiente)" if b["grupo_letra"] else ""
            )
            inicio, fin = int(b["hora_inicio"][:2]), int(b["hora_fin"][:2])
            clases.append(
                {
                    **b,
                    "inicio": inicio,
                    "fin": fin,
                    "celda": celda,
                    "horas": fin - inicio,
                    "asignatura": self.nombres["asignaturas"]
                    .get(b["asignatura_id"], {})
                    .get("nombre", "?"),
                    "grupo": grupo,
                    "aula": self.nombres["aulas"].get(b["aula_id"], {}).get("clave", ""),
                }
            )
        return clases

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
            if h["estado"] in ("vigente", "historico"):
                texto += (
                    f" · vigencia confirmada: {h['vigente_desde']} a "
                    f"{h['vigente_hasta'] or 'sin fecha final'}"
                    if h.get("vigencia_confirmada")
                    else " · VIGENCIA DESCONOCIDA: excluida de consultas por fecha"
                )
            self.estado.setText(texto)
            self.estado.setStyleSheet(
                f"color: {COLORES_ESTADO.get(h['estado'], '')}; font-weight: 600;"
            )
        editable = self._editable()
        con_docente = bool(self._docente() and self._periodo())
        self.boton_agregar.setEnabled(con_docente)
        self.boton_editar_clase.setEnabled(bool(self.celdas))
        self.boton_eliminar_clase.setEnabled(bool(self.celdas))
        self.boton_vigencia.setEnabled(bool(h and h["estado"] in ("vigente", "historico")))
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

    # --- clases (captura manual) ----------------------------------------------------

    def _catalogos_periodo(self) -> dict:
        periodo = self._periodo() or {}
        return {
            **self.catalogos,
            "grupos": [
                g
                for g in self.catalogos["grupos"]
                if g.get("periodo_id") in (None, periodo.get("id"))
            ],
        }

    def _asegurar_borrador(self) -> bool:
        """Solo los borradores se editan: si se ve una versión oficial, ofrece crear otra."""
        if self._editable():
            return True
        if not self.puede_editar or not self._docente() or not self._periodo():
            return False
        if self.horario and self.horario["estado"] == "borrador":
            return False  # borrador de un periodo cerrado
        if self.horario and not confirmar(
            self,
            "Para cambiar el horario se crea una nueva versión (borrador).",
            "La versión actual no se modifica: queda igual hasta que confirmes la nueva. "
            "La asistencia ya registrada conserva el horario que regía ese día.",
            "Crear nueva versión",
        ):
            return False
        self.nueva_version()
        return self._editable()

    def _clase_elegida(self) -> dict | None:
        clases = self._clases()
        if self.vistas.currentWidget() is self.lista:
            fila = self.lista.seleccionado()
            return next(
                (
                    c
                    for c in clases
                    if fila and (c["dia"], c["inicio"]) == (fila["dia"], fila["inicio"])
                ),
                None,
            )
        fila, columna = self.cuadricula.currentRow(), self.cuadricula.currentColumn()
        if fila < 0 or columna < 0:
            return None
        dia, hora = DIAS[columna], HORAS[fila]
        return next((c for c in clases if c["dia"] == dia and c["inicio"] <= hora < c["fin"]), None)

    def _colocar(self, clase: dict, anterior: dict | None = None) -> bool:
        """Pone la clase en sus horas. Avisa si repite una clase o si ocupa horas con otra."""
        dia, horas = clase["dia"], range(clase["inicio"], clase["fin"])
        propias = (
            set(range(anterior["inicio"], anterior["fin"]))
            if anterior and anterior["dia"] == dia
            else set()
        )
        ocupadas = {
            h: self.celdas[(dia, h)] for h in horas if (dia, h) in self.celdas and h not in propias
        }
        titulo = TITULOS_DIAS[DIAS.index(dia)]
        if ocupadas and all(c == clase["celda"] for c in ocupadas.values()) and not anterior:
            informar(
                self,
                "Esa clase ya está en el horario",
                f"{titulo} de {_hora_texto(min(ocupadas))} a {_hora_texto(max(ocupadas) + 1)} "
                "ya tiene esa misma clase: no se duplicó.",
            )
            return False
        if ocupadas:
            detalle = "\n".join(
                f"• {titulo} {_hora_texto(h)}–{_hora_texto(h + 1)}: "
                + self.nombres["asignaturas"].get(c.asignatura_id, {}).get("nombre", "?")
                for h, c in sorted(ocupadas.items())
            )
            if not confirmar(
                self,
                "Esas horas ya tienen otra clase en este horario.",
                detalle + "\n\n¿Reemplazarlas por la nueva clase?",
                "Reemplazar",
            ):
                return False
        if anterior:
            for h in range(anterior["inicio"], anterior["fin"]):
                self.celdas.pop((anterior["dia"], h), None)
        for h in horas:
            self.celdas[(dia, h)] = clase["celda"]
        self._marcar_cambio()
        return True

    def agregar_clase(self) -> None:
        if not self._asegurar_borrador():
            return
        dialogo = DialogoClase(self._catalogos_periodo(), None, self)
        while dialogo.exec():
            if self._colocar(dialogo.clase()):
                return

    def editar_clase(self) -> None:
        elegida = self._clase_elegida()
        if elegida is None:
            informar(self, "Elige una clase", "Selecciónala en la cuadrícula o en la lista.")
            return
        if not self._asegurar_borrador():
            return
        elegida = self._clase_elegida() or elegida  # el borrador nuevo copia las mismas clases
        dialogo = DialogoClase(self._catalogos_periodo(), elegida, self)
        while dialogo.exec():
            if self._colocar(dialogo.clase(), anterior=elegida):
                return

    def eliminar_clase(self) -> None:
        elegida = self._clase_elegida()
        if elegida is None:
            informar(self, "Elige una clase", "Selecciónala en la cuadrícula o en la lista.")
            return
        cuando = (
            f"{TITULOS_DIAS[DIAS.index(elegida['dia'])]} {_hora_texto(elegida['inicio'])}–"
            f"{_hora_texto(elegida['fin'])}"
        )
        if not confirmar(
            self,
            f"¿Eliminar {elegida['asignatura']} del {cuando}?",
            "Se quita del borrador; las versiones anteriores y la asistencia ya registrada "
            "no cambian.",
            "Eliminar",
        ):
            return
        if not self._asegurar_borrador():
            return
        for h in range(elegida["inicio"], elegida["fin"]):
            self.celdas.pop((elegida["dia"], h), None)
        self._marcar_cambio()

    def nuevo_docente(self) -> None:
        dialogo = DialogoFormulario(
            "Nuevo docente",
            [
                Campo("nombre", "Nombre (apellidos y nombres)", obligatorio=True),
                Campo("nomina", "Nómina"),
            ],
            padre=self,
        )
        while dialogo.exec():
            datos = {k: v for k, v in dialogo.valores().items() if v}
            try:
                docente = self.api.post("/docentes", datos)
            except ErrorApi as error:
                mostrar_error(self, error, "El docente no se agregó")
                continue
            self.recargar()
            indice = next(
                (
                    i
                    for i in range(self.docente.count())
                    if (self.docente.itemData(i) or {}).get("id") == docente["id"]
                ),
                -1,
            )
            if indice >= 0:
                self.docente.setCurrentIndex(indice)
                self.cargar_versiones()
            return

    def _version_de_otro_periodo(self) -> dict | None:
        """La versión oficial más reciente del docente en otro periodo (semestre anterior)."""
        periodo, docente = self._periodo(), self._docente()
        try:
            versiones = self.api.get("/horarios", docente_id=docente["id"])
        except ErrorApi:
            return None
        otras = [
            v
            for v in versiones
            if v["periodo"]["id"] != periodo["id"] and v["estado"] in ("vigente", "historico")
        ]
        otras.sort(key=lambda v: (v["periodo"]["id"], v["estado"] == "vigente", v["version"]))
        return otras[-1] if otras else None

    def _copiar_clases(self, origen: dict, destino_id: int) -> None:
        """Copia materias, horas y aulas. Los grupos cambian cada semestre: queda la letra
        pendiente de validar, para asignar el grupo del periodo nuevo."""
        letras = {g["id"]: g.get("letra") for g in self.catalogos["grupos"]}
        bloques = []
        for b in self.api.get(f"/horarios/{origen['id']}")["bloques"]:
            letra = letras.get(b["grupo"]["id"]) if b.get("grupo") else b.get("grupo_letra")
            bloques.append(
                {
                    "dia": b["dia"],
                    "hora_inicio": b["hora_inicio"],
                    "hora_fin": b["hora_fin"],
                    "asignatura_id": b["asignatura"]["id"],
                    "grupo_id": None,
                    "grupo_letra": letra,
                    "aula_id": b["aula"]["id"] if b.get("aula") else None,
                }
            )
        self.api.put(f"/horarios/{destino_id}/bloques", bloques)

    # --- acciones --------------------------------------------------------------------

    def nueva_version(self) -> None:
        periodo, docente = self._periodo(), self._docente()
        if not periodo or not docente or not self._puede_salir():
            return
        vigente = next((v for v in self.versiones.filas if v["estado"] == "vigente"), None)
        datos = {"docente_id": docente["id"], "periodo_id": periodo["id"]}
        copiar = None
        if vigente:
            datos["basado_en_id"] = vigente["id"]
        elif (anterior := self._version_de_otro_periodo()) and confirmar(
            self,
            f"¿Copiar las clases de {anterior['periodo']['nombre']} como punto de partida?",
            "Se copian materias, días, horas y aulas. Los grupos cambian cada semestre: "
            "queda solo la letra, pendiente de asignar al grupo del periodo nuevo. El "
            "horario del periodo anterior no se modifica.",
            "Sí, copiar",
        ):
            copiar = anterior
        try:
            nuevo = self.api.post("/horarios", datos)
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        if copiar:
            try:
                self._copiar_clases(copiar, nuevo["id"])
            except ErrorApi as error:
                mostrar_error(self, error, "El borrador se creó vacío: no se copiaron las clases")
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
        """Solicita siempre una fecha real explícita; False indica cancelación."""
        dialogo = DialogoFormulario(
            "Confirma la fecha real de vigencia (no se deduce del periodo)",
            [Campo("vigente_desde", "La nueva versión rige desde", "fecha")],
            {"vigente_desde": date.today().isoformat()},
            padre=self,
        )
        return dialogo.valores()["vigente_desde"] if dialogo.exec() else False

    def confirmar_fechas(self):
        if not self.horario or not self.puede_confirmar:
            return
        h = self.horario
        dialogo = DialogoFormulario(
            "Fechas reales verificadas: no se modifican los bloques",
            [
                Campo("desde", "Inicio real (AAAA-MM-DD)", obligatorio=True),
                Campo(
                    "hasta",
                    "Fin real (obligatorio para históricos)",
                    obligatorio=h["estado"] == "historico",
                ),
                Campo("motivo", "Motivo y evidencia de las fechas", obligatorio=True),
            ],
            {"desde": h.get("vigente_desde"), "hasta": h.get("vigente_hasta")},
            padre=self,
        )
        while dialogo.exec():
            try:
                self.api.post(f"/horarios/{h['id']}/vigencia", dialogo.valores())
            except ErrorApi as e:
                mostrar_error(self, e)
                continue
            self.cargar_versiones(seleccionar=h["id"])
            break

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
