"""Conexión a PostgreSQL."""

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
    return create_engine(url, pool_pre_ping=True)


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: abre una sesión por petición y la cierra al terminar."""
    fabrica = sessionmaker(bind=obtener_engine(), expire_on_commit=False)
    with fabrica() as sesion:
        yield sesion
