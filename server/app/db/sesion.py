"""Conexión a la base: PostgreSQL (servidor) o SQLite (aplicación local)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import obtener_configuracion
from app.db.proteccion_pruebas import en_pruebas, validar_url_pruebas


@lru_cache
def obtener_engine() -> Engine:
    url = obtener_configuracion().database_url
    if en_pruebas():
        validar_url_pruebas(url)
    if url.startswith("sqlite"):
        # Aplicación local: un archivo SQLite en la computadora (ver app.db.sqlite_local).
        from app.db.sqlite_local import configurar_sqlite

        return configurar_sqlite(
            create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})
        )
    return create_engine(url, pool_pre_ping=True)


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: abre una sesión por petición y la cierra al terminar.

    En SQLite la transacción reserva la base desde el inicio (ver app.db.sqlite_local).
    """
    from app.db.sqlite_local import motor_de_escritura

    fabrica = sessionmaker(bind=motor_de_escritura(obtener_engine()), expire_on_commit=False)
    with fabrica() as sesion:
        yield sesion
