"""Conexión inicial: solo preferencias no sensibles; contraseñas en memoria."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, validar_url
from asi_cliente.views.ventana_principal import secciones_visibles
from asi_shared.version import PROTOCOLO


class ConfiguracionInicial(QDialog):
    def __init__(self, direccion="", padre=None, fabrica_api=ClienteApi):
        super().__init__(padre)
        self.setWindowTitle("ASI-ARCHIVO — Conectar con Jefatura")
        self.setMinimumWidth(580)
        self.fabrica_api = fabrica_api
        self.api = None
        self.url_validada = None
        self.direccion = QLineEdit(direccion, placeholderText="https://servidor.autorizado.mx")
        self.correo = QLineEdit(placeholderText="Tu correo")
        self.contrasena = QLineEdit(echoMode=QLineEdit.Password)
        self.probar = QPushButton("1. Comprobar conexión HTTPS")
        self.entrar = QPushButton("2. Iniciar sesión y validar permisos")
        self.entrar.setEnabled(False)
        self.mensaje = QLabel("Solicita al administrador la dirección oficial del servidor.")
        self.mensaje.setTextFormat(Qt.PlainText)
        self.mensaje.setWordWrap(True)
        self.botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.botones.button(QDialogButtonBox.Ok).setText("Abrir ASI-ARCHIVO")
        self.botones.button(QDialogButtonBox.Ok).setEnabled(False)
        self.botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel("Conexión al servidor central", objectName="titulo"))
        formulario = QFormLayout()
        formulario.addRow("Dirección del servidor", self.direccion)
        capa.addLayout(formulario)
        capa.addWidget(self.probar)
        credenciales = QFormLayout()
        credenciales.addRow("Correo", self.correo)
        credenciales.addRow("Contraseña", self.contrasena)
        capa.addLayout(credenciales)
        capa.addWidget(self.entrar)
        capa.addWidget(self.mensaje)
        capa.addWidget(self.botones)
        self.probar.clicked.connect(self.comprobar)
        self.entrar.clicked.connect(self.autenticar)
        self.direccion.textChanged.connect(self.invalidar)
        self.correo.textChanged.connect(self.invalidar_usuario)
        self.botones.accepted.connect(self.finalizar)
        self.botones.rejected.connect(self.reject)

    def invalidar_usuario(self):
        self.botones.button(QDialogButtonBox.Ok).setEnabled(False)
        if self.api:
            self.api.cerrar_sesion()

    def invalidar(self):
        self.invalidar_usuario()
        self.contrasena.clear()
        self.url_validada = None
        self.entrar.setEnabled(False)
        if self.api:
            self.api.cerrar()
            self.api = None

    def comprobar(self):
        self.invalidar()
        self.probar.setEnabled(False)
        try:
            url = validar_url(self.direccion.text(), solo_https=True)
            self.api = self.fabrica_api(url)
            datos = self.api.get("/sistema/identidad")
            if datos.get("producto") != "ASI-ARCHIVO" or datos.get("protocolo") != PROTOCOLO:
                raise ErrorApi("El servidor no es una versión compatible de ASI-ARCHIVO")
            self.url_validada = url
            self.entrar.setEnabled(True)
            self.mensaje.setText(
                f"Conexión HTTPS verificada · API {datos['version']}. Inicia sesión para continuar."
            )
        except (ErrorApi, KeyError, ValueError) as error:
            self.invalidar()
            self.mensaje.setText(str(error))
        finally:
            self.probar.setEnabled(True)

    def autenticar(self):
        if not self.api or not self.url_validada:
            return
        self.invalidar_usuario()
        self.entrar.setEnabled(False)
        try:
            usuario = self.api.iniciar_sesion(self.correo.text().strip(), self.contrasena.text())
            estado = self.api.get("/sistema/estado")
            if estado.get("estado") != "ok" or estado.get("esquema") != "compatible":
                raise ErrorApi("El servicio requiere revisión del administrador")
            secciones = secciones_visibles(usuario)
            if not secciones:
                raise ErrorApi(
                    "Tu cuenta no tiene permisos para abrir módulos; consulta al administrador"
                )
            aviso = (
                " El antivirus aún requiere configuración; la carga de documentos no está lista."
                if not estado.get("antivirus_configurado")
                else ""
            )
            self.mensaje.setText(
                f"Sesión verificada · Roles: {', '.join(usuario.roles)}. "
                f"Módulos disponibles: {', '.join(s[0] for s in secciones)}." + aviso
            )
            self.botones.button(QDialogButtonBox.Ok).setEnabled(True)
        except ErrorApi as error:
            self.api.cerrar_sesion()
            self.mensaje.setText(str(error))
        finally:
            self.contrasena.clear()
            self.entrar.setEnabled(True)

    def finalizar(self):
        if self.url_validada and self.api and self.api.usuario:
            self.accept()

    def reject(self):
        self.invalidar()
        super().reject()
