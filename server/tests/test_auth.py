import pytest
from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.api.deps import requiere_permiso
from app.cli import crear_usuario
from app.core.seguridad import crear_token, hashear_contrasena, verificar_contrasena
from app.main import app
from app.models import Auditoria
from asi_shared import Permiso

CONTRASENA = "contrasena-de-prueba"  # igual que en conftest.py


def iniciar_sesion(cliente, correo, contrasena=CONTRASENA):
    return cliente.post("/auth/login", data={"username": correo, "password": contrasena})


def test_salud(cliente):
    assert cliente.get("/salud").json() == {"estado": "ok"}


def test_contrasena_se_guarda_como_hash():
    h = hashear_contrasena("secreta-123456")
    assert "secreta" not in h
    assert verificar_contrasena("secreta-123456", h)
    assert not verificar_contrasena("otra", h)


def test_login_correcto_devuelve_token_y_datos(cliente, admin):
    respuesta = iniciar_sesion(cliente, "ADMIN@prueba.mx ")  # mayúsculas y espacios se ignoran
    assert respuesta.status_code == 200
    token = respuesta.json()["access_token"]

    yo = cliente.get("/auth/yo", headers={"Authorization": f"Bearer {token}"}).json()
    assert yo["correo"] == "admin@prueba.mx"
    assert yo["roles"] == ["administrador"]
    assert set(yo["permisos"]) == {p.value for p in Permiso}


def test_login_incorrecto_mismo_mensaje_y_queda_auditado(cliente, admin, sesion):
    mal_contrasena = iniciar_sesion(cliente, "admin@prueba.mx", "equivocada")
    no_existe = iniciar_sesion(cliente, "nadie@prueba.mx")
    assert mal_contrasena.status_code == no_existe.status_code == 401
    assert mal_contrasena.json() == no_existe.json()

    acciones = sesion.scalars(select(Auditoria.accion)).all()
    assert acciones.count("login_fallido") == 2


def test_usuario_desactivado_no_entra(cliente, admin, sesion):
    token = crear_token(admin.id)
    admin.activo = False
    sesion.merge(admin)
    sesion.commit()
    assert iniciar_sesion(cliente, "admin@prueba.mx").status_code == 401
    assert cliente.get("/auth/yo", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_sin_token_o_token_falso(cliente):
    assert cliente.get("/auth/yo").status_code == 401
    falso = {"Authorization": "Bearer abc.def.ghi"}
    assert cliente.get("/auth/yo", headers=falso).status_code == 401


def test_rol_consulta_solo_tiene_permisos_de_lectura(cliente, consulta):
    token = iniciar_sesion(cliente, "consulta@prueba.mx").json()["access_token"]
    permisos = cliente.get("/auth/yo", headers={"Authorization": f"Bearer {token}"}).json()[
        "permisos"
    ]
    assert permisos and all(p.endswith(".ver") for p in permisos)


def test_requiere_permiso_bloquea_sin_permiso(cliente, admin, consulta):
    @app.get("/_prueba_permiso", dependencies=[Depends(requiere_permiso(Permiso.DOCENTES_EDITAR))])
    def _ruta():
        return {"ok": True}

    try:
        for correo, esperado in [("admin@prueba.mx", 200), ("consulta@prueba.mx", 403)]:
            token = iniciar_sesion(cliente, correo).json()["access_token"]
            r = cliente.get("/_prueba_permiso", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == esperado
    finally:
        app.router.routes.pop()


def test_permisos_en_bd_coinciden_con_los_del_codigo(sesion):
    en_bd = set(sesion.scalars(text("SELECT clave FROM permiso")).all())
    assert en_bd == {p.value for p in Permiso}


def test_auditoria_no_se_puede_modificar(sesion, admin):
    with pytest.raises(DBAPIError, match="no se puede modificar"):
        sesion.execute(text("UPDATE auditoria SET accion = 'alterado'"))
    sesion.rollback()


def test_crear_usuario_valida_datos(sesion, admin):
    with pytest.raises(ValueError, match="al menos"):
        crear_usuario(sesion, "x@prueba.mx", "X", "consulta", "corta")
    with pytest.raises(ValueError, match="Ya existe"):
        crear_usuario(sesion, "admin@prueba.mx", "X", "consulta", CONTRASENA)
    with pytest.raises(ValueError, match="no existe"):
        crear_usuario(sesion, "y@prueba.mx", "Y", "superusuario", CONTRASENA)
