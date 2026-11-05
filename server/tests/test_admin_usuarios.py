"""Comandos de administración de usuarios (consola del servidor)."""

import pytest
from sqlalchemy import select

from app.cli import cambiar_estado, cambiar_rol, listar_usuarios, restablecer_contrasena
from app.models import Auditoria

CONTRASENA = "contrasena-de-prueba"  # igual que en conftest.py


def entrar(cliente, correo, contrasena=CONTRASENA):
    return cliente.post("/auth/login", data={"username": correo, "password": contrasena})


def test_listar_usuarios(sesion, admin, consulta):
    assert [u.correo for u in listar_usuarios(sesion)] == ["admin@prueba.mx", "consulta@prueba.mx"]


def test_restablecer_contrasena(cliente, sesion, consulta):
    with pytest.raises(ValueError, match="al menos"):
        restablecer_contrasena(sesion, consulta.correo, "corta")
    restablecer_contrasena(sesion, "CONSULTA@prueba.mx ", "otra-contrasena-larga")
    assert entrar(cliente, consulta.correo).status_code == 401
    assert entrar(cliente, consulta.correo, "otra-contrasena-larga").status_code == 200
    with pytest.raises(ValueError, match="No existe"):
        restablecer_contrasena(sesion, "nadie@prueba.mx", "otra-contrasena-larga")


def test_desactivar_corta_el_acceso_incluso_con_sesion_abierta(cliente, sesion, consulta):
    token = entrar(cliente, consulta.correo).json()["access_token"]
    encabezado = {"Authorization": f"Bearer {token}"}
    cambiar_estado(sesion, consulta.correo, activo=False)
    assert cliente.get("/auth/yo", headers=encabezado).status_code == 401
    assert entrar(cliente, consulta.correo).status_code == 401
    cambiar_estado(sesion, consulta.correo, activo=True)
    assert entrar(cliente, consulta.correo).status_code == 200


def test_cambiar_rol_y_auditoria(cliente, sesion, consulta):
    cambiar_rol(sesion, consulta.correo, "administrador")
    token = entrar(cliente, consulta.correo).json()["access_token"]
    yo = cliente.get("/auth/yo", headers={"Authorization": f"Bearer {token}"}).json()
    assert yo["roles"] == ["administrador"]
    with pytest.raises(ValueError, match="no existe"):
        cambiar_rol(sesion, consulta.correo, "superusuario")

    registros = sesion.scalars(
        select(Auditoria).where(Auditoria.entidad == "usuario", Auditoria.accion == "cambiar_rol")
    ).all()
    assert registros[0].antes == {"roles": ["consulta"]}
    assert registros[0].despues == {"roles": ["administrador"], "origen": "consola"}
