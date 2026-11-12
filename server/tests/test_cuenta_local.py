"""Cuenta única de la aplicación local: primera ejecución, cambio y recuperación de la
contraseña sin internet. Datos ficticios. La tabla del código de recuperación solo existe en
la base local, por eso estas pruebas corren con SQLite (paso SQLite de la suite)."""

import pytest
from sqlalchemy import func, select, text

from app.core.config import obtener_configuracion
from app.local import cuenta as servicio
from app.models import Auditoria
from server.tests.conftest import CONTRASENA

USUARIO, NOMBRE, CLAVE = "jefatura", "Jefatura Ficticia", "clave-ficticia-01"


@pytest.fixture
def modo_local(monkeypatch):
    monkeypatch.setattr(obtener_configuracion(), "modo_local", True)


def crear(cliente, **cambios):
    datos = {"usuario": USUARIO, "nombre": NOMBRE, "contrasena": CLAVE, **cambios}
    return cliente.post("/local/cuenta", json=datos)


def entrar(cliente, clave=CLAVE, usuario=USUARIO):
    return cliente.post("/auth/login", data={"username": usuario, "password": clave})


def encabezados(token):
    return {"Authorization": f"Bearer {token}"}


def auditoria(sesion, accion=None):
    consulta = select(func.count()).select_from(Auditoria)
    if accion:
        consulta = consulta.where(Auditoria.accion == accion)
    return sesion.scalar(consulta)


def test_rutas_locales_no_existen_en_el_servidor(cliente):
    for metodo, ruta in [("get", "/local/estado"), ("post", "/local/cuenta")]:
        assert getattr(cliente, metodo)(ruta).status_code == 404


@pytest.mark.solo_sqlite
def test_primera_ejecucion_crea_una_sola_cuenta_con_todos_los_permisos(cliente, modo_local, sesion):
    assert cliente.get("/local/estado").json() == {"configurada": False, "usuario": None}
    r = crear(cliente, usuario="  Jefatura ")
    assert r.status_code == 201, r.text
    codigo = r.json()["codigo_recuperacion"]
    assert r.json()["usuario"] == USUARIO
    assert len(servicio.normalizar_codigo(codigo)) == 25
    assert cliente.get("/local/estado").json() == {"configurada": True, "usuario": USUARIO}
    yo = cliente.get("/auth/yo", headers=encabezados(entrar(cliente).json()["access_token"]))
    assert yo.json()["roles"] == ["administrador"]
    todos = set(sesion.scalars(text("SELECT clave FROM permiso")))
    assert set(yo.json()["permisos"]) == todos and "asistencia.corregir" in todos
    # No hay segunda cuenta, ni con otro nombre.
    assert crear(cliente, usuario="otra.cuenta").status_code == 409
    assert sesion.scalar(text("SELECT count(*) FROM usuario")) == 1
    # Solo la huella del código queda guardada.
    huella = sesion.scalar(text("SELECT huella FROM cuenta_recuperacion"))
    assert huella.startswith("$argon2") and servicio.normalizar_codigo(codigo) not in huella
    assert auditoria(sesion, "crear") == 1


@pytest.mark.solo_sqlite
@pytest.mark.parametrize(
    "cambio",
    [{"contrasena": "corta"}, {"usuario": "con espacio"}, {"usuario": "ñu"}, {"nombre": " "}],
)
def test_datos_invalidos_no_crean_cuenta(cliente, modo_local, sesion, cambio):
    assert crear(cliente, **cambio).status_code == 422
    assert cliente.get("/local/estado").json()["configurada"] is False


@pytest.mark.solo_sqlite
def test_cambiar_contrasena_cierra_las_otras_sesiones(cliente, modo_local, sesion):
    crear(cliente)
    vieja = entrar(cliente).json()["access_token"]
    datos = {"actual": "no-es-la-clave", "nueva": "otra-clave-ficticia"}
    r = cliente.post("/auth/contrasena", json=datos, headers=encabezados(vieja))
    assert r.status_code == 401 and auditoria(sesion, "contrasena_fallida") == 1
    corta = {"actual": CLAVE, "nueva": "corta"}
    assert (
        cliente.post("/auth/contrasena", json=corta, headers=encabezados(vieja)).status_code == 422
    )
    igual = {"actual": CLAVE, "nueva": CLAVE}
    assert (
        cliente.post("/auth/contrasena", json=igual, headers=encabezados(vieja)).status_code == 422
    )
    r = cliente.post(
        "/auth/contrasena",
        json={"actual": CLAVE, "nueva": "otra-clave-ficticia"},
        headers=encabezados(vieja),
    )
    assert r.status_code == 200, r.text
    assert cliente.get("/auth/yo", headers=encabezados(vieja)).status_code == 401
    assert cliente.get("/auth/yo", headers=encabezados(r.json()["access_token"])).status_code == 200
    assert entrar(cliente).status_code == 401
    assert entrar(cliente, "otra-clave-ficticia").status_code == 200
    assert auditoria(sesion, "cambiar_contrasena") == 1


@pytest.mark.solo_sqlite
def test_recuperar_con_el_codigo_renueva_el_codigo(cliente, modo_local, sesion):
    codigo = crear(cliente).json()["codigo_recuperacion"]
    abierta = entrar(cliente).json()["access_token"]
    datos = {
        "usuario": USUARIO,
        "codigo": "AAAAA-AAAAA-AAAAA-AAAAA-AAAAA",
        "nueva": "nueva-clave-01",
    }
    r = cliente.post("/local/recuperar", json=datos)
    assert r.status_code == 401 and auditoria(sesion, "recuperacion_fallida") == 1
    # Usuario inexistente: mismo mensaje.
    r = cliente.post("/local/recuperar", json={**datos, "usuario": "nadie", "codigo": codigo})
    assert r.status_code == 401 and r.json()["detail"].startswith("Usuario o código")
    # El código se acepta escrito a mano: minúsculas, espacios y sin guiones.
    escrito = codigo.lower().replace("-", " ")
    r = cliente.post("/local/recuperar", json={**datos, "codigo": escrito})
    assert r.status_code == 200, r.text
    nuevo = r.json()["codigo_recuperacion"]
    assert nuevo != codigo
    assert cliente.get("/auth/yo", headers=encabezados(abierta)).status_code == 401
    assert entrar(cliente, "nueva-clave-01").status_code == 200
    # El código anterior ya no sirve; el nuevo sí.
    otra = {**datos, "nueva": "tercera-clave-01"}
    assert cliente.post("/local/recuperar", json={**otra, "codigo": codigo}).status_code == 401
    assert cliente.post("/local/recuperar", json={**otra, "codigo": nuevo}).status_code == 200
    assert auditoria(sesion, "recuperar_contrasena") == 2


@pytest.mark.solo_sqlite
def test_intentos_de_recuperacion_limitados(cliente, modo_local, sesion):
    codigo = crear(cliente).json()["codigo_recuperacion"]
    datos = {
        "usuario": USUARIO,
        "codigo": "ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ",
        "nueva": "nueva-clave-01",
    }
    for _ in range(servicio.LIMITE_INTENTOS):
        assert cliente.post("/local/recuperar", json=datos).status_code == 401
    # Bloqueado aun con el código correcto.
    r = cliente.post("/local/recuperar", json={**datos, "codigo": codigo})
    assert r.status_code == 429
    assert auditoria(sesion, "recuperacion_limitada") == 1
    assert entrar(cliente).status_code == 200  # la contraseña no cambió


@pytest.mark.solo_sqlite
def test_renovar_codigo_pide_la_contrasena(cliente, modo_local, sesion):
    codigo = crear(cliente).json()["codigo_recuperacion"]
    h = encabezados(entrar(cliente).json()["access_token"])
    assert (
        cliente.post("/local/codigo", json={"contrasena": "incorrecta"}, headers=h).status_code
        == 401
    )
    r = cliente.post("/local/codigo", json={"contrasena": CLAVE}, headers=h)
    assert r.status_code == 200
    datos = {"usuario": USUARIO, "nueva": "nueva-clave-01"}
    assert cliente.post("/local/recuperar", json={**datos, "codigo": codigo}).status_code == 401
    nuevo = r.json()["codigo_recuperacion"]
    assert cliente.post("/local/recuperar", json={**datos, "codigo": nuevo}).status_code == 200
    assert auditoria(sesion, "renovar_codigo_recuperacion") == 1


@pytest.mark.solo_sqlite
def test_la_auditoria_de_la_cuenta_solo_crece(cliente, modo_local, sesion):
    crear(cliente)
    entrar(cliente, "incorrecta-01")
    antes = auditoria(sesion)
    assert antes >= 2
    for sql in ("DELETE FROM auditoria", "UPDATE auditoria SET accion = 'otra'"):
        with (
            pytest.raises(Exception, match="auditoría no se puede modificar"),
            sesion.get_bind().begin() as c,
        ):
            c.execute(text(sql))
    assert auditoria(sesion) == antes


def test_codigo_generado_es_legible_y_aleatorio():
    codigos = {servicio.generar_codigo() for _ in range(50)}
    assert len(codigos) == 50
    for c in codigos:
        grupos = c.split("-")
        assert len(grupos) == 5 and all(len(g) == 5 for g in grupos)
        assert not set(c) & set("ILOU")
    assert servicio.normalizar_codigo("abcde-0OIL1") == "ABCDE00111"


def test_cambiar_contrasena_tambien_en_el_servidor(cliente, admin, sesion):
    """El cambio de contraseña no depende del modo local (corre en ambas bases)."""
    token = entrar(cliente, CONTRASENA, admin.correo).json()["access_token"]
    datos = {"actual": CONTRASENA, "nueva": "nueva-clave-servidor"}
    r = cliente.post("/auth/contrasena", json=datos, headers=encabezados(token))
    assert r.status_code == 200, r.text
    assert cliente.get("/auth/yo", headers=encabezados(token)).status_code == 401
    assert entrar(cliente, "nueva-clave-servidor", admin.correo).status_code == 200
    assert auditoria(sesion, "cambiar_contrasena") == 1
