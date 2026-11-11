"""Modo local: toda la información en una sola computadora, en un archivo SQLite.

En el servidor central las tablas y los datos iniciales los crean las migraciones de
Alembic, escritas para PostgreSQL. En el modo local la base se crea desde los modelos y
aquí se cargan los mismos datos iniciales y protecciones que dejan esas migraciones.
"""

from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from app.models import Base, CategoriaDocumento, ConfiguracionAsistencia, Permiso, Rol, Usuario

# Revisión de Alembic equivalente al esquema de los modelos (la que exige /sistema/estado).
REVISION_ESQUEMA = "e6a001"

# Mismo contenido que dejan las migraciones fe6d6759717c, 0697ceadce0c, 8b4cb2f4fef8
# y e6a001. Si una migración nueva agrega permisos, agrégalos también aquí.
PERMISOS = [
    ("docentes.ver", "Consultar docentes"),
    ("docentes.editar", "Crear y editar docentes"),
    ("horarios.ver", "Consultar horarios"),
    ("horarios.editar", "Crear, importar y editar horarios"),
    ("periodos.gestionar", "Crear, activar y cerrar periodos"),
    ("asistencia.ver", "Consultar bitácora y asistencia"),
    ("asistencia.registrar", "Registrar y corregir asistencia"),
    ("documentos.ver", "Consultar documentos permitidos"),
    ("documentos.gestionar", "Subir, clasificar y editar documentos"),
    ("reportes.ver", "Consultar reportes autorizados"),
    ("reportes.generar", "Generar y exportar reportes"),
    ("usuarios.gestionar", "Administrar usuarios y permisos"),
    ("horarios.confirmar", "Confirmar la versión vigente de un horario"),
    ("asistencia.corregir", "Corregir asistencias de días anteriores y en días inhábiles"),
    ("documentos.descargar", "Descargar originales del archivo privado"),
]

CATEGORIAS = [
    ("horario", "Horario original", False),
    ("justificante", "Justificante", True),
    ("permiso", "Permiso", True),
    ("comision", "Comisión", True),
    ("otro", "Otro documento", False),
]

# Equivalentes en SQLite de las funciones plpgsql de las migraciones: la auditoría
# solo admite inserciones y el archivo digital no se borra definitivamente.
_PROTECCIONES = [
    """CREATE TRIGGER IF NOT EXISTS trg_auditoria_inmutable_upd BEFORE UPDATE ON auditoria
    BEGIN SELECT RAISE(ABORT, 'La auditoría no se puede modificar ni borrar'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_auditoria_inmutable_del BEFORE DELETE ON auditoria
    BEGIN SELECT RAISE(ABORT, 'La auditoría no se puede modificar ni borrar'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_documento_no_borrar BEFORE DELETE ON documento
    BEGIN SELECT RAISE(ABORT,
        'El archivo y sus versiones no se eliminan definitivamente'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_version_inmutable_upd
    BEFORE UPDATE ON documento_version
    BEGIN SELECT RAISE(ABORT,
        'El archivo y sus versiones no se eliminan definitivamente'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_version_inmutable_del
    BEFORE DELETE ON documento_version
    BEGIN SELECT RAISE(ABORT,
        'El archivo y sus versiones no se eliminan definitivamente'); END""",
    """CREATE TRIGGER IF NOT EXISTS trg_vinculo_no_borrar BEFORE DELETE ON documento_asistencia
    BEGIN SELECT RAISE(ABORT,
        'El archivo y sus versiones no se eliminan definitivamente'); END""",
]


def preparar_base(engine: Engine) -> bool:
    """Crea las tablas y los datos iniciales si la base está vacía.

    Devuelve True si la base se creó en esta llamada. Una base existente no se toca,
    salvo para reponer protecciones o datos iniciales que falten.
    """
    if engine.dialect.name != "sqlite":
        raise RuntimeError("El modo local solo usa SQLite; el servidor central usa Alembic")
    nueva = not inspect(engine).has_table("usuario")
    Base.metadata.create_all(engine)
    with Session(engine) as sesion, sesion.begin():
        for sql in _PROTECCIONES:
            sesion.execute(text(sql))
        sesion.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        )
        if sesion.scalar(text("SELECT count(*) FROM alembic_version")) == 0:
            sesion.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:r)"),
                {"r": REVISION_ESQUEMA},
            )
        _datos_iniciales(sesion)
    return nueva


def _datos_iniciales(sesion: Session) -> None:
    existentes = set(sesion.scalars(select(Permiso.clave)))
    for clave, descripcion in PERMISOS:
        if clave not in existentes:
            sesion.add(Permiso(clave=clave, descripcion=descripcion))
    sesion.flush()
    permisos = list(sesion.scalars(select(Permiso)))

    roles = {r.nombre: r for r in sesion.scalars(select(Rol))}
    if "administrador" not in roles:
        roles["administrador"] = Rol(
            nombre="administrador", descripcion="Gestión completa del sistema"
        )
        sesion.add(roles["administrador"])
    if "consulta" not in roles:
        roles["consulta"] = Rol(nombre="consulta", descripcion="Solo consulta de información")
        sesion.add(roles["consulta"])
    sesion.flush()
    for p in permisos:
        if p not in roles["administrador"].permisos:
            roles["administrador"].permisos.append(p)
        if p.clave.endswith(".ver") and p not in roles["consulta"].permisos:
            roles["consulta"].permisos.append(p)

    claves = set(sesion.scalars(select(CategoriaDocumento.clave)))
    for clave, nombre, justificantes in CATEGORIAS:
        if clave not in claves:
            sesion.add(
                CategoriaDocumento(clave=clave, nombre=nombre, admite_justificantes=justificantes)
            )

    if sesion.get(ConfiguracionAsistencia, 1) is None:
        sesion.add(ConfiguracionAsistencia(id=1, tolerancia_minutos=10))


def hay_usuarios(engine: Engine) -> bool:
    with Session(engine) as sesion:
        return sesion.scalar(select(Usuario.id).limit(1)) is not None


def crear_administrador(engine: Engine, correo: str, nombre: str, contrasena: str) -> None:
    """Primer usuario de la computadora (lo pide la aplicación la primera vez)."""
    from app.cli import crear_usuario

    with Session(engine) as sesion:
        crear_usuario(sesion, correo, nombre, "administrador", contrasena)  # hace commit
