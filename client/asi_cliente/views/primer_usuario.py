"""Primera vez en el modo local: crear la cuenta de administrador de esta computadora."""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout

LONGITUD_MINIMA = 10


class VentanaPrimerUsuario(QDialog):
    def __init__(self, crear: Callable[[str, str, str], None]):
        super().__init__()
        self._crear = crear
        self.correo_creado = ""
        self.contrasena_creada = ""
        self.setWindowTitle("ASI-ARCHIVO — Bienvenida")
        self.setMinimumWidth(460)

        tarjeta = QFrame(objectName="tarjeta")
        caja = QVBoxLayout(tarjeta)
        caja.setContentsMargins(28, 28, 28, 28)
        caja.setSpacing(10)
        caja.addWidget(QLabel("Bienvenida a ASI-ARCHIVO", objectName="titulo"))
        caja.addWidget(
            QLabel(
                "Es la primera vez que se abre en esta computadora. Crea tu cuenta de "
                "administrador; con ella entrarás de aquí en adelante.",
                objectName="subtitulo",
                wordWrap=True,
            )
        )
        caja.addSpacing(8)
        self.nombre = QLineEdit(placeholderText="Nombre completo")
        self.correo = QLineEdit(placeholderText="Correo institucional")
        self.contrasena = QLineEdit(
            placeholderText=f"Contraseña (mínimo {LONGITUD_MINIMA} caracteres)",
            echoMode=QLineEdit.Password,
        )
        self.confirmacion = QLineEdit(
            placeholderText="Repite la contraseña", echoMode=QLineEdit.Password
        )
        self.mensaje = QLabel("", objectName="error", wordWrap=True)
        self.boton = QPushButton("Crear cuenta y entrar", objectName="primario")
        self.boton.setDefault(True)
        for w in (
            self.nombre,
            self.correo,
            self.contrasena,
            self.confirmacion,
            self.mensaje,
            self.boton,
        ):
            caja.addWidget(w)

        externo = QVBoxLayout(self)
        externo.setContentsMargins(24, 24, 24, 24)
        externo.addWidget(tarjeta, alignment=Qt.AlignCenter)
        self.boton.clicked.connect(self._crear_cuenta)
        self.nombre.setFocus()

    def _crear_cuenta(self) -> None:
        nombre = " ".join(self.nombre.text().split())
        correo = self.correo.text().strip().lower()
        contrasena = self.contrasena.text()
        if not nombre or "@" not in correo:
            self.mensaje.setText("Escribe tu nombre y un correo válido.")
            return
        if len(contrasena) < LONGITUD_MINIMA:
            self.mensaje.setText(f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres.")
            return
        if contrasena != self.confirmacion.text():
            self.mensaje.setText("Las contraseñas no coinciden.")
            self.confirmacion.clear()
            return
        try:
            self._crear(correo, nombre, contrasena)
        except ValueError as error:
            self.mensaje.setText(str(error))
            return
        self.correo_creado, self.contrasena_creada = correo, contrasena
        self.accept()
