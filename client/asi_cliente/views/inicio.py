"""Inicio: lo que pasa hoy y accesos rápidos a las tareas más comunes.

Solo lee información (no registra nada). Cada acceso rápido abre la pantalla real
correspondiente y solo aparece si el usuario tiene permiso para usarla.
"""

from collections import Counter
from collections.abc import Callable
from datetime import date, datetime

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.views.asistencia_hora import NOMBRES as ESTADOS_HORA
from asi_cliente.views.comunes import Columna, Tabla, busqueda_para, indicador

# (texto del botón, explicación, pantalla que abre, permiso necesario)
ACCESOS = [
    (
        "Registrar asistencia",
        "Marca asistió, falta o retardo en cada hora de clase de hoy.",
        "Asistencia por hora",
        "asistencia.registrar",
    ),
    (
        "Ver la bitácora del día",
        "Resumen por docente y turno, con incidencias.",
        "Bitácora del día",
        "asistencia.ver",
    ),
    (
        "Importar horarios",
        "Asistente paso a paso para cargar PDF o ZIP de horarios.",
        "Importar horarios",
        "horarios.editar",
    ),
    (
        "Consultar horarios",
        "Horario de cada docente y su historial de versiones.",
        "Horarios",
        "horarios.ver",
    ),
    (
        "Generar un reporte",
        "PDF o Excel de asistencia por día o por rango de fechas.",
        "Reportes",
        "reportes.generar",
    ),
    (
        "Buscar un docente",
        "Catálogo de docentes con su nómina y estado.",
        "Docentes",
        "docentes.ver",
    ),
]


def _hora(f: dict) -> str:
    return f"{f['programado_inicio'][:5]}–{f['programado_fin'][:5]}"


def _grupo_aula(f: dict) -> str:
    return " · ".join(x for x in (f["grupo"], f["aula"]) if x)


def saludo(ahora: datetime | None = None) -> str:
    hora = (ahora or datetime.now()).hour
    return "Buenos días" if hora < 12 else "Buenas tardes" if hora < 19 else "Buenas noches"


class VistaInicio(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api, self.usuario = api, usuario
        self.navegar: Callable[[str], object] | None = None  # lo asigna la ventana
        self.puede_asistencia = usuario.puede("asistencia.ver")

        nombre = usuario.nombre.split()[0] if usuario.nombre else ""
        self.bienvenida = QLabel(f"{saludo()}, {nombre}".strip(", "), objectName="titulo_seccion")
        self.aviso_periodo = QLabel("", objectName="advertencia", wordWrap=True)
        self.aviso_periodo.hide()
        self.boton_actualizar = QPushButton("Actualizar")
        self.boton_actualizar.setToolTip("Volver a consultar la información de hoy (F5)")
        self.boton_actualizar.setShortcut("F5")
        cabecera = QHBoxLayout()
        cabecera.addWidget(self.bienvenida, 1)
        cabecera.addWidget(self.boton_actualizar)

        # --- cifras del día ---
        self.cifras: dict[str, QLabel] = {}
        fila_cifras = QHBoxLayout()
        fila_cifras.setSpacing(12)
        for clave, titulo, ayuda in (
            ("programadas", "Horas de clase programadas hoy", "Según los horarios vigentes"),
            ("pendientes", "Horas pendientes de registrar", "Aún sin asistencia capturada"),
            ("falto", "Faltas registradas hoy", "Horas marcadas como falta"),
            ("retardo", "Retardos registrados hoy", "Horas marcadas como retardo"),
        ):
            caja, valor = indicador(titulo, "—", ayuda)
            self.cifras[clave] = valor
            fila_cifras.addWidget(caja)
        self.contenedor_cifras = QWidget()
        self.contenedor_cifras.setLayout(fila_cifras)
        fila_cifras.setContentsMargins(0, 0, 0, 0)
        self.contenedor_cifras.setVisible(self.puede_asistencia)

        # --- clases de hoy ---
        self.tabla = Tabla(
            [
                Columna("Hora", _hora),
                Columna("Docente", lambda f: f["docente_nombre"]),
                Columna("Materia o actividad", lambda f: f["asignatura"]),
                Columna("Grupo · aula", _grupo_aula),
                Columna("Estado", lambda f: ESTADOS_HORA.get(f["estado"], f["estado"])),
            ],
            "No hay clases programadas para hoy (puede ser fin de semana, día inhábil o "
            "aún no hay horarios vigentes en el periodo).",
        )
        self.tabla.setToolTip("Doble clic para abrir el registro de asistencia")
        self.buscar = busqueda_para(self.tabla, "Buscar docente, materia o aula…")
        panel_clases = QFrame(objectName="panel")
        capa_clases = QVBoxLayout(panel_clases)
        capa_clases.setContentsMargins(16, 14, 16, 16)
        titulo_clases = QHBoxLayout()
        titulo_clases.addWidget(QLabel("Clases de hoy", objectName="estado"))
        titulo_clases.addStretch()
        titulo_clases.addWidget(self.buscar, 1)
        capa_clases.addLayout(titulo_clases)
        capa_clases.addWidget(self.tabla, 1)
        panel_clases.setVisible(self.puede_asistencia)

        # --- accesos rápidos ---
        self.accesos: dict[str, QPushButton] = {}
        panel_accesos = QFrame(objectName="panel")
        capa_accesos = QVBoxLayout(panel_accesos)
        capa_accesos.setContentsMargins(16, 14, 16, 16)
        capa_accesos.addWidget(QLabel("Accesos rápidos", objectName="estado"))
        rejilla = QGridLayout()
        rejilla.setSpacing(8)
        visibles = [a for a in ACCESOS if usuario.puede(a[3])]
        for i, (texto, explicacion, pantalla, _permiso) in enumerate(visibles):
            boton = QPushButton(texto, objectName="acceso")
            boton.setToolTip(explicacion)
            boton.setAccessibleDescription(explicacion)
            boton.clicked.connect(lambda _=False, p=pantalla: self.ir(p))
            self.accesos[pantalla] = boton
            caja = QVBoxLayout()
            caja.setSpacing(2)
            caja.addWidget(boton)
            caja.addWidget(QLabel(explicacion, objectName="ayuda", wordWrap=True))
            rejilla.addLayout(caja, i // 2, i % 2)
        capa_accesos.addLayout(rejilla)
        capa_accesos.addStretch()

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(16)
        cuerpo.addWidget(panel_clases, 3)
        cuerpo.addWidget(panel_accesos, 2)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 24, 32, 24)
        capa.setSpacing(14)
        capa.addLayout(cabecera)
        capa.addWidget(self.aviso_periodo)
        capa.addWidget(self.contenedor_cifras)
        capa.addLayout(cuerpo, 1)

        self.boton_actualizar.clicked.connect(self.recargar)
        self.tabla.cellDoubleClicked.connect(lambda *_: self.ir("Asistencia por hora"))
        self.recargar()

    def ir(self, pantalla: str) -> None:
        if self.navegar is not None:
            self.navegar(pantalla)

    def recargar(self) -> None:
        try:
            activo = self.api.get("/periodos/activo")
        except ErrorApi:
            activo = None
        self.aviso_periodo.setVisible(activo is None)
        self.aviso_periodo.setText(
            "No hay un periodo académico activo. El administrador debe crearlo y activarlo "
            "en Administración › Periodos para registrar horarios y asistencia."
        )
        if not self.puede_asistencia:
            return
        try:
            datos = self.api.get("/bitacora/horas", fecha=date.today().isoformat())
        except ErrorApi:
            self.tabla.mensaje_vacio = "No se pudo consultar la información de hoy."
            self.tabla.cargar([])
            for etiqueta in self.cifras.values():
                etiqueta.setText("—")
            return
        filas = sorted(datos.get("filas", []), key=lambda f: f["programado_inicio"])
        self.tabla.cargar(filas)
        conteo = Counter(f["estado"] for f in filas)
        self.cifras["programadas"].setText(str(len(filas)))
        self.cifras["pendientes"].setText(str(conteo.get("pendiente", 0)))
        self.cifras["falto"].setText(str(conteo.get("falto", 0)))
        self.cifras["retardo"].setText(str(conteo.get("retardo", 0)))
