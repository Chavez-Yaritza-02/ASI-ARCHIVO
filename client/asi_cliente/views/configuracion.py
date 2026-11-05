"""Configuración de esta computadora: usuario, servidor, versión, tema y atajos.

No cambia datos del servidor. El tema y el cierre de sesión usan las mismas señales
que los botones del menú lateral.
"""

from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion
from asi_shared.version import VERSION

ATAJOS = [
    ("Ctrl+1 … Ctrl+6", "Ir a Inicio, Asistencias, Horarios, Docentes, Reportes o Administración"),
    ("Ctrl+Tab / Ctrl+Mayús+Tab", "Pasar a la pestaña siguiente o anterior de la sección"),
    ("Tab / Mayús+Tab", "Moverse entre botones y campos"),
    ("Flechas ↑ ↓", "Moverse por el menú y por las filas de una tabla"),
    ("Enter o doble clic", "Abrir o editar el elemento seleccionado"),
    ("F5", "Actualizar la pantalla de Inicio"),
]


def _panel(titulo: str) -> tuple[QFrame, QVBoxLayout]:
    panel = QFrame(objectName="panel")
    capa = QVBoxLayout(panel)
    capa.setContentsMargins(18, 14, 18, 16)
    capa.addWidget(QLabel(titulo, objectName="estado"))
    return panel, capa


class VistaConfiguracion(QWidget):
    def __init__(self, api: ClienteApi, usuario: UsuarioSesion):
        super().__init__()
        self.api, self.usuario = api, usuario
        self.ventana = None  # la asigna la ventana principal

        panel_cuenta, capa_cuenta = _panel("Tu cuenta")
        datos = QFormLayout()
        datos.addRow("Nombre", QLabel(usuario.nombre))
        datos.addRow("Correo", QLabel(usuario.correo))
        datos.addRow("Rol", QLabel(", ".join(r.capitalize() for r in usuario.roles)))
        capa_cuenta.addLayout(datos)
        self.boton_salir = QPushButton("Cerrar sesión")
        fila = QHBoxLayout()
        fila.addWidget(self.boton_salir)
        fila.addStretch()
        capa_cuenta.addLayout(fila)

        panel_conexion, capa_conexion = _panel("Conexión")
        self.servidor = QLabel(self.direccion_servidor())
        self.servidor.setWordWrap(True)
        self.estado_servidor = QLabel("", objectName="suave")
        conexion = QFormLayout()
        conexion.addRow("Servidor", self.servidor)
        conexion.addRow("Estado", self.estado_servidor)
        conexion.addRow("Versión de la aplicación", QLabel(VERSION))
        capa_conexion.addLayout(conexion)
        capa_conexion.addWidget(
            QLabel(
                "Para usar otro servidor: cierra sesión y, en la ventana de inicio de sesión, "
                "elige «Cambiar servidor». Pide la dirección al administrador.",
                objectName="ayuda",
                wordWrap=True,
            )
        )
        self.boton_probar = QPushButton("Probar conexión")
        fila = QHBoxLayout()
        fila.addWidget(self.boton_probar)
        fila.addStretch()
        capa_conexion.addLayout(fila)

        panel_apariencia, capa_apariencia = _panel("Apariencia")
        capa_apariencia.addWidget(
            QLabel(
                "El tema oscuro descansa la vista en jornadas largas. Se recuerda en esta "
                "computadora.",
                objectName="ayuda",
                wordWrap=True,
            )
        )
        self.boton_tema = QPushButton("Cambiar entre tema claro y oscuro")
        fila = QHBoxLayout()
        fila.addWidget(self.boton_tema)
        fila.addStretch()
        capa_apariencia.addLayout(fila)

        panel_atajos, capa_atajos = _panel("Atajos de teclado")
        atajos = QFormLayout()
        atajos.setVerticalSpacing(8)
        for tecla, accion in ATAJOS:
            atajos.addRow(QLabel(tecla, objectName="estado"), QLabel(accion, wordWrap=True))
        capa_atajos.addLayout(atajos)

        izquierda = QVBoxLayout()
        izquierda.setSpacing(14)
        for p in (panel_cuenta, panel_conexion, panel_apariencia):
            izquierda.addWidget(p)
        izquierda.addStretch()
        derecha = QVBoxLayout()
        derecha.addWidget(panel_atajos)
        derecha.addStretch()
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(16)
        cuerpo.addLayout(izquierda, 1)
        cuerpo.addLayout(derecha, 1)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(32, 24, 32, 24)
        capa.addLayout(cuerpo)

        self.boton_tema.clicked.connect(self._tema)
        self.boton_salir.clicked.connect(self._salir)
        self.boton_probar.clicked.connect(self.probar_conexion)
        self.probar_conexion()

    def direccion_servidor(self) -> str:
        http = getattr(self.api, "_http", None)
        return str(getattr(http, "base_url", "")) or "No configurado"

    def probar_conexion(self) -> bool:
        try:
            estado = self.api.get("/sistema/estado")
        except ErrorApi:
            self.estado_servidor.setObjectName("error")
            self.estado_servidor.setText("Sin conexión con el servidor")
            ok = False
        else:
            ok = estado.get("base_de_datos", estado.get("estado")) == "ok"
            self.estado_servidor.setObjectName("exito" if ok else "advertencia")
            self.estado_servidor.setText(
                "Conectado y funcionando" if ok else "Conectado, con problemas en el servidor"
            )
        self.estado_servidor.style().unpolish(self.estado_servidor)
        self.estado_servidor.style().polish(self.estado_servidor)
        return ok

    def _tema(self) -> None:
        if self.ventana is not None:
            self.ventana.cambiar_tema.emit()

    def _salir(self) -> None:
        if self.ventana is not None:
            self.ventana.cerrar_sesion.emit()
