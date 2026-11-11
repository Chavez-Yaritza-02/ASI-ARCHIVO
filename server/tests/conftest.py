"""Configuración de pruebas: usan una base de datos aparte (asi_archivo_test)."""

import os
from pathlib import Path

import pytest


# Debe definirse antes de importar la app, porque la configuración se lee al importar.
def _url_de_pruebas() -> str:
    """Toma ASI_TEST_DATABASE_URL del entorno o del archivo .env de la raíz."""
    if url := os.environ.get("ASI_TEST_DATABASE_URL"):
        return url
    env = Path(__file__).parents[2] / ".env"
    for linea in env.read_text().splitlines() if env.exists() else []:
        if linea.startswith("ASI_TEST_DATABASE_URL="):
            return linea.split("=", 1)[1].strip()
    raise RuntimeError("Define ASI_TEST_DATABASE_URL (ver .env.example)")


os.environ["ASI_DATABASE_URL"] = _url_de_pruebas()
os.environ.setdefault("ASI_SECRET_KEY", "clave-solo-para-pruebas-" + "x" * 32)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.cli import crear_usuario  # noqa: E402
from app.db.sesion import obtener_engine  # noqa: E402
from app.main import app  # noqa: E402

CONTRASENA = "contrasena-de-prueba"


@pytest.fixture(scope="session", autouse=True)
def base_de_datos():
    """Recrea el esquema con las migraciones reales: así también se prueban."""
    engine = obtener_engine()
    with engine.begin() as conexion:
        conexion.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        config.attributes["connection"] = conexion
        command.upgrade(config, "head")
    yield engine


@pytest.fixture(autouse=True)
def limpiar_datos(base_de_datos):
    yield
    with base_de_datos.begin() as conexion:
        # Solo en pruebas: se desactiva el bloqueo de la auditoría para limpiar.
        conexion.execute(text("ALTER TABLE auditoria DISABLE TRIGGER trg_auditoria_inmutable"))
        conexion.execute(
            text(
                "TRUNCATE usuario, usuario_rol, auditoria, docente, asignatura, grupo, aula, "
                "periodo, horario, bloque_horario, importacion, importacion_documento, "
                "importacion_pagina, importacion_celda RESTART IDENTITY"
            )
        )
        conexion.execute(text("ALTER TABLE auditoria ENABLE TRIGGER trg_auditoria_inmutable"))


@pytest.fixture
def sesion(base_de_datos):
    with Session(base_de_datos) as s:
        yield s


@pytest.fixture
def cliente():
    return TestClient(app)


@pytest.fixture
def admin(sesion):
    return crear_usuario(sesion, "admin@prueba.mx", "Admin Prueba", "administrador", CONTRASENA)


@pytest.fixture
def consulta(sesion):
    return crear_usuario(sesion, "consulta@prueba.mx", "Consulta Prueba", "consulta", CONTRASENA)


def _encabezados(cliente, correo: str) -> dict[str, str]:
    r = cliente.post("/auth/login", data={"username": correo, "password": CONTRASENA})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def como_admin(cliente, admin):
    """Encabezados de autenticación de un administrador."""
    return _encabezados(cliente, admin.correo)


@pytest.fixture
def como_consulta(cliente, consulta):
    """Encabezados de autenticación de un usuario de solo consulta."""
    return _encabezados(cliente, consulta.correo)
