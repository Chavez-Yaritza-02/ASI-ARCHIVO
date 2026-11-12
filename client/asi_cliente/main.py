"""Arranque de la aplicación de escritorio.

Ejecutar en desarrollo:
    uv run asi-archivo            conectada a un servidor (como hasta ahora)
    uv run asi-archivo --local    sola en esta computadora: SQLite, sin servidor ni internet
"""

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
    def __init__(self, app: QApplication, api: ClienteApi, usuario_local: str | None = None):
        self.app = app
        self.api = api
        # Modo local: la cuenta única de esta computadora (no se mezcla con el servidor).
        self.usuario_local = usuario_local
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

    def ultimo_correo(self) -> str:
        if self.api.es_local:
            return self.usuario_local or ""
        return self.preferencias.value("ultimo_correo", "")

    def iniciar(self) -> bool:
        correo = self.ultimo_correo()
        usuario = self.api.usuario or (self.api.restaurar_sesion(correo) if correo else None)
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
                if login.reconfigurar and self.configurar_servidor():
                    return self.iniciar()
                return False
            usuario = login.usuario
            if self.api.es_local:
                self.usuario_local = usuario.correo
            else:
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
        self.api.cerrar_sesion(self.ultimo_correo())
        if self.ventana:
            # Se oculta (no se cierra) para que Qt no termine la app antes del nuevo login.
            self.ventana.hide()
            self.ventana.deleteLater()
        if not self.iniciar():
            self.app.quit()


def modo_local_solicitado(argumentos: list[str]) -> bool:
    if "--local" in argumentos:
        return True
    if os.environ.get("ASI_MODO_LOCAL", "").lower() in ("1", "true"):
        return True
    return QSettings("TecMM-Zapopan", "ASI-ARCHIVO").value("modo", "") == "local"


def main_local(app: QApplication) -> int:
    """Aplicación sola en esta computadora: abre o crea la base local y pide la cuenta."""
    from asi_cliente import local
    from asi_cliente.views.cuenta_local import DialogoPrimeraEjecucion

    try:
        abierta = local.iniciar()
    except local.ErrorLocal as error:
        QMessageBox.critical(None, "ASI-ARCHIVO", str(error))
        return 1
    app.aboutToQuit.connect(abierta.cerrar)
    if abierta.interrumpidas:
        QMessageBox.information(
            None,
            "ASI-ARCHIVO",
            f"{abierta.interrumpidas} importación(es) de horarios quedaron a medias porque la "
            "aplicación se cerró durante el OCR. Están marcadas con error; vuelve a "
            "importarlas.",
        )
    estado = abierta.api.get("/local/estado")
    usuario = estado["usuario"]
    if not estado["configurada"]:
        primera = DialogoPrimeraEjecucion(abierta.api)
        if primera.exec() != QDialog.Accepted:
            abierta.cerrar()
            return 0
        usuario = primera.usuario
    aplicacion = Aplicacion(app, abierta.api, usuario_local=usuario)
    if not aplicacion.iniciar():
        abierta.cerrar()
        return 0
    return app.exec()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("ASI-ARCHIVO")
    if modo_local_solicitado(sys.argv):
        sys.exit(main_local(app))
    if "--comprobar-tls" in sys.argv:
        from asi_cliente.diagnostico_tls import ejecutar

        sys.exit(ejecutar())
    if "--autoprueba" in sys.argv:
        from asi_cliente.autoprueba import ejecutar

        sys.exit(ejecutar(app))
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
