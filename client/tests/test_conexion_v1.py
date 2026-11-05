"""Conexión inicial y protección de sesiones sin servidor ni llavero reales."""

import httpx
import pytest
from PySide6.QtWidgets import QDialogButtonBox

from asi_cliente.api.cliente import ClienteApi, ErrorApi, validar_url
from asi_cliente.views.configuracion_inicial import ConfiguracionInicial
from asi_shared.version import PROTOCOLO, VERSION


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://servidor.invalid",
        "https://usuario:clave@servidor.invalid",
        "https://servidor.invalid/ruta",
        "https://servidor.invalid?token=ficticio",
        "https://servidor.invalid#ficticio",
        "https://",
        "https://servidor.invalid:invalido",
        "https://servidor.invalid\\ruta",
    ],
)
def test_asistente_rechaza_direcciones_inseguras(url):
    with pytest.raises(ErrorApi):
        validar_url(url, solo_https=True)


def test_redireccion_no_recibe_credenciales():
    llamadas = []

    def responder(p):
        llamadas.append(str(p.url))
        return httpx.Response(307, headers={"Location": "https://ajeno.invalid/auth/login"})

    api = ClienteApi("https://oficial.invalid", transporte=httpx.MockTransport(responder))
    with pytest.raises(ErrorApi, match="redirigió"):
        api.iniciar_sesion("ficticio@example.invalid", "ficticia")
    assert llamadas == ["https://oficial.invalid/auth/login"]
    api.cerrar()


def test_sesiones_de_servidores_distintos_no_comparten_llavero(monkeypatch):
    import keyring

    llavero = {}
    monkeypatch.setattr(keyring, "set_password", lambda s, u, p: llavero.__setitem__((s, u), p))
    monkeypatch.setattr(keyring, "get_password", lambda s, u: llavero.get((s, u)))
    a = ClienteApi(
        "https://uno.invalid", transporte=httpx.MockTransport(lambda p: httpx.Response(404))
    )
    b = ClienteApi(
        "https://dos.invalid", transporte=httpx.MockTransport(lambda p: httpx.Response(404))
    )
    a._token = "token-ficticio"
    a._guardar_token("ficticio@example.invalid")
    assert b.restaurar_sesion("ficticio@example.invalid") is None
    a.cerrar()
    b.cerrar()


def test_asistente_real_verifica_permisos_y_borra_contrasena(qtbot):
    def responder(p):
        if p.url.path == "/sistema/identidad":
            datos = {"producto": "ASI-ARCHIVO", "version": VERSION, "protocolo": PROTOCOLO}
        elif p.url.path == "/auth/login":
            datos = {"access_token": "ficticio"}
        elif p.url.path == "/auth/yo":
            datos = {
                "id": 1,
                "nombre": "Ficticio",
                "correo": "ficticio@example.invalid",
                "roles": ["consulta"],
                "permisos": ["asistencia.ver"],
            }
        else:
            datos = {"estado": "ok", "esquema": "compatible", "antivirus_configurado": False}
        return httpx.Response(200, json=datos)

    d = ConfiguracionInicial(
        "https://ficticio.invalid",
        fabrica_api=lambda url: ClienteApi(url, transporte=httpx.MockTransport(responder)),
    )
    qtbot.addWidget(d)
    d.comprobar()
    d.correo.setText("ficticio@example.invalid")
    d.contrasena.setText("dato-ficticio")
    d.autenticar()
    assert d.botones.button(QDialogButtonBox.Ok).isEnabled()
    assert d.contrasena.text() == ""
    assert "Asistencia por hora" in d.mensaje.text()
    d.direccion.setText("https://otro.invalid")
    assert d.api is None and not d.botones.button(QDialogButtonBox.Ok).isEnabled()


def test_asistente_no_acepta_otra_aplicacion(qtbot):
    d = ConfiguracionInicial(
        "https://ficticio.invalid",
        fabrica_api=lambda url: ClienteApi(
            url,
            transporte=httpx.MockTransport(
                lambda p: httpx.Response(200, json={"producto": "OTRO"})
            ),
        ),
    )
    qtbot.addWidget(d)
    d.comprobar()
    assert not d.entrar.isEnabled() and d.api is None
