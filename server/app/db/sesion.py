"""Conexión a PostgreSQL."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import obtener_configuracion


@lru_cache
def obtener_engine() -> Engine:
    return create_engine(obtener_configuracion().database_url, pool_pre_ping=True)


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: abre una sesión por petición y la cierra al terminar."""
    fabrica = sessionmaker(bind=obtener_engine(), expire_on_commit=False)
    with fabrica() as sesion:
        yield sesion
