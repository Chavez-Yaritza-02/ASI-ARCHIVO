"""Modo local de punta a punta: base SQLite nueva, primer usuario, API interna y respaldos.

No usa PostgreSQL ni el llavero: todo vive en una carpeta temporal.
"""

import os
import zipfile

import pytest

from asi_cliente import local
from asi_cliente.api.cliente import ClienteApi

CORREO = "jefatura@ejemplo.mx"
CONTRASENA = "contrasena-ficticia-123"


def _limpiar_caches():
    from app.core.config import obtener_configuracion
    from app.db.sesion import obtener_engine

    if obtener_engine.cache_info().currsize:
        obtener_engine().dispose()
    obtener_engine.cache_clear()
    obtener_configuracion.cache_clear()


@pytest.fixture
def datos(tmp_path, monkeypatch):
    antes = dict(os.environ)
    carpeta = tmp_path / "ASI-ARCHIVO-DATOS"
    monkeypatch.setenv("ASI_DATOS", str(carpeta))
    _limpiar_caches()
    yield carpeta
    _limpiar_caches()
    os.environ.clear()
    os.environ.update(antes)


@pytest.fixture
def servidor(datos):
    servidor, hay_usuarios = local.preparar(datos)
    assert not hay_usuarios
    yield servidor
    servidor.detener()


def test_primer_uso_crea_base_y_permite_trabajar(datos, servidor):
    assert (datos / local.NOMBRE_BASE).is_file()
    local.crear_administrador(CORREO, "Persona Ficticia", CONTRASENA)

    api = ClienteApi(http=servidor.cliente_http())
    usuario = api.iniciar_sesion(CORREO, CONTRASENA)
    assert "administrador" in usuario.roles

    identidad = api.get("/sistema/identidad")
    assert identidad["entorno"] == "local"
    estado = api.get("/sistema/estado")
    assert estado["estado"] == "ok" and estado["esquema"] == "compatible"

    periodo = api.post(
        "/periodos",
        {
            "nombre": "AGOSTO - DICIEMBRE 2099",
            "fecha_inicio": "2099-08-01",
            "fecha_fin": "2099-12-15",
        },
    )
    api.post(f"/periodos/{periodo['id']}/activar")
    assert api.get("/periodos/activo")["id"] == periodo["id"]
    docente = api.post("/docentes", {"nombre": "Docente Ficticio Uno"})
    assert any(d["id"] == docente["id"] for d in api.get("/docentes"))
    api.cerrar()


def test_contrasena_incorrecta_se_rechaza(datos, servidor):
    local.crear_administrador(CORREO, "Persona Ficticia", CONTRASENA)
    api = ClienteApi(http=servidor.cliente_http())
    with pytest.raises(Exception):  # noqa: B017 - ErrorApi u otro rechazo de la API
        api.iniciar_sesion(CORREO, "otra-contrasena-ficticia")
    api.cerrar()


def test_reabrir_conserva_la_informacion(datos):
    servidor, _ = local.preparar(datos)
    local.crear_administrador(CORREO, "Persona Ficticia", CONTRASENA)
    servidor.detener()
    _limpiar_caches()
    servidor, hay_usuarios = local.preparar(datos)
    try:
        assert hay_usuarios
    finally:
        servidor.detener()


def test_respaldo_y_restauracion(datos, servidor, tmp_path):
    local.crear_administrador(CORREO, "Persona Ficticia", CONTRASENA)
    respaldo = local.hacer_respaldo(datos, tmp_path / "usb")
    assert respaldo.name.startswith(local.PREFIJO_RESPALDO)
    with zipfile.ZipFile(respaldo) as zipf:
        assert local.NOMBRE_BASE in zipf.namelist()

    local.programar_restauracion(datos, respaldo)
    servidor.detener()
    _limpiar_caches()
    anterior = local.aplicar_restauracion_pendiente(datos)
    assert anterior is not None and (anterior / local.NOMBRE_BASE).is_file()
    assert (datos / local.NOMBRE_BASE).is_file()
    assert not (datos / local.RESTAURACION_PENDIENTE).exists()


def test_rechaza_respaldo_con_rutas_peligrosas(datos, tmp_path):
    malo = tmp_path / "malo.zip"
    with zipfile.ZipFile(malo, "w") as zipf:
        zipf.writestr("../fuera.txt", "x")
        zipf.writestr(local.NOMBRE_BASE, "x")
    datos.mkdir(parents=True)
    with pytest.raises(local.ErrorLocal):
        local.programar_restauracion(datos, malo)
