"""Consultas de escritorio: búsqueda, semana de grupo y ubicación programada."""

from pathlib import Path

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ErrorApi
from asi_cliente.views.comunes import Columna, Desplegable, Tabla, encabezado, mostrar_error

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]


class Filtros(QWidget):
    def __init__(self, api, usuario, semana=False):
        super().__init__()
        self.fecha = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.fecha.setDisplayFormat("dd/MM/yyyy")
        self.periodo = QComboBox()
        self.periodo.addItem("Todos", None)
        self.carrera = QLineEdit()
        self.carrera.setPlaceholderText("Todas las carreras")
        self.semestre = QComboBox()
        self.semestre.addItem("Todos", None)
        for i in range(1, 13):
            self.semestre.addItem(str(i), i)
        formulario = QFormLayout(self)
        formulario.addRow("Fecha de la semana" if semana else "Fecha de vigencia", self.fecha)
        formulario.addRow("Periodo", self.periodo)
        formulario.addRow("Carrera", self.carrera)
        formulario.addRow("Semestre", self.semestre)
        self.nombres_periodo: dict[int, str] = {}
        if usuario.puede("horarios.ver"):
            try:
                for p in api.get("/periodos"):
                    self.periodo.addItem(p["nombre"], p["id"])
                    self.nombres_periodo[p["id"]] = p["nombre"]
            except ErrorApi as e:
                mostrar_error(self, e)
        else:
            for control in (self.periodo, self.carrera, self.semestre):
                control.setEnabled(False)

    def datos(self):
        return {
            "periodo_id": self.periodo.currentData(),
            "carrera": self.carrera.text().strip() or None,
            "semestre": self.semestre.currentData(),
        }

    def fecha_iso(self):
        return self.fecha.date().toPython().isoformat()


def columnas_bloques(aula_titulo="Aula"):
    return [
        Columna("Fecha", lambda b: b["fecha"]),
        Columna("Materia", lambda b: b["materia"]),
        Columna("Docente", lambda b: b["docente"]),
        Columna("Grupo", lambda b: b["grupo"] or b.get("grupo_pendiente") or "Sin grupo"),
        Columna(aula_titulo, lambda b: b["aula"] or "Sin aula"),
        Columna("Entrada", lambda b: b["inicio"][:5]),
        Columna("Salida", lambda b: b["fin"][:5]),
    ]


class VistaBuscador(QWidget):
    def __init__(self, api, usuario):
        super().__init__()
        self.api, self.usuario = api, usuario
        self.offset = 0
        self.filtros = Filtros(api, usuario)
        self.texto = QLineEdit()
        self.texto.setPlaceholderText("Nombre de docente, materia, grupo o aula")
        self.dia = QComboBox()
        self.dia.addItem("Todos los días", None)
        for i, nombre in enumerate(DIAS):
            self.dia.addItem(nombre, i)
        self.turno = QComboBox()
        for nombre, valor in [
            ("Todos los turnos", None),
            ("Matutino", "matutino"),
            ("Vespertino", "vespertino"),
        ]:
            self.turno.addItem(nombre, valor)
        self.dia.setEnabled(usuario.puede("horarios.ver"))
        self.turno.setEnabled(usuario.puede("horarios.ver"))
        self.boton_buscar = QPushButton("Buscar", objectName="primario")
        self.boton_anterior = QPushButton("Anterior")
        self.boton_siguiente = QPushButton("Siguiente")
        self.resumen = QLabel("", wordWrap=True)
        self.entidades = Tabla(
            [
                Columna("Tipo", lambda f: f["tipo"]),
                Columna("Resultado", lambda f: f["nombre"]),
                Columna("Estado", lambda f: "Activo" if f["activo"] else "Inactivo"),
            ],
            "Escribe un nombre de docente, materia, grupo o aula y pulsa «Buscar».",
        )
        self.tabla = Tabla(
            [Columna("Día", lambda b: DIAS[b["dia"]]), *columnas_bloques()[1:]],
            "Sin actividades programadas que coincidan con la búsqueda.",
        )
        capa = QVBoxLayout(self)
        capa.addWidget(encabezado("Buscador", "Consulta catálogos y actividades programadas."))
        fila = QHBoxLayout()
        fila.addWidget(self.texto, 1)
        fila.addWidget(self.boton_buscar)
        capa.addLayout(fila)
        avanzados = QWidget()
        capa_avanzados = QVBoxLayout(avanzados)
        capa_avanzados.setContentsMargins(0, 0, 0, 0)
        capa_avanzados.addWidget(self.filtros)
        fila_dia = QHBoxLayout()
        for w in (QLabel("Día"), self.dia, QLabel("Turno"), self.turno):
            fila_dia.addWidget(w)
        fila_dia.addStretch()
        capa_avanzados.addLayout(fila_dia)
        self.filtros_avanzados = Desplegable("Filtros avanzados", avanzados)
        capa.addWidget(self.filtros_avanzados)
        capa.addWidget(self.resumen)
        capa.addWidget(self.entidades, 1)
        capa.addWidget(QLabel("Actividades según la versión vigente en la fecha seleccionada"))
        capa.addWidget(self.tabla, 1)
        pagina = QHBoxLayout()
        pagina.addStretch()
        pagina.addWidget(self.boton_anterior)
        pagina.addWidget(self.boton_siguiente)
        capa.addLayout(pagina)
        self.boton_buscar.clicked.connect(self.buscar)
        self.texto.returnPressed.connect(self.buscar)
        self.boton_anterior.clicked.connect(lambda: self.paginar(-100))
        self.boton_siguiente.clicked.connect(lambda: self.paginar(100))
        self.buscar()

    def buscar(self):
        self.offset = 0
        self.cargar()

    def paginar(self, incremento):
        self.offset = max(0, self.offset + incremento)
        self.cargar()

    def cargar(self):
        self.entidades.cargar([])
        self.tabla.cargar([])
        try:
            datos = self.api.get(
                "/buscador",
                texto=self.texto.text(),
                fecha=self.filtros.fecha_iso(),
                **self.filtros.datos(),
                dia=self.dia.currentData(),
                turno=self.turno.currentData(),
                offset=self.offset,
            )
        except ErrorApi as e:
            self.resumen.setText("No se pudo consultar. Ajusta los filtros e intenta de nuevo.")
            mostrar_error(self, e)
            return
        filas = []
        totales = []
        for tipo in ("docentes", "materias", "grupos", "aulas"):
            totales.append(f"{tipo.capitalize()}: {datos[tipo]['total']}")
            filas.extend({**r, "tipo": tipo.capitalize()} for r in datos[tipo]["resultados"])
        self.entidades.cargar(filas)
        self.tabla.cargar(datos["actividades"]["resultados"])
        self.resumen.setText(" · ".join(totales) + f" · Página {self.offset // 100 + 1}")
        self.boton_anterior.setEnabled(self.offset > 0)
        self.boton_siguiente.setEnabled(
            any(
                datos[k]["total"] > self.offset + 100
                for k in (*("docentes", "materias", "grupos", "aulas"), "actividades")
            )
        )


class VistaGrupos(QWidget):
    def __init__(self, api, usuario):
        super().__init__()
        self.api, self.usuario = api, usuario
        self.datos = None
        self.filtros = Filtros(api, usuario, semana=True)
        self.letra = QLineEdit()
        self.letra.setPlaceholderText("Todas las letras")
        self.grupo = QComboBox()
        self.boton_filtrar = QPushButton("Buscar grupos")
        self.boton_consultar = QPushButton("Consultar semana", objectName="primario")
        self.resumen = QLabel("", wordWrap=True)
        self.tabla = Tabla(
            [
                *columnas_bloques(),
                Columna(
                    "Avisos",
                    lambda b: ("TRASLAPE · " if b["conflictos"] else "") + b["aviso_calendario"],
                ),
            ],
            "Elige un grupo y pulsa «Consultar semana» para ver sus clases.",
        )
        self.boton_pdf = QPushButton("Exportar PDF")
        self.boton_excel = QPushButton("Exportar Excel")
        for b in (self.boton_pdf, self.boton_excel):
            b.setVisible(usuario.puede("reportes.generar"))
        capa = QVBoxLayout(self)
        capa.addWidget(
            encabezado("Horarios por grupo", "Una fila por clase de la semana consultada.")
        )
        self.filtros_avanzados = Desplegable("Semana y filtros", self.filtros)
        capa.addWidget(self.filtros_avanzados)
        fila = QHBoxLayout()
        for w in (
            QLabel("Letra"),
            self.letra,
            self.boton_filtrar,
            self.grupo,
            self.boton_consultar,
            self.boton_pdf,
            self.boton_excel,
        ):
            fila.addWidget(w)
        capa.addLayout(fila)
        capa.addWidget(self.resumen)
        capa.addWidget(self.tabla, 1)
        self.boton_filtrar.clicked.connect(self.cargar_grupos)
        self.boton_consultar.clicked.connect(self.consultar)
        self.boton_pdf.clicked.connect(lambda: self.exportar("pdf"))
        self.boton_excel.clicked.connect(lambda: self.exportar("xlsx"))
        self.grupo.currentIndexChanged.connect(self.limpiar)
        self.filtros.fecha.dateChanged.connect(self.limpiar)
        self.cargar_grupos()

    def limpiar(self, *_):
        self.datos = None
        self.tabla.cargar([])
        self.resumen.setText("Selecciona un grupo y consulta su semana.")
        self.boton_pdf.setEnabled(False)
        self.boton_excel.setEnabled(False)

    def cargar_grupos(self):
        self.limpiar()
        self.grupo.clear()
        try:
            for g in self.api.get(
                "/consultas/grupos", **self.filtros.datos(), letra=self.letra.text().strip() or None
            ):
                periodo = self.filtros.nombres_periodo.get(g["periodo_id"], "sin periodo")
                self.grupo.addItem(f"{g['clave']} · {periodo}", g["id"])
        except ErrorApi as e:
            mostrar_error(self, e)

    def consultar(self):
        self.limpiar()
        if self.grupo.currentData() is None:
            return
        try:
            self.datos = self.api.get(
                f"/consultas/grupos/{self.grupo.currentData()}/horario",
                fecha=self.filtros.fecha_iso(),
            )
        except ErrorApi as e:
            mostrar_error(self, e)
            return
        self.tabla.cargar(self.datos["bloques"])
        texto = f"{self.datos['grupo']} · {self.datos['desde']} a {self.datos['hasta']}"
        texto += f" · {len(self.datos['bloques'])} clases. " + self.datos["aviso"]
        if self.datos["horarios_sin_vigencia_confirmada"]:
            texto += " Hay versiones excluidas por vigencia desconocida."
        self.resumen.setText(texto)
        self.boton_pdf.setEnabled(True)
        self.boton_excel.setEnabled(True)

    def exportar(self, formato):
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar horario", f"horario_grupo.{formato}", f"Archivo (*.{formato})"
        )
        if ruta:
            self.exportar_a(Path(ruta), formato)

    def exportar_a(self, ruta, formato):
        if self.datos is None or not self.usuario.puede("reportes.generar"):
            return False
        try:
            contenido = self.api.descargar(
                f"/consultas/grupos/{self.datos['grupo_id']}/exportar",
                fecha=self.datos["desde"],
                formato=formato,
            )
            Path(ruta).write_bytes(contenido)
        except (ErrorApi, OSError) as e:
            mostrar_error(self, ErrorApi(str(e)))
            return False
        return True


class VistaUbicacion(QWidget):
    def __init__(self, api, usuario):
        super().__init__()
        self.api = api
        self.nombre = QLineEdit()
        self.nombre.setPlaceholderText("Buscar docente por nombre")
        self.docente = QComboBox()
        self.fecha = QDateEdit(QDate.currentDate(), calendarPopup=True)
        self.hora = QTimeEdit(QTime.currentTime())
        self.hora.setDisplayFormat("HH:mm")
        self.boton_buscar = QPushButton("Buscar docente")
        self.boton_consultar = QPushButton("Consultar ubicación programada")
        self.aviso = QLabel("Ubicación programada: no confirma presencia física.", wordWrap=True)
        self.detalle = QLabel("", wordWrap=True)
        self.tabla = Tabla(
            [
                *columnas_bloques("Aula del horario base"),
                Columna("Situación", lambda b: b["estado"]),
                Columna(
                    "Aula programada", lambda b: b["aula_programada"] or "Revisar avisos / sin aula"
                ),
            ],
            "Elige un docente, la fecha y la hora, y pulsa «Consultar ubicación programada».",
        )
        self.fecha.setDisplayFormat("dd/MM/yyyy")
        self.boton_consultar.setObjectName("primario")
        capa = QVBoxLayout(self)
        capa.addWidget(
            encabezado(
                "Ubicación programada",
                "La fecha y hora corresponden a la zona horaria de la Jefatura.",
            )
        )
        fila = QHBoxLayout()
        for w in (self.nombre, self.boton_buscar):
            fila.addWidget(w)
        fila.addStretch()
        capa.addLayout(fila)
        fila = QHBoxLayout()
        for w in (
            QLabel("Docente"),
            self.docente,
            QLabel("Fecha"),
            self.fecha,
            QLabel("Hora"),
            self.hora,
            self.boton_consultar,
        ):
            fila.addWidget(w)
        fila.addStretch()
        capa.addLayout(fila)
        capa.addWidget(self.aviso)
        capa.addWidget(self.detalle)
        capa.addWidget(self.tabla, 1)
        self.boton_buscar.clicked.connect(self.buscar_docentes)
        self.boton_consultar.clicked.connect(self.consultar)
        self.nombre.returnPressed.connect(self.buscar_docentes)
        try:
            ahora = api.get("/consultas/ahora")
            self.fecha.setDate(QDate.fromString(ahora["fecha"], "yyyy-MM-dd"))
            self.hora.setTime(QTime.fromString(ahora["hora"][:5], "HH:mm"))
        except ErrorApi as e:
            mostrar_error(self, e)
        self.buscar_docentes()

    def buscar_docentes(self):
        self.docente.clear()
        self.tabla.cargar([])
        self.detalle.clear()
        try:
            for d in self.api.get("/docentes", buscar=self.nombre.text()):
                self.docente.addItem(d["nombre"], d["id"])
        except ErrorApi as e:
            mostrar_error(self, e)

    def consultar(self):
        self.tabla.cargar([])
        self.detalle.clear()
        if self.docente.currentData() is None:
            return
        try:
            datos = self.api.get(
                f"/consultas/docentes/{self.docente.currentData()}/ubicacion",
                fecha=self.fecha.date().toPython().isoformat(),
                hora=self.hora.time().toString("HH:mm"),
            )
        except ErrorApi as e:
            mostrar_error(self, e)
            return
        self.tabla.cargar(datos["bloques"])
        estados = {
            "sin_clase_asignada": "Sin clase asignada para esta fecha y hora.",
            "vigencia_desconocida": "Vigencia desconocida: no se puede determinar la ubicación.",
            "con_programacion": "Actividades programadas para esta fecha y hora.",
        }
        textos = [estados[datos["estado"]], datos["aviso"]]
        if datos["horarios_sin_vigencia_confirmada"]:
            textos.append("Hay versiones de vigencia desconocida excluidas de la consulta.")
        if datos["conflicto"]:
            textos.append("CONFLICTO: hay actividades simultáneas.")
        textos.extend(b["aviso_calendario"] for b in datos["bloques"] if b["aviso_calendario"])
        textos.extend(i["descripcion"] for i in datos["incidencias"])
        self.detalle.setText("\n".join(textos))


class VistaConfiguracionAsistencia(QWidget):
    def __init__(self, api, usuario):
        super().__init__()
        self.api = api
        self.minutos = QSpinBox()
        self.minutos.setRange(0, 120)
        self.minutos.setSuffix(" minutos")
        self.boton_guardar = QPushButton("Guardar tolerancia")
        self.boton_guardar.setVisible("administrador" in usuario.roles)
        self.minutos.setEnabled("administrador" in usuario.roles)
        self.mensaje = QLabel("")
        capa = QVBoxLayout(self)
        capa.addWidget(
            encabezado(
                "Tolerancia de retardos",
                "Valor provisional inicial: 10 minutos. Los cambios quedan auditados.",
            )
        )
        self.minutos.setMinimumWidth(160)
        self.minutos.setAccessibleName("Tolerancia de retardo en minutos")
        self.boton_guardar.setObjectName("primario")
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Minutos de tolerancia"))
        fila.addWidget(self.minutos)
        fila.addWidget(self.boton_guardar)
        fila.addStretch()
        capa.addLayout(fila)
        capa.addWidget(
            QLabel(
                "Es la referencia para decidir si una llegada cuenta como retardo; se muestra "
                "en la bitácora. El sistema no marca retardos por su cuenta: el estado de cada "
                "hora lo elige quien registra la asistencia.",
                objectName="ayuda",
                wordWrap=True,
            )
        )
        capa.addWidget(self.mensaje)
        capa.addStretch()
        try:
            self.minutos.setValue(api.get("/configuracion/asistencia")["tolerancia_minutos"])
        except ErrorApi as e:
            mostrar_error(self, e)
        self.boton_guardar.clicked.connect(self.guardar)

    def guardar(self):
        try:
            self.api.put("/configuracion/asistencia", {"tolerancia_minutos": self.minutos.value()})
            self.mensaje.setText(
                "Tolerancia guardada. Se aplicará al volver a consultar la bitácora."
            )
        except ErrorApi as e:
            mostrar_error(self, e)
