"""Etapa 2 de la aplicación local: compatibilidad con SQLite sin cambiar PostgreSQL.

Unas pruebas usan una base SQLite temporal propia (siempre, con cualquier motor de la
suite) y otras comparan contra la base PostgreSQL de pruebas migrada con Alembic.
Datos ficticios únicamente.
"""

import sqlite3
from datetime import UTC, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.db import sqlite_local
from app.db.datos_iniciales import (
    CATEGORIAS,
    PERMISOS_INICIALES,
    PERMISOS_POSTERIORES,
    TOLERANCIA_INICIAL,
)
from app.models import AsistenciaHora, Auditoria, Base


@pytest.fixture
def local(tmp_path):
    """Base SQLite nueva, como la que creará la aplicación local en su primera ejecución."""
    motor = sqlite_local.configurar_sqlite(
        # Nombre autorizado por la barrera de pruebas, dentro de una carpeta temporal propia.
        create_engine(f"sqlite:///{tmp_path / 'asi_archivo_pytest.sqlite3'}")
    )
    # Fuera de pytest esta base sería la real; aquí es un archivo temporal propio.
    sqlite_local.crear_esquema(motor)
    yield motor
    motor.dispose()


# Otras pruebas crean roles y categorías ficticios en la base PostgreSQL de pruebas (esas
# tablas no se vacían); se comparan solo los que crean las migraciones.
ROLES_DE_MIGRACION = "('administrador', 'consulta')"
CATEGORIAS_DE_MIGRACION = "(" + ", ".join(f"'{c}'" for c, _n, _j in CATEGORIAS) + ")"


def _catalogos(conexion):
    permisos = set(conexion.execute(text("SELECT clave, descripcion FROM permiso")).all())
    por_rol = set(
        conexion.execute(
            text(
                "SELECT r.nombre, p.clave FROM rol_permiso rp "
                "JOIN rol r ON r.id = rp.rol_id JOIN permiso p ON p.id = rp.permiso_id "
                f"WHERE r.nombre IN {ROLES_DE_MIGRACION}"
            )
        ).all()
    )
    roles = set(
        conexion.execute(
            text(f"SELECT nombre, descripcion FROM rol WHERE nombre IN {ROLES_DE_MIGRACION}")
        ).all()
    )
    categorias = {
        (c, n, bool(j))
        for c, n, j in conexion.execute(
            text(
                "SELECT clave, nombre, admite_justificantes FROM categoria_documento "
                f"WHERE clave IN {CATEGORIAS_DE_MIGRACION}"
            )
        ).all()
    }
    tolerancia = conexion.execute(
        text("SELECT id, tolerancia_minutos FROM configuracion_asistencia")
    ).all()
    return permisos, por_rol, roles, categorias, [tuple(t) for t in tolerancia]


# --- base nueva ------------------------------------------------------------------------


def test_base_local_nueva_con_todas_las_tablas_y_protecciones(local):
    with local.connect() as c:
        tablas = set(c.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars())
        assert set(Base.metadata.tables) <= tablas
        assert sqlite_local.triggers_presentes(c) == set(sqlite_local.TRIGGERS)
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        permisos, por_rol, _roles, categorias, tolerancia = _catalogos(c)
    assert permisos == set(PERMISOS_INICIALES + PERMISOS_POSTERIORES)
    assert {p for r, p in por_rol if r == "administrador"} == {p for p, _ in permisos}
    assert {p for r, p in por_rol if r == "consulta"} == {
        p for p, _ in PERMISOS_INICIALES if p.endswith(".ver")
    }
    assert categorias == set(CATEGORIAS)
    assert tolerancia == [(1, TOLERANCIA_INICIAL)]


def test_no_recrea_una_base_que_ya_tiene_datos(local):
    with pytest.raises(RuntimeError, match="ya existe"):
        sqlite_local.crear_esquema(local)


@pytest.mark.solo_postgresql
def test_datos_iniciales_iguales_a_las_migraciones(local, base_de_datos):
    """Lo que carga la base local coincide con lo que dejan las migraciones de PostgreSQL."""
    if base_de_datos.dialect.name != "postgresql":
        pytest.skip("Necesita la base PostgreSQL migrada")
    with local.connect() as c_local, base_de_datos.connect() as c_pg:
        assert _catalogos(c_local) == _catalogos(c_pg)


# --- protecciones de la historia ----------------------------------------------------------


def test_auditoria_no_se_modifica_ni_se_borra(local):
    with local.begin() as c:
        c.execute(insert(Auditoria).values(accion="prueba", entidad="ficticia", entidad_id="1"))
    for sentencia in (
        "UPDATE auditoria SET accion = 'otra'",
        "DELETE FROM auditoria",
    ):
        with (
            pytest.raises(IntegrityError, match="auditoría no se puede modificar"),
            local.begin() as c,
        ):
            c.exec_driver_sql(sentencia)
    with local.connect() as c:
        assert c.execute(select(Auditoria.accion)).scalars().all() == ["prueba"]


def test_archivo_digital_no_se_borra(local):
    with local.connect() as c:
        protecciones = {
            (tabla, sql.split()[3], sql.split()[4])  # nombre, BEFORE, UPDATE/DELETE
            for tabla, sql in c.execute(
                text("SELECT tbl_name, sql FROM sqlite_master WHERE type = 'trigger'")
            ).all()
            if "no se eliminan definitivamente" in sql
        }
    assert {(t, momento) for t, _n, momento in protecciones} >= {
        ("documento", "DELETE"),
        ("documento_version", "UPDATE"),
        ("documento_version", "DELETE"),
        ("documento_asistencia", "DELETE"),
    }


# --- reglas de las tablas -------------------------------------------------------------------


def test_regla_de_duracion_igual_en_ambas_bases():
    from sqlalchemy.dialects import postgresql, sqlite

    pg = str(CreateTable(AsistenciaHora.__table__).compile(dialect=postgresql.dialect()))
    assert (
        "CHECK (programado_fin > programado_inicio AND "
        "EXTRACT(EPOCH FROM (programado_fin-programado_inicio)) <= 3600)" in pg
    )
    lite = str(CreateTable(AsistenciaHora.__table__).compile(dialect=sqlite.dialect()))
    assert "strftime('%s', programado_fin) - strftime('%s', programado_inicio)" in lite


def test_sqlite_rechaza_tramos_de_mas_de_una_hora(local):
    with local.connect() as c:
        dur = c.exec_driver_sql(
            "SELECT strftime('%s', '09:00:00.000000') - strftime('%s', '07:30:00.000000')"
        ).scalar()
    assert dur == 5400  # la regla compara contra 3600


# --- fechas con zona horaria -------------------------------------------------------------


def test_fechas_con_zona_se_conservan(local):
    mexico = timezone(timedelta(hours=-6))
    momento = datetime(2026, 11, 2, 7, 55, 30, tzinfo=mexico)
    with local.begin() as c:
        c.execute(
            insert(Auditoria).values(
                accion="prueba", entidad="ficticia", entidad_id="1", fecha=momento
            )
        )
        c.execute(insert(Auditoria).values(accion="ahora", entidad="ficticia", entidad_id="2"))
    with local.connect() as c:
        guardada, automatica = c.execute(select(Auditoria.fecha).order_by(Auditoria.id)).scalars()
    assert guardada == momento and guardada.tzinfo is not None
    assert guardada.astimezone(UTC).hour == 13
    assert automatica.tzinfo is not None
    assert abs(datetime.now(UTC) - automatica) < timedelta(minutes=5)


def test_horas_se_guardan_y_comparan(local):
    with local.connect() as c:
        valor = c.execute(select(text("time(:h)")), {"h": time(7, 30).isoformat()}).scalar()
    assert valor == "07:30:00"


# --- barrera de pruebas también para SQLite -----------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///asi_archivo_pytest.sqlite3",  # relativa, fuera del temporal
        "sqlite:////Users/compartido/asi_archivo_pytest.sqlite3",
        "sqlite:////tmp/otra_base.sqlite3",  # otro nombre
        "sqlite://",  # en memoria
    ],
)
def test_barrera_rechaza_sqlite_no_autorizado(url):
    from app.db.proteccion_pruebas import validar_url_pruebas

    with pytest.raises(RuntimeError, match="SQLite no autorizado"):
        validar_url_pruebas(url)


@pytest.mark.parametrize(
    "extra",
    [{"database": "otra.sqlite3"}, {"uri": True}, {"factory": sqlite3.Connection}],
)
def test_connect_args_no_puede_cambiar_el_archivo_sqlite(tmp_path, extra):
    """Equivalente SQLite de la barrera de connect_args/libpq de PostgreSQL."""
    extra = {k: (str(tmp_path / v) if k == "database" else v) for k, v in extra.items()}
    engine = create_engine(
        f"sqlite:///{tmp_path / 'asi_archivo_pytest.sqlite3'}", connect_args=extra
    )
    with pytest.raises(RuntimeError, match="parámetros de conexión no autorizados"):
        engine.connect()
    assert not (tmp_path / "otra.sqlite3").exists()


def test_archivo_adjunto_no_autorizado_se_detecta(local, tmp_path):
    """Una base adjunta (ATTACH) fuera del temporal de pruebas hace fallar la validación."""
    from app.db.proteccion_pruebas import validar_conexion_pruebas

    with local.connect() as c:
        c.exec_driver_sql(f"ATTACH DATABASE '{tmp_path / 'ajena.sqlite3'}' AS ajena")
        with pytest.raises(RuntimeError, match="SQLite no autorizado"):
            validar_conexion_pruebas(c)
        c.exec_driver_sql("DETACH DATABASE ajena")


def test_version_de_esquema_igual_a_la_ultima_migracion(local):
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    cabeza = ScriptDirectory.from_config(config).get_current_head()
    with local.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == [
            cabeza
        ]
