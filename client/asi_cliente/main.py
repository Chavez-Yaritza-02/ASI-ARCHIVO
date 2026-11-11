"""Arranque de la aplicación de escritorio.

Ejecutar en desarrollo:  uv run asi-archivo
"""

import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from asi_cliente.api.cliente import ClienteApi, ErrorApi
from asi_cliente.theme.estilos import hoja_de_estilo
from asi_cliente.views.login import VentanaLogin
from asi_cliente.views.ventana_principal import VentanaPrincipal


class Aplicacion:
    def __init__(self, app: QApplication, api: ClienteApi):
        self.app = app
        self.api = api
        # Preferencias locales (no son datos institucionales): tema y último correo.
        self.preferencias = QSettings("TecMM-Zapopan", "ASI-ARCHIVO")
        self.ventana: VentanaPrincipal | None = None
        self.aplicar_tema(self.preferencias.value("tema", "claro"))

    def aplicar_tema(self, tema: str) -> None:
        self.preferencias.setValue("tema", tema)
        self.app.setStyleSheet(hoja_de_estilo(tema))

    def alternar_tema(self) -> None:
        actual = self.preferencias.value("tema", "claro")
        self.aplicar_tema("oscuro" if actual == "claro" else "claro")

    def iniciar(self) -> bool:
        correo = self.preferencias.value("ultimo_correo", "")
        usuario = self.api.restaurar_sesion(correo) if correo else None
        if usuario is None:
            if not self.api.servidor_disponible():
                QMessageBox.warning(
                    None,
                    "ASI-ARCHIVO",
                    "No se pudo conectar con el servidor.\n"
                    "Revisa tu conexión a internet o avisa al administrador.",
                )
            login = VentanaLogin(self.api, correo)
            if login.exec() != QDialog.Accepted:
                return False
            usuario = login.usuario
            self.preferencias.setValue("ultimo_correo", usuario.correo)

        self.ventana = VentanaPrincipal(usuario, self.api)
        self.ventana.cambiar_tema.connect(self.alternar_tema)
        self.ventana.cerrar_sesion.connect(self.salir_de_sesion)
        self.ventana.show()
        return True

    def salir_de_sesion(self) -> None:
        self.api.cerrar_sesion(self.preferencias.value("ultimo_correo", ""))
        if self.ventana:
            # Se oculta (no se cierra) para que Qt no termine la app antes del nuevo login.
            self.ventana.hide()
            self.ventana.deleteLater()
        if not self.iniciar():
            self.app.quit()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("ASI-ARCHIVO")
    try:
        api = ClienteApi()
    except ErrorApi as error:
        QMessageBox.critical(None, "ASI-ARCHIVO", str(error))
        sys.exit(1)
    aplicacion = Aplicacion(app, api)
    if not aplicacion.iniciar():
        sys.exit(0)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
