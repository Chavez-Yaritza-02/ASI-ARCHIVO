"""Pruebas del cliente HTTP con un servidor simulado (no requiere red ni API real)."""

from datetime import date

import httpx
import keyring
import pytest

from asi_cliente.api.cliente import ClienteApi, ErrorApi, UsuarioSesion, validar_url
from asi_cliente.views.ventana_principal import fecha_larga, secciones_visibles

USUARIO = {
    "id": 1,
    "correo": "admin@prueba.mx",
    "nombre": "Admin",
    "roles": ["administrador"],
    "permisos": ["docentes.ver", "asistencia.ver"],
}


def servidor_simulado(peticion: httpx.Request) -> httpx.Response:
    if peticion.url.path == "/auth/login":
        if b"password=correcta" in peticion.content:
            return httpx.Response(200, json={"access_token": "tok-123", "token_type": "bearer"})
        return httpx.Response(401, json={"detail": "Correo o contraseña incorrectos"})
    if peticion.url.path == "/auth/yo":
        if peticion.headers.get("Authorization") == "Bearer tok-123":
            return httpx.Response(200, json=USUARIO)
        return httpx.Response(401, json={"detail": "Sesión inválida o expirada"})
    return httpx.Response(404)


@pytest.fixture
def llavero(monkeypatch):
    """Reemplaza el llavero del sistema por un diccionario en memoria."""
    datos: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "set_password", lambda s, u, p: datos.__setitem__((s, u), p))
    monkeypatch.setattr(keyring, "get_password", lambda s, u: datos.get((s, u)))
    monkeypatch.setattr(keyring, "delete_password", lambda s, u: datos.pop((s, u), None))
    return datos


@pytest.fixture
def api(llavero):
    return ClienteApi("http://127.0.0.1:8000", transporte=httpx.MockTransport(servidor_simulado))


def test_url_requiere_https_salvo_en_local():
    assert validar_url("https://asi.ejemplo.mx/") == "https://asi.ejemplo.mx"
    assert validar_url("http://localhost:8000") == "http://localhost:8000"
    with pytest.raises(ErrorApi, match="HTTPS"):
        validar_url("http://asi.ejemplo.mx")


def test_login_correcto_carga_usuario(api):
    usuario = api.iniciar_sesion("admin@prueba.mx", "correcta")
    assert usuario.nombre == "Admin"
    assert usuario.puede("docentes.ver")
    assert not usuario.puede("usuarios.gestionar")


def test_login_incorrecto_muestra_mensaje_del_servidor(api):
    with pytest.raises(ErrorApi, match="incorrectos"):
        api.iniciar_sesion("admin@prueba.mx", "mala")


def test_recordar_sesion_guarda_y_restaura_token(api, llavero):
    api.iniciar_sesion("admin@prueba.mx", "correcta", recordar=True)
    assert llavero[("ASI-ARCHIVO", "admin@prueba.mx")] == "tok-123"

    nuevo = ClienteApi("http://127.0.0.1:8000", transporte=httpx.MockTransport(servidor_simulado))
    assert nuevo.restaurar_sesion("admin@prueba.mx").correo == "admin@prueba.mx"

    nuevo.cerrar_sesion("admin@prueba.mx")
    assert llavero == {}


def test_token_vencido_se_descarta(api, llavero):
    llavero[("ASI-ARCHIVO", "admin@prueba.mx")] = "token-viejo"
    assert api.restaurar_sesion("admin@prueba.mx") is None
    assert llavero == {}


def test_sin_conexion_da_mensaje_claro(llavero):
    def sin_red(_):
        raise httpx.ConnectError("sin red")

    api = ClienteApi("http://127.0.0.1:8000", transporte=httpx.MockTransport(sin_red))
    assert not api.servidor_disponible()
    with pytest.raises(ErrorApi, match="No se pudo conectar"):
        api.iniciar_sesion("a@b.mx", "x")


def test_menu_solo_muestra_secciones_permitidas():
    usuario = UsuarioSesion(**USUARIO)
    titulos = [s[0] for s in secciones_visibles(usuario)]
    assert "Bitácora del día" in titulos and "Docentes" in titulos
    assert "Periodos" not in titulos and "Documentos" not in titulos
    usuario.permisos = ["horarios.ver"]
    titulos = [s[0] for s in secciones_visibles(usuario)]
    assert "Buscador" in titulos
    assert "Ubicación programada" not in titulos and "Horarios por grupo" not in titulos


def test_fecha_en_espanol():
    assert fecha_larga(date(2026, 11, 4)) == "Miércoles 4 de noviembre de 2026"
