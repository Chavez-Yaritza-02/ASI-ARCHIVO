"""Asistente de importación de horarios en cuatro pasos.

1. Periodo: elegir (o crear) el periodo académico al que pertenecen los horarios.
2. Archivo: subir un PDF o ZIP; el servidor lo lee con OCR.
3. Revisar: corregir docente, materias, grupos, aulas, días y horas (pantalla de
   revisión existente, sin cambios en su lógica).
4. Confirmar: ver duplicados y conflictos, aprobar las páginas listas y confirmar
   los horarios como vigentes.

Todo pasa por los servicios de siempre (/periodos, /importaciones, /horarios): las
reglas de duplicados, choques, versiones e historial siguen en el servidor. Los
horarios de cada periodo quedan separados y los anteriores se conservan.
"""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.views.comunes import (
    Columna,
    DialogoFormulario,
    Tabla,
    busqueda_para,
    confirmar,
    mostrar_error,
)
from asi_cliente.views.importacion import VistaImportacion
from asi_cliente.views.periodos import CAMPOS as CAMPOS_PERIODO

PASOS = ["Periodo", "Archivo", "Revisar", "Confirmar"]
ESTADOS_PAGINA = {
    "por_revisar": "Por revisar",
    "aprobada": "Aprobada",
    "descartada": "Descartada",
    "duplicada": "Copia repetida",
    "error": "No se pudo leer",
}


def _fecha(texto: str) -> str:
    return date.fromisoformat(texto).strftime("%d/%m/%Y")


def _panel() -> tuple[QFrame, QVBoxLayout]:
    panel = QFrame(objectName="panel")
    capa = QVBoxLayout(panel)
    capa.setContentsMargins(20, 16, 20, 18)
    capa.setSpacing(10)
    return panel, capa


def clasificar_aviso(texto: str) -> str:
    if "ya se importó" in texto:
        return "Duplicado"
    if "ocupad" in texto:
        return "Conflicto"
    return "Aviso"


class VistaAsistenteImportacion(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api, self.usuario = api, usuario
        self.periodos: list[dict] = []
        self.archivo: Path | None = None
        self.importacion: dict | None = None
        self.resumen: list[dict] = []
        self.temporizador = QTimer(self, interval=1500)
        self.temporizador.timeout.connect(self._avance)

        # --- indicador de pasos ---
        self.marcas: list[QLabel] = []
        fila_pasos = QHBoxLayout()
        fila_pasos.setSpacing(6)
        for i, nombre in enumerate(PASOS):
            marca = QLabel(f"{i + 1}. {nombre}", objectName="paso")
            self.marcas.append(marca)
            fila_pasos.addWidget(marca)
            if i < len(PASOS) - 1:
                fila_pasos.addWidget(QLabel("›", objectName="suave"))
        fila_pasos.addStretch()

        self.pasos = QStackedWidget()
        self.pasos.addWidget(self._paso_periodo())
        self.pasos.addWidget(self._paso_archivo())
        self.revision = VistaImportacion(api, usuario)
        self.revision.modo_asistente()
        self.pasos.addWidget(self.revision)
        self.pasos.addWidget(self._paso_confirmar())

        self.boton_anterior = QPushButton("‹ Anterior")
        self.boton_siguiente = QPushButton("Siguiente ›", objectName="primario")
        self.boton_reiniciar = QPushButton("Empezar otra importación")
        navegacion = QHBoxLayout()
        navegacion.addWidget(self.boton_reiniciar)
        navegacion.addStretch()
        navegacion.addWidget(self.boton_anterior)
        navegacion.addWidget(self.boton_siguiente)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 24, 32, 24)
        capa.setSpacing(12)
        capa.addLayout(fila_pasos)
        capa.addWidget(self.pasos, 1)
        capa.addLayout(navegacion)

        self.boton_anterior.clicked.connect(lambda: self.ir_a(self.pasos.currentIndex() - 1))
        self.boton_siguiente.clicked.connect(self.siguiente)
        self.boton_reiniciar.clicked.connect(self.reiniciar)
        self.recargar()
        self.ir_a(0)

    # --- paso 1: periodo ------------------------------------------------------------

    def _paso_periodo(self) -> QWidget:
        panel, capa = _panel()
        capa.addWidget(QLabel("¿A qué periodo pertenecen estos horarios?", objectName="estado"))
        capa.addWidget(
            QLabel(
                "Cada semestre tiene su propio periodo. Los horarios que importes quedarán "
                "en el periodo elegido y no cambiarán los de semestres anteriores.",
                objectName="ayuda",
                wordWrap=True,
            )
        )
        self.periodo = QComboBox()
        self.periodo.setMinimumWidth(360)
        self.periodo.setAccessibleName("Periodo académico")
        self.boton_nuevo_periodo = QPushButton("Crear periodo nuevo…")
        self.boton_nuevo_periodo.setVisible(self.usuario.puede("periodos.gestionar"))
        fila = QHBoxLayout()
        fila.addWidget(self.periodo)
        fila.addWidget(self.boton_nuevo_periodo)
        fila.addStretch()
        capa.addLayout(fila)
        self.detalle_periodo = QLabel("", objectName="suave", wordWrap=True)
        capa.addWidget(self.detalle_periodo)
        capa.addStretch()
        self.periodo.currentIndexChanged.connect(self._periodo_elegido)
        self.boton_nuevo_periodo.clicked.connect(self.crear_periodo)
        return panel

    def recargar(self) -> None:
        elegido = self.periodo_id()
        try:
            self.periodos = [p for p in self.api.get("/periodos") if p["estado"] != "cerrado"]
        except ErrorApi as error:
            mostrar_error(self, error, "No se pudieron cargar los periodos")
            return
        self.periodo.blockSignals(True)
        self.periodo.clear()
        for p in self.periodos:
            marca = " (activo)" if p["estado"] == "activo" else " (aún no activo)"
            self.periodo.addItem(p["nombre"] + marca, p)
        indice = next(
            (i for i, p in enumerate(self.periodos) if p["id"] == elegido),
            next((i for i, p in enumerate(self.periodos) if p["estado"] == "activo"), 0),
        )
        self.periodo.setCurrentIndex(indice if self.periodos else -1)
        self.periodo.blockSignals(False)
        self._periodo_elegido()

    def periodo_id(self) -> int | None:
        dato = self.periodo.currentData() if hasattr(self, "periodo") else None
        return dato["id"] if dato else None

    def _periodo_elegido(self, *_args) -> None:
        p = self.periodo.currentData()
        if not p:
            self.detalle_periodo.setText(
                "No hay periodos abiertos. Crea uno con «Crear periodo nuevo…»."
            )
        else:
            self.detalle_periodo.setText(
                f"Del {_fecha(p['fecha_inicio'])} al {_fecha(p['fecha_fin'])}."
                + ("" if p["estado"] == "activo" else " Este periodo todavía no está activo.")
            )
        self._actualizar_botones()

    def crear_periodo(self) -> None:
        dialogo = DialogoFormulario("Nuevo periodo académico", CAMPOS_PERIODO, padre=self)
        while dialogo.exec():
            try:
                nuevo = self.api.post("/periodos", dialogo.valores())
            except ErrorApi as error:
                mostrar_error(self, error)
                continue
            self.recargar()
            self.periodo.setCurrentIndex(
                next(i for i, p in enumerate(self.periodos) if p["id"] == nuevo["id"])
            )
            return

    # --- paso 2: archivo ------------------------------------------------------------

    def _paso_archivo(self) -> QWidget:
        panel, capa = _panel()
        capa.addWidget(QLabel("Sube el archivo de horarios", objectName="estado"))
        capa.addWidget(
            QLabel(
                "Acepta un PDF (uno o varios horarios escaneados) o un ZIP con varios PDF. "
                "El archivo original no se modifica.",
                objectName="ayuda",
                wordWrap=True,
            )
        )
        self.boton_elegir = QPushButton("Elegir PDF o ZIP…", objectName="primario")
        self.nombre_archivo = QLabel("Ningún archivo elegido.", objectName="suave")
        fila = QHBoxLayout()
        fila.addWidget(self.boton_elegir)
        fila.addWidget(self.nombre_archivo, 1)
        capa.addLayout(fila)
        self.boton_subir = QPushButton("Subir y leer con OCR")
        self.boton_subir.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.progreso = QProgressBar()
        self.progreso.setTextVisible(True)
        self.progreso.hide()
        self.estado_subida = QLabel("", objectName="suave", wordWrap=True)
        fila = QHBoxLayout()
        fila.addWidget(self.boton_subir)
        fila.addWidget(self.progreso, 1)
        capa.addLayout(fila)
        capa.addWidget(self.estado_subida)
        capa.addSpacing(12)
        capa.addWidget(QLabel("¿Quedó una importación a medias?", objectName="estado"))
        self.pendientes = QComboBox()
        self.boton_retomar = QPushButton("Continuar esa importación")
        fila = QHBoxLayout()
        fila.addWidget(self.pendientes, 1)
        fila.addWidget(self.boton_retomar)
        capa.addLayout(fila)
        capa.addStretch()
        self.boton_elegir.clicked.connect(self.elegir_archivo)
        self.boton_subir.clicked.connect(self.subir)
        self.boton_retomar.clicked.connect(self.retomar)
        return panel

    def _cargar_pendientes(self) -> None:
        self.pendientes.clear()
        try:
            lotes = self.api.get("/importaciones")
        except ErrorApi:
            lotes = []
        for lote in lotes:
            if lote["periodo"]["id"] != self.periodo_id():
                continue
            if lote["estado"] in ("procesando", "en_revision"):
                por_revisar = lote["conteo"].get("por_revisar", 0)
                self.pendientes.addItem(
                    f"#{lote['id']} {lote['nombre_archivo']} · {por_revisar} página(s) por revisar",
                    lote["id"],
                )
        vacio = self.pendientes.count() == 0
        if vacio:
            self.pendientes.addItem("No hay importaciones pendientes en este periodo", None)
        self.pendientes.setEnabled(not vacio)
        self.boton_retomar.setEnabled(not vacio)

    def elegir_archivo(self) -> None:
        p = self.periodo.currentData()
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            f"Elegir horarios para {p['nombre'] if p else 'el periodo'}",
            str(Path.home()),
            "Horarios (*.zip *.pdf)",
        )
        if ruta:
            self.usar_archivo(Path(ruta))

    def usar_archivo(self, ruta: Path) -> None:
        self.archivo = ruta
        tamano = ruta.stat().st_size / 1024 / 1024 if ruta.exists() else 0
        self.nombre_archivo.setText(f"{ruta.name} ({tamano:.1f} MB)")
        self.estado_subida.setText("Listo para subir.")
        self._actualizar_botones()

    def subir(self) -> None:
        if self.archivo is None or self.periodo_id() is None:
            return
        p = self.periodo.currentData()
        if not confirmar(
            self,
            f"¿Importar {self.archivo.name} en {p['nombre']}?",
            "Los horarios quedarán asociados a ese periodo. Nada se guarda como horario "
            "hasta que revises y confirmes en los pasos siguientes.",
            texto_si="Sí, subir",
        ):
            return
        try:
            lote = self.api.subir(
                "/importaciones",
                self.archivo.name,
                self.archivo.read_bytes(),
                {"periodo_id": str(self.periodo_id())},
            )
        except (ErrorApi, OSError) as error:
            mostrar_error(self, error if isinstance(error, ErrorApi) else ErrorApi(str(error)))
            return
        self.importacion = lote
        self.progreso.show()
        self._avance()

    def retomar(self) -> None:
        if self.pendientes.currentData() is None:
            return
        try:
            self.importacion = self.api.get(f"/importaciones/{self.pendientes.currentData()}")
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self._avance()
        if self.importacion["estado"] != "procesando":
            self.ir_a(2)

    def _avance(self) -> None:
        if self.importacion is None:
            return
        try:
            self.importacion = self.api.get(f"/importaciones/{self.importacion['id']}")
        except ErrorApi as error:
            self.temporizador.stop()
            mostrar_error(self, error)
            return
        total = max(self.importacion["total_documentos"], 1)
        self.progreso.setRange(0, total)
        self.progreso.setValue(self.importacion["procesados"])
        if self.importacion["estado"] == "procesando":
            self.estado_subida.setText(
                f"Leyendo con OCR: {self.importacion['procesados']} de "
                f"{self.importacion['total_documentos']} documento(s)…"
            )
            if not self.temporizador.isActive():
                self.temporizador.start()
        else:
            self.temporizador.stop()
            paginas = sum(len(d["paginas"]) for d in self.importacion["documentos"])
            self.estado_subida.setText(
                f"Lectura terminada: {paginas} página(s). Pulsa «Siguiente» para revisarlas."
            )
        self._actualizar_botones()

    # --- paso 4: confirmar ----------------------------------------------------------

    def _paso_confirmar(self) -> QWidget:
        panel, capa = _panel()
        titulo = QLabel("Revisa duplicados y conflictos antes de confirmar", objectName="estado")
        capa.addWidget(titulo)
        self.conteo = QLabel("", wordWrap=True)
        capa.addWidget(self.conteo)
        self.tabla_resumen = Tabla(
            [
                Columna("Documento", lambda r: r["documento"]),
                Columna("Docente", lambda r: r["docente"]),
                Columna("Estado", lambda r: r["estado"]),
                Columna("Tipo de aviso", lambda r: r["tipo"]),
                Columna("Detalle", lambda r: r["detalle"]),
            ],
            "Todavía no hay páginas leídas en esta importación.",
        )
        self.tabla_resumen.horizontalHeader().setStretchLastSection(True)
        capa.addWidget(busqueda_para(self.tabla_resumen, "Buscar por docente o aviso…"))
        capa.addWidget(self.tabla_resumen, 1)
        self.vigente_desde = QDateEdit(calendarPopup=True)
        self.vigente_desde.setDisplayFormat("dd/MM/yyyy")
        self.vigente_desde.setAccessibleName("Fecha desde la que aplican los horarios")
        self.boton_aprobar = QPushButton("1) Aprobar las páginas revisadas")
        self.boton_aprobar.setToolTip("Crea un borrador por cada página sin pendientes")
        self.boton_confirmar = QPushButton("2) Confirmar como vigentes", objectName="primario")
        self.boton_confirmar.setToolTip(
            "Los borradores pasan a vigentes; la versión anterior de cada docente queda en el "
            "historial"
        )
        fila = QHBoxLayout()
        fila.addWidget(self.boton_aprobar)
        fila.addStretch()
        fila.addWidget(QLabel("Aplican desde"))
        fila.addWidget(self.vigente_desde)
        fila.addWidget(self.boton_confirmar)
        capa.addLayout(fila)
        capa.addWidget(
            QLabel(
                "«Aplican desde» es el primer día en que la asistencia usará estos horarios.",
                objectName="ayuda",
                wordWrap=True,
            )
        )
        self.boton_aprobar.clicked.connect(self.aprobar_listas)
        self.boton_confirmar.clicked.connect(self.confirmar_borradores)
        return panel

    def cargar_resumen(self) -> None:
        if self.importacion is None:
            self.tabla_resumen.cargar([])
            return
        try:
            self.importacion = self.api.get(f"/importaciones/{self.importacion['id']}")
            filas = []
            for doc in self.importacion["documentos"]:
                for pag in doc["paginas"]:
                    detalle = self.api.get(f"/importaciones/paginas/{pag['id']}")
                    filas.append({**pag, "avisos": detalle["avisos"]})
        except ErrorApi as error:
            mostrar_error(self, error)
            return
        self.resumen = filas
        tabla = []
        for f in filas:
            base = {
                "id": f["id"],
                "documento": f"{Path(f['documento']).stem} · p{f['numero']}",
                "docente": (f["docente"] or {}).get("nombre") or f["docente_texto"] or "—",
                "estado": ESTADOS_PAGINA.get(f["estado"], f["estado"])
                + (f" ({f['pendientes']} pendientes)" if f["pendientes"] else ""),
            }
            avisos = [a for a in f["avisos"] if f["estado"] not in ("descartada", "duplicada")]
            if not avisos:
                tabla.append({**base, "tipo": "Sin avisos", "detalle": ""})
            for aviso in avisos:
                tabla.append({**base, "tipo": clasificar_aviso(aviso), "detalle": aviso})
        self.tabla_resumen.cargar(tabla)
        listas = [f for f in filas if f["estado"] == "por_revisar" and not f["pendientes"]]
        faltan = [f for f in filas if f["estado"] == "por_revisar" and f["pendientes"]]
        borradores = self.borradores()
        conflictos = sum(1 for t in tabla if t["tipo"] == "Conflicto")
        duplicados = sum(1 for t in tabla if t["tipo"] == "Duplicado")
        self.conteo.setText(
            f"{len(filas)} página(s): {len(listas)} lista(s) para aprobar, "
            f"{len(faltan)} con pendientes (corrígelas en el paso 3), "
            f"{len(borradores)} borrador(es) por confirmar. "
            f"Conflictos detectados: {conflictos}. Posibles duplicados: {duplicados}."
        )
        self.boton_aprobar.setEnabled(bool(listas))
        self.boton_confirmar.setEnabled(bool(borradores))
        p = self.periodo.currentData()
        if p:
            inicio = date.fromisoformat(p["fecha_inicio"])
            fin = date.fromisoformat(p["fecha_fin"])
            sugerida = min(max(date.today(), inicio), fin)
            self.vigente_desde.setMinimumDate(QDate(inicio.year, inicio.month, inicio.day))
            self.vigente_desde.setMaximumDate(QDate(fin.year, fin.month, fin.day))
            self.vigente_desde.setDate(QDate(sugerida.year, sugerida.month, sugerida.day))

    def borradores(self) -> list[int]:
        ids = {f["horario_id"] for f in self.resumen if f["horario_id"]}
        resultado = []
        for id_ in sorted(ids):
            try:
                if self.api.get(f"/horarios/{id_}")["estado"] == "borrador":
                    resultado.append(id_)
            except ErrorApi:
                continue
        return resultado

    def aprobar_listas(self) -> None:
        listas = [f for f in self.resumen if f["estado"] == "por_revisar" and not f["pendientes"]]
        creados, omitidos = 0, []
        for f in listas:
            opciones: dict = {}
            while True:
                try:
                    self.api.post(f"/importaciones/paginas/{f['id']}/aprobar", opciones)
                    creados += 1
                    break
                except ErrorApi as error:
                    bandera = (
                        "permitir_duplicado"
                        if "ya se importó" in str(error)
                        else "aceptar_diferencia_horas"
                        if "horas" in str(error)
                        else None
                    )
                    nombre = f"{Path(f['documento']).stem} · p{f['numero']}"
                    if error.estado == 409 and bandera and bandera not in opciones:
                        if confirmar(
                            self,
                            f"{nombre}: {error}",
                            "\n".join(error.problemas) + "\n\n¿Aprobar de todos modos?",
                            texto_si="Sí, aprobar",
                        ):
                            opciones[bandera] = True
                            continue
                        omitidos.append(nombre)
                        break
                    mostrar_error(self, error, f"No se pudo aprobar {nombre}")
                    omitidos.append(nombre)
                    break
        self.cargar_resumen()
        self.conteo.setText(
            f"Se crearon {creados} borrador(es)."
            + (f" Sin aprobar: {', '.join(omitidos)}." if omitidos else "")
            + " Ahora confírmalos como vigentes.\n"
            + self.conteo.text()
        )

    def confirmar_borradores(self) -> None:
        ids = self.borradores()
        if not ids:
            return
        desde = self.vigente_desde.date().toPython().isoformat()
        avisos: list[str] = []
        for id_ in ids:
            try:
                detalle = self.api.get(f"/horarios/{id_}")
            except ErrorApi:
                continue
            avisos += [f"{detalle['docente']['nombre']}: {a}" for a in detalle["advertencias"]]
        pregunta = f"¿Confirmar {len(ids)} horario(s) como vigentes desde el {_fecha(desde)}?"
        detalle = (
            "La versión anterior de cada docente pasará al historial (no se borra)."
            + ("\n\nAdvertencias:\n" + "\n".join(f"• {a}" for a in avisos[:15]) if avisos else "")
            + (f"\n… y {len(avisos) - 15} más." if len(avisos) > 15 else "")
        )
        if not confirmar(self, pregunta, detalle, texto_si="Sí, confirmar"):
            return
        hechos, errores = 0, []
        for id_ in ids:
            try:
                self.api.post(
                    f"/horarios/{id_}/confirmar",
                    {"aceptar_advertencias": bool(avisos), "vigente_desde": desde},
                )
                hechos += 1
            except ErrorApi as error:
                errores.append(f"Horario #{id_}: {error}")
        if errores:
            mostrar_error(
                self, ErrorApi(f"Se confirmaron {hechos} de {len(ids)} horarios", errores)
            )
        self.cargar_resumen()
        mensaje = f"Se confirmaron {hechos} horario(s) como vigentes.\n"
        self.conteo.setText(mensaje + self.conteo.text())

    # --- navegación -----------------------------------------------------------------

    def ir_a(self, paso: int) -> None:
        paso = max(0, min(paso, len(PASOS) - 1))
        if paso == 1:
            self._cargar_pendientes()
        if paso == 2 and self.importacion is not None:
            self.revision.seleccionar_importacion(self.importacion["id"])
        if paso == 3:
            if self.revision.cambios_pendientes and not self.revision.guardar():
                return
            self.cargar_resumen()
        self.pasos.setCurrentIndex(paso)
        for i, marca in enumerate(self.marcas):
            nombre = "paso_actual" if i == paso else "paso_hecho" if i < paso else "paso"
            marca.setObjectName(nombre)
            marca.style().unpolish(marca)
            marca.style().polish(marca)
        self._actualizar_botones()

    def siguiente(self) -> None:
        self.ir_a(self.pasos.currentIndex() + 1)

    def _actualizar_botones(self) -> None:
        if not hasattr(self, "boton_siguiente"):
            return
        paso = self.pasos.currentIndex()
        listo = {
            0: self.periodo_id() is not None,
            1: self.importacion is not None and self.importacion["estado"] != "procesando",
            2: self.importacion is not None,
            3: False,
        }[paso]
        self.boton_siguiente.setEnabled(listo)
        self.boton_siguiente.setVisible(paso < 3)
        self.boton_anterior.setEnabled(paso > 0)
        self.boton_subir.setEnabled(
            self.archivo is not None
            and self.periodo_id() is not None
            and not self.temporizador.isActive()
        )

    def reiniciar(self) -> None:
        self.temporizador.stop()
        self.archivo, self.importacion, self.resumen = None, None, []
        self.nombre_archivo.setText("Ningún archivo elegido.")
        self.estado_subida.setText("")
        self.progreso.hide()
        self.recargar()
        self.ir_a(0)
