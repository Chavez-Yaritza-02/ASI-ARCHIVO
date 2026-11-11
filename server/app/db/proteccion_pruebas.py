"""Barrera de pruebas: destino fijo y rol PostgreSQL sin privilegios administrativos."""

import os
import sys

from sqlalchemy import Engine, event
from sqlalchemy.engine import make_url

BASE_PRUEBAS = "asi_archivo_pytest"
USUARIO_PRUEBAS = "asi_archivo_pytest"


def en_pruebas() -> bool:
    return "pytest" in sys.modules or os.environ.get("ASI_ENTORNO") == "pruebas"


def validar_url_pruebas(url) -> None:
    url = make_url(url)
    if (
        url.drivername != "postgresql+psycopg"
        or url.database != BASE_PRUEBAS
        or url.username != USUARIO_PRUEBAS
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or url.port not in {None, 5432}
        or url.query
    ):
        raise RuntimeError("Pruebas bloqueadas: destino PostgreSQL no autorizado")


def validar_conexion_pruebas(conexion) -> None:
    validar_url_pruebas(conexion.engine.url)
    fila = conexion.exec_driver_sql(
        "SELECT current_database(), current_user, r.rolsuper, r.rolcreatedb, "
        "r.rolcreaterole, r.rolreplication, r.rolbypassrls, "
        "EXISTS (SELECT 1 FROM pg_auth_members WHERE member = r.oid) "
        "FROM pg_roles r WHERE r.rolname = current_user"
    ).one()
    if tuple(fila[:2]) != (BASE_PRUEBAS, USUARIO_PRUEBAS) or any(fila[2:]):
        raise RuntimeError("Pruebas bloqueadas: identidad o privilegios no autorizados")


@event.listens_for(Engine, "do_connect")
def _antes_de_conectar(dialect, registro, argumentos, opciones):
    if en_pruebas():
        # Los parámetros efectivos incluyen también cualquier connect_args.
        permitidos = {"dbname", "user", "password", "host", "port", "connect_timeout", "context"}
        if (
            argumentos
            or set(opciones) - permitidos
            or any(
                os.environ.get(k) for k in ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR", "PGOPTIONS")
            )
        ):
            raise RuntimeError("Pruebas bloqueadas: parámetros de conexión no autorizados")
        from sqlalchemy import URL

        validar_url_pruebas(
            URL.create(
                "postgresql+psycopg",
                username=opciones.get("user"),
                host=opciones.get("host"),
                port=int(opciones["port"]) if opciones.get("port") else None,
                database=opciones.get("dbname"),
            )
        )


@event.listens_for(Engine, "engine_connect")
def _identidad_real(conexion):
    if en_pruebas():
        validar_conexion_pruebas(conexion)
        # engine_connect sucede antes de que el consumidor abra su transacción.
        conexion.rollback()
