"""Cuenta única de la aplicación local: primera ejecución, código de recuperación,
recuperar, cambiar contraseña y renovar el código. Todo funciona sin internet.

El código de recuperación se muestra **una sola vez**. La aplicación solo guarda su huella;
por eso la ventana del código no se cierra hasta confirmar que se guardó fuera de la
computadora (kit en PDF o impreso).
"""

from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import QMarginsF, Qt
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from asi_cliente.api.cliente import ClienteApi, ErrorApi

LONGITUD_MINIMA = 10


def _clave(marcador: str) -> QLineEdit:
    campo = QLineEdit(placeholderText=marcador, echoMode=QLineEdit.Password)
    campo.setMaxLength(128)
    return campo


def _mensaje_error(error: ErrorApi) -> str:
    return "\n".join([str(error), *error.problemas])


def revisar_contrasena(nueva: str, confirmacion: str) -> str | None:
    """Mensaje si la contraseña nueva no sirve; None si está bien."""
    if len(nueva) < LONGITUD_MINIMA:
        return f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres."
    if nueva != confirmacion:
        return "Las dos contraseñas no coinciden."
    return None


def html_kit(usuario: str, codigo: str, fecha: datetime) -> str:
    return f"""
<h2>ASI-ARCHIVO · Kit de recuperación</h2>
<p>Jefatura de Electromecánica</p>
<p>Fecha: {fecha:%d/%m/%Y %H:%M}</p>
<table cellpadding="6">
<tr><td><b>Usuario</b></td><td>{escape(usuario)}</td></tr>
<tr><td><b>Código de recuperación</b></td>
<td><span style="font-family: monospace; font-size: 16pt">{escape(codigo)}</span></td></tr>
</table>
<h3>Cómo usarlo</h3>
<ol>
<li>En la ventana de inicio de sesión pulsa <b>«¿Olvidaste tu contraseña?»</b>.</li>
<li>Escribe el usuario y este código, y elige una contraseña nueva.</li>
<li>Se generará un código nuevo: guarda el nuevo kit; este dejará de servir.</li>
</ol>
<h3>Cómo guardarlo</h3>
<ul>
<li>Guárdalo <b>fuera de esta computadora</b>: impreso en un lugar bajo llave o en una memoria
USB resguardada.</li>
<li>No lo envíes por correo ni lo compartas: con él se puede cambiar la contraseña.</li>
<li>Si se pierden la contraseña y este código, no hay otra forma de entrar a la aplicación.</li>
</ul>
"""


def guardar_kit_pdf(ruta: Path, usuario: str, codigo: str) -> None:
    escritor = QPdfWriter(str(ruta))
    escritor.setTitle("ASI-ARCHIVO · Kit de recuperación")
    escritor.setPageSize(QPageSize(QPageSize.Letter))
    escritor.setPageMargins(QMarginsF(20, 20, 20, 20), QPageLayout.Millimeter)
    documento = QTextDocument()
    documento.setDefaultFont(QFont("Helvetica", 11))
    documento.setHtml(html_kit(usuario, codigo, datetime.now()))
    documento.setPageSize(escritor.pageLayout().paintRectPixels(escritor.resolution()).size())
    documento.print_(escritor)


class DialogoCodigoRecuperacion(QDialog):
    """Muestra el código una vez. No se cierra sin confirmar que se guardó."""

    def __init__(self, usuario: str, codigo: str, explicacion: str, padre=None):
        super().__init__(padre)
        self.usuario, self.codigo = usuario, codigo
        self.kit_guardado: Path | None = None
        self.setWindowTitle("Código de recuperación")
        self.setMinimumWidth(520)
        caja = QVBoxLayout(self)
        caja.addWidget(QLabel(explicacion, wordWrap=True))
        caja.addWidget(QLabel(f"Usuario: <b>{escape(usuario)}</b>"))
        self.etiqueta = QLabel(codigo, objectName="codigo_recuperacion")
        self.etiqueta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.etiqueta.setAlignment(Qt.AlignCenter)
        fuente = QFont("Menlo, Consolas, monospace")
        fuente.setStyleHint(QFont.Monospace)
        fuente.setPointSize(18)
        fuente.setBold(True)
        self.etiqueta.setFont(fuente)
        caja.addWidget(self.etiqueta)
        caja.addWidget(
            QLabel(
                "Se muestra <b>solo esta vez</b>. Guárdalo fuera de esta computadora: si "
                "olvidas la contraseña, es la única forma de volver a entrar.",
                objectName="advertencia",
                wordWrap=True,
            )
        )
        self.boton_kit = QPushButton("Guardar kit de recuperación (PDF)…")
        self.boton_kit.clicked.connect(self.guardar_kit)
        self.aviso = QLabel("", objectName="exito", wordWrap=True)
        self.confirmar = QCheckBox("Ya guardé el código fuera de esta computadora")
        self.continuar = QPushButton("Continuar", objectName="primario")
        self.continuar.setEnabled(False)
        self.confirmar.toggled.connect(self.continuar.setEnabled)
        self.continuar.clicked.connect(self.accept)
        caja.addWidget(self.boton_kit)
        caja.addWidget(self.aviso)
        caja.addWidget(self.confirmar)
        fila = QHBoxLayout()
        fila.addStretch()
        fila.addWidget(self.continuar)
        caja.addLayout(fila)

    def guardar_kit(self, ruta: str | None = None) -> None:
        if not ruta:
            ruta, _ = QFileDialog.getSaveFileName(
                self,
                "Guardar kit de recuperación",
                str(Path.home() / "ASI-ARCHIVO-kit-de-recuperacion.pdf"),
                "PDF (*.pdf)",
            )
        if not ruta:
            return
        try:
            guardar_kit_pdf(Path(ruta), self.usuario, self.codigo)
        except OSError as error:
            QMessageBox.warning(self, "Kit de recuperación", f"No se pudo guardar: {error}")
            return
        self.kit_guardado = Path(ruta)
        self.aviso.setText(
            f"Kit guardado en {ruta}. Cópialo a una memoria USB o imprímelo y bórralo de "
            "esta computadora."
        )

    def reject(self) -> None:  # Esc o cerrar la ventana
        if self.confirmar.isChecked():
            self.accept()
            return
        QMessageBox.information(
            self,
            "Código de recuperación",
            "Antes de continuar, guarda el código y marca la casilla de confirmación.",
        )


class DialogoPrimeraEjecucion(QDialog):
    """Crea la única cuenta de administrador la primera vez que se abre la aplicación."""

    def __init__(self, api: ClienteApi, padre=None):
        super().__init__(padre)
        self.api = api
        self.usuario: str | None = None
        self.codigo: str | None = None
        self.setWindowTitle("ASI-ARCHIVO — Primera configuración")
        self.setMinimumWidth(480)
        caja = QVBoxLayout(self)
        caja.addWidget(QLabel("Bienvenida a ASI-ARCHIVO", objectName="titulo"))
        caja.addWidget(
            QLabel(
                "La aplicación trabaja en esta computadora, sin internet. Crea la cuenta de "
                "administrador: es la única cuenta y tiene acceso a todas las funciones.",
                wordWrap=True,
            )
        )
        self.campo_usuario = QLineEdit(placeholderText="p. ej. jefatura")
        self.campo_usuario.setMaxLength(120)
        self.campo_nombre = QLineEdit(placeholderText="Nombre de quien la usará")
        self.campo_nombre.setMaxLength(120)
        self.campo_clave = _clave(f"Al menos {LONGITUD_MINIMA} caracteres")
        self.campo_confirmar = _clave("Repite la contraseña")
        formulario = QFormLayout()
        formulario.addRow("Usuario", self.campo_usuario)
        formulario.addRow("Nombre", self.campo_nombre)
        formulario.addRow("Contraseña", self.campo_clave)
        formulario.addRow("Confirmar", self.campo_confirmar)
        caja.addLayout(formulario)
        self.mensaje = QLabel("", objectName="error", wordWrap=True)
        caja.addWidget(self.mensaje)
        self.boton = QPushButton("Crear cuenta", objectName="primario")
        self.boton.setDefault(True)
        self.boton.clicked.connect(self.crear)
        cancelar = QPushButton("Salir")
        cancelar.clicked.connect(self.reject)
        fila = QHBoxLayout()
        fila.addWidget(cancelar)
        fila.addStretch()
        fila.addWidget(self.boton)
        caja.addLayout(fila)

    def crear(self) -> bool:
        usuario, nombre = self.campo_usuario.text().strip(), self.campo_nombre.text().strip()
        if not usuario or not nombre:
            self.mensaje.setText("Escribe el usuario y el nombre.")
            return False
        problema = revisar_contrasena(self.campo_clave.text(), self.campo_confirmar.text())
        if problema:
            self.mensaje.setText(problema)
            return False
        try:
            r = self.api.post(
                "/local/cuenta",
                {"usuario": usuario, "nombre": nombre, "contrasena": self.campo_clave.text()},
            )
        except ErrorApi as error:
            self.mensaje.setText(_mensaje_error(error))
            return False
        self.campo_clave.clear()
        self.campo_confirmar.clear()
        self.usuario, self.codigo = r["usuario"], r["codigo_recuperacion"]
        self.mostrar_codigo()
        self.accept()
        return True

    def mostrar_codigo(self) -> None:
        DialogoCodigoRecuperacion(
            self.usuario,
            self.codigo,
            "La cuenta quedó creada. Este es tu código de recuperación: sirve para poner "
            "una contraseña nueva si la olvidas, sin internet.",
            self,
        ).exec()


class DialogoRecuperar(QDialog):
    """«¿Olvidaste tu contraseña?»: código de recuperación + contraseña nueva."""

    def __init__(self, api: ClienteApi, usuario: str = "", padre=None):
        super().__init__(padre)
        self.api = api
        self.usuario: str | None = None
        self.codigo_nuevo: str | None = None
        self.setWindowTitle("Recuperar la contraseña")
        self.setMinimumWidth(480)
        caja = QVBoxLayout(self)
        caja.addWidget(
            QLabel(
                "Escribe el código de recuperación de tu kit (impreso o en la memoria USB) y "
                "elige una contraseña nueva. Después se generará un código nuevo.",
                wordWrap=True,
            )
        )
        self.campo_usuario = QLineEdit(usuario, placeholderText="Usuario")
        self.campo_codigo = QLineEdit(placeholderText="XXXXX-XXXXX-XXXXX-XXXXX-XXXXX")
        self.campo_codigo.setMaxLength(64)
        self.campo_clave = _clave(f"Al menos {LONGITUD_MINIMA} caracteres")
        self.campo_confirmar = _clave("Repite la contraseña")
        formulario = QFormLayout()
        formulario.addRow("Usuario", self.campo_usuario)
        formulario.addRow("Código", self.campo_codigo)
        formulario.addRow("Contraseña nueva", self.campo_clave)
        formulario.addRow("Confirmar", self.campo_confirmar)
        caja.addLayout(formulario)
        self.mensaje = QLabel("", objectName="error", wordWrap=True)
        caja.addWidget(self.mensaje)
        self.boton = QPushButton("Cambiar contraseña", objectName="primario")
        self.boton.setDefault(True)
        self.boton.clicked.connect(self.recuperar)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        fila = QHBoxLayout()
        fila.addWidget(cancelar)
        fila.addStretch()
        fila.addWidget(self.boton)
        caja.addLayout(fila)
        (self.campo_codigo if usuario else self.campo_usuario).setFocus()

    def recuperar(self) -> bool:
        usuario, codigo = self.campo_usuario.text().strip(), self.campo_codigo.text().strip()
        if not usuario or not codigo:
            self.mensaje.setText("Escribe el usuario y el código de recuperación.")
            return False
        problema = revisar_contrasena(self.campo_clave.text(), self.campo_confirmar.text())
        if problema:
            self.mensaje.setText(problema)
            return False
        try:
            r = self.api.post(
                "/local/recuperar",
                {"usuario": usuario, "codigo": codigo, "nueva": self.campo_clave.text()},
            )
        except ErrorApi as error:
            self.mensaje.setText(_mensaje_error(error))
            return False
        finally:
            self.campo_clave.clear()
            self.campo_confirmar.clear()
        self.usuario, self.codigo_nuevo = r["usuario"], r["codigo_recuperacion"]
        self.mostrar_codigo()
        self.accept()
        return True

    def mostrar_codigo(self) -> None:
        DialogoCodigoRecuperacion(
            self.usuario,
            self.codigo_nuevo,
            "La contraseña se cambió. El código anterior ya no sirve; este es el nuevo.",
            self,
        ).exec()


class DialogoCambiarContrasena(QDialog):
    def __init__(self, api: ClienteApi, padre=None):
        super().__init__(padre)
        self.api = api
        self.setWindowTitle("Cambiar contraseña")
        self.setMinimumWidth(440)
        caja = QVBoxLayout(self)
        self.campo_actual = _clave("Contraseña actual")
        self.campo_clave = _clave(f"Al menos {LONGITUD_MINIMA} caracteres")
        self.campo_confirmar = _clave("Repite la contraseña nueva")
        formulario = QFormLayout()
        formulario.addRow("Actual", self.campo_actual)
        formulario.addRow("Nueva", self.campo_clave)
        formulario.addRow("Confirmar", self.campo_confirmar)
        caja.addLayout(formulario)
        self.mensaje = QLabel("", objectName="error", wordWrap=True)
        caja.addWidget(self.mensaje)
        self.boton = QPushButton("Cambiar", objectName="primario")
        self.boton.setDefault(True)
        self.boton.clicked.connect(self.cambiar)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        fila = QHBoxLayout()
        fila.addWidget(cancelar)
        fila.addStretch()
        fila.addWidget(self.boton)
        caja.addLayout(fila)

    def cambiar(self) -> bool:
        problema = revisar_contrasena(self.campo_clave.text(), self.campo_confirmar.text())
        if problema:
            self.mensaje.setText(problema)
            return False
        try:
            self.api.cambiar_contrasena(self.campo_actual.text(), self.campo_clave.text())
        except ErrorApi as error:
            self.mensaje.setText(_mensaje_error(error))
            return False
        finally:
            for campo in (self.campo_actual, self.campo_clave, self.campo_confirmar):
                campo.clear()
        self.accept()
        return True


class DialogoRenovarCodigo(QDialog):
    """Genera un código de recuperación nuevo (p. ej. si se perdió el kit)."""

    def __init__(self, api: ClienteApi, padre=None):
        super().__init__(padre)
        self.api = api
        self.codigo: str | None = None
        self.setWindowTitle("Nuevo código de recuperación")
        self.setMinimumWidth(440)
        caja = QVBoxLayout(self)
        caja.addWidget(
            QLabel(
                "Se generará un código nuevo y el anterior dejará de servir. Confirma con tu "
                "contraseña.",
                wordWrap=True,
            )
        )
        self.campo_clave = _clave("Contraseña actual")
        caja.addWidget(self.campo_clave)
        self.mensaje = QLabel("", objectName="error", wordWrap=True)
        caja.addWidget(self.mensaje)
        self.boton = QPushButton("Generar código", objectName="primario")
        self.boton.setDefault(True)
        self.boton.clicked.connect(self.renovar)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        fila = QHBoxLayout()
        fila.addWidget(cancelar)
        fila.addStretch()
        fila.addWidget(self.boton)
        caja.addLayout(fila)

    def renovar(self) -> bool:
        try:
            r = self.api.post("/local/codigo", {"contrasena": self.campo_clave.text()})
        except ErrorApi as error:
            self.mensaje.setText(_mensaje_error(error))
            return False
        finally:
            self.campo_clave.clear()
        self.codigo = r["codigo_recuperacion"]
        self.mostrar_codigo(r["usuario"])
        self.accept()
        return True

    def mostrar_codigo(self, usuario: str) -> None:
        DialogoCodigoRecuperacion(
            usuario, self.codigo, "Este es tu nuevo código de recuperación.", self
        ).exec()
