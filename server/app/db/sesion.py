"""Conexión a la base de datos: PostgreSQL (servidor central) o SQLite (modo local)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import obtener_configuracion
from app.db.proteccion_pruebas import en_pruebas, validar_sqlite_pruebas, validar_url_pruebas


def _preparar_sqlite(conexion, _registro) -> None:
    """SQLite no revisa llaves foráneas si no se le pide, y espera a que se libere
    el archivo en vez de fallar cuando dos pantallas guardan al mismo tiempo."""
    cursor = conexion.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA busy_timeout = 15000")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = FULL")
    cursor.close()


@lru_cache
def obtener_engine() -> Engine:
    url = obtener_configuracion().database_url
    if url.startswith("sqlite"):
        if en_pruebas():
            validar_sqlite_pruebas(make_url(url).database)
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})
        event.listen(engine, "connect", _preparar_sqlite)
        return engine
    if en_pruebas():
        validar_url_pruebas(url)
    return create_engine(url, pool_pre_ping=True)


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: abre una sesión por petición y la cierra al terminar."""
    fabrica = sessionmaker(bind=obtener_engine(), expire_on_commit=False)
    with fabrica() as sesion:
        yield sesion
