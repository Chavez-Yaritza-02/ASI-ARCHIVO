"""Ventana de inicio de sesión."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion


class VentanaLogin(QDialog):
    def __init__(self, api: ClienteApi, correo_previo: str = ""):
        super().__init__()
        self.api = api
        self.usuario: UsuarioSesion | None = None
        self.reconfigurar = False
        self.setWindowTitle("ASI-ARCHIVO — Iniciar sesión")
        self.setMinimumWidth(420)

        tarjeta = QFrame(objectName="tarjeta")
        caja = QVBoxLayout(tarjeta)
        caja.setContentsMargins(28, 28, 28, 28)
        caja.setSpacing(10)

        caja.addWidget(QLabel("ASI-ARCHIVO", objectName="titulo"))
        caja.addWidget(QLabel("Jefatura de Electromecánica", objectName="subtitulo"))
        caja.addSpacing(12)

        self.correo = QLineEdit(correo_previo, placeholderText="Correo institucional")
        self.contrasena = QLineEdit(placeholderText="Contraseña", echoMode=QLineEdit.Password)
        self.recordar = QCheckBox("Recordar sesión en este equipo")
        self.mensaje = QLabel("", objectName="error", wordWrap=True)
        self.boton = QPushButton("Entrar", objectName="primario")
        self.boton_servidor = QPushButton("Cambiar servidor")
        self.boton.setDefault(True)

        for w in (
            self.correo,
            self.contrasena,
            self.recordar,
            self.mensaje,
            self.boton,
            self.boton_servidor,
        ):
            caja.addWidget(w)

        externo = QVBoxLayout(self)
        externo.setContentsMargins(24, 24, 24, 24)
        externo.addWidget(tarjeta, alignment=Qt.AlignCenter)

        self.boton.clicked.connect(self._entrar)
        self.boton_servidor.clicked.connect(self.cambiar_servidor)
        (self.contrasena if correo_previo else self.correo).setFocus()

    def _entrar(self) -> None:
        correo, contrasena = self.correo.text().strip(), self.contrasena.text()
        if not correo or not contrasena:
            self.mensaje.setText("Escribe tu correo y contraseña.")
            return
        self.boton.setEnabled(False)
        self.mensaje.setText("")
        try:
            self.usuario = self.api.iniciar_sesion(correo, contrasena, self.recordar.isChecked())
        except ErrorApi as error:
            self.mensaje.setText(str(error))
            self.contrasena.clear()
            return
        finally:
            self.boton.setEnabled(True)
        self.accept()

    def cambiar_servidor(self):
        self.reconfigurar = True
        self.contrasena.clear()
        self.reject()
