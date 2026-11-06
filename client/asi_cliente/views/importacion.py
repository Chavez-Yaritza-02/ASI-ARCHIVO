"""Pantalla de importación de horarios desde PDF y revisión de lo leído.

1. Elegir periodo e "Importar archivo…" (ZIP con PDFs o un PDF). El OCR corre en el
   servidor; aquí solo se muestra el avance.
2. Elegir una página: se ven el encabezado leído, los avisos, lo que falta revisar y
   la cuadrícula con colores según el estado de cada celda.
3. Doble clic en una celda: imagen del documento, texto leído y valores asignados
   (asignatura, grupo, aula, día y hora), con opción de crear un registro nuevo.
4. Si la misma lectura del OCR se repite en la página, una corrección puede aplicarse a
   todas las celdas con ese texto (con pregunta previa y opción de deshacer).
5. "Aprobar" crea un horario en *borrador*; se confirma después en Horarios.
"""

import copy
import re
import unicodedata
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.cuadricula import DIAS, HORAS, TITULOS_DIAS, mostrar_primera_clase
from asi_cliente.views.comunes import Columna, Tabla, confirmar, encabezado, mostrar_error

RESUELTOS = ("coincide", "confirmado")
COLORES = {  # fondo de la celda según su estado
    "ok": "#bbf7d0",
    "sugerido": "#fde68a",
    "falta": "#fecaca",
    "grupo": "#ddd6fe",
}
NOMBRES_ESTADO_PAGINA = {
    "por_revisar": "Por revisar",
    "aprobada": "Aprobada",
    "descartada": "Descartada",
    "duplicada": "Duplicada",
    "error": "Error",
}
COLORES_ESTADO_PAGINA = {
    "por_revisar": "#d97706",
    "aprobada": "#16a34a",
    "descartada": "#6b7280",
    "duplicada": "#6b7280",
    "error": "#b91c1c",
}
TEXTO_ESTADO_CAMPO = {
    "coincide": "coincide con el catálogo",
    "confirmado": "confirmado",
    "sugerido": "SUGERIDO: revisa y acepta",
    "sin_coincidencia": "SIN COINCIDENCIA: elige",
    "vacio": "el documento no lo trae",
    "pendiente": "solo la letra: pendiente de validar",
}


def estado_campo(c: dict, campo: str) -> str:
    """Estado de la asignatura o el aula de una celda: falta | sugerido | ok.

    `sugerencia_<campo>` es una coincidencia aproximada calculada con los catálogos
    actuales: se pinta en amarillo y no cuenta hasta que el usuario la acepta.
    """
    if campo == "asignatura":
        if c["asignatura_id"] is None:
            return "sugerido" if c.get("sugerencia_asignatura") else "falta"
        return "sugerido" if c["asignatura_estado"] == "sugerido" else "ok"
    if c["aula_id"] is None and c["aula_estado"] == "sin_coincidencia":
        return "sugerido" if c.get("sugerencia_aula") else "falta"
    return "sugerido" if c["aula_estado"] == "sugerido" else "ok"


def estado_celda(c: dict) -> str:
    """Resume la celda en: falta | sugerido | grupo | ok (para el color)."""
    estados = {estado_campo(c, "asignatura"), estado_campo(c, "aula")}
    if "falta" in estados:
        return "falta"
    if "sugerido" in estados:
        return "sugerido"
    if c["grupo_id"] is None and c["grupo_letra"]:
        return "grupo"
    return "ok"


def normal(texto: str | None) -> str:
    """Forma comparable de un texto leído: sin acentos, signos ni mayúsculas/minúsculas."""
    plano = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", plano.upper()).strip()


# Campos que se pueden corregir en bloque: texto leído por el OCR y valores asignados.
CORRECCIONES = {
    "asignatura": ("Asignatura", "actividad_texto", ("asignatura_id",)),
    "grupo": ("Grupo", "grupo_texto", ("grupo_id", "grupo_letra")),
    "aula": ("Aula", "aula_texto", ("aula_id",)),
}


def preguntar_correccion_repetida(padre, cantidad: int, detalle: str) -> str | None:
    """'una', 'todas' o None (cancelar)."""
    caja = QMessageBox(padre)
    caja.setIcon(QMessageBox.Question)
    caja.setWindowTitle("Corrección repetida")
    caja.setText(
        f"Se encontraron {cantidad} celdas con el mismo texto. "
        "¿Quieres aplicar esta corrección a todas?"
    )
    caja.setInformativeText(
        detalle + "\n\nSolo se cambia esta página. Nada se guarda hasta que pulses "
        "«Guardar revisión», y puedes deshacerlo con «Deshacer»."
    )
    una = caja.addButton("Solo esta celda", QMessageBox.NoRole)
    todas = caja.addButton("Todas las coincidencias de esta página", QMessageBox.YesRole)
    caja.addButton("Cancelar", QMessageBox.RejectRole)
    caja.setDefaultButton(todas)
    caja.exec()
    return {una: "una", todas: "todas"}.get(caja.clickedButton())


def _combo_buscable(minimo: int = 220) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.completer().setFilterMode(Qt.MatchContains)
    combo.completer().setCompletionMode(QCompleter.PopupCompletion)
    combo.setMinimumWidth(minimo)
    return combo


class DialogoCeldaImportada(QDialog):
    """Revisión de una celda: imagen original, texto leído y valores a asignar."""

    ELIMINAR = 2

    def __init__(
        self, api: ClienteApi, catalogos: dict, celda: dict | None, dia: str, hora: int, padre=None
    ):
        super().__init__(padre)
        self.api, self.catalogos = api, catalogos
        self.celda = (
            dict(celda)
            if celda
            else {
                "id": None,
                "texto_ocr": "",
                "actividad_texto": "",
                "aula_texto": None,
                "grupo_texto": None,
                "asignatura_id": None,
                "asignatura_estado": "confirmado",
                "aula_id": None,
                "aula_estado": "confirmado",
                "grupo_id": None,
                "grupo_letra": None,
                "grupo_estado": "vacio",
                "origen": "manual",
            }
        )
        self.setWindowTitle(f"{TITULOS_DIAS[DIAS.index(dia)]} {hora:02d}:00")
        self.setMinimumWidth(520)
        capa = QVBoxLayout(self)

        if self.celda["id"]:
            imagen = api.obtener_bytes(f"/importaciones/celdas/{self.celda['id']}/imagen")
            if imagen:
                vista = QLabel()
                pix = QPixmap()
                pix.loadFromData(imagen)
                vista.setPixmap(
                    pix.scaledToWidth(min(pix.width() * 2, 480), Qt.SmoothTransformation)
                )
                vista.setAlignment(Qt.AlignCenter)
                vista.setStyleSheet("background: white; border: 1px solid #d9dde3;")
                capa.addWidget(QLabel("Documento original:", objectName="suave"))
                capa.addWidget(vista)
            leido = self.celda["texto_ocr"].replace("\n", " / ")
            capa.addWidget(QLabel(f"Texto leído: {leido}", wordWrap=True, objectName="suave"))
        else:
            capa.addWidget(QLabel("Celda capturada a mano.", objectName="suave"))

        self.asignatura = self._combo(
            "asignaturas",
            "nombre",
            self.celda["asignatura_id"] or self.celda.get("sugerencia_asignatura"),
        )
        self.aula = self._combo(
            "aulas",
            "clave",
            self.celda["aula_id"] or self.celda.get("sugerencia_aula"),
            opcional=True,
        )
        self.grupo = _combo_buscable()
        self.grupo.addItem("—", None)
        if self.celda["grupo_letra"]:
            self.grupo.addItem(
                f"Letra «{self.celda['grupo_letra']}» (pendiente de validar)",
                f"letra:{self.celda['grupo_letra']}",
            )
        for g in catalogos["grupos"]:
            if g["activo"]:
                pendiente = " (pendiente)" if g["pendiente_validacion"] else ""
                self.grupo.addItem(g["clave"] + pendiente, g["id"])
        actual = self.celda["grupo_id"] or (
            f"letra:{self.celda['grupo_letra']}" if self.celda["grupo_letra"] else None
        )
        self.grupo.setCurrentIndex(max(self.grupo.findData(actual), 0))
        self.dia = QComboBox()
        for i, titulo in enumerate(TITULOS_DIAS):
            self.dia.addItem(titulo, DIAS[i])
        self.dia.setCurrentIndex(DIAS.index(dia))
        self.hora = QComboBox()
        for h in HORAS:
            self.hora.addItem(f"{h:02d}:00–{h + 1:02d}:00", h)
        self.hora.setCurrentIndex(HORAS.index(hora))

        nueva_asignatura = QPushButton("Nueva…")
        nueva_aula = QPushButton("Nueva…")
        nueva_asignatura.clicked.connect(self._nueva_asignatura)
        nueva_aula.clicked.connect(self._nueva_aula)
        formulario = QFormLayout()
        formulario.addRow(
            "Asignatura",
            self._fila(self.asignatura, nueva_asignatura, "asignatura"),
        )
        formulario.addRow("Grupo", self._fila(self.grupo, None, "grupo"))
        formulario.addRow("Aula", self._fila(self.aula, nueva_aula, "aula"))
        formulario.addRow("Día", self.dia)
        formulario.addRow("Hora", self.hora)
        capa.addLayout(formulario)

        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Aplicar (acepto estos valores)")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        if celda:
            eliminar = botones.addButton("Eliminar celda", QDialogButtonBox.DestructiveRole)
            eliminar.clicked.connect(lambda: self.done(self.ELIMINAR))
        botones.accepted.connect(self._aplicar)
        botones.rejected.connect(self.reject)
        self.mensaje = QLabel("", objectName="error")
        capa.addWidget(self.mensaje)
        capa.addWidget(botones)

    def _combo(self, catalogo: str, campo: str, actual, opcional: bool = False) -> QComboBox:
        combo = _combo_buscable()
        combo.addItem("—" if opcional else "(elige)", None)
        for r in self.catalogos[catalogo]:
            if r["activo"]:
                combo.addItem(r[campo], r["id"])
        combo.setCurrentIndex(max(combo.findData(actual), 0))
        return combo

    def _estado(self, campo: str) -> str:
        fuentes = {"asignatura": ("asignaturas", "nombre"), "aula": ("aulas", "clave")}
        catalogo, nombre = fuentes.get(campo, (None, None))

        def nombres(ids):
            return " o ".join(
                f"«{r[nombre]}»" for r in self.catalogos.get(catalogo, []) if r["id"] in ids
            )

        if catalogo and self.celda.get(f"sugerencia_{campo}"):
            return (
                f"SUGERIDO: {nombres([self.celda[f'sugerencia_{campo}']])} se parece a lo "
                "leído. Revisa y acepta"
            )
        if catalogo and self.celda.get(f"candidatos_{campo}"):
            return (
                f"SIN COINCIDENCIA: se parece a {nombres(self.celda[f'candidatos_{campo}'])}. "
                "Elige el correcto"
            )
        estado = self.celda[f"{campo}_estado"]
        return TEXTO_ESTADO_CAMPO.get(estado, estado)

    def _fila(self, combo, boton, campo: str) -> QWidget:
        caja = QWidget()
        capa = QVBoxLayout(caja)
        capa.setContentsMargins(0, 0, 0, 0)
        fila = QHBoxLayout()
        fila.addWidget(combo, 1)
        if boton:
            fila.addWidget(boton)
        capa.addLayout(fila)
        leido = self.celda.get(CORRECCIONES[campo][1])
        if self.celda["origen"] == "ocr":
            # Con ajuste de línea: el estado («SIN COINCIDENCIA…») se lee completo.
            capa.addWidget(
                QLabel(
                    f"Leído: «{leido or '—'}» · {self._estado(campo)}",
                    objectName="suave",
                    wordWrap=True,
                )
            )
        return caja

    def _crear(
        self,
        ruta: str,
        campo: str,
        sugerido: str,
        combo: QComboBox,
        titulo: str,
        extra: dict | None = None,
    ) -> None:
        texto, ok = QInputDialog.getText(
            self, titulo, "Nombre exacto del registro nuevo:", text=sugerido or ""
        )
        if not ok or not texto.strip():
            return
        try:
            nuevo = self.api.post(ruta, {campo: texto.strip(), **(extra or {})})
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        clave = ruta.strip("/")
        self.catalogos[clave].append(nuevo)
        combo.addItem(nuevo[campo], nuevo["id"])
        combo.setCurrentIndex(combo.count() - 1)

    def _nueva_asignatura(self) -> None:
        tipo, ok = QInputDialog.getItem(
            self, "Nueva asignatura", "Tipo:", ["Materia (con grupo)", "Actividad"], 0, False
        )
        if ok:
            self._crear(
                "/asignaturas",
                "nombre",
                self.celda["actividad_texto"],
                self.asignatura,
                "Nueva asignatura",
                {"tipo": "materia" if tipo.startswith("Materia") else "actividad"},
            )

    def _nueva_aula(self) -> None:
        self._crear("/aulas", "clave", self.celda["aula_texto"], self.aula, "Nueva aula")

    def _aplicar(self) -> None:
        if self.asignatura.currentData() is None:
            self.mensaje.setText("Elige la asignatura (o elimina la celda).")
            return
        grupo = self.grupo.currentData()
        letra = grupo.removeprefix("letra:") if isinstance(grupo, str) else None
        self.celda.update(
            asignatura_id=self.asignatura.currentData(),
            aula_id=self.aula.currentData(),
            grupo_id=None if letra else grupo,
            grupo_letra=letra,
            confirmar=True,
        )
        # Lo aceptado por el usuario se muestra como confirmado de inmediato.
        for clave in ("sugerencia_asignatura", "sugerencia_aula"):
            self.celda.pop(clave, None)
        for clave in ("candidatos_asignatura", "candidatos_aula"):
            self.celda.pop(clave, None)
        self.celda["asignatura_estado"] = "confirmado"
        self.celda["aula_estado"] = "confirmado"
        self.celda["dia"], self.celda["hora"] = self.dia.currentData(), self.hora.currentData()
        self.accept()


def importacion_original(documento: dict) -> int | None:
    """Importación donde se leyó un PDF repetido.

    Los servidores actualizados lo envían en `original_importacion_id`; los anteriores solo
    en el mensaje («Idéntico a X.pdf (importación 2)»), que se usa como respaldo.
    """
    if documento.get("estado") != "duplicado":
        return None
    if documento.get("original_importacion_id") is not None:
        return documento["original_importacion_id"]
    encontrado = re.search(r"importación (\d+)\)?\s*$", documento.get("mensaje") or "")
    return int(encontrado.group(1)) if encontrado else None


class VistaImportacion(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api = api
        self.importacion: dict | None = None
        self.pagina: dict | None = None
        self.celdas: dict[tuple[str, int], dict] = {}
        self.cambios_pendientes = False
        # Estados anteriores de la página (celdas y docente) para «Deshacer» antes de guardar.
        self.historial: list[tuple[dict, int | None]] = []
        self._docente_actual: int | None = None
        self.sugerencia_docente: dict | None = None
        self.catalogos: dict[str, list[dict]] = {}
        self.temporizador = QTimer(self, interval=1500)
        self.temporizador.timeout.connect(self._actualizar_avance)

        # --- barra superior ---
        self.periodo = QComboBox()
        self.boton_importar = QPushButton("Importar archivo…", objectName="primario")
        self.lotes = QComboBox()
        self.lotes.setMinimumWidth(320)
        self.avance = QLabel("", objectName="suave")
        self.boton_cancelar = QPushButton("Cancelar importación")
        self.aviso_lote = QLabel("", objectName="advertencia", wordWrap=True)
        self.aviso_lote.hide()
        self.boton_original = QPushButton("Abrir la importación original", objectName="primario")
        self.boton_original.hide()
        self.importacion_original: int | None = None
        barra = QHBoxLayout()
        self.etiqueta_periodo = QLabel("Periodo")
        barra.addWidget(self.etiqueta_periodo)
        barra.addWidget(self.periodo)
        barra.addWidget(self.boton_importar)
        barra.addSpacing(24)
        barra.addWidget(QLabel("Importación"))
        barra.addWidget(self.lotes, 1)
        barra.addWidget(self.avance)
        barra.addWidget(self.boton_cancelar)

        # --- páginas ---
        self.paginas = Tabla(
            [
                Columna("Documento", lambda p: f"{Path(p['documento']).stem} · p{p['numero']}"),
                Columna("Estado", lambda p: NOMBRES_ESTADO_PAGINA.get(p["estado"], p["estado"])),
                Columna("Pend.", lambda p: p["pendientes"] or ""),
            ]
        )
        cabecera = self.paginas.horizontalHeader()
        cabecera.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2):
            cabecera.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        # --- revisión ---
        self.titulo_pagina = QLabel("", objectName="estado", wordWrap=True)
        self.docente = _combo_buscable(320)
        self.estado_docente = QLabel("", objectName="suave")
        self.boton_nuevo_docente = QPushButton("Crear docente con el nombre leído")
        fila_docente = QHBoxLayout()
        fila_docente.addWidget(QLabel("Docente"))
        fila_docente.addWidget(self.docente, 1)
        fila_docente.addWidget(self.boton_nuevo_docente)
        self.estado_docente.setWordWrap(True)  # el estado se lee completo, sin recortes
        self.avisos = QLabel("", objectName="advertencia", wordWrap=True)
        self.lista_pendientes = QLabel("", objectName="error", wordWrap=True)
        # Pendientes agrupados por tipo; al elegir uno se señala su celda en la cuadrícula.
        self.arbol_pendientes = QTreeWidget(objectName="pendientes")
        self.arbol_pendientes.setHeaderHidden(True)
        self.arbol_pendientes.setTextElideMode(Qt.ElideNone)
        self.arbol_pendientes.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.arbol_pendientes.header().setStretchLastSection(False)
        self.arbol_pendientes.setMinimumWidth(300)
        self.arbol_pendientes.setAccessibleName("Pendientes por revisar")
        self.cuadricula = QTableWidget(len(HORAS), len(DIAS), objectName="cuadricula")
        self.cuadricula.setHorizontalHeaderLabels(TITULOS_DIAS)
        self.cuadricula.setVerticalHeaderLabels([f"{h:02d}:00" for h in HORAS])
        self.cuadricula.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cuadricula.verticalHeader().setDefaultSectionSize(40)
        self.cuadricula.verticalHeader().setMinimumSectionSize(40)
        self.cuadricula.setEditTriggers(QAbstractItemView.NoEditTriggers)
        leyenda = QLabel(
            "Colores: verde = listo · amarillo = sugerido, acéptalo · rojo = falta elegir · "
            "morado = grupo pendiente de validar (solo letra). Doble clic para revisar una celda.",
            objectName="suave",
            wordWrap=True,
        )
        self.boton_sugerencias = QPushButton("Aceptar todas las sugerencias")
        self.boton_deshacer = QPushButton("Deshacer")
        self.boton_deshacer.setToolTip("Deshace la última corrección no guardada (Ctrl+Z)")
        self.boton_guardar = QPushButton("Guardar revisión")
        self.boton_descartar = QPushButton("Descartar página")
        self.boton_restaurar = QPushButton("Restaurar")
        self.boton_aprobar = QPushButton("Aprobar: crear borrador", objectName="primario")
        acciones = QHBoxLayout()
        acciones.addWidget(self.boton_sugerencias)
        acciones.addWidget(self.boton_deshacer)
        acciones.addStretch()
        for b in (
            self.boton_descartar,
            self.boton_restaurar,
            self.boton_guardar,
            self.boton_aprobar,
        ):
            acciones.addWidget(b)

        panel = QWidget()
        capa_p = QVBoxLayout(panel)
        capa_p.setContentsMargins(8, 0, 0, 0)
        for w in (self.titulo_pagina,):
            capa_p.addWidget(w)
        capa_p.addLayout(fila_docente)
        capa_p.addWidget(self.estado_docente)
        capa_p.addWidget(self.avisos)
        columna_pendientes = QWidget()
        capa_pend = QVBoxLayout(columna_pendientes)
        capa_pend.setContentsMargins(0, 0, 0, 0)
        capa_pend.addWidget(self.lista_pendientes)
        capa_pend.addWidget(self.arbol_pendientes, 1)
        self.divisor_revision = QSplitter()
        self.divisor_revision.addWidget(self.cuadricula)
        self.divisor_revision.addWidget(columna_pendientes)
        self.divisor_revision.setStretchFactor(0, 1)
        self.divisor_revision.setSizes([640, 340])
        capa_p.addWidget(self.divisor_revision, 1)
        capa_p.addWidget(leyenda)
        capa_p.addLayout(acciones)

        divisor = QSplitter()
        divisor.addWidget(self.paginas)
        divisor.addWidget(panel)
        divisor.setSizes([330, 950])

        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 28, 32, 28)
        capa.addWidget(
            encabezado(
                "Importar horarios",
                "Sube un ZIP o PDF de horarios. Nada se guarda como horario hasta que revises y "
                "apruebes cada página; al aprobar se crea un borrador que se confirma en Horarios.",
            )
        )
        capa.addLayout(barra)
        fila_aviso = QHBoxLayout()
        fila_aviso.addWidget(self.aviso_lote, 1)
        fila_aviso.addWidget(self.boton_original)
        capa.addLayout(fila_aviso)
        capa.addWidget(divisor, 1)

        self.boton_importar.clicked.connect(self.importar)
        self.lotes.activated.connect(lambda *_: self.cargar_importacion())
        self.boton_cancelar.clicked.connect(self.cancelar_importacion)
        self.boton_original.clicked.connect(self.abrir_original)
        self.paginas.itemSelectionChanged.connect(self._pagina_elegida)
        self.docente.activated.connect(self._docente_cambiado)
        self.boton_nuevo_docente.clicked.connect(self.crear_docente)
        self.cuadricula.cellDoubleClicked.connect(self.editar_celda)
        self.boton_sugerencias.clicked.connect(self.aceptar_sugerencias)
        self.boton_deshacer.clicked.connect(self.deshacer)
        QShortcut(QKeySequence.Undo, self, activated=self.deshacer)
        self.arbol_pendientes.currentItemChanged.connect(self._ir_a_pendiente)
        self.arbol_pendientes.itemDoubleClicked.connect(self._editar_pendiente)
        self.boton_guardar.clicked.connect(self.guardar)
        self.boton_descartar.clicked.connect(lambda: self._accion_pagina("descartar"))
        self.boton_restaurar.clicked.connect(lambda: self._accion_pagina("restaurar"))
        self.boton_aprobar.clicked.connect(self.aprobar)
        self.recargar()

    def modo_asistente(self) -> None:
        """Dentro del asistente, el periodo y el archivo se eligen en pasos anteriores."""
        for w in (self.etiqueta_periodo, self.periodo, self.boton_importar):
            w.hide()
        for titulo in self.findChildren(QLabel, "subtitulo"):
            titulo.hide()

    def seleccionar_importacion(self, importacion_id: int) -> None:
        try:
            self._llenar_lotes(self.api.get("/importaciones"), importacion_id)
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self.cargar_importacion()

    # --- carga ---------------------------------------------------------------------

    def recargar(self) -> None:
        try:
            periodos = self.api.get("/periodos")
            for clave in ("asignaturas", "aulas", "docentes"):
                self.catalogos[clave] = self.api.get(f"/{clave}", activo="true")
            lotes = self.api.get("/importaciones")
        except ErrorApi as error:
            mostrar_error(self, error, "No se pudo cargar la información")
            return
        self.periodo.clear()
        for p in periodos:
            if p["estado"] != "cerrado":
                self.periodo.addItem(p["nombre"], p)
        activo = self.periodo.findText(
            next((p["nombre"] for p in periodos if p["estado"] == "activo"), "")
        )
        self.periodo.setCurrentIndex(max(activo, 0))
        self.docente.clear()
        self.docente.addItem("(elige el docente)", None)
        for d in self.catalogos["docentes"]:
            self.docente.addItem(d["nombre"], d["id"])
        self._llenar_lotes(lotes)
        self.cargar_importacion()

    def _llenar_lotes(self, lotes: list[dict], seleccionar: int | None = None) -> None:
        self.lotes.clear()
        for lote in lotes:
            pendientes = lote["conteo"].get("por_revisar", 0)
            texto = (
                f"#{lote['id']} {lote['nombre_archivo']} · {lote['periodo']['nombre']} · "
                f"{lote['estado'].replace('_', ' ')}"
                + (f" · {pendientes} por revisar" if pendientes else "")
            )
            self.lotes.addItem(texto, lote["id"])
        if seleccionar is not None:
            self.lotes.setCurrentIndex(max(self.lotes.findData(seleccionar), 0))

    def cargar_importacion(self, seleccionar_pagina: int | None = None) -> None:
        id_ = self.lotes.currentData()
        self.importacion = None
        if id_ is None:
            self.paginas.cargar([])
            self._mostrar_pagina(None)
            self._actualizar_barra()
            return
        try:
            self.importacion = self.api.get(f"/importaciones/{id_}")
            self.catalogos["grupos"] = self.api.get(
                "/grupos", activo="true", periodo_id=self.importacion["periodo"]["id"]
            )
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        filas = [p for d in self.importacion["documentos"] for p in d["paginas"]]
        self._explicar_lote(filas)
        self.paginas.cargar(filas)
        for i, p in enumerate(filas):
            self.paginas.item(i, 1).setForeground(
                QColor(COLORES_ESTADO_PAGINA.get(p["estado"], "#6b7280"))
            )
        objetivo = seleccionar_pagina or next(
            (p["id"] for p in filas if p["estado"] == "por_revisar"),
            filas[0]["id"] if filas else None,
        )
        self.paginas.blockSignals(True)
        if objetivo:
            self.paginas.seleccionar_id(objetivo)
        self.paginas.blockSignals(False)
        self._cargar_pagina(objetivo)
        self._actualizar_barra()
        if self.importacion["estado"] == "procesando":
            self.temporizador.start()

    def _explicar_lote(self, filas: list[dict]) -> None:
        """Explica en palabras sencillas por qué una importación no tiene páginas que revisar."""
        docs = self.importacion["documentos"] if self.importacion else []
        duplicados = [d for d in docs if d["estado"] == "duplicado"]
        errores = [d for d in docs if d["estado"] == "error"]
        originales = sorted({importacion_original(d) for d in duplicados} - {None})
        self.importacion_original = originales[0] if originales else None
        textos = []
        if duplicados:
            nombres = ", ".join(d["nombre_archivo"] for d in duplicados[:3])
            mas = f" y {len(duplicados) - 3} más" if len(duplicados) > 3 else ""
            donde = f"la importación #{', #'.join(map(str, originales))}" if originales else "antes"
            textos.append(
                f"{nombres}{mas}: este PDF ya se había importado en {donde}. No se vuelve a "
                "leer; sus clases se revisan en esa importación."
            )
        for d in errores:
            textos.append(f"{d['nombre_archivo']}: no se pudo leer ({d['mensaje']}).")
        if (
            not filas
            and not textos
            and self.importacion
            and (self.importacion["estado"] != "procesando")
        ):
            textos.append("Esta importación no tiene páginas para revisar.")
        self.aviso_lote.setText("\n".join(textos))
        self.aviso_lote.setVisible(bool(textos))
        self.boton_original.setVisible(self.importacion_original is not None and not filas)
        self.paginas.mensaje_vacio = (
            "Sin páginas: revisa el aviso de arriba."
            if textos
            else "Las páginas aparecerán aquí cuando termine la lectura."
        )

    def abrir_original(self) -> None:
        if self.importacion_original is not None:
            self.seleccionar_importacion(self.importacion_original)

    def _actualizar_barra(self) -> None:
        i = self.importacion
        if i is None:
            self.avance.setText("")
        elif i["estado"] == "procesando":
            self.avance.setText(f"Procesando {i['procesados']}/{i['total_documentos']}…")
        else:
            errores = [d["nombre_archivo"] for d in i["documentos"] if d["estado"] == "error"]
            duplicados = sum(1 for d in i["documentos"] if d["estado"] == "duplicado")
            partes = [f"{i['total_documentos']} PDF"]
            if duplicados:
                partes.append(f"{duplicados} ya importados")
            if errores:
                partes.append(f"{len(errores)} con error")
            self.avance.setText(" · ".join(partes))
        self.boton_cancelar.setEnabled(bool(i and i["estado"] == "en_revision"))

    def _actualizar_avance(self) -> None:
        if not self.importacion:
            self.temporizador.stop()
            return
        try:
            lote = self.api.get(f"/importaciones/{self.importacion['id']}")
        except ErrorApi:
            return
        self.importacion = lote
        self._actualizar_barra()
        if lote["estado"] != "procesando":
            self.temporizador.stop()
            self._llenar_lotes(self.api.get("/importaciones"), lote["id"])
            self.cargar_importacion()

    def _pagina_elegida(self) -> None:
        fila = self.paginas.seleccionado()
        if fila is None or (self.pagina and fila["id"] == self.pagina["id"]):
            return
        if not self._puede_salir():
            self.paginas.blockSignals(True)
            self.paginas.seleccionar_id(self.pagina["id"])
            self.paginas.blockSignals(False)
            return
        self._cargar_pagina(fila["id"])

    def _cargar_pagina(self, id_: int | None) -> None:
        pagina = None
        if id_ is not None:
            try:
                pagina = self.api.get(f"/importaciones/paginas/{id_}")
            except ErrorApi as error:
                mostrar_error(self, error)
        self._mostrar_pagina(pagina)

    # --- presentación -----------------------------------------------------------------

    def _editable(self) -> bool:
        return bool(self.pagina and self.pagina["estado"] == "por_revisar")

    def _mostrar_pagina(self, pagina: dict | None) -> None:
        self.pagina = pagina
        self.cambios_pendientes = False
        self.historial = []
        self.celdas = {}
        self.sugerencia_docente = None
        if pagina is None:
            self.titulo_pagina.setText("Elige una página para revisarla.")
            for w in (self.avisos, self.lista_pendientes, self.estado_docente):
                w.setText("")
            self.cuadricula.clearContents()
            self.arbol_pendientes.clear()
            self._actualizar_botones()
            return
        self.celdas = {(c["dia"], c["hora"]): dict(c) for c in pagina["celdas_detalle"]}
        self._cargar_sugerencias()
        partes = [
            f"{Path(pagina['documento']).stem}, página {pagina['numero']}",
            NOMBRES_ESTADO_PAGINA.get(pagina["estado"], pagina["estado"]),
        ]
        if pagina["version_documento"]:
            partes.append(f"versión {pagina['version_documento']} del {pagina['fecha_documento']}")
        if pagina["horas_qr"] is not None:
            partes.append(f"{pagina['horas_qr']} h según el documento")
        if pagina["mensaje"]:
            partes.append(pagina["mensaje"])
        self.titulo_pagina.setText(" · ".join(partes))
        self._docente_actual = pagina["docente"]["id"] if pagina["docente"] else None
        self.docente.setCurrentIndex(max(self.docente.findData(self._docente_actual), 0))
        self._mostrar_estado_docente()
        avisos = [f"⚠ {a}" for a in pagina["avisos"]]
        if not pagina["celdas_detalle"]:
            avisos.insert(
                0,
                "⚠ El OCR no reconoció ninguna clase en esta página (puede estar borrosa o "
                "girada). Puedes capturarlas a mano: doble clic en el día y la hora de cada "
                "clase. Compara con el PDF original antes de aprobar.",
            )
        self.avisos.setText("\n".join(avisos))
        self._pintar()
        self._actualizar_botones()

    def _cargar_sugerencias(self) -> None:
        """Coincidencias aproximadas con los catálogos actuales (solo se proponen).

        Un servidor anterior no tiene esta consulta: entonces simplemente no hay propuestas.
        """
        if not self._editable():
            return
        try:
            datos = self.api.get(f"/importaciones/paginas/{self.pagina['id']}/sugerencias")
        except ErrorApi:
            return
        por_id = {c.get("id"): c for c in self.celdas.values()}
        for s in datos.get("celdas", []):
            celda = por_id.get(s["celda_id"])
            if celda is None:
                continue
            if s["id"] is not None:
                celda[f"sugerencia_{s['campo']}"] = s["id"]
            elif s["candidatos"]:
                celda[f"candidatos_{s['campo']}"] = s["candidatos"]
        self.sugerencia_docente = datos.get("docente")

    def _mostrar_estado_docente(self) -> None:
        pagina = self.pagina
        estado = TEXTO_ESTADO_CAMPO.get(pagina["docente_estado"], pagina["docente_estado"])
        propuesta = self.sugerencia_docente or {}
        if self.docente.currentData() is None and propuesta.get("id"):
            nombre = self._nombre("docentes", propuesta["id"], "nombre")
            estado = f"SUGERIDO: «{nombre}» se parece a lo leído. Revisa y acepta"
        elif self.docente.currentData() is None and propuesta.get("candidatos"):
            nombres = " o ".join(
                f"«{self._nombre('docentes', i, 'nombre')}»" for i in propuesta["candidatos"]
            )
            estado = f"SIN COINCIDENCIA: se parece a {nombres}. Elige el correcto"
        self.estado_docente.setText(f"Leído: «{pagina['docente_texto']}» · {estado}")

    def _pendientes_por_tipo(self) -> dict[str, list[tuple[str, tuple[str, int] | None]]]:
        """Lo que falta revisar, agrupado: {tipo: [(texto, (día, hora) o None)]}.

        Se calcula con lo que se ve en pantalla (incluye cambios aún no guardados).
        """
        grupos: dict[str, list] = {"Asignaturas": [], "Grupos": [], "Aulas": [], "Docente": []}
        materias = {
            a["id"] for a in self.catalogos.get("asignaturas", []) if a.get("tipo") == "materia"
        }
        for (dia, hora), c in sorted(
            self.celdas.items(), key=lambda x: (x[0][1], DIAS.index(x[0][0]))
        ):
            donde = f"{TITULOS_DIAS[DIAS.index(dia)]} {hora:02d}:00"
            pos = (dia, hora)
            leido = f"«{c['actividad_texto'] or '—'}»"
            estado = estado_campo(c, "asignatura")
            if estado == "falta":
                parecidas = len(c.get("candidatos_asignatura") or [])
                extra = f" (se parece a {parecidas})" if parecidas else ""
                grupos["Asignaturas"].append((f"{donde} · {leido}\nSIN COINCIDENCIA{extra}", pos))
            elif estado == "sugerido":
                nombre = self._nombre(
                    "asignaturas",
                    c["asignatura_id"] or c.get("sugerencia_asignatura"),
                    "nombre",
                )
                grupos["Asignaturas"].append((f"{donde} · {leido}\nSUGERIDA: {nombre}", pos))
            if c["asignatura_id"] in materias and c["grupo_id"] is None:
                if c["grupo_letra"]:
                    texto = f"solo la letra «{c['grupo_letra']}», pendiente de validar"
                else:
                    texto = "SIN GRUPO: la materia necesita grupo"
                grupos["Grupos"].append((f"{donde}\n{texto}", pos))
            leida = f"«{c['aula_texto'] or '—'}»"
            estado = estado_campo(c, "aula")
            if estado == "falta":
                grupos["Aulas"].append((f"{donde} · {leida}\nSIN COINCIDENCIA", pos))
            elif estado == "sugerido":
                clave = self._nombre("aulas", c["aula_id"] or c.get("sugerencia_aula"), "clave")
                grupos["Aulas"].append((f"{donde} · {leida}\nSUGERIDA: {clave}", pos))
        if self.pagina:
            if self.docente.currentData() is None:
                grupos["Docente"].append(
                    (f"«{self.pagina['docente_texto'] or '—'}»\nSIN COINCIDENCIA: elígelo", None)
                )
            elif (
                self.docente.currentData() == (self.pagina["docente"] or {}).get("id")
                and self.pagina["docente_estado"] == "sugerido"
            ):
                grupos["Docente"].append(("Confirma el docente sugerido", None))
        return grupos

    def _actualizar_pendientes(self) -> None:
        self.arbol_pendientes.blockSignals(True)
        self.arbol_pendientes.clear()
        if not self.pagina or not self._editable():
            self.lista_pendientes.setText("")
            self.arbol_pendientes.blockSignals(False)
            return
        grupos = self._pendientes_por_tipo()
        total = sum(len(v) for v in grupos.values())
        if not self.celdas:
            total += 1
            self.arbol_pendientes.addTopLevelItem(
                QTreeWidgetItem(["La página no tiene actividades: captúralas a mano"])
            )
        resumen = " · ".join(
            f"{tipo}\u00a0{len(v)}" for tipo, v in grupos.items() if v or tipo != "Docente"
        )
        self.lista_pendientes.setText(
            f"Falta revisar: {total}\n{resumen}" if total else "Nada pendiente en esta página."
        )
        self.lista_pendientes.setObjectName("error" if total else "exito")
        self.lista_pendientes.style().unpolish(self.lista_pendientes)
        self.lista_pendientes.style().polish(self.lista_pendientes)
        for tipo, elementos in grupos.items():
            if not elementos:
                continue
            raiz = QTreeWidgetItem([f"{tipo} ({len(elementos)})"])
            fuente = raiz.font(0)
            fuente.setBold(True)
            raiz.setFont(0, fuente)
            for texto, pos in elementos:
                hijo = QTreeWidgetItem([texto])
                hijo.setData(0, Qt.UserRole, pos)
                hijo.setToolTip(0, texto)
                raiz.addChild(hijo)
            self.arbol_pendientes.addTopLevelItem(raiz)
            raiz.setExpanded(True)
        self.arbol_pendientes.blockSignals(False)

    def _ir_a_pendiente(self, item, *_args) -> None:
        """Señala en la cuadrícula la celda del pendiente elegido."""
        pos = item.data(0, Qt.UserRole) if item else None
        if not pos:
            if item and item.childCount() == 0 and self.pagina:
                self.docente.setFocus()
            return
        dia, hora = pos
        fila, columna = HORAS.index(hora), DIAS.index(dia)
        self.cuadricula.setCurrentCell(fila, columna)
        self.cuadricula.scrollTo(
            self.cuadricula.model().index(fila, columna), QAbstractItemView.EnsureVisible
        )

    def _editar_pendiente(self, item, *_args) -> None:
        pos = item.data(0, Qt.UserRole) if item else None
        if pos:
            self.editar_celda(HORAS.index(pos[1]), DIAS.index(pos[0]))

    def _nombre(self, catalogo: str, id_, campo: str) -> str | None:
        return next((r[campo] for r in self.catalogos.get(catalogo, []) if r["id"] == id_), None)

    def _pintar(self) -> None:
        self.cuadricula.clearContents()
        for (dia, hora), c in self.celdas.items():
            sugerida = self._nombre("asignaturas", c.get("sugerencia_asignatura"), "nombre")
            asignatura = (
                self._nombre("asignaturas", c["asignatura_id"], "nombre")
                or (f"¿{sugerida}?" if c["asignatura_id"] is None and sugerida else None)
                or f"«{c['actividad_texto']}»"
            )
            grupo = self._nombre("grupos", c["grupo_id"], "clave") or (
                f"{c['grupo_letra']}?" if c["grupo_letra"] else None
            )
            aula_sugerida = self._nombre("aulas", c.get("sugerencia_aula"), "clave")
            aula = self._nombre("aulas", c["aula_id"], "clave") or (
                (f"¿{aula_sugerida}?" if aula_sugerida else f"«{c['aula_texto']}»")
                if c["aula_texto"] and c["aula_id"] is None
                else None
            )
            breve = " · ".join(x for x in (grupo, aula) if x)
            item = QTableWidgetItem("\n".join(x for x in (asignatura, breve) if x))
            item.setTextAlignment(Qt.AlignCenter)
            item.setBackground(QColor(COLORES[estado_celda(c)]))
            item.setForeground(QColor("#1f2937"))
            item.setToolTip(f"Leído: {c['texto_ocr']}" if c["texto_ocr"] else "Capturada a mano")
            self.cuadricula.setItem(HORAS.index(hora), DIAS.index(dia), item)
        # Filas a la altura de su contenido: ninguna clase queda cortada.
        self.cuadricula.resizeRowsToContents()
        self._actualizar_pendientes()
        mostrar_primera_clase(self.cuadricula, [h for _d, h in self.celdas])

    def _actualizar_botones(self) -> None:
        editable = self._editable()
        hay_sugerencias = editable and (
            self.pagina["docente_estado"] == "sugerido"
            or self._docente_sugerido() is not None
            or any(
                "sugerido" in (estado_campo(c, "asignatura"), estado_campo(c, "aula"))
                for c in self.celdas.values()
            )
        )
        self.boton_sugerencias.setEnabled(bool(hay_sugerencias))
        self.boton_deshacer.setEnabled(editable and bool(self.historial))
        self.boton_guardar.setEnabled(editable and self.cambios_pendientes)
        self.boton_aprobar.setEnabled(editable)
        self.boton_descartar.setEnabled(editable)
        self.boton_restaurar.setEnabled(
            bool(self.pagina and self.pagina["estado"] in ("descartada", "duplicada"))
        )
        self.docente.setEnabled(editable)
        self.boton_nuevo_docente.setEnabled(editable and self.pagina["docente"] is None)

    # --- edición -----------------------------------------------------------------------

    def _docente_sugerido(self) -> int | None:
        propuesta = self.sugerencia_docente or {}
        return propuesta.get("id") if self.docente.currentData() is None else None

    def _guardar_estado(self, docente: int | None = None) -> None:
        """Apunta el estado actual para poder deshacer el siguiente cambio."""
        anterior = self._docente_actual if docente is None else docente
        self.historial.append((copy.deepcopy(self.celdas), anterior))

    def deshacer(self) -> None:
        if not self._editable() or not self.historial:
            return
        self.celdas, docente = self.historial.pop()
        self._docente_actual = docente
        self.docente.setCurrentIndex(max(self.docente.findData(docente), 0))
        self.cambios_pendientes = bool(self.historial)
        self._mostrar_estado_docente()
        self._pintar()
        self._actualizar_botones()

    def _marcar_cambio(self) -> None:
        self.cambios_pendientes = True
        self._mostrar_estado_docente()
        self._pintar()
        self._actualizar_botones()

    def _docente_cambiado(self, *_args) -> None:
        nuevo = self.docente.currentData()
        if not self._editable() or nuevo == self._docente_actual:
            return
        self._guardar_estado()
        self._docente_actual = nuevo
        self._marcar_cambio()

    def _repetidas(self, antes: dict | None, despues: dict, excluir) -> dict:
        """Otras celdas de esta página con el mismo texto leído en un campo corregido.

        Devuelve {(día, hora): [campos]} solo con celdas cuyo valor actual es distinto.
        """
        if not antes or antes.get("origen") != "ocr":
            return {}
        repetidas: dict[tuple[str, int], list[str]] = {}
        for campo, (_titulo, clave_texto, claves) in CORRECCIONES.items():
            if all(antes.get(k) == despues.get(k) for k in claves):
                continue  # este campo no se corrigió
            leido = normal(antes.get(clave_texto))
            if not leido:
                continue
            for pos, c in self.celdas.items():
                if (
                    pos not in excluir
                    and c.get("origen") == "ocr"
                    and normal(c.get(clave_texto)) == leido
                    and any(c.get(k) != despues.get(k) for k in claves)
                ):
                    repetidas.setdefault(pos, []).append(campo)
        return repetidas

    def _describir_correccion(self, antes: dict, despues: dict, repetidas: dict) -> str:
        lineas = []
        for campo, (titulo, clave_texto, _claves) in CORRECCIONES.items():
            cuantas = sum(1 for campos in repetidas.values() if campo in campos)
            if not cuantas:
                continue
            if campo == "asignatura":
                valor = self._nombre("asignaturas", despues["asignatura_id"], "nombre")
            elif campo == "aula":
                valor = self._nombre("aulas", despues["aula_id"], "clave") or "sin aula"
            else:
                valor = self._nombre("grupos", despues["grupo_id"], "clave") or (
                    f"letra {despues['grupo_letra']}" if despues["grupo_letra"] else "sin grupo"
                )
            lineas.append(f"{titulo} «{antes.get(clave_texto)}» → {valor} ({cuantas} más)")
        return "\n".join(lineas)

    @staticmethod
    def _copiar_correccion(origen: dict, destino: dict, campos: list[str]) -> None:
        for campo in campos:
            for clave in CORRECCIONES[campo][2]:
                destino[clave] = origen[clave]
            destino.pop(f"sugerencia_{campo}", None)
            destino.pop(f"candidatos_{campo}", None)
            if campo == "grupo":
                destino["grupo_estado"] = (
                    "confirmado"
                    if destino["grupo_id"]
                    else ("pendiente" if destino["grupo_letra"] else "vacio")
                )
            else:
                destino[f"{campo}_estado"] = "confirmado"

    def editar_celda(self, fila: int, columna: int) -> None:
        if not self._editable():
            return
        dia, hora = DIAS[columna], HORAS[fila]
        actual = self.celdas.get((dia, hora))
        dialogo = DialogoCeldaImportada(self.api, self.catalogos, actual, dia, hora, self)
        resultado = dialogo.exec()
        if resultado == DialogoCeldaImportada.ELIMINAR:
            self._guardar_estado()
            self.celdas.pop((dia, hora), None)
        elif resultado == QDialog.Accepted:
            nueva = dialogo.celda
            destino = (nueva["dia"], nueva["hora"])
            if (
                destino != (dia, hora)
                and destino in self.celdas
                and not confirmar(self, "Ya hay una actividad en ese día y hora.", "¿Reemplazarla?")
            ):
                return
            repetidas = self._repetidas(actual, nueva, {(dia, hora), destino})
            aplicar_a: dict = {}
            if repetidas:
                eleccion = preguntar_correccion_repetida(
                    self, len(repetidas), self._describir_correccion(actual, nueva, repetidas)
                )
                if eleccion is None:
                    return  # cancelar: no se aplica nada
                if eleccion == "todas":
                    aplicar_a = repetidas
            self._guardar_estado()
            self.celdas.pop((dia, hora), None)
            self.celdas[destino] = nueva
            for pos, campos in aplicar_a.items():
                self._copiar_correccion(nueva, self.celdas[pos], campos)
        else:
            return
        self._marcar_cambio()

    def _puede_salir(self) -> bool:
        if not self.cambios_pendientes:
            return True
        return confirmar(self, "Hay cambios sin guardar en esta página.", "¿Descartarlos?")

    def crear_docente(self) -> None:
        nombre, ok = QInputDialog.getText(
            self,
            "Nuevo docente",
            "Nombre (apellidos y nombres):",
            text=self.pagina["docente_texto"],
        )
        if not ok or not nombre.strip():
            return
        datos = {"nombre": nombre.strip()}
        if self.pagina.get("nomina"):
            datos["nomina"] = self.pagina["nomina"]
        try:
            nuevo = self.api.post("/docentes", datos)
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self.catalogos["docentes"].append(nuevo)
        self.docente.addItem(nuevo["nombre"], nuevo["id"])
        self._guardar_estado()
        self.docente.setCurrentIndex(self.docente.count() - 1)
        self._docente_actual = nuevo["id"]
        self._marcar_cambio()

    # --- acciones ------------------------------------------------------------------------

    def _datos_revision(self) -> dict:
        return {
            "docente_id": self.docente.currentData(),
            "celdas": [
                {
                    "id": c.get("id"),
                    "dia": dia,
                    "hora": hora,
                    "asignatura_id": c["asignatura_id"],
                    "aula_id": c["aula_id"],
                    "grupo_id": c["grupo_id"],
                    "grupo_letra": c["grupo_letra"],
                    "confirmar": bool(c.get("confirmar")),
                }
                for (dia, hora), c in sorted(
                    self.celdas.items(), key=lambda x: (DIAS.index(x[0][0]), x[0][1])
                )
            ],
        }

    def guardar(self) -> bool:
        try:
            pagina = self.api.put(
                f"/importaciones/paginas/{self.pagina['id']}", self._datos_revision()
            )
        except ErrorApi as error:
            mostrar_error(self, error, "La revisión no se guardó")
            return False
        self._mostrar_pagina(pagina)
        self._refrescar_lista(pagina["id"])
        return True

    def aceptar_sugerencias(self) -> None:
        """Acepta, por decisión del usuario, todo lo sugerido en la página."""
        locales = [
            c
            for c in self.celdas.values()
            if c.get("sugerencia_asignatura") or c.get("sugerencia_aula")
        ]
        docente = self._docente_sugerido()
        if locales or docente is not None:
            self._guardar_estado()
            for c in locales:
                for campo in ("asignatura", "aula"):
                    if c.get(f"sugerencia_{campo}"):
                        c[f"{campo}_id"] = c.pop(f"sugerencia_{campo}")
                        c[f"{campo}_estado"] = "confirmado"
            if docente is not None:
                self.docente.setCurrentIndex(max(self.docente.findData(docente), 0))
                self._docente_actual = docente
            self.cambios_pendientes = True
        if self.cambios_pendientes and not self.guardar():
            return
        try:
            pagina = self.api.post(
                f"/importaciones/paginas/{self.pagina['id']}/aceptar-sugerencias"
            )
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self._mostrar_pagina(pagina)
        self._refrescar_lista(pagina["id"])

    def aprobar(self, opciones: dict | None = None) -> None:
        opciones = opciones or {}
        if self.cambios_pendientes and not self.guardar():
            return
        try:
            horario = self.api.post(f"/importaciones/paginas/{self.pagina['id']}/aprobar", opciones)
        except ErrorApi as error:
            if error.estado == 409 and "horas" in str(error):
                if confirmar(
                    self, str(error), "\n".join(error.problemas) + "\n\n¿Aprobar de todos modos?"
                ):
                    self.aprobar({**opciones, "aceptar_diferencia_horas": True})
                return
            if error.estado == 409 and "ya se importó" in str(error):
                if confirmar(
                    self,
                    str(error),
                    "\n".join(error.problemas) + "\n\n¿Crear otro borrador de todos modos?",
                ):
                    self.aprobar({**opciones, "permitir_duplicado": True})
                return
            mostrar_error(self, error, "No se puede aprobar todavía")
            return
        QMessageBox.information(
            self,
            "Borrador creado",
            f"Se creó el horario de {horario['docente']['nombre']} (versión "
            f"{horario['version']}) en borrador.\nConfírmalo como vigente en Horarios.",
        )
        self._refrescar_lista(self.pagina["id"])

    def _accion_pagina(self, accion: str) -> None:
        if accion == "descartar" and not confirmar(
            self, "¿Descartar esta página?", "Podrás restaurarla después."
        ):
            return
        try:
            self.api.post(f"/importaciones/paginas/{self.pagina['id']}/{accion}")
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self._refrescar_lista(self.pagina["id"])

    def cancelar_importacion(self) -> None:
        if not self.importacion or not confirmar(
            self,
            "¿Cancelar toda la importación?",
            "Las páginas por revisar se descartan. Los borradores ya creados no se tocan.",
        ):
            return
        try:
            self.api.post(f"/importaciones/{self.importacion['id']}/cancelar")
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self._llenar_lotes(self.api.get("/importaciones"), self.importacion["id"])
        self.cargar_importacion()

    def _refrescar_lista(self, pagina_id: int) -> None:
        self.cambios_pendientes = False
        actual = self.importacion["id"]
        self._llenar_lotes(self.api.get("/importaciones"), actual)
        self.cargar_importacion(seleccionar_pagina=pagina_id)

    def importar(self) -> None:
        periodo = self.periodo.currentData()
        if not periodo:
            mostrar_error(self, ErrorApi("Primero crea o activa un periodo"))
            return
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            f"Elegir horarios para {periodo['nombre']}",
            str(Path.home()),
            "Horarios (*.zip *.pdf)",
        )
        if not ruta:
            return
        if not confirmar(
            self,
            f"¿Importar {Path(ruta).name} en {periodo['nombre']}?",
            "Los horarios quedarán asociados a ese periodo. Nada se guarda como horario hasta "
            "que revises y apruebes cada página. Si el periodo no es el correcto, elige otro "
            "en la lista «Periodo» antes de importar.",
        ):
            return
        self.importar_archivo(Path(ruta), periodo["id"])

    def importar_archivo(self, ruta: Path, periodo_id: int) -> None:
        """Sube el archivo. El original no se modifica: solo se lee."""
        try:
            lote = self.api.subir(
                "/importaciones", ruta.name, ruta.read_bytes(), {"periodo_id": str(periodo_id)}
            )
        except (ErrorApi, OSError) as error:
            mostrar_error(self, error if isinstance(error, ErrorApi) else ErrorApi(str(error)))
            return
        self._llenar_lotes(self.api.get("/importaciones"), lote["id"])
        self.cargar_importacion()
