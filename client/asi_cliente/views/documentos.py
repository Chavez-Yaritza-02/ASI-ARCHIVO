"""Archivo digital: versiones privadas, vista pasiva, descarga y evidencia horaria."""

import json
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ErrorApi
from asi_cliente.views.bitacora import DialogoHistorial
from asi_cliente.views.comunes import (
    Campo,
    Columna,
    Desplegable,
    DialogoFormulario,
    Tabla,
    encabezado,
    mostrar_error,
)


class ImagenAjustada(QLabel):
    """Ajusta la página completa al panel; no recorta el encabezado del documento."""

    def __init__(self):
        super().__init__()
        self.original = None
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setMinimumSize(1, 1)

    def mostrar(self, imagen):
        self.original = imagen
        self.ajustar()

    def ajustar(self):
        if self.original is not None:
            self.setPixmap(
                self.original.scaled(
                    max(50, self.width() - 20),
                    max(50, self.height() - 20),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.ajustar()

    def clear(self):
        self.original = None
        super().clear()


class VistaDocumentos(QWidget):
    def __init__(self, api, usuario, asistencia=None):
        super().__init__()
        self.api, self.usuario, self.asistencia = api, usuario, asistencia
        self.documento = None
        self.offset = 0
        self.categorias = []
        self.docentes = []
        self.periodos = []
        self.limite_mb = 20
        self.cargas_habilitadas = False
        self.texto = QLineEdit(placeholderText="Nombre del documento")
        self.docente = QLineEdit(placeholderText="Nombre del docente")
        self.periodo = QComboBox()
        self.periodo.addItem("Todos los periodos", None)
        self.categoria = QComboBox()
        self.categoria.addItem("Todas las categorías", None)
        self.desde = QDateEdit(calendarPopup=True)
        self.hasta = QDateEdit(calendarPopup=True)
        self.desde.setDate(QDate.currentDate().addMonths(-1))
        self.hasta.setDate(QDate.currentDate())
        for campo in (self.desde, self.hasta):
            campo.setDisplayFormat("dd/MM/yyyy")
            campo.setEnabled(False)
        self.filtrar_fechas = QCheckBox("Filtrar fechas")
        self.filtrar_fechas.toggled.connect(self.desde.setEnabled)
        self.filtrar_fechas.toggled.connect(self.hasta.setEnabled)
        self.archivados = QCheckBox("Incluir archivados")
        self.solo_vinculados = QCheckBox("Solo vinculados a esta hora")
        self.solo_vinculados.setVisible(asistencia is not None)
        self.solo_vinculados.setChecked(asistencia is not None)
        self.boton_buscar = QPushButton("Buscar documentos", objectName="primario")
        self.boton_anterior = QPushButton("Anterior")
        self.boton_siguiente = QPushButton("Siguiente")
        self.estado = QLabel("", wordWrap=True)
        self.tabla = Tabla(
            [
                Columna("Documento", lambda d: d["nombre"]),
                Columna("Docente", lambda d: d["docente"] or "General"),
                Columna("Periodo", lambda d: d["periodo"] or "General"),
                Columna("Categoría", lambda d: d["categoria"]),
                Columna("Fecha", lambda d: d["fecha"]),
                Columna("Versión", lambda d: d["version_actual"]["numero"]),
                Columna("Estado", lambda d: "Activo" if d["activo"] else "Archivado"),
            ],
            "No se encontraron documentos. Cambia los filtros o carga un documento nuevo.",
        )
        self.versiones = QComboBox()
        self.pagina = QSpinBox()
        self.pagina.setMinimum(1)
        self.boton_ver = QPushButton("Ver página")
        self.imagen = ImagenAjustada()
        self.imagen.setText("Selecciona un documento y una versión para visualizarlo.")
        self.imagen.setAlignment(Qt.AlignCenter)
        self.imagen.setTextFormat(Qt.PlainText)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.imagen)
        self.informacion = QLabel("", wordWrap=True)
        self.informacion.setTextFormat(Qt.PlainText)
        panel = QWidget()
        capa_p = QVBoxLayout(panel)
        selector = QHBoxLayout()
        for w in (QLabel("Versión"), self.versiones, QLabel("Página"), self.pagina, self.boton_ver):
            selector.addWidget(w)
        capa_p.addLayout(selector)
        capa_p.addWidget(scroll, 1)
        capa_p.addWidget(self.informacion)
        divisor = QSplitter(Qt.Vertical)
        divisor.addWidget(self.tabla)
        divisor.addWidget(panel)
        divisor.setSizes([250, 450])
        self.boton_cargar = QPushButton("Cargar documento", objectName="primario")
        self.boton_version = QPushButton("Nueva versión")
        self.boton_editar = QPushButton("Editar metadatos")
        self.boton_archivar = QPushButton("Archivar / restaurar")
        self.boton_descargar = QPushButton("Descargar original")
        self.boton_historial = QPushButton("Historial y accesos")
        self.boton_vincular = QPushButton("Vincular esta versión a la hora")
        self.boton_desvincular = QPushButton("Retirar vínculo de esta hora")
        gestor = usuario.puede("documentos.gestionar")
        for b in (self.boton_cargar, self.boton_version, self.boton_editar, self.boton_archivar):
            b.setVisible(gestor)
        self.boton_descargar.setVisible(usuario.puede("documentos.descargar"))
        for b in (self.boton_vincular, self.boton_desvincular):
            b.setVisible(bool(asistencia) and gestor and usuario.puede("asistencia.registrar"))
        capa = QVBoxLayout(self)
        capa.addWidget(
            encabezado(
                "Archivo digital",
                "Documentos privados, versiones conservadas y accesos registrados. "
                "La vista previa muestra imágenes; descargar el original requiere permiso.",
            )
        )
        if asistencia:
            contexto = QLabel(
                f"Hora seleccionada: {asistencia['docente_nombre']} · {asistencia['fecha']} · "
                f"{asistencia['programado_inicio'][:5]}–{asistencia['programado_fin'][:5]}"
            )
            contexto.setTextFormat(Qt.PlainText)
            capa.addWidget(contexto)
        filtros = QHBoxLayout()
        for w in (self.texto, self.docente, self.boton_buscar):
            filtros.addWidget(w)
        capa.addLayout(filtros)
        avanzados = QWidget()
        capa_avanzados = QVBoxLayout(avanzados)
        capa_avanzados.setContentsMargins(0, 0, 0, 0)
        fila_a = QHBoxLayout()
        for w in (QLabel("Periodo"), self.periodo, QLabel("Categoría"), self.categoria):
            fila_a.addWidget(w)
        fila_a.addStretch()
        fila_b = QHBoxLayout()
        for w in (
            self.filtrar_fechas,
            self.desde,
            self.hasta,
            self.archivados,
            self.solo_vinculados,
        ):
            fila_b.addWidget(w)
        fila_b.addStretch()
        capa_avanzados.addLayout(fila_a)
        capa_avanzados.addLayout(fila_b)
        self.filtros_avanzados = Desplegable(
            "Filtros avanzados", avanzados, abierto=asistencia is not None
        )
        capa.addWidget(self.filtros_avanzados)
        paginas = QHBoxLayout()
        paginas.addWidget(self.estado, 1)
        paginas.addWidget(self.boton_anterior)
        paginas.addWidget(self.boton_siguiente)
        capa.addLayout(paginas)
        capa.addWidget(divisor, 1)
        acciones = QHBoxLayout()
        for b in (
            self.boton_cargar,
            self.boton_version,
            self.boton_editar,
            self.boton_archivar,
            self.boton_descargar,
            self.boton_historial,
        ):
            acciones.addWidget(b)
        capa.addLayout(acciones)
        vinculos = QHBoxLayout()
        vinculos.addWidget(self.boton_vincular)
        vinculos.addWidget(self.boton_desvincular)
        capa.addLayout(vinculos)
        self.boton_buscar.clicked.connect(self.buscar)
        self.texto.returnPressed.connect(self.buscar)
        self.boton_anterior.clicked.connect(lambda: self.paginar(-50))
        self.boton_siguiente.clicked.connect(lambda: self.paginar(50))
        self.tabla.itemSelectionChanged.connect(self.consultar)
        self.boton_cargar.clicked.connect(self.cargar)
        self.boton_version.clicked.connect(self.nueva_version)
        self.boton_editar.clicked.connect(self.editar)
        self.boton_archivar.clicked.connect(self.archivar)
        self.boton_descargar.clicked.connect(self.descargar)
        self.boton_historial.clicked.connect(self.historial)
        self.boton_ver.clicked.connect(self.ver)
        self.versiones.currentIndexChanged.connect(self.cambiar_version)
        self.boton_vincular.clicked.connect(self.vincular)
        self.boton_desvincular.clicked.connect(self.desvincular)
        try:
            config = api.get("/documentos/estado")
            self.limite_mb = config["limite_mb"]
            self.cargas_habilitadas = config["cargas_habilitadas"]
            if not config["cargas_habilitadas"]:
                self.estado.setText(
                    "Las cargas requieren configurar el análisis antivirus del servidor."
                )
            self.categorias = api.get("/documentos/categorias")
            for c in self.categorias:
                self.categoria.addItem(c["nombre"], c["id"])
            if usuario.puede("docentes.ver"):
                self.docentes = api.get("/docentes")
            if usuario.puede("horarios.ver"):
                self.periodos = api.get("/periodos")
                for p in self.periodos:
                    self.periodo.addItem(p["nombre"], p["id"])
        except ErrorApi as e:
            mostrar_error(self, e)
        self.buscar()

    def buscar(self):
        self.offset = 0
        self.recargar()

    def paginar(self, incremento):
        self.offset = max(0, self.offset + incremento)
        self.recargar()

    def recargar(self, seleccionar=None):
        self.documento = None
        self.tabla.cargar([])
        self.versiones.clear()
        self.imagen.clear()
        self.informacion.clear()
        params = {
            "texto": self.texto.text(),
            "docente_nombre": self.docente.text(),
            "periodo_id": self.periodo.currentData(),
            "categoria_id": self.categoria.currentData(),
            "incluir_archivados": self.archivados.isChecked(),
            "offset": self.offset,
        }
        if self.filtrar_fechas.isChecked():
            params.update(
                desde=self.desde.date().toPython().isoformat(),
                hasta=self.hasta.date().toPython().isoformat(),
            )
        if self.asistencia and self.solo_vinculados.isChecked():
            params["asistencia_id"] = self.asistencia["id"]
        try:
            datos = self.api.get("/documentos", **params)
            self.tabla.cargar(datos["resultados"])
            self.estado.setText(
                f"{datos['total']} documentos · Página {self.offset // 50 + 1} · "
                f"PDF, PNG y JPEG, máximo {self.limite_mb} MB por versión."
                + (
                    " Cargas deshabilitadas: configura el antivirus del servidor."
                    if not self.cargas_habilitadas
                    else ""
                )
            )
            self.boton_anterior.setEnabled(self.offset > 0)
            self.boton_siguiente.setEnabled(datos["total"] > self.offset + 50)
            if seleccionar:
                self.tabla.seleccionar_id(seleccionar)
        except ErrorApi as e:
            mostrar_error(self, e)
        self.botones()

    def consultar(self):
        fila = self.tabla.seleccionado()
        if not fila:
            return
        self.documento = None
        self.imagen.clear()
        self.versiones.blockSignals(True)
        self.versiones.clear()
        try:
            self.documento = self.api.get(f"/documentos/{fila['id']}")
            for v in self.documento["versiones"]:
                self.versiones.addItem(f"Versión {v['numero']} · {v['nombre_original']}", v)
            self.informacion.setText(self.documento["descripcion"] or "Sin descripción.")
        except ErrorApi as e:
            mostrar_error(self, e)
        self.versiones.blockSignals(False)
        self.cambiar_version()
        self.botones()

    def cambiar_version(self, *_):
        v = self.versiones.currentData()
        self.imagen.clear()
        self.imagen.setText("Pulsa «Ver página» para consultar esta versión.")
        self.pagina.setRange(1, v["paginas"] if v else 1)
        self.botones()

    def botones(self):
        d = self.documento
        self.boton_editar.setEnabled(bool(d and d["activo"]))
        self.boton_version.setEnabled(bool(d and d["activo"] and self.cargas_habilitadas))
        self.boton_cargar.setEnabled(self.cargas_habilitadas)
        for b in (
            self.boton_descargar,
            self.boton_historial,
            self.boton_archivar,
            self.boton_ver,
            self.boton_vincular,
            self.boton_desvincular,
        ):
            b.setEnabled(bool(d and self.versiones.currentData()))

    def ver(self):
        if not self.documento or not self.versiones.currentData():
            return
        v = self.versiones.currentData()
        try:
            png = self.api.descargar(
                f"/documentos/{self.documento['id']}/versiones/{v['id']}/vista",
                pagina=self.pagina.value(),
            )
            imagen = QPixmap()
            if not imagen.loadFromData(png, "PNG"):
                raise ErrorApi("No se pudo mostrar la vista previa.")
            self.imagen.mostrar(imagen)
            self.imagen.setMinimumSize(1, 1)
        except ErrorApi as e:
            mostrar_error(self, e)

    def _campos(self):
        return [
            Campo("nombre", "Nombre", obligatorio=True),
            Campo("descripcion", "Descripción"),
            Campo("fecha", "Fecha del documento", "fecha"),
            Campo(
                "categoria_id",
                "Categoría",
                "opciones",
                opciones=[(c["nombre"], c["id"]) for c in self.categorias],
            ),
            Campo(
                "docente_id",
                "Docente",
                "opciones",
                opciones=[("General / sin docente", None)]
                + [(d["nombre"], d["id"]) for d in self.docentes],
            ),
            Campo(
                "periodo_id",
                "Periodo",
                "opciones",
                opciones=[("General / sin periodo", None)]
                + [(p["nombre"], p["id"]) for p in self.periodos],
            ),
        ]

    def _archivo(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Selecciona PDF o imagen",
            str(Path.home()),
            "Documentos (*.pdf *.png *.jpg *.jpeg)",
        )
        return Path(ruta) if ruta else None

    def _leer(self, ruta):
        if ruta.stat().st_size > self.limite_mb * 1024 * 1024:
            raise ErrorApi("El archivo excede el tamaño permitido.")
        with ruta.open("rb") as archivo:
            contenido = archivo.read(self.limite_mb * 1024 * 1024 + 1)
        if len(contenido) > self.limite_mb * 1024 * 1024:
            raise ErrorApi("El archivo excede el tamaño permitido.")
        return contenido

    def cargar(self):
        ruta = self._archivo()
        if ruta is None:
            return
        valores = {"nombre": ruta.stem, "fecha": date.today().isoformat()}
        if self.asistencia:
            valores.update(
                docente_id=self.asistencia["docente_id"], periodo_id=self.asistencia["periodo_id"]
            )
            cat = next((c for c in self.categorias if c["clave"] == "justificante"), None)
            if cat:
                valores["categoria_id"] = cat["id"]
        dialogo = DialogoFormulario("Cargar documento privado", self._campos(), valores, padre=self)
        while dialogo.exec():
            try:
                resultado = self.api.subir(
                    "/documentos",
                    ruta.name,
                    self._leer(ruta),
                    {
                        "datos": json.dumps(
                            {
                                **dialogo.valores(),
                                "descripcion": dialogo.valores().get("descripcion") or "",
                            },
                            ensure_ascii=False,
                        )
                    },
                )
            except (ErrorApi, OSError) as e:
                mostrar_error(self, ErrorApi(str(e)))
                continue
            self.solo_vinculados.setChecked(False)
            self.recargar(seleccionar=resultado["documento_id"])
            break

    def nueva_version(self):
        if not self.documento:
            return
        ruta = self._archivo()
        if ruta is None:
            return
        dialogo = DialogoFormulario(
            "Nueva versión: se conserva la anterior",
            [Campo("motivo", "Motivo del reemplazo", obligatorio=True)],
            padre=self,
        )
        while dialogo.exec():
            try:
                self.api.subir(
                    f"/documentos/{self.documento['id']}/versiones",
                    ruta.name,
                    self._leer(ruta),
                    dialogo.valores(),
                )
            except (ErrorApi, OSError) as e:
                mostrar_error(self, ErrorApi(str(e)))
                continue
            self.consultar()
            break

    def editar(self):
        if not self.documento:
            return
        dialogo = DialogoFormulario(
            "Editar metadatos sin alterar el archivo",
            [*self._campos(), Campo("motivo", "Motivo del cambio", obligatorio=True)],
            self.documento,
            padre=self,
        )
        while dialogo.exec():
            try:
                self.api.patch(
                    f"/documentos/{self.documento['id']}",
                    {
                        **dialogo.valores(),
                        "descripcion": dialogo.valores().get("descripcion") or "",
                    },
                )
            except ErrorApi as e:
                mostrar_error(self, e)
                continue
            self.recargar(seleccionar=self.documento["id"])
            break

    def _motivo(self, titulo):
        dialogo = DialogoFormulario(
            titulo, [Campo("motivo", "Motivo", obligatorio=True)], padre=self
        )
        return dialogo.valores() if dialogo.exec() else None

    def archivar(self):
        if not self.documento:
            return
        accion = "archivar" if self.documento["activo"] else "restaurar"
        datos = self._motivo(f"{accion.capitalize()} sin eliminar archivos ni versiones")
        if datos:
            try:
                self.api.post(f"/documentos/{self.documento['id']}/{accion}", datos)
                self.recargar()
            except ErrorApi as e:
                mostrar_error(self, e)

    def descargar(self):
        if not self.documento:
            return
        v = self.versiones.currentData()
        ruta, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar copia del original",
            str(Path.home() / "Downloads" / v["nombre_original"]),
        )
        if ruta:
            self.descargar_a(Path(ruta))

    def descargar_a(self, ruta):
        if not self.documento or not self.usuario.puede("documentos.descargar"):
            return False
        v = self.versiones.currentData()
        try:
            datos = self.api.descargar(
                f"/documentos/{self.documento['id']}/versiones/{v['id']}/descargar"
            )
            Path(ruta).write_bytes(datos)
            return True
        except (ErrorApi, OSError) as e:
            mostrar_error(self, ErrorApi(str(e)))
            return False

    def historial(self):
        if not self.documento:
            return
        try:
            cambios = self.api.get(f"/documentos/{self.documento['id']}/historial")
            DialogoHistorial(cambios, self).exec()
        except ErrorApi as e:
            mostrar_error(self, e)

    def vincular(self):
        if not self.asistencia or not self.documento:
            return
        datos = self._motivo("Vincular esta versión sin cambiar el estado de asistencia")
        if datos:
            try:
                self.api.post(
                    f"/documentos/{self.documento['id']}/vinculos",
                    {
                        **datos,
                        "asistencia_id": self.asistencia["id"],
                        "version_id": self.versiones.currentData()["id"],
                    },
                )
                self.recargar()
            except ErrorApi as e:
                mostrar_error(self, e)

    def desvincular(self):
        if not self.asistencia or not self.documento:
            return
        v = self.versiones.currentData()
        enlace = next(
            (
                a
                for a in self.documento["asistencias"]
                if a["activo"]
                and a["asistencia_id"] == self.asistencia["id"]
                and a["version_id"] == v["id"]
            ),
            None,
        )
        if not enlace:
            return
        datos = self._motivo("Retirar vínculo sin borrar el documento ni la asistencia")
        if datos:
            try:
                self.api.post(
                    f"/documentos/{self.documento['id']}/vinculos/{enlace['id']}/anular", datos
                )
                self.recargar()
            except ErrorApi as e:
                mostrar_error(self, e)


class DialogoDocumentosHora(QDialog):
    def __init__(self, api, usuario, asistencia, padre=None):
        super().__init__(padre)
        self.setWindowTitle("Documentos relacionados con esta hora")
        self.resize(1300, 900)
        self.vista = VistaDocumentos(api, usuario, asistencia)
        capa = QVBoxLayout(self)
        capa.addWidget(self.vista)
        botones = QDialogButtonBox(QDialogButtonBox.Close)
        botones.rejected.connect(self.reject)
        capa.addWidget(botones)
