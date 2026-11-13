"""Base SQLite para la aplicación local (una sola computadora).

- configurar_sqlite(): llaves foráneas activas, diario WAL y espera ante bloqueo. Las
  sesiones de la aplicación usan motor_de_escritura(): empiezan con BEGIN IMMEDIATE y
  reservan la base desde el principio, como los bloqueos de fila de PostgreSQL; un segundo
  escritor espera su turno (son transacciones cortas) en lugar de chocar con una lectura
  atrasada. Las lecturas de otros procesos no se bloquean (WAL).
- crear_esquema(): crea las tablas desde los modelos, las protecciones (triggers) que
  impiden alterar la auditoría y el archivo digital, y los datos iniciales.

PostgreSQL sigue usando sus migraciones de Alembic; nada de esto se aplica a él.
"""

from sqlalchemy import Engine, event, select, text

from app.db.datos_iniciales import cargar_datos_iniciales
from app.local.modelos import METADATOS_LOCALES
from app.models import Base

# Última migración de PostgreSQL a la que equivale el esquema creado desde los modelos.
VERSION_ESQUEMA = "i7a001"

# Actualizaciones locales permitidas: solo AGREGAN tablas nuevas y vacías (como la
# migración de PostgreSQL equivalente). Nunca modifican ni mueven registros existentes.
ACTUALIZACIONES_ADITIVAS = {
    "e6a001": ("i7a001", ("importacion_incidencias", "incidencia_importada")),
}

# Mismas protecciones y mensajes que los triggers de PostgreSQL (migraciones fe6d6759717c
# y e6a001). SQLite no tiene funciones en plpgsql: cada trigger aborta directamente.
TRIGGERS = {
    "trg_auditoria_inmutable_update": (
        "BEFORE UPDATE ON auditoria",
        "La auditoría no se puede modificar ni borrar",
    ),
    "trg_auditoria_inmutable_delete": (
        "BEFORE DELETE ON auditoria",
        "La auditoría no se puede modificar ni borrar",
    ),
    "trg_documento_no_borrar": (
        "BEFORE DELETE ON documento",
        "El archivo y sus versiones no se eliminan definitivamente",
    ),
    "trg_version_inmutable_update": (
        "BEFORE UPDATE ON documento_version",
        "El archivo y sus versiones no se eliminan definitivamente",
    ),
    "trg_version_inmutable_delete": (
        "BEFORE DELETE ON documento_version",
        "El archivo y sus versiones no se eliminan definitivamente",
    ),
    "trg_vinculo_no_borrar": (
        "BEFORE DELETE ON documento_asistencia",
        "El archivo y sus versiones no se eliminan definitivamente",
    ),
}


def es_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite"


def configurar_sqlite(engine: Engine) -> Engine:
    """Ajustes de conexión de SQLite. Solo se llama para motores SQLite."""

    @event.listens_for(engine, "connect")
    def _al_conectar(conexion_dbapi, _registro):
        # El controlador de Python no abre transacciones solo: las abre el evento "begin".
        conexion_dbapi.isolation_level = None
        cursor = conexion_dbapi.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = FULL")
        cursor.execute("PRAGMA busy_timeout = 15000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _al_empezar(conexion):
        opciones = conexion.get_execution_options()
        if opciones.get("sqlite_escritura"):
            conexion.exec_driver_sql("BEGIN IMMEDIATE")
        elif not opciones.get("sqlite_por_instruccion"):
            conexion.exec_driver_sql("BEGIN")
        # sqlite_por_instruccion: cada instrucción se confirma sola (herramientas y pruebas)

    return engine


def motor_de_escritura(engine: Engine) -> Engine:
    """Mismo motor; en SQLite sus transacciones reservan la base desde el inicio."""
    return engine.execution_options(sqlite_escritura=True) if es_sqlite(engine) else engine


def crear_triggers(conexion) -> None:
    for nombre, (momento, mensaje) in TRIGGERS.items():
        conexion.exec_driver_sql(
            f"CREATE TRIGGER IF NOT EXISTS {nombre} {momento} FOR EACH ROW "
            f"BEGIN SELECT RAISE(ABORT, '{mensaje}'); END"
        )


def quitar_triggers(conexion) -> None:
    """Solo para limpiar entre pruebas automáticas (base temporal de pruebas)."""
    for nombre in TRIGGERS:
        conexion.exec_driver_sql(f"DROP TRIGGER IF EXISTS {nombre}")


def crear_esquema(engine: Engine) -> None:
    """Crea una base local nueva y completa. No modifica una base que ya tenga datos."""
    if not es_sqlite(engine):
        raise RuntimeError("crear_esquema() es solo para SQLite; PostgreSQL usa Alembic")
    with motor_de_escritura(engine).begin() as conexion:
        existentes = conexion.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table'")
        ).scalars()
        if set(existentes) & set(Base.metadata.tables):
            raise RuntimeError("La base local ya existe: no se vuelve a crear")
        Base.metadata.create_all(conexion)
        METADATOS_LOCALES.create_all(conexion)
        crear_triggers(conexion)
        cargar_datos_iniciales(conexion)
        # El esquema creado equivale a la última migración de PostgreSQL; se registra igual
        # que Alembic, para que las siguientes versiones partan de aquí.
        conexion.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        conexion.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES (?)", (VERSION_ESQUEMA,)
        )


def triggers_presentes(conexion) -> set[str]:
    return set(
        conexion.execute(
            select(text("name")).select_from(text("sqlite_master")).where(text("type='trigger'"))
        ).scalars()
    )


class BaseLocalIncompatible(RuntimeError):
    """La base local existe pero no es de esta versión o le faltan protecciones."""


def preparar_base_local(engine: Engine) -> bool:
    """Al abrir la aplicación local: crea la base si no existe; si existe, la verifica.

    Devuelve True si se creó. Nunca borra ni recrea una base con datos: si algo no
    coincide, se detiene con un mensaje para el administrador.
    """
    with engine.connect() as conexion:
        tablas = set(
            conexion.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).scalars()
        )
    if not tablas:
        crear_esquema(engine)
        return True
    if "alembic_version" not in tablas:
        raise BaseLocalIncompatible("La base local está incompleta; no se modificó")
    with motor_de_escritura(engine).begin() as conexion:
        version = conexion.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        siguiente, nuevas = (
            ACTUALIZACIONES_ADITIVAS.get(version[0], (None, ()))
            if len(version) == 1
            else (None, ())
        )
        if version != [VERSION_ESQUEMA] and siguiente != VERSION_ESQUEMA:
            raise BaseLocalIncompatible(
                f"La base local es de otra versión ({', '.join(version) or 'sin versión'}); "
                "no se modificó"
            )
        esperadas = set(Base.metadata.tables) - (set(nuevas) if siguiente else set())
        if esperadas - tablas or (siguiente and set(nuevas) & tablas):
            raise BaseLocalIncompatible("La base local está incompleta; no se modificó")
        if set(TRIGGERS) - triggers_presentes(conexion):
            raise BaseLocalIncompatible("A la base local le faltan protecciones; no se modificó")
        if conexion.exec_driver_sql("PRAGMA quick_check").scalar() != "ok":
            raise BaseLocalIncompatible("La base local está dañada; usa un respaldo")
        if siguiente:
            # Misma transacción: si algo falla, la base queda exactamente como estaba.
            for nombre in nuevas:
                Base.metadata.tables[nombre].create(conexion)
            conexion.execute(
                text("UPDATE alembic_version SET version_num = :nueva WHERE version_num = :actual"),
                {"nueva": siguiente, "actual": version[0]},
            )
        # Tablas exclusivas de la aplicación local añadidas después (solo se agregan).
        METADATOS_LOCALES.create_all(conexion)
    return False


def marcar_importaciones_interrumpidas(engine: Engine) -> int:
    """El OCR corre dentro de la aplicación: si se cerró a medias, se marca como error."""
    with motor_de_escritura(engine).begin() as conexion:
        return conexion.execute(
            text(
                "UPDATE importacion SET estado = 'error', mensaje = :mensaje "
                "WHERE estado = 'procesando'"
            ),
            {"mensaje": "Interrumpida: la aplicación se cerró antes de terminar el OCR"},
        ).rowcount
