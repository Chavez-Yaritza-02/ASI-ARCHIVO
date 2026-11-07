"""La aplicación muestra siempre a qué servidor está conectada y avisa antes de cerrar con
cambios sin guardar. Datos ficticios."""

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from test_interfaz_navegacion import api, ventana_de  # noqa: F401

from app.core.config import obtener_configuracion
from asi_cliente.servidor import describir_servidor
from asi_cliente.theme.estilos import hoja_de_estilo
from asi_cliente.views import ventana_principal as modulo_ventana

# --- qué servidor es ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("identidad", "tipo", "texto"),
    [
        # Demostración actual (versión anterior: solo envía aceptacion_ficticia).
        (
            {"aceptacion_ficticia": True},
            "demostracion",
            "SERVIDOR DE DEMOSTRACIÓN · pruebas, no es el sistema oficial",
        ),
        (
            {"aceptacion_ficticia": False, "tipo_servidor": "revision"},
            "revision",
            "SERVIDOR DE REVISIÓN · datos ficticios",
        ),
        (
            {"aceptacion_ficticia": False, "entorno": "produccion"},
            "institucional",
            "SERVIDOR INSTITUCIONAL · datos oficiales",
        ),
        ({"entorno": "desarrollo"}, "desarrollo", "SERVIDOR DE DESARROLLO"),
        ({}, "desconocido", "SERVIDOR SIN IDENTIFICAR"),  # no responde o es muy antiguo
        # El tipo declarado manda sobre lo deducido.
        (
            {"aceptacion_ficticia": True, "tipo_servidor": "revision"},
            "revision",
            "SERVIDOR DE REVISIÓN",
        ),
    ],
)
def test_describir_servidor(identidad, tipo, texto):
    s = describir_servidor("https://localhost:8443", identidad)
    assert s.tipo == tipo
    assert s.texto.startswith(texto)
    assert s.texto.endswith("localhost:8443")  # siempre con la dirección


def test_identidad_informa_entorno_y_tipo(api, monkeypatch):  # noqa: F811
    monkeypatch.setattr(obtener_configuracion(), "tipo_servidor", "revision")
    identidad = api.identidad()
    assert identidad["tipo_servidor"] == "revision"
    assert identidad["entorno"] == obtener_configuracion().entorno


@pytest.mark.parametrize(
    ("tipo", "color"),
    [("revision", "#6d28d9"), ("demostracion", "#9a3412"), ("institucional", "#166534")],
)
def test_franja_visible_con_color_por_tipo(qtbot, api, monkeypatch, tipo, color):  # noqa: F811
    monkeypatch.setattr(obtener_configuracion(), "tipo_servidor", tipo)
    QApplication.instance().setStyleSheet(hoja_de_estilo("claro"))
    try:
        v = ventana_de(qtbot, api)
        v.resize(1280, 800)
        v.show()
        qtbot.waitExposed(v)
        franja = v.franja_servidor
        assert franja.isVisible() and franja.y() == 0  # arriba de todo
        esperado = describir_servidor(api.url, {"tipo_servidor": tipo})
        assert franja.text() == esperado.texto
        assert esperado.titulo in v.windowTitle()
        pixel = franja.grab().toImage().pixelColor(4, franja.height() // 2)
        assert pixel.name() == color
        # Sigue visible al cambiar de sección.
        v.abrir_seccion("Importar horarios")
        assert franja.isVisible()
    finally:
        QApplication.instance().setStyleSheet("")


# --- cambios sin guardar ----------------------------------------------------------------------


@pytest.fixture
def respuesta(monkeypatch):
    estado = {"salir": False, "llamadas": []}

    def falsa(_padre, accion, cambios):
        estado["llamadas"].append((accion, cambios))
        return estado["salir"]

    monkeypatch.setattr(modulo_ventana, "confirmar_salida", falsa)
    return estado


def _con_cambios(qtbot, api):  # noqa: F811
    v = ventana_de(qtbot, api)
    v.show()
    asistente = v.abrir_seccion("Importar horarios")
    asistente.revision.cambios_pendientes = True  # p. ej. una celda corregida sin guardar
    return v, asistente


def test_sin_cambios_cierra_sin_preguntar(qtbot, api, respuesta):  # noqa: F811
    v = ventana_de(qtbot, api)
    v.show()
    assert v.cambios_sin_guardar() == []
    assert v.close()
    assert respuesta["llamadas"] == []


def test_avisa_antes_de_cerrar_la_ventana(qtbot, api, respuesta):  # noqa: F811
    v, asistente = _con_cambios(qtbot, api)
    assert v.cambios_sin_guardar() == ["Importar horarios: revisión de una página"]

    respuesta["salir"] = False  # «Volver y guardar»
    assert not v.close()
    assert v.isVisible()
    accion, cambios = respuesta["llamadas"][0]
    assert accion == "cerrar la ventana"
    assert cambios == ["Importar horarios: revisión de una página"]
    assert asistente.revision.cambios_pendientes  # nada se descartó

    respuesta["salir"] = True  # «Salir sin guardar»
    assert v.close()


def test_avisa_antes_de_cerrar_sesion(qtbot, api, respuesta):  # noqa: F811
    v, _ = _con_cambios(qtbot, api)
    salidas = []
    v.cerrar_sesion.connect(lambda: salidas.append(True))
    respuesta["salir"] = False
    v.boton_salir.click()
    assert salidas == [] and respuesta["llamadas"][0][0] == "cerrar sesión"
    respuesta["salir"] = True
    v.boton_salir.click()
    assert salidas == [True]


def test_cerrar_el_aviso_sin_elegir_no_pierde_cambios(qtbot, api, monkeypatch):  # noqa: F811
    """Si se cierra el cuadro (Esc) la ventana sigue abierta: lo seguro es no salir."""
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: 0)
    v, _ = _con_cambios(qtbot, api)
    assert not v.close()
    assert v.isVisible()
