"""Arranque de la aplicación de escritorio.

Ejecutar en desarrollo:  uv run asi-archivo
    Modo local (predeterminado): todo se guarda en esta computadora (ver asi_cliente/local.py).
    Con servidor central:     uv run asi-archivo --servidor   (o definiendo ASI_SERVIDOR_URL)
"""

import multiprocessing
import os
import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from asi_cliente.api.cliente import ClienteApi, ErrorApi
from asi_cliente.theme.estilos import hoja_de_estilo
from asi_cliente.views.configuracion_inicial import ConfiguracionInicial
from asi_cliente.views.login import VentanaLogin
from asi_cliente.views.ventana_principal import VentanaPrincipal


class Aplicacion:
    def __init__(self, app: QApplication, api: ClienteApi, modo_local: bool = False):
        self.app = app
        self.api = api
        self.modo_local = modo_local
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
        usuario = self.api.usuario or (self.api.restaurar_sesion(correo) if correo else None)
        if usuario is None:
            if not self.modo_local and not self.api.servidor_disponible():
                QMessageBox.warning(
                    None,
                    "ASI-ARCHIVO",
                    "No se pudo conectar con el servidor.\n"
                    "Revisa tu conexión a internet o avisa al administrador.",
                )
            login = VentanaLogin(self.api, correo)
            # En el modo local no hay otro servidor al cual cambiarse.
            login.boton_servidor.setVisible(not self.modo_local)
            if login.exec() != QDialog.Accepted:
                if login.reconfigurar and self.configurar_servidor():
                    return self.iniciar()
                return False
            usuario = login.usuario
            self.preferencias.setValue("ultimo_correo", usuario.correo)

        self.ventana = VentanaPrincipal(usuario, self.api)
        self.ventana.cambiar_tema.connect(self.alternar_tema)
        self.ventana.cerrar_sesion.connect(self.salir_de_sesion)
        self.ventana.show()
        return True

    def configurar_servidor(self):
        dialogo = ConfiguracionInicial(self.preferencias.value("servidor_url", ""))
        if dialogo.exec() != QDialog.Accepted:
            return False
        self.api.cerrar()
        self.api = dialogo.api
        self.preferencias.setValue("servidor_url", dialogo.url_validada)
        self.preferencias.setValue("ultimo_correo", self.api.usuario.correo)
        return True

    def salir_de_sesion(self) -> None:
        self.api.cerrar_sesion(self.preferencias.value("ultimo_correo", ""))
        if self.ventana:
            # Se oculta (no se cierra) para que Qt no termine la app antes del nuevo login.
            self.ventana.hide()
            self.ventana.deleteLater()
        if not self.iniciar():
            self.app.quit()


def main_local(app: QApplication) -> int:
    """Modo local: arranca la base y la API dentro de la aplicación."""
    from asi_cliente import local
    from asi_cliente.views.primer_usuario import VentanaPrimerUsuario

    datos = local.carpeta_datos()
    try:
        servidor, hay_usuarios = local.preparar(datos)
    except Exception as error:  # cualquier fallo aquí impide abrir: se explica y se sale
        QMessageBox.critical(
            None,
            "ASI-ARCHIVO",
            "No se pudo abrir la información guardada en esta computadora.\n\n"
            f"Carpeta de datos: {datos}\nDetalle: {error}",
        )
        return 1
    api = ClienteApi(http=servidor.cliente_http())
    aplicacion = Aplicacion(app, api, modo_local=True)  # aplica el tema desde la bienvenida
    try:
        if not hay_usuarios:
            bienvenida = VentanaPrimerUsuario(local.crear_administrador)
            if bienvenida.exec() != QDialog.Accepted:
                return 0
            api.iniciar_sesion(bienvenida.correo_creado, bienvenida.contrasena_creada)
            QSettings("TecMM-Zapopan", "ASI-ARCHIVO").setValue(
                "ultimo_correo", bienvenida.correo_creado
            )
        if not aplicacion.iniciar():
            return 0
        return app.exec()
    finally:
        aplicacion.api.cerrar()
        servidor.detener()


def main() -> None:
    # La importación de horarios usa varios procesos; en el .exe empaquetado cada proceso
    # hijo vuelve a abrir este mismo programa y aquí se desvía a su tarea.
    multiprocessing.freeze_support()
    if "--procesar-archivo" in sys.argv:
        # Proceso aislado que el modo local usa para revisar documentos (ver almacen.py).
        from app.archivos.procesador import main as procesar

        procesar(sys.argv[sys.argv.index("--procesar-archivo") + 1 :])
        sys.exit(0)
    app = QApplication(sys.argv)
    app.setApplicationName("ASI-ARCHIVO")
    if "--comprobar-tls" in sys.argv:
        from asi_cliente.diagnostico_tls import ejecutar

        sys.exit(ejecutar())
    if "--autoprueba-local" in sys.argv:
        from pathlib import Path

        from asi_cliente.local import autoprueba

        sys.exit(autoprueba(Path(sys.argv[sys.argv.index("--resultado") + 1])))
    if "--autoprueba" in sys.argv:
        from asi_cliente.autoprueba import ejecutar

        sys.exit(ejecutar(app))
    if "--servidor" not in sys.argv and not os.environ.get("ASI_SERVIDOR_URL"):
        sys.exit(main_local(app))
    preferencias = QSettings("TecMM-Zapopan", "ASI-ARCHIVO")
    direccion = os.environ.get("ASI_SERVIDOR_URL") or preferencias.value("servidor_url", "")
    if not direccion or "--configurar" in sys.argv:
        dialogo = ConfiguracionInicial(direccion)
        if dialogo.exec() != QDialog.Accepted:
            sys.exit(0)
        api = dialogo.api
        preferencias.setValue("servidor_url", dialogo.url_validada)
        preferencias.setValue("ultimo_correo", api.usuario.correo)
    else:
        try:
            api = ClienteApi(direccion)
        except ErrorApi as error:
            QMessageBox.critical(None, "ASI-ARCHIVO", str(error))
            sys.exit(1)
    aplicacion = Aplicacion(app, api)
    app.aboutToQuit.connect(lambda: aplicacion.api.cerrar())
    if not aplicacion.iniciar():
        sys.exit(0)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
