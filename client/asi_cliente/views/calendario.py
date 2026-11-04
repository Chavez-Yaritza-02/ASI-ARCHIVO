"""Calendario institucional: días inhábiles, vacaciones, suspensiones y excepciones."""

from datetime import date

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_cliente.views.comunes import (
    Campo,
    Columna,
    DialogoFormulario,
    Tabla,
    confirmar,
    encabezado,
    mostrar_error,
)

TIPOS = {
    "inhabil": "Día inhábil",
    "vacaciones": "Vacaciones",
    "suspension": "Suspensión",
    "habil": "Día hábil (excepción)",
}
TURNOS = [("Todo el día", None), ("Matutino", "matutino"), ("Vespertino", "vespertino")]
CAMPOS = [
    Campo("tipo", "Tipo", "opciones", [(n, c) for c, n in TIPOS.items()]),
    Campo("fecha_inicio", "Desde", "fecha"),
    Campo("fecha_fin", "Hasta", "fecha"),
    Campo("turno", "Turno", "opciones", TURNOS),
    Campo("descripcion", "Motivo", obligatorio=True),
]


def _fecha(texto: str) -> str:
    return date.fromisoformat(texto).strftime("%d/%m/%Y")


class VistaCalendario(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api = api
        self.puede_gestionar = usuario.puede("periodos.gestionar")
        self.tabla = Tabla(
            [
                Columna("Tipo", lambda e: TIPOS[e["tipo"]]),
                Columna("Desde", lambda e: _fecha(e["fecha_inicio"])),
                Columna("Hasta", lambda e: _fecha(e["fecha_fin"])),
                Columna("Turno", lambda e: (e["turno"] or "todo el día").capitalize()),
                Columna("Motivo", lambda e: e["descripcion"]),
                Columna("Estado", lambda e: "Vigente" if e["activo"] else "Anulado"),
            ]
        )
        cabecera = self.tabla.horizontalHeader()
        for col in range(6):
            cabecera.setSectionResizeMode(
                col, QHeaderView.Stretch if col == 4 else QHeaderView.ResizeToContents
            )
        self.anulados = QCheckBox("Mostrar anulados")
        self.boton_nuevo = QPushButton("Nuevo evento", objectName="primario")
        self.boton_editar = QPushButton("Editar")
        self.boton_anular = QPushButton("Anular")
        barra = QHBoxLayout()
        barra.addWidget(self.anulados)
        barra.addStretch()
        for b in (self.boton_nuevo, self.boton_editar, self.boton_anular):
            b.setVisible(self.puede_gestionar)
            barra.addWidget(b)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 28, 32, 28)
        capa.addWidget(
            encabezado(
                "Calendario institucional",
                "En los días inhábiles, vacaciones y suspensiones la bitácora no espera "
                "registros ni genera faltas. Un «día hábil (excepción)» gana sobre ellos "
                "(p. ej. una reposición).",
            )
        )
        capa.addLayout(barra)
        capa.addWidget(self.tabla, 1)
        self.anulados.toggled.connect(self.recargar)
        self.boton_nuevo.clicked.connect(self.nuevo)
        self.boton_editar.clicked.connect(self.editar)
        self.boton_anular.clicked.connect(self.anular)
        self.tabla.itemSelectionChanged.connect(self._actualizar_botones)
        self.recargar()

    def recargar(self, *_args) -> None:
        try:
            eventos = self.api.get(
                "/calendario", incluir_anulados="true" if self.anulados.isChecked() else None
            )
        except ErrorApi as error:
            mostrar_error(self, error, "No se pudo cargar el calendario")
            return
        self.tabla.cargar(eventos)
        self._actualizar_botones()

    def _actualizar_botones(self) -> None:
        e = self.tabla.seleccionado()
        self.boton_editar.setEnabled(bool(e and e["activo"]))
        self.boton_anular.setEnabled(bool(e and e["activo"]))

    def _guardar(self, titulo: str, valores: dict | None, enviar) -> None:
        dialogo = DialogoFormulario(titulo, CAMPOS, valores, padre=self)
        while dialogo.exec():
            try:
                evento = enviar(dialogo.valores())
            except ErrorApi as error:
                mostrar_error(self, error)
                continue
            self.recargar()
            self.tabla.seleccionar_id(evento["id"])
            return

    def nuevo(self) -> None:
        self._guardar("Nuevo evento", None, lambda d: self.api.post("/calendario", d))

    def editar(self) -> None:
        e = self.tabla.seleccionado()
        if e:
            self._guardar("Editar evento", e, lambda d: self.api.put(f"/calendario/{e['id']}", d))

    def anular(self) -> None:
        e = self.tabla.seleccionado()
        if not e or not confirmar(
            self,
            f"¿Anular «{e['descripcion']}»?",
            "Queda en el historial; la bitácora vuelve a esperar registros.",
        ):
            return
        try:
            self.api.post(f"/calendario/{e['id']}/anular")
        except ErrorApi as error:
            mostrar_error(self, error)
        self.recargar()
