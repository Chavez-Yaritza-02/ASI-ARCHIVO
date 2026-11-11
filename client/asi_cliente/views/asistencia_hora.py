"""Captura independiente por hora, parciales, historial y reportes."""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ErrorApi
from asi_cliente.views.bitacora import DialogoAsistencia, DialogoHistorial
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


class DialogoAsistenciaHora(DialogoAsistencia):
    def __init__(self, fila, padre=None):
        adaptada = {
            **fila,
            "docente": {"id": fila["docente_id"], "nombre": fila["docente_nombre"]},
            "actividades": [
                {
                    "asignatura": fila["asignatura"],
                    "grupo": fila["grupo"],
                    "aula": fila["aula"],
                    "inicio": fila["programado_inicio"],
                    "fin": fila["programado_fin"],
                }
            ],
        }
        super().__init__(adaptada, date.fromisoformat(fila["fecha"]), padre)
        self.setWindowTitle("Asistencia de esta hora de clase")
        self.minutos_justificados = QSpinBox()
        self.minutos_justificados.setRange(0, 60)
        fila_extra = QHBoxLayout()
        fila_extra.addWidget(QLabel("Minutos justificados (solo en asistencia parcial)"))
        fila_extra.addWidget(self.minutos_justificados)
        self.layout().insertLayout(self.layout().count() - 2, fila_extra)
        self.estado.addItem("Parcial", "parcial")
        registro = fila.get("asistencia")
        if registro:
            self.estado.setCurrentIndex(self.estado.findData(registro["estado"]))
            if registro["estado"] == "parcial":
                self.minutos_justificados.setValue(registro["minutos_justificados"])
        self._actualizar()

    def _actualizar(self):
        super()._actualizar()
        estado = self.estado.currentData()
        if estado in ("falto", "justificado"):
            self.usar_entrada.setChecked(False)
            self.usar_salida.setChecked(False)
            self.entrada.setEnabled(False)
            self.salida.setEnabled(False)
        if estado == "parcial":
            self.usar_entrada.setChecked(True)
            self.usar_salida.setChecked(True)
        if hasattr(self, "minutos_justificados"):
            self.minutos_justificados.setEnabled(estado == "parcial")
            self.justificacion.setEnabled(estado in ("parcial", "justificado"))

    def datos(self):
        datos = super().datos()
        datos["minutos_justificados"] = (
            self.minutos_justificados.value() if datos["estado"] == "parcial" else 0
        )
        return datos


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
        self.historicos = Tabla(columnas)
        self.pestanas = QTabWidget()
        self.pestanas.addTab(self.tabla, "Programa vigente en la fecha")
        self.pestanas.addTab(self.historicos, "Capturas fuera del programa actual")
        self.boton_registrar = QPushButton("Registrar / corregir esta hora")
        self.boton_registrar.setVisible(usuario.puede("asistencia.registrar"))
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
        for b in (self.boton_registrar, self.boton_historial, self.boton_pdf, self.boton_excel):
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
