"""Pantalla de importación de horarios desde PDF y revisión de lo leído.

1. Elegir periodo e "Importar archivo…" (ZIP con PDFs o un PDF). El OCR corre en el
   servidor; aquí solo se muestra el avance.
2. Elegir una página: se ven el encabezado leído, los avisos, lo que falta revisar y
   la cuadrícula con colores según el estado de cada celda.
3. Doble clic en una celda: imagen del documento, texto leído y valores asignados
   (asignatura, grupo, aula, día y hora), con opción de crear un registro nuevo.
4. "Aprobar" crea un horario en *borrador*; se confirma después en Horarios.
"""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
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
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.cuadricula import DIAS, HORAS, TITULOS_DIAS
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


def estado_celda(c: dict) -> str:
    """Resume la celda en: falta | sugerido | grupo | ok (para el color)."""
    if c["asignatura_id"] is None or c["aula_estado"] == "sin_coincidencia":
        return "falta"
    if c["asignatura_estado"] == "sugerido" or c["aula_estado"] == "sugerido":
        return "sugerido"
    if c["grupo_id"] is None and c["grupo_letra"]:
        return "grupo"
    return "ok"


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

        self.asignatura = self._combo("asignaturas", "nombre", self.celda["asignatura_id"])
        self.aula = self._combo("aulas", "clave", self.celda["aula_id"], opcional=True)
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
            self._fila(self.asignatura, nueva_asignatura, "asignatura_estado", "actividad_texto"),
        )
        formulario.addRow("Grupo", self._fila(self.grupo, None, "grupo_estado", "grupo_texto"))
        formulario.addRow("Aula", self._fila(self.aula, nueva_aula, "aula_estado", "aula_texto"))
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

    def _fila(self, combo, boton, campo_estado: str, campo_texto: str) -> QWidget:
        caja = QWidget()
        capa = QVBoxLayout(caja)
        capa.setContentsMargins(0, 0, 0, 0)
        fila = QHBoxLayout()
        fila.addWidget(combo, 1)
        if boton:
            fila.addWidget(boton)
        capa.addLayout(fila)
        leido = self.celda.get(campo_texto)
        estado = TEXTO_ESTADO_CAMPO.get(self.celda[campo_estado], self.celda[campo_estado])
        if self.celda["origen"] == "ocr":
            capa.addWidget(QLabel(f"Leído: «{leido or '—'}» · {estado}", objectName="suave"))
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
        self.celda["asignatura_estado"] = "confirmado"
        self.celda["aula_estado"] = "confirmado"
        self.celda["dia"], self.celda["hora"] = self.dia.currentData(), self.hora.currentData()
        self.accept()


class VistaImportacion(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api = api
        self.importacion: dict | None = None
        self.pagina: dict | None = None
        self.celdas: dict[tuple[str, int], dict] = {}
        self.cambios_pendientes = False
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
        barra = QHBoxLayout()
        barra.addWidget(QLabel("Periodo"))
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
        fila_docente.addWidget(self.estado_docente)
        fila_docente.addWidget(self.boton_nuevo_docente)
        self.avisos = QLabel("", objectName="advertencia", wordWrap=True)
        self.lista_pendientes = QLabel("", objectName="error", wordWrap=True)
        self.cuadricula = QTableWidget(len(HORAS), len(DIAS), objectName="cuadricula")
        self.cuadricula.setHorizontalHeaderLabels(TITULOS_DIAS)
        self.cuadricula.setVerticalHeaderLabels([f"{h:02d}:00" for h in HORAS])
        self.cuadricula.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cuadricula.verticalHeader().setDefaultSectionSize(40)
        self.cuadricula.setEditTriggers(QAbstractItemView.NoEditTriggers)
        leyenda = QLabel(
            "Colores: verde = listo · amarillo = sugerido, acéptalo · rojo = falta elegir · "
            "morado = grupo pendiente de validar (solo letra). Doble clic para revisar una celda.",
            objectName="suave",
            wordWrap=True,
        )
        self.boton_sugerencias = QPushButton("Aceptar todas las sugerencias")
        self.boton_guardar = QPushButton("Guardar revisión")
        self.boton_descartar = QPushButton("Descartar página")
        self.boton_restaurar = QPushButton("Restaurar")
        self.boton_aprobar = QPushButton("Aprobar: crear borrador", objectName="primario")
        acciones = QHBoxLayout()
        acciones.addWidget(self.boton_sugerencias)
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
        capa_p.addWidget(self.avisos)
        capa_p.addWidget(self.lista_pendientes)
        capa_p.addWidget(self.cuadricula, 1)
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
        capa.addWidget(divisor, 1)

        self.boton_importar.clicked.connect(self.importar)
        self.lotes.activated.connect(lambda *_: self.cargar_importacion())
        self.boton_cancelar.clicked.connect(self.cancelar_importacion)
        self.paginas.itemSelectionChanged.connect(self._pagina_elegida)
        self.docente.activated.connect(self._docente_cambiado)
        self.boton_nuevo_docente.clicked.connect(self.crear_docente)
        self.cuadricula.cellDoubleClicked.connect(self.editar_celda)
        self.boton_sugerencias.clicked.connect(self.aceptar_sugerencias)
        self.boton_guardar.clicked.connect(self.guardar)
        self.boton_descartar.clicked.connect(lambda: self._accion_pagina("descartar"))
        self.boton_restaurar.clicked.connect(lambda: self._accion_pagina("restaurar"))
        self.boton_aprobar.clicked.connect(self.aprobar)
        self.recargar()

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
        self.celdas = {}
        if pagina is None:
            self.titulo_pagina.setText("Elige una página para revisarla.")
            for w in (self.avisos, self.lista_pendientes, self.estado_docente):
                w.setText("")
            self.cuadricula.clearContents()
            self._actualizar_botones()
            return
        self.celdas = {(c["dia"], c["hora"]): dict(c) for c in pagina["celdas_detalle"]}
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
        self.docente.setCurrentIndex(
            max(self.docente.findData(pagina["docente"]["id"] if pagina["docente"] else None), 0)
        )
        self.estado_docente.setText(
            f"Leído: «{pagina['docente_texto']}» · "
            + TEXTO_ESTADO_CAMPO.get(pagina["docente_estado"], pagina["docente_estado"])
        )
        self.avisos.setText("\n".join(f"⚠ {a}" for a in pagina["avisos"]))
        self._mostrar_pendientes(pagina["lista_pendientes"])
        self._pintar()
        self._actualizar_botones()

    def _mostrar_pendientes(self, pendientes: list[str]) -> None:
        if not pendientes:
            self.lista_pendientes.setText("")
            return
        visibles = pendientes[:5]
        extra = f"\n… y {len(pendientes) - 5} más" if len(pendientes) > 5 else ""
        self.lista_pendientes.setText(
            "Falta revisar:\n" + "\n".join(f"• {p}" for p in visibles) + extra
        )

    def _nombre(self, catalogo: str, id_, campo: str) -> str | None:
        return next((r[campo] for r in self.catalogos.get(catalogo, []) if r["id"] == id_), None)

    def _pintar(self) -> None:
        self.cuadricula.clearContents()
        for (dia, hora), c in self.celdas.items():
            asignatura = self._nombre("asignaturas", c["asignatura_id"], "nombre") or (
                f"«{c['actividad_texto']}»"
            )
            grupo = self._nombre("grupos", c["grupo_id"], "clave") or (
                f"{c['grupo_letra']}?" if c["grupo_letra"] else None
            )
            aula = self._nombre("aulas", c["aula_id"], "clave") or (
                f"«{c['aula_texto']}»" if c["aula_texto"] and c["aula_id"] is None else None
            )
            breve = " · ".join(x for x in (grupo, aula) if x)
            item = QTableWidgetItem("\n".join(x for x in (asignatura, breve) if x))
            item.setTextAlignment(Qt.AlignCenter)
            item.setBackground(QColor(COLORES[estado_celda(c)]))
            item.setForeground(QColor("#1f2937"))
            item.setToolTip(f"Leído: {c['texto_ocr']}" if c["texto_ocr"] else "Capturada a mano")
            self.cuadricula.setItem(HORAS.index(hora), DIAS.index(dia), item)

    def _actualizar_botones(self) -> None:
        editable = self._editable()
        hay_sugerencias = editable and (
            self.pagina["docente_estado"] == "sugerido"
            or any(
                "sugerido" in (c["asignatura_estado"], c["aula_estado"])
                for c in self.celdas.values()
            )
        )
        self.boton_sugerencias.setEnabled(bool(hay_sugerencias))
        self.boton_guardar.setEnabled(editable and self.cambios_pendientes)
        self.boton_aprobar.setEnabled(editable)
        self.boton_descartar.setEnabled(editable)
        self.boton_restaurar.setEnabled(
            bool(self.pagina and self.pagina["estado"] in ("descartada", "duplicada"))
        )
        self.docente.setEnabled(editable)
        self.boton_nuevo_docente.setEnabled(editable and self.pagina["docente"] is None)

    # --- edición -----------------------------------------------------------------------

    def _marcar_cambio(self) -> None:
        self.cambios_pendientes = True
        self._pintar()
        self._actualizar_botones()

    def _docente_cambiado(self, *_args) -> None:
        if self._editable() and self.docente.currentData() != (self.pagina["docente"] or {}).get(
            "id"
        ):
            self._marcar_cambio()

    def editar_celda(self, fila: int, columna: int) -> None:
        if not self._editable():
            return
        dia, hora = DIAS[columna], HORAS[fila]
        actual = self.celdas.get((dia, hora))
        dialogo = DialogoCeldaImportada(self.api, self.catalogos, actual, dia, hora, self)
        resultado = dialogo.exec()
        if resultado == DialogoCeldaImportada.ELIMINAR:
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
            self.celdas.pop((dia, hora), None)
            self.celdas[destino] = nueva
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
        self.docente.setCurrentIndex(self.docente.count() - 1)
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
