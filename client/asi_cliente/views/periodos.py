"""Pantalla de periodos académicos: crear, editar, activar y cerrar."""

from datetime import date

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

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

CAMPOS = [
    Campo("nombre", "Nombre (p. ej. AGOSTO - DICIEMBRE 2026)", obligatorio=True),
    Campo("fecha_inicio", "Inicio", "fecha"),
    Campo("fecha_fin", "Fin", "fecha"),
]


def _fecha(texto: str) -> str:
    return date.fromisoformat(texto).strftime("%d/%m/%Y")


class VistaPeriodos(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api = api
        self.puede_gestionar = usuario.puede("periodos.gestionar")
        self.tabla = Tabla(
            [
                Columna("Periodo", lambda p: p["nombre"]),
                Columna("Inicio", lambda p: _fecha(p["fecha_inicio"])),
                Columna("Fin", lambda p: _fecha(p["fecha_fin"])),
                Columna("Estado", lambda p: p["estado"], estado=True),
            ]
        )
        self.boton_nuevo = QPushButton("Nuevo periodo", objectName="primario")
        self.boton_editar = QPushButton("Editar")
        self.boton_activar = QPushButton("Activar")
        self.boton_cerrar = QPushButton("Cerrar periodo")

        barra = QHBoxLayout()
        barra.addStretch()
        for boton in (self.boton_nuevo, self.boton_editar, self.boton_activar, self.boton_cerrar):
            boton.setVisible(self.puede_gestionar)
            barra.addWidget(boton)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 28, 32, 28)
        capa.addWidget(
            encabezado(
                "Periodos",
                "Solo un periodo puede estar activo. Al cambiar de semestre, cierra el periodo "
                "actual y activa el nuevo. Los periodos cerrados se conservan como historial.",
            )
        )
        capa.addLayout(barra)
        capa.addWidget(self.tabla, 1)

        self.boton_nuevo.clicked.connect(self.nuevo)
        self.boton_editar.clicked.connect(self.editar)
        self.boton_activar.clicked.connect(lambda: self._cambiar("activar"))
        self.boton_cerrar.clicked.connect(lambda: self._cambiar("cerrar"))
        self.tabla.itemSelectionChanged.connect(self._actualizar_botones)
        self.recargar()

    def recargar(self) -> None:
        try:
            self.tabla.cargar(self.api.get("/periodos"))
        except ErrorApi as error:
            mostrar_error(self, error, "No se pudieron cargar los periodos")
        self._actualizar_botones()

    def _actualizar_botones(self) -> None:
        p = self.tabla.seleccionado()
        estado = p["estado"] if p else None
        self.boton_editar.setEnabled(estado in ("borrador", "activo"))
        self.boton_activar.setEnabled(estado == "borrador")
        self.boton_cerrar.setEnabled(estado in ("borrador", "activo"))

    def _guardar(self, titulo: str, valores: dict | None, enviar) -> None:
        dialogo = DialogoFormulario(titulo, CAMPOS, valores, padre=self)
        while dialogo.exec():
            try:
                periodo = enviar(dialogo.valores())
            except ErrorApi as error:
                mostrar_error(self, error)
                continue
            self.recargar()
            self.tabla.seleccionar_id(periodo["id"])
            return

    def nuevo(self) -> None:
        self._guardar("Nuevo periodo", None, lambda datos: self.api.post("/periodos", datos))

    def editar(self) -> None:
        p = self.tabla.seleccionado()
        if p:
            self._guardar(
                "Editar periodo", p, lambda datos: self.api.put(f"/periodos/{p['id']}", datos)
            )

    def _cambiar(self, accion: str) -> None:
        p = self.tabla.seleccionado()
        if p is None:
            return
        avisos = {
            "activar": ("¿Activar {}?", "Será el periodo de trabajo para horarios y bitácora."),
            "cerrar": (
                "¿Cerrar {}?",
                "Sus horarios quedarán de solo lectura. "
                "Esta acción no se puede deshacer desde la aplicación.",
            ),
        }
        pregunta, detalle = avisos[accion]
        if not confirmar(self, pregunta.format(p["nombre"]), detalle):
            return
        try:
            self.api.post(f"/periodos/{p['id']}/{accion}")
        except ErrorApi as error:
            mostrar_error(self, error)
        self.recargar()
        self.tabla.seleccionar_id(p["id"])
