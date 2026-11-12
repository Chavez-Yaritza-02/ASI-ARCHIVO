"""Configuración de pruebas: usan una base de datos aparte (asi_archivo_pytest).

Por omisión, PostgreSQL. Con ASI_TEST_MOTOR=sqlite, un archivo SQLite temporal nuevo
(aplicación local): misma suite, mismas reglas. Las pruebas propias de PostgreSQL
(migraciones de Alembic, roles y privilegios de la base) llevan la marca `solo_postgresql`.
"""

import os
import tempfile
from pathlib import Path

import pytest

# Debe definirse antes de importar la app, porque la configuración se lee al importar.
MOTOR = os.environ.get("ASI_TEST_MOTOR", "postgresql")


def _url_de_pruebas() -> str:
    """Toma ASI_TEST_DATABASE_URL del entorno o del archivo .env de la raíz."""
    if MOTOR == "sqlite":
        archivo = Path(tempfile.gettempdir()) / "asi_archivo_pytest.sqlite3"
        for sobrante in (archivo, Path(f"{archivo}-wal"), Path(f"{archivo}-shm")):
            sobrante.unlink(missing_ok=True)  # siempre una base nueva
        return f"sqlite:///{archivo}"
    if url := os.environ.get("ASI_TEST_DATABASE_URL"):
        return url
    env = Path(__file__).parents[2] / ".env"
    for linea in env.read_text().splitlines() if env.exists() else []:
        if linea.startswith("ASI_TEST_DATABASE_URL="):
            return linea.split("=", 1)[1].strip()
    raise RuntimeError("Define ASI_TEST_DATABASE_URL (ver .env.example)")


os.environ["ASI_DATABASE_URL"] = _url_de_pruebas()
os.environ["ASI_ENTORNO"] = "pruebas"
from app.db.proteccion_pruebas import validar_conexion_pruebas, validar_url_pruebas  # noqa: E402

validar_url_pruebas(os.environ["ASI_DATABASE_URL"])
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


# Tablas que se vacían entre pruebas (las de catálogos iniciales se conservan).
TABLAS_DE_PRUEBA = (
    "usuario, usuario_rol, auditoria, docente, asignatura, grupo, aula, "
    "periodo, horario, bloque_horario, importacion, importacion_documento, "
    "importacion_pagina, importacion_celda, calendario_evento, asistencia, "
    "incidencia, asistencia_hora, documento_asistencia, documento_version, documento"
)


def pytest_collection_modifyitems(config, items):
    if MOTOR == "sqlite":
        marca, motivo = "solo_postgresql", "Propia de PostgreSQL (Alembic, roles o privilegios)"
    else:
        marca, motivo = "solo_sqlite", "Propia de la aplicación local (SQLite)"
    saltar = pytest.mark.skip(reason=motivo)
    for item in items:
        if marca in item.keywords:
            item.add_marker(saltar)


def pytest_configure(config):
    config.addinivalue_line("markers", "solo_postgresql: prueba propia de PostgreSQL")
    config.addinivalue_line("markers", "solo_sqlite: prueba propia de la aplicación local")


@pytest.fixture(scope="session", autouse=True)
def base_de_datos():
    """Recrea el esquema con las migraciones reales: así también se prueban."""
    engine = obtener_engine()
    if MOTOR == "sqlite":
        from app.db.sqlite_local import crear_esquema

        with engine.connect() as conexion:
            validar_conexion_pruebas(conexion)
        crear_esquema(engine)
        yield engine
        return
    with engine.begin() as conexion:
        validar_conexion_pruebas(conexion)
        conexion.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        config.attributes["connection"] = conexion
        command.upgrade(config, "head")
    yield engine


@pytest.fixture(autouse=True)
def limpiar_datos(base_de_datos):
    yield
    if MOTOR == "sqlite":
        from app.db.sqlite_local import crear_triggers, quitar_triggers
        from app.models import Base

        vaciar = {t.strip() for t in TABLAS_DE_PRUEBA.split(",")}
        with base_de_datos.begin() as conexion:
            validar_conexion_pruebas(conexion)
            # Solo en pruebas: se quitan los bloqueos de la auditoría para limpiar.
            quitar_triggers(conexion)
            for tabla in reversed(Base.metadata.sorted_tables):
                if tabla.name in vaciar:
                    conexion.execute(tabla.delete())
            conexion.execute(text("DELETE FROM cuenta_recuperacion"))
            crear_triggers(conexion)
            conexion.execute(text("UPDATE configuracion_asistencia SET tolerancia_minutos = 10"))
        return
    with base_de_datos.begin() as conexion:
        validar_conexion_pruebas(conexion)
        # Solo en pruebas: se desactiva el bloqueo de la auditoría para limpiar.
        conexion.execute(text("ALTER TABLE auditoria DISABLE TRIGGER trg_auditoria_inmutable"))
        conexion.execute(text(f"TRUNCATE {TABLAS_DE_PRUEBA} RESTART IDENTITY CASCADE"))
        conexion.execute(text("ALTER TABLE auditoria ENABLE TRIGGER trg_auditoria_inmutable"))
        conexion.execute(text("UPDATE configuracion_asistencia SET tolerancia_minutos = 10"))


@pytest.fixture
def sesion(base_de_datos):
    motor = base_de_datos
    if MOTOR == "sqlite":
        # Sesión auxiliar de las pruebas: no deja lecturas abiertas que bloqueen a la API.
        motor = base_de_datos.execution_options(sqlite_por_instruccion=True)
    with Session(motor) as s:
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


@pytest.fixture
def almacen_documentos(tmp_path, monkeypatch):
    """Cada prueba de archivos tiene almacén temporal marcado, nunca el real."""
    from app.core.config import obtener_configuracion

    ruta = tmp_path / "archivo-privado-pruebas"
    ruta.mkdir(mode=0o700)
    marcador = ruta / ".asi-archivo-pruebas"
    marcador.write_text("ASI-ARCHIVO-PRUEBAS")
    marcador.chmod(0o600)
    cfg = obtener_configuracion()
    monkeypatch.setattr(cfg, "archivo_raiz", ruta)
    monkeypatch.setattr(cfg, "archivo_requerir_antivirus", False)
    monkeypatch.setattr(cfg, "archivo_antivirus_cmd", None)
    return ruta
