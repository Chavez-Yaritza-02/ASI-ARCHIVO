"""Diagnóstico y sesiones; todos los usuarios pertenecen a la base exclusiva de pruebas."""

from app.cli import cambiar_estado, restablecer_contrasena
from asi_shared.version import PROTOCOLO, VERSION


def test_identidad_estado_y_permisos(cliente, como_consulta):
    ident = cliente.get("/sistema/identidad").json()
    assert (ident["version"], ident["protocolo"]) == (VERSION, PROTOCOLO)
    assert ident["aceptacion_ficticia"] is False
    assert cliente.get("/sistema/estado").status_code == 401
    r = cliente.get("/sistema/estado", headers=como_consulta)
    assert r.status_code == 200 and r.json()["esquema"] == "compatible"
    assert "database_url" not in r.text and "secret_key" not in r.text


def test_restablecer_clave_revoca_token_previo(cliente, consulta, sesion):
    r = cliente.post(
        "/auth/login", data={"username": consulta.correo, "password": "contrasena-de-prueba"}
    )
    headers = {"Authorization": "Bearer " + r.json()["access_token"]}
    assert cliente.get("/auth/yo", headers=headers).status_code == 200
    restablecer_contrasena(sesion, consulta.correo, "nueva-contrasena-ficticia")
    assert cliente.get("/auth/yo", headers=headers).status_code == 401
    assert (
        cliente.post(
            "/auth/login",
            data={"username": consulta.correo, "password": "nueva-contrasena-ficticia"},
        ).status_code
        == 200
    )


def test_reactivar_no_revalida_sesion_antigua(cliente, consulta, sesion):
    r = cliente.post(
        "/auth/login", data={"username": consulta.correo, "password": "contrasena-de-prueba"}
    )
    headers = {"Authorization": "Bearer " + r.json()["access_token"]}
    cambiar_estado(sesion, consulta.correo, False)
    cambiar_estado(sesion, consulta.correo, True)
    assert cliente.get("/auth/yo", headers=headers).status_code == 401


def test_limite_intentos_es_auditado(cliente, admin, sesion):
    from sqlalchemy import func, select

    from app.models import Auditoria

    for _ in range(10):
        assert (
            cliente.post(
                "/auth/login", data={"username": admin.correo, "password": "equivocada"}
            ).status_code
            == 401
        )
    r = cliente.post(
        "/auth/login", data={"username": admin.correo, "password": "contrasena-de-prueba"}
    )
    assert r.status_code == 429 and r.headers["retry-after"] == "900"
    assert (
        sesion.scalar(
            select(func.count()).select_from(Auditoria).where(Auditoria.accion == "login_limitado")
        )
        == 1
    )
