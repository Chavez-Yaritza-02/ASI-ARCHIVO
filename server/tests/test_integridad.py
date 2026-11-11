"""Barreras de pruebas y vigencias: solo identidades y datos ficticios."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text

from app.cli import crear_usuario
from app.db.proteccion_pruebas import validar_conexion_pruebas, validar_url_pruebas
from app.models import Auditoria
from server.tests.test_horarios import nuevo_borrador

pytest_plugins = ["server.tests.test_horarios"]


@pytest.mark.parametrize("base", ["asi_archivo", "asi_archivo_test", "asi_archivo_ocr", "postgres"])
def test_rechaza_bases_no_autorizadas_antes_de_conectar(base, monkeypatch):
    conectar = Mock(side_effect=AssertionError("No debe llegar al controlador"))
    import psycopg

    monkeypatch.setattr(psycopg, "connect", conectar)
    engine = create_engine(f"postgresql+psycopg://asi_archivo_pytest@localhost/{base}")
    with pytest.raises(RuntimeError, match="no autorizado"):
        engine.connect()
    conectar.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://asi_dev@localhost/asi_archivo_pytest",
        "postgresql+psycopg://asi_archivo_pytest@otro-servidor/asi_archivo_pytest",
        "postgresql+psycopg://asi_archivo_pytest@localhost/asi_archivo_pytest?options=x",
        "postgresql+psycopg://asi_archivo_pytest@localhost:5433/asi_archivo_pytest",
        "sqlite:///asi_archivo_pytest",
    ],
)
def test_rechaza_roles_hosts_y_opciones(url):
    with pytest.raises(RuntimeError):
        validar_url_pruebas(url)


def test_rechaza_identidad_o_privilegios_servidor():
    conexion = Mock()
    conexion.engine.url = "postgresql+psycopg://asi_archivo_pytest@localhost/asi_archivo_pytest"
    for fila in [
        ("asi_archivo", "asi_archivo_pytest", False, False, False, False, False, False),
        ("asi_archivo_pytest", "asi_dev", False, False, False, False, False, False),
        ("asi_archivo_pytest", "asi_archivo_pytest", True, False, False, False, False, False),
        ("asi_archivo_pytest", "asi_archivo_pytest", False, False, False, False, False, True),
    ]:
        conexion.exec_driver_sql.return_value.one.return_value = fila
        with pytest.raises(RuntimeError):
            validar_conexion_pruebas(conexion)


def test_cli_y_migraciones_rechazan_conexion_inyectada():
    conexion = Mock()
    conexion.engine.url = "postgresql+psycopg://asi_dev@localhost/asi_archivo"
    sesion = Mock()
    sesion.connection.return_value = conexion
    with pytest.raises(RuntimeError):
        crear_usuario(sesion, "ficticio@prueba.mx", "Ficticio", "consulta", "ficticia-de-prueba")
    sesion.scalar.assert_not_called()
    cfg = Config("server/alembic.ini")
    cfg.attributes["connection"] = conexion
    with pytest.raises(RuntimeError):
        command.upgrade(cfg, "head")
    conexion.execute.assert_not_called()


def test_pytest_rechaza_variable_incorrecta_en_recoleccion():
    entorno = {
        **os.environ,
        "ASI_TEST_DATABASE_URL": "postgresql+psycopg://asi_dev@localhost/asi_archivo_ocr",
    }
    resultado = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "server/tests/test_auth.py"],
        env=entorno,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert resultado.returncode != 0
    assert "destino PostgreSQL no autorizado" in resultado.stderr


def test_conexion_real_tiene_rol_exclusivo(base_de_datos):
    with base_de_datos.connect() as c:
        validar_conexion_pruebas(c)


def test_sin_fecha_no_inventa_vigencia(cliente, como_admin, base, bloques_validos):
    h = nuevo_borrador(cliente, como_admin, base)
    cliente.put(f"/horarios/{h['id']}/bloques", json=bloques_validos, headers=como_admin)
    respuesta = cliente.post(f"/horarios/{h['id']}/confirmar", json={}, headers=como_admin)
    assert respuesta.status_code == 200
    assert respuesta.json()["vigente_desde"] is None
    assert respuesta.json()["vigente_hasta"] is None
    assert not respuesta.json()["vigencia_confirmada"]
    b = cliente.get("/bitacora", params={"fecha": "2026-08-03"}, headers=como_admin).json()
    assert b["filas"] == []


def test_confirmar_fechas_con_permiso_validacion_y_auditoria(
    cliente, como_admin, como_consulta, base, bloques_validos, sesion
):
    h = nuevo_borrador(cliente, como_admin, base)
    cliente.put(f"/horarios/{h['id']}/bloques", json=bloques_validos, headers=como_admin)
    cliente.post(f"/horarios/{h['id']}/confirmar", json={}, headers=como_admin)
    ruta = f"/horarios/{h['id']}/vigencia"
    datos = {"desde": "2026-08-03", "motivo": "Acta ficticia de confirmación"}
    assert cliente.post(ruta, json=datos, headers=como_consulta).status_code == 403
    assert (
        cliente.post(ruta, json={**datos, "hasta": "2026-08-02"}, headers=como_admin).status_code
        == 422
    )
    assert (
        cliente.post(ruta, json={**datos, "desde": "2027-01-01"}, headers=como_admin).status_code
        == 422
    )
    r = cliente.post(ruta, json=datos, headers=como_admin)
    assert r.status_code == 200 and r.json()["vigencia_confirmada"]
    assert (
        len(
            cliente.get("/bitacora", params={"fecha": "2026-08-03"}, headers=como_admin).json()[
                "filas"
            ]
        )
        == 1
    )
    assert (
        cliente.get("/bitacora", params={"fecha": "2026-08-01"}, headers=como_admin).json()["filas"]
        == []
    )
    auditoria = sesion.scalar(select(Auditoria).where(Auditoria.accion == "confirmar_vigencia"))
    assert auditoria.antes["vigente_desde"] is None
    assert auditoria.despues["motivo"] == datos["motivo"]
    # Reemplazo confirmado; no se permite reextender la versión anterior sobre él.
    v2 = nuevo_borrador(cliente, como_admin, base, basado_en_id=h["id"])
    assert (
        cliente.post(
            f"/horarios/{v2['id']}/confirmar",
            headers=como_admin,
            json={"vigente_desde": "2026-09-01", "aceptar_advertencias": True},
        ).status_code
        == 200
    )
    assert (
        cliente.post(ruta, json={**datos, "hasta": "2026-09-02"}, headers=como_admin).status_code
        == 409
    )


def test_migracion_desde_etapa4_conserva_versiones_y_evidencia(base_de_datos):
    # Esquema temporal dentro de la BD exclusiva; toda la simulación hace rollback.
    with base_de_datos.connect() as c:
        transaccion = c.begin()
        try:
            c.execute(text("CREATE SCHEMA prueba_migracion"))
            c.execute(text("SET LOCAL search_path TO prueba_migracion"))
            cfg = Config("server/alembic.ini")
            cfg.attributes["connection"] = c
            command.upgrade(cfg, "8b4cb2f4fef8")
            c.execute(
                text(
                    "INSERT INTO docente (id,nombre,nombre_normalizado,activo) "
                    "VALUES (1,'FICTICIO','FICTICIO',true)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO periodo (id,nombre,fecha_inicio,fecha_fin,estado) "
                    "VALUES (1,'FICTICIO','2026-08-01','2026-12-31','activo')"
                )
            )
            c.execute(
                text(
                    "INSERT INTO horario (docente_id,periodo_id,version,estado,origen,notas,"
                    "vigente_desde,vigente_hasta) VALUES "
                    "(1,1,1,'historico','manual','','2026-08-01','2026-07-31'),"
                    "(1,1,2,'vigente','manual','','2026-08-01',NULL)"
                )
            )
            command.upgrade(cfg, "head")
            filas = c.execute(
                text(
                    "SELECT vigente_desde,vigente_hasta,vigencia_confirmada "
                    "FROM horario ORDER BY version"
                )
            ).all()
            assert [tuple(f) for f in filas] == [(None, None, False)] * 2
            assert (
                c.execute(
                    text("SELECT count(*) FROM auditoria WHERE accion='vigencia_desconocida'")
                ).scalar()
                == 2
            )
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "e5a001"
        finally:
            transaccion.rollback()


@pytest.mark.parametrize(
    "comando,entrada",
    [
        ([sys.executable, "-m", "alembic", "-c", "server/alembic.ini", "upgrade", "head"], None),
        (
            [
                sys.executable,
                "-m",
                "app.cli",
                "crear-usuario",
                "--correo",
                "ficticio@prueba.mx",
                "--nombre",
                "Ficticio",
                "--rol",
                "consulta",
            ],
            "clave-ficticia-larga\nclave-ficticia-larga\n",
        ),
    ],
)
def test_subprocesos_rechazan_destino_ficticio_no_autorizado(comando, entrada):
    # Destino ficticio sin servidor PostgreSQL: nunca se apunta a una base real.
    entorno = {
        **os.environ,
        "ASI_ENTORNO": "pruebas",
        "ASI_DATABASE_URL": "postgresql+psycopg://ficticio@127.0.0.1:1/base_ficticia_prohibida",
        "PYTHONPATH": str(Path("server").resolve()),
    }
    resultado = subprocess.run(
        comando, input=entrada, env=entorno, capture_output=True, text=True, timeout=30
    )
    assert resultado.returncode != 0
    assert "destino PostgreSQL no autorizado" in resultado.stderr


def test_connect_args_no_puede_cambiar_el_destino(base_de_datos, monkeypatch):
    import psycopg

    conectar = Mock(side_effect=AssertionError("No debe abrir una conexión"))
    monkeypatch.setattr(psycopg, "connect", conectar)
    engine = create_engine(base_de_datos.url, connect_args={"dbname": "base_ficticia_prohibida"})
    with pytest.raises(RuntimeError):
        engine.connect()
    conectar.assert_not_called()


def test_libpq_no_puede_redirigir_conexion(base_de_datos, monkeypatch):
    monkeypatch.setenv("PGOPTIONS", "-c search_path=otro")
    engine = create_engine(base_de_datos.url)
    with pytest.raises(RuntimeError, match="parámetros de conexión no autorizados"):
        engine.connect()
